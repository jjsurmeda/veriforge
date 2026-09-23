"""Hybrid retrieval query (TRD §9.2): vector + BM25 in one SQL, RRF fusion.

vec CTE (top 50 cosine, scope-filtered), lex CTE (top 50 pg_search BM25,
same scope), fused = Σ weight_i / (60 + rank_i), top 40 out. Rerank,
dedupe and small-to-big expansion live in rerank.py/expand.py.

The ownership scope is always injected (filters.build_scope); the fusion
weight is the `lexical_weight` Score decision from ingress (TRD §8). The
parameter is required — there is no default, so a caller that has not
run ingress cannot accidentally fuse with an arbitrary weight.
"""

import logging
from dataclasses import dataclass, replace
from uuid import UUID

import asyncpg
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from retrieval.errors import RetrievalTimeout
from retrieval.filters import ClientFilters, Ownership, build_scope

logger = logging.getLogger(__name__)

VEC_LIMIT = 50
LEX_LIMIT = 50
FUSED_LIMIT = 40
RRF_K = 60

_QUERY = """
WITH vec AS (
  SELECT c.id,
         ROW_NUMBER() OVER (ORDER BY c.embedding <=> CAST(:emb AS vector)) AS rank,
         1 - (c.embedding <=> CAST(:emb AS vector)) AS score
  FROM chunks c
  WHERE {scope} AND c.embedding IS NOT NULL
  ORDER BY c.embedding <=> CAST(:emb AS vector)
  LIMIT :vec_limit
),
lex AS (
  SELECT c.id,
         ROW_NUMBER() OVER (ORDER BY paradedb.score(c.id) DESC) AS rank,
         paradedb.score(c.id) AS score
  FROM chunks c
  WHERE {scope} AND c.text @@@ paradedb.parse(:q, lenient => true)
  ORDER BY paradedb.score(c.id) DESC
  LIMIT :lex_limit
),
fused AS (
  SELECT COALESCE(v.id, l.id) AS id,
         v.score AS vector_score,
         l.score AS bm25_score,
         COALESCE(CAST(:vec_w AS float8) / ({rrf_k} + v.rank), 0)
           + COALESCE(CAST(:lex_w AS float8) / ({rrf_k} + l.rank), 0) AS fused_score
  FROM vec v FULL OUTER JOIN lex l ON l.id = v.id
)
SELECT c.id, c.document_id, c.section_id, c.ord, c.page, c.text, c.source_type,
       d.name AS document_name, s.heading_path,
       f.vector_score, f.bm25_score, f.fused_score
FROM fused f
JOIN chunks c ON c.id = f.id
LEFT JOIN documents d ON d.id = c.document_id
LEFT JOIN sections s ON s.id = c.section_id
ORDER BY f.fused_score DESC
LIMIT :fused_limit
"""


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: UUID
    document_id: UUID | None
    document_name: str | None
    section_id: UUID | None
    ord: int
    page: int | None
    text: str
    heading_path: str | None
    source_type: str
    vector_score: float | None
    bm25_score: float | None
    fused_score: float
    rerank_score: float | None = None

    def with_rerank(self, score: float) -> "ScoredChunk":
        return replace(self, rerank_score=score)


async def hybrid_search(
    session: AsyncSession,
    *,
    query_text: str,
    query_embedding: list[float],
    ownership: Ownership,
    filters: ClientFilters | None = None,
    lexical_weight: float,
) -> list[ScoredChunk]:
    """Run the §9.2 query; returns up to FUSED_LIMIT chunks, fused order."""
    settings = get_settings()
    weight = lexical_weight
    scope, params = build_scope(ownership, filters or ClientFilters())
    params.update(
        {
            "emb": "[" + ",".join(repr(v) for v in query_embedding) + "]",
            "q": query_text,
            "vec_limit": VEC_LIMIT,
            "lex_limit": LEX_LIMIT,
            "fused_limit": FUSED_LIMIT,
            "vec_w": 1.0 - weight,
            "lex_w": weight,
        }
    )
    # int() keeps the SET literal injection-safe.
    await session.execute(
        text(f"SET LOCAL statement_timeout = {int(settings.retrieval_statement_timeout_ms)}")
    )
    try:
        rows = await session.execute(
            text(_QUERY.format(scope=scope, rrf_k=RRF_K)), params
        )
    except DBAPIError as exc:
        if isinstance(exc.orig, asyncpg.QueryCanceledError):
            logger.warning("retrieval statement timeout")
            raise RetrievalTimeout from exc
        raise
    return [
        ScoredChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document_name=row.document_name,
            section_id=row.section_id,
            ord=row.ord,
            page=row.page,
            text=row.text,
            heading_path=row.heading_path,
            source_type=row.source_type,
            vector_score=row.vector_score,
            bm25_score=row.bm25_score,
            fused_score=row.fused_score,
        )
        for row in rows
    ]
