"""Hop retrieve node (TRD §7 Deep row): one retrieve-and-extract cycle per
sub-question. Reuses slice 3's hybrid retrieval and slice 4's sanitizer —
no forked retrieval path (python.md package-boundary rule)."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from decisions import DecisionEngine
from decisions.sanitize import sanitize_chunks
from graph.timing import make_sub_step_timer
from retrieval.cache import get_query_embedding
from retrieval.expand import dedupe_adjacent
from retrieval.filters import ClientFilters, Ownership
from retrieval.hybrid import ScoredChunk, hybrid_search
from retrieval.rerank import apply_rerank, get_reranker
from schemas.decisions import Answer
from schemas.events import Retrieval, RetrievedChunk, SubQuestion

EXCERPT_CHARS = 240
NOTE_CHUNKS = 5
NOTE_EXCERPT_CHARS = 500

SubStep = Callable[[str, Callable[[], Awaitable[Any]]], Awaitable[Any]]


@dataclass(frozen=True)
class HopNote:
    sub_question: SubQuestion
    note: str
    kept_chunks: list[ScoredChunk]
    dropped_chunks: list[ScoredChunk]
    retrieval_event: Retrieval
    decision_answers: dict[str, Answer]


# Each sub-question keeps at least its best two chunks in the merged winners.
# Two, because a compound question needs the fact and one corroborating or
# neighbouring passage per clause, and more would start to crowd out the
# globally best chunks the rerank score exists to pick.
MIN_PER_SUB_QUESTION = 2


def rerank_score_key(chunk: ScoredChunk) -> float:
    return chunk.rerank_score if chunk.rerank_score is not None else chunk.fused_score


def merge_winners(groups: list[list[ScoredChunk]]) -> list[ScoredChunk]:
    """Merge the hops' winners (one list per sub-question) into one ranked list.

    Ranked by rerank score, as before, so one sub-question could take every
    slot of the final context (`cross-two-elizabeths`). Each sub-question's
    best `MIN_PER_SUB_QUESTION` surviving chunks now come first, the rest
    follow by score. The set of winners is unchanged (the evidence floor and
    entity guard see the same chunks); only the order, which is what the
    context trim keeps from the front, moves. With one non-empty group the
    guaranteed chunks are already the first ones, so the result is identical
    to the plain sort.
    """
    ranked = dedupe_adjacent(
        sorted((c for group in groups for c in group), key=rerank_score_key, reverse=True)
    )
    if sum(1 for group in groups if group) < 2:
        return ranked
    surviving = {c.chunk_id for c in ranked}
    guaranteed: set[object] = set()
    for group in groups:
        best = [
            c for c in sorted(group, key=rerank_score_key, reverse=True) if c.chunk_id in surviving
        ]
        guaranteed.update(c.chunk_id for c in best[:MIN_PER_SUB_QUESTION])
    return [c for c in ranked if c.chunk_id in guaranteed] + [
        c for c in ranked if c.chunk_id not in guaranteed
    ]


def _note_text(sub_question: SubQuestion, winners: list[ScoredChunk]) -> str:
    if not winners:
        return f"[{sub_question.id}] {sub_question.question}\n(no evidence retrieved)"
    evidence = "\n".join(
        f"- ({c.chunk_id}) {c.text[:NOTE_EXCERPT_CHARS]}" for c in winners[:NOTE_CHUNKS]
    )
    return f"[{sub_question.id}] {sub_question.question}\n{evidence}"


async def run_hop(
    session: AsyncSession,
    *,
    engine: DecisionEngine,
    run_id: UUID,
    hop_index: int,
    sub_question: SubQuestion,
    user_id: UUID,
    collection_ids: list[UUID],
    chat_id: UUID,
    client_filters: ClientFilters,
    lexical_weight: float,
    sub_step: SubStep | None = None,
) -> HopNote:
    # CH-5 / KI-93: retrieve, rerank and sanitize show as sub-steps of this
    # hop, labelled by sub-question so parallel hops stay distinguishable.
    # No sub_step publisher means no events, same behaviour as before.
    step = sub_step or make_sub_step_timer(None, node="deep", run_id=run_id)

    async def _retrieve() -> list[ScoredChunk]:
        embedding = await get_query_embedding(session, sub_question.question)
        ownership = Ownership(user_id=user_id, collection_ids=collection_ids, chat_id=chat_id)
        return await hybrid_search(
            session,
            query_text=sub_question.question,
            query_embedding=embedding,
            ownership=ownership,
            filters=client_filters,
            lexical_weight=lexical_weight,
        )

    fused: list[ScoredChunk] = await step(f"retrieve: {sub_question.id}", _retrieve)

    async def _rerank() -> list[ScoredChunk]:
        return dedupe_adjacent(
            await apply_rerank(
                get_reranker(engine, str(run_id)),
                query=sub_question.question,
                chunks=fused,
            )
        )

    reranked: list[ScoredChunk] = await step(f"rerank: {sub_question.id}", _rerank)
    # Sanitize after rerank (TRD §11 layer 4, amended for KI-11): only the
    # chunks that can reach the generator are asked about; a dropped chunk
    # is not backfilled from beyond the reranked set.
    winners, dropped, answers = await step(
        f"sanitize: {sub_question.id}",
        partial(sanitize_chunks, engine, run_id=str(run_id), chunks=reranked),
    )

    dropped_ids = {c.chunk_id for c in dropped}
    retrieval_event = Retrieval(
        run_id=str(run_id),
        hop=hop_index,
        query=sub_question.question,
        chunks=[
            RetrievedChunk(
                chunk_id=str(c.chunk_id),
                document_id=str(c.document_id) if c.document_id else None,
                document_name=c.document_name,
                url=c.url,
                page=c.page,
                heading_path=c.heading_path,
                source_type=c.source_type,
                excerpt=c.text[:EXCERPT_CHARS],
                vector_score=c.vector_score,
                bm25_score=c.bm25_score,
                fused_score=c.fused_score,
                rerank_score=c.rerank_score,
                dropped=c.chunk_id in dropped_ids,
            )
            for c in fused
        ],
    )
    return HopNote(
        sub_question=sub_question,
        note=_note_text(sub_question, winners),
        kept_chunks=winners,
        dropped_chunks=dropped,
        retrieval_event=retrieval_event,
        decision_answers=answers,
    )


def ready_sub_questions(
    plan: list[SubQuestion], answered_ids: set[str]
) -> list[SubQuestion]:
    """Sub-questions whose dependencies are all answered and that are not
    themselves answered yet — the next batch to run in parallel."""
    return [
        sq
        for sq in plan
        if sq.id not in answered_ids and all(d in answered_ids for d in sq.depends_on)
    ]


async def run_hop_batch(
    sub_questions: list[SubQuestion],
    *,
    session: AsyncSession,
    engine: DecisionEngine,
    run_id: UUID,
    hop_index: int,
    user_id: UUID,
    collection_ids: list[UUID],
    chat_id: UUID,
    client_filters: ClientFilters,
    lexical_weight: float,
    sub_step: SubStep | None = None,
) -> list[HopNote]:
    """Independent sub-questions in the same batch run concurrently
    (asyncio.gather, not sequential) — this is what keeps Deep's p50 under
    the 30s target when the plan fans out."""
    return list(
        await asyncio.gather(
            *(
                run_hop(
                    session,
                    engine=engine,
                    run_id=run_id,
                    hop_index=hop_index,
                    sub_question=sq,
                    user_id=user_id,
                    collection_ids=collection_ids,
                    chat_id=chat_id,
                    client_filters=client_filters,
                    lexical_weight=lexical_weight,
                    sub_step=sub_step,
                )
                for sq in sub_questions
            )
        )
    )
