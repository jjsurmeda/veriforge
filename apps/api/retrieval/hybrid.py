"""Hybrid retrieval query (TRD §9.2): vector + BM25 in one SQL, RRF fusion.

vec CTE (top 50 cosine, scope-filtered), lex CTE (top 50 pg_search BM25,
same scope), fused = Σ weight_i / (60 + rank_i). The pool is the fused top
40 plus the first 8 BM25-only candidates (lex rank order) that no weight
would carry over the vector top-40 (see `LEX_RESERVE`). Rerank, dedupe and
small-to-big expansion live in rerank.py/expand.py.

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
from runtime import runtime_value

logger = logging.getLogger(__name__)

VEC_LIMIT = 50
LEX_LIMIT = 50
FUSED_LIMIT = 40
# The BM25 leg's own top candidates ride IN ADDITION to the fused order: the
# pool is the fused top `FUSED_LIMIT` plus up to `LEX_RESERVE` lex-only rows
# (no vector score) the fused order never carries. The ingress
# `lexical_weight` Score reads 0.00-0.04 on the books set, and the RRF score is
# proportional to the weight, so a fact that matches lexically but embeds far
# from the query (`ml-zh-xiyou-nezha`'s answer passage) never reached the
# rerank. Measured 2026-10-18 with `scripts/measure_recall.py` over the R2a-4
# proof's recorded queries (23 answer passages, books):
#   recorded weight 22/23 (misses nezha) · floor 0.2-0.4 22/23 (same miss)
#   floor 0.5 22/23 (misses frame-walton) · floor 0.6 19/23 · floor 0.8 16/23
#   reserve 8 23/23, mean pool 48 · reserve 12 23/23, 52 · reserve 24 23/23, 64
# A reserve keeps the fused top 40 unchanged, so the thresholds calibrated on
# it still apply; 8 is the smallest measured value that reaches every passage.
LEX_RESERVE = 8

RRF_K = 60

# Must stay in step with the `text` tokenizer in migration 0013. The
# query side has to name the tokenizer explicitly — `paradedb.parse` always
# tokenises with the default one, so against an icu index it still treats a
# whole CJK question as a single unsegmented token and matches nothing.
LEX_TOKENIZER = '{"type": "icu"}'

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
  WHERE {scope} AND c.text @@@ paradedb.match('text', :q, tokenizer := :tok)
  ORDER BY paradedb.score(c.id) DESC
  LIMIT :lex_limit
),
fused AS (
  SELECT COALESCE(v.id, l.id) AS id,
         v.score AS vector_score,
         l.score AS bm25_score,
         l.rank AS lex_rank,
         COALESCE(CAST(:vec_w AS float8) / ({rrf_k} + v.rank), 0)
           + COALESCE(CAST(:lex_w AS float8) / ({rrf_k} + l.rank), 0) AS fused_score
  FROM vec v FULL OUTER JOIN lex l ON l.id = v.id
),
kept AS (
  SELECT id, vector_score, bm25_score, fused_score
  FROM fused
  WHERE id IS NOT NULL
  ORDER BY fused_score DESC, id
  LIMIT :fused_limit
),
rescued AS (
  SELECT id, vector_score, bm25_score, fused_score
  FROM fused
  WHERE id IS NOT NULL
    AND vector_score IS NULL
    AND id NOT IN (SELECT id FROM kept)
  ORDER BY lex_rank, id
  LIMIT :lex_reserve
),
pool AS (SELECT * FROM kept UNION ALL SELECT * FROM rescued)
SELECT c.id, c.document_id, c.section_id, c.ord, c.page, c.text, c.source_type,
       d.name AS document_name, s.heading_path,
       p.vector_score, p.bm25_score, p.fused_score
FROM pool p
JOIN chunks c ON c.id = p.id
LEFT JOIN documents d ON d.id = c.document_id
LEFT JOIN sections s ON s.id = c.section_id
ORDER BY p.fused_score DESC
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
    vec_limit = int(runtime_value("retrieval.vec_limit", VEC_LIMIT))
    lex_limit = int(runtime_value("retrieval.lex_limit", LEX_LIMIT))
    fused_limit = int(runtime_value("retrieval.fused_limit", FUSED_LIMIT))
    lex_reserve = int(runtime_value("retrieval.lex_reserve", LEX_RESERVE))
    rrf_k = int(runtime_value("retrieval.rrf_k", RRF_K))
    scope, params = build_scope(ownership, filters or ClientFilters())
    params.update(
        {
            "emb": "[" + ",".join(repr(v) for v in query_embedding) + "]",
            "q": query_text,
            "tok": LEX_TOKENIZER,
            "vec_limit": vec_limit,
            "lex_limit": lex_limit,
            "fused_limit": fused_limit,
            "lex_reserve": lex_reserve,
            "vec_w": 1.0 - weight,
            "lex_w": weight,
        }
    )
    # int() keeps the SET literal injection-safe.
    await session.execute(
        text(f"SET LOCAL statement_timeout = {int(settings.retrieval_statement_timeout_ms)}")
    )
    try:
        rows = await session.execute(text(_QUERY.format(scope=scope, rrf_k=rrf_k)), params)
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
