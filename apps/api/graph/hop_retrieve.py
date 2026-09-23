"""Hop retrieve node (TRD §7 Deep row): one retrieve-and-extract cycle per
sub-question. Reuses slice 3's hybrid retrieval and slice 4's sanitizer —
no forked retrieval path (python.md package-boundary rule)."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from decisions import DecisionEngine
from decisions.sanitize import sanitize_chunks
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


@dataclass(frozen=True)
class HopNote:
    sub_question: SubQuestion
    note: str
    kept_chunks: list[ScoredChunk]
    dropped_chunks: list[ScoredChunk]
    retrieval_event: Retrieval
    decision_answers: dict[str, Answer]


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
) -> HopNote:
    embedding = await get_query_embedding(session, sub_question.question)
    ownership = Ownership(user_id=user_id, collection_ids=collection_ids, chat_id=chat_id)
    fused = await hybrid_search(
        session,
        query_text=sub_question.question,
        query_embedding=embedding,
        ownership=ownership,
        filters=client_filters,
        lexical_weight=lexical_weight,
    )
    kept, dropped, answers = await sanitize_chunks(engine, run_id=str(run_id), chunks=fused)
    winners = dedupe_adjacent(
        await apply_rerank(get_reranker(), query=sub_question.question, chunks=kept)
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
                )
                for sq in sub_questions
            )
        )
    )
