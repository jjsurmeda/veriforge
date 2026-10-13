"""Rerank stage (TRD §7): grade the fused candidates and take the top-k.

For a compare question the candidates come from several named entities, and
one flat rerank can score the second book out of the top-k entirely. So the
fused set is split by the query that surfaced each chunk, each entity's own
set is reranked on its own name, and every group takes an equal share of the
top-k.
"""

from __future__ import annotations

import math
from uuid import UUID

from retrieval.hybrid import ScoredChunk
from retrieval.rerank import RerankProvider, apply_rerank
from schemas.events import Retrieval


def add_rerank_scores(events: list[Retrieval], reranked: list[ScoredChunk]) -> None:
    """Carry the rerank scores onto the retrieval events the client already
    saw, so one chunk id shows the same score in both places."""
    scores = {str(chunk.chunk_id): chunk.rerank_score for chunk in reranked}
    for event in events:
        for chunk in event.chunks:
            if chunk.chunk_id in scores:
                chunk.rerank_score = scores[chunk.chunk_id]


async def _rerank_candidates(
    reranker: RerankProvider,
    *,
    query: str,
    chunks: list[ScoredChunk],
    provenance: dict[UUID, str],
    limit: int,
) -> list[ScoredChunk]:
    """Rerank the fused set, except when a compare run's chunks came from
    several named entities: rerank each entity's own set and take an equal
    share of `limit` from each, so the second book can't be scored out of
    the top-k entirely. The "" group is the chunks no entity surfaced; it
    takes a share too, reranked on the original query."""
    groups: dict[str, list[ScoredChunk]] = {}
    for chunk in chunks:
        groups.setdefault(provenance.get(chunk.chunk_id, ""), []).append(chunk)
    if len(groups) < 2:
        return await apply_rerank(reranker, query=query, chunks=chunks, top_n=limit)
    share = math.ceil(limit / len(groups))
    picked: list[ScoredChunk] = []
    for label, group in groups.items():
        picked.extend(await apply_rerank(reranker, query=label or query, chunks=group, top_n=share))
    # Order by rerank score, not group insertion order. Dict order put the
    # "" (no-entity) share first whatever it scored, so a compare run's
    # citations [1]-[3] could be the weakest passages. The shares stay the
    # same; only the order changes.
    picked.sort(key=lambda chunk: chunk.rerank_score or 0.0, reverse=True)
    return picked
