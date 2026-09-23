"""Fast mode pipeline (TRD §7 mode table): rewrite → single retrieval →
generate, streamed. No multi-query, no retry loop, no hops, no inline
review — the async-after-delivery review is a slice-6 addition; Fast mode
delivers and that deferral is recorded here.

TODO(slice-4): auto/deep route here too until their graphs land; replace
with real mode routing when ingress/DecisionEngine exists.
"""

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import Chat, Citation, Message
from graph import rewrite as rewrite_node
from graph.generate import stream_grounded_answer
from providers.llm import complete
from retrieval.cache import get_query_embedding
from retrieval.context import count_tokens, trim_context
from retrieval.expand import ExpandedContext, dedupe_adjacent, expand_context
from retrieval.filters import ClientFilters, Ownership
from retrieval.hybrid import hybrid_search
from retrieval.rerank import apply_rerank, get_reranker
from retrieval.web import ensure_web_chunks
from schemas.chats import RunFilters
from schemas.events import Metrics, Retrieval, RetrievedChunk

logger = logging.getLogger(__name__)

EXCERPT_CHARS = 240


@dataclass(frozen=True)
class FastRunInput:
    run_id: UUID
    message_id: UUID
    chat_id: UUID
    user_id: UUID
    question: str
    litellm_model: str
    small_model: str
    context_window: int
    source: str
    client_filters: ClientFilters
    collection_ids: list[UUID]


def to_client_filters(filters: RunFilters | None) -> ClientFilters:
    if filters is None:
        return ClientFilters()
    return ClientFilters(
        source_type=filters.source_type,
        document_ids=filters.document_ids,
        tags=filters.tags,
        date_from=filters.date_from,
        date_to=filters.date_to,
        mime=filters.mime,
        page=filters.page,
    )


async def _history(
    session: AsyncSession, chat_id: UUID, exclude_message_id: UUID
) -> list[tuple[str, str]]:
    messages = (
        await session.execute(
            select(Message)
            .where(Message.chat_id == chat_id, Message.id != exclude_message_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    return [(m.role, m.content) for m in messages if m.content]


@dataclass
class FastRun:
    params: FastRunInput
    history: list[tuple[str, str]]
    contexts: list[ExpandedContext]
    rewritten: str
    retrieval_event: Retrieval
    latency_ms: dict[str, int]
    context_used: int

    async def stream_answer(self) -> AsyncIterator[str]:
        async for token in stream_grounded_answer(
            litellm_model=self.params.litellm_model,
            question=self.rewritten,
            contexts=self.contexts,
            history=self.history,
            metadata={
                "run_id": str(self.params.run_id),
                "user_id": str(self.params.user_id),
            },
        ):
            yield token


async def prepare_fast_run(
    session_factory: async_sessionmaker[AsyncSession], params: FastRunInput
) -> FastRun:
    """Run rewrite + retrieval + budget + citation rows; returns everything
    the runner needs to stream the answer."""
    async with session_factory() as session, session.begin():
        chat = await session.get(Chat, params.chat_id)
        history = await _history(session, params.chat_id, params.message_id)
        summary = chat.summary if chat is not None else None
        if params.source == "web":
            await ensure_web_chunks(session, query=params.question, chat_id=params.chat_id)

        t0 = time.monotonic()
        rewritten = await rewrite_node.rewrite_query(
            question=params.question,
            history=history,
            summary=summary,
            small_model=params.small_model,
            complete_fn=complete,
        )
        t1 = time.monotonic()

        collection_ids = list(params.collection_ids)
        embedding = await get_query_embedding(session, rewritten)
        ownership = Ownership(
            user_id=params.user_id, collection_ids=collection_ids, chat_id=params.chat_id
        )
        fused = await hybrid_search(
            session,
            query_text=rewritten,
            query_embedding=embedding,
            ownership=ownership,
            filters=params.client_filters,
        )
        winners = dedupe_adjacent(
            await apply_rerank(get_reranker(), query=rewritten, chunks=fused)
        )
        contexts = await expand_context(session, winners)
        history_tokens = sum(count_tokens(text) for _, text in history[-6:])
        contexts, context_used = trim_context(
            contexts,
            window_tokens=params.context_window,
            history_tokens=history_tokens,
        )
        t2 = time.monotonic()

        session.add_all(
            Citation(
                message_id=params.message_id,
                n=i + 1,
                chunk_id=context.chunk.chunk_id,
                rerank_score=context.chunk.rerank_score,
            )
            for i, context in enumerate(contexts)
        )

    return FastRun(
        params=params,
        history=history,
        contexts=contexts,
        rewritten=rewritten,
        retrieval_event=Retrieval(
            run_id=str(params.run_id),
            hop=0,
            query=rewritten,
            chunks=[
                RetrievedChunk(
                    chunk_id=str(context.chunk.chunk_id),
                    document_id=(
                        str(context.chunk.document_id)
                        if context.chunk.document_id
                        else None
                    ),
                    document_name=context.chunk.document_name,
                    page=context.chunk.page,
                    heading_path=context.chunk.heading_path,
                    source_type=context.chunk.source_type,
                    excerpt=context.chunk.text[:EXCERPT_CHARS],
                    vector_score=context.chunk.vector_score,
                    bm25_score=context.chunk.bm25_score,
                    fused_score=context.chunk.fused_score,
                    rerank_score=context.chunk.rerank_score,
                    dropped=False,
                )
                for context in contexts
            ],
        ),
        latency_ms={
            "rewrite": int((t1 - t0) * 1000),
            "retrieve": int((t2 - t1) * 1000),
        },
        context_used=context_used,
    )


async def finalize_fast_run(
    session_factory: async_sessionmaker[AsyncSession],
    run: FastRun,
    *,
    generate_ms: int,
    tokens_in: int,
    tokens_out: int,
) -> Metrics:
    """Post-delivery: refresh the rolling summary if due; returns the
    metrics event (TRD §12)."""
    async with session_factory() as session, session.begin():
        chat = await session.get(Chat, run.params.chat_id)
        await rewrite_node.maybe_refresh_summary(
            session,
            chat_id=run.params.chat_id,
            summary=chat.summary if chat is not None else None,
            small_model=run.params.small_model,
            complete_fn=complete,
        )
    return Metrics(
        run_id=str(run.params.run_id),
        latency_ms={**run.latency_ms, "generate": generate_ms},
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        credits=tokens_in + tokens_out,
        context_used=run.context_used,
        context_window=run.params.context_window,
    )
