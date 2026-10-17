"""Hybrid retrieval query (TRD §9.2): vector + BM25 in one SQL, RRF fusion.

vec CTE (top 50 cosine, scope-filtered), lex CTE (top 50 pg_search BM25,
same scope), fused = Σ weight_i / (60 + rank_i). The pool is the fused top
40 plus the BM25-only candidates of the first 24 lex ranks that no weight
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
# (candidates no vector score) the fused order never carries. The ingress
# `lexical_weight` Score reads low on most questions (0.02-0.18 across the
# R2a live runs), and the RRF score is proportional to the weight: at 0.05 a
# pure-lexical chunk carries at most 0.05 / (rrf_k + rank) ≈ 0.0007, while
# every candidate in the vector top-50 carries 0.95 / (rrf_k + rank) ≥ 0.0059
# — so without the reservation the fused order is the vector top-40 at ANY
# weight, and a fact that matches lexically but embeds far from the query is
# unretrievable. The R2a-4 live proof ran exactly this: `ml-zh-xiyou-nezha`'s
# answer passage 「原來是天王住宅 號雲樓宮」 sits at BM25 rank 13-22 for its
# own question (readings across the variants) — inside every lex window —
# and was in no variant's pool at all, so the rubric graded the wrong
# passages and the run declined. 24 keeps every recorded rank inside the
# window; nothing already in the fused order is displaced, and the rerank
# grades what the pool holds so the floor fails closed only in front of a
# graded absence, not an ungraded one (ADR-006's ordering).
LEX_RESERVE = 24

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
