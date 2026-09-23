"""Dedupe + small-to-big expansion (TRD §9.2).

After rerank: adjacent chunks from the same document collapse to the
better-scored one, then each winner expands to its parent section (if the
parent is ≤ 1,200 tokens) or its ±1 neighbours. Citations still point at
the winning child and its page. Web chunks (no parent) expand to themselves.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, Section
from retrieval.hybrid import ScoredChunk

PARENT_TOKEN_LIMIT = 1200


@dataclass(frozen=True)
class ExpandedContext:
    chunk: ScoredChunk
    context_text: str


def dedupe_adjacent(winners: list[ScoredChunk]) -> list[ScoredChunk]:
    kept: list[ScoredChunk] = []
    for chunk in winners:
        adjacent = any(
            chunk.document_id is not None
            and chunk.document_id == other.document_id
            and abs(chunk.ord - other.ord) <= 1
            for other in kept
        )
        if not adjacent:
            kept.append(chunk)
    return kept


async def expand_context(
    session: AsyncSession, winners: list[ScoredChunk]
) -> list[ExpandedContext]:
    contexts: list[ExpandedContext] = []
    for chunk in winners:
        if chunk.section_id is None:
            contexts.append(ExpandedContext(chunk, chunk.text))
            continue
        section = await session.get(Section, chunk.section_id)
        if section is not None and section.tokens <= PARENT_TOKEN_LIMIT:
            contexts.append(ExpandedContext(chunk, section.text))
            continue
        neighbours = (
            await session.execute(
                select(Chunk)
                .where(
                    Chunk.section_id == chunk.section_id,
                    Chunk.ord.between(chunk.ord - 1, chunk.ord + 1),
                )
                .order_by(Chunk.ord)
            )
        ).scalars().all()
        contexts.append(ExpandedContext(chunk, "\n\n".join(n.text for n in neighbours)))
    return contexts
