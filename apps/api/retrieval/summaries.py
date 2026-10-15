"""Summary retrieval (TRD §9.1 step 6, §9.2): the gist-question index.

A gist question — "what is this book about", "tell me the story of" — matches
no single 300-token child, which is the mechanism behind KI-70: the recorded
`broad-alice` run scored the passages that *did* contain Alice's arc **0.36**
on the old relevance score, against 0.97 from the entity check on the same
passages. The evidence was there and the question could not reach it. These
rows are what a gist question retrieves instead.

**The ownership filter is the reason this module is written the way it is.**
A summary is a second copy of a corpus, reachable by a second query, and the
one thing that turns that into a data leak is a *simplified* scope. So there is
no summary-specific predicate here. The query below is written with the same
`chunks c` alias and the same `documents`/`collections` joins that
`filters.build_scope` expects, and its `{scope}` is that builder's output,
verbatim. Reuse, not paraphrase — and the tests in
`tests/retrieval/test_summaries.py` are written to fail the moment that stops
being true.

Two more decisions the shape carries:

* **Hybrid, like chunks.** Vector + BM25 fused with RRF. The summaries are
  model-written prose, so lexical overlap with the user's wording is weaker
  than for chunks; a vector-only query would miss a gist question that names
  the book's title.
* **Small result set.** A gist question wants the *shape* of the book. Eight
  summaries is already more than the evidence budget wants before the chunks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from uuid import UUID

import asyncpg
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from retrieval.errors import RetrievalTimeout
from retrieval.filters import ClientFilters, Ownership, ScopeTable, build_scope
from retrieval.hybrid import LEX_LIMIT, RRF_K, VEC_LIMIT
from runtime import runtime_value

logger = logging.getLogger(__name__)

#: The two kinds of row in `summaries`. Mirrors `db.models.Summary.kind`.
SUMMARY_KINDS: tuple[str, ...] = ("section", "document")

#: The intents whose questions a summary can answer on the *first* retrieval.
#: Deliberately a fixed tuple rather than "anything that is not a lookup": a
#: new intent added to ingress but not here has to be **added**, and until then
#: it takes the lookup path.
GIST_INTENTS: frozenset[str] = frozenset({"summarize"})

#: How many summaries come back.
SUMMARY_TOP_N = 6

# Same tokenizer as `hybrid.LEX_TOKENIZER`, and for the same reason: the
# migration's `bm25` index is built on the ICU tokenizer, so naming a different
# one at query time treats a whole CJK question as one unsegmented token and
# matches nothing.
LEX_TOKENIZER = '{"type": "icu"}'

# The same three-arm shape as `retrieval/hybrid._QUERY`, over `summaries`.
# Aliased `c`, not `s`, because `build_scope`'s fragment names `c.source_type`,
# `c.document_id` and `c.page` — the alias is the reuse, and it is why the
# fragment can be passed through untouched.
_SUMMARY_QUERY = """
WITH vec AS (
  SELECT c.id,
         ROW_NUMBER() OVER (ORDER BY c.embedding <=> CAST(:emb AS vector)) AS rank,
         1 - (c.embedding <=> CAST(:emb AS vector)) AS score
  FROM summaries c
  JOIN documents d ON d.id = c.document_id
  JOIN collections col ON col.id = d.collection_id
  WHERE {scope} AND c.embedding IS NOT NULL
  ORDER BY c.embedding <=> CAST(:emb AS vector)
  LIMIT :vec_limit
),
lex AS (
  SELECT c.id,
         ROW_NUMBER() OVER (ORDER BY paradedb.score(c.id) DESC) AS rank,
         paradedb.score(c.id) AS score
  FROM summaries c
  JOIN documents d ON d.id = c.document_id
  JOIN collections col ON col.id = d.collection_id
  WHERE {scope} AND c.text @@@ paradedb.match('text', :q, tokenizer := :tok)
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
SELECT c.id, c.document_id, c.section_id, c.kind, c.ord, c.heading_path, c.text,
       d.name AS document_name,
       f.vector_score, f.bm25_score, f.fused_score
FROM fused f
JOIN summaries c ON c.id = f.id
LEFT JOIN documents d ON d.id = c.document_id
ORDER BY f.fused_score DESC
LIMIT :top_n
"""


@dataclass(frozen=True)
class ScoredSummary:
    """One retrieved summary, carrying enough to be cited.

    `document_name` and `section_id` are here rather than looked up later
    because a summary that cannot be cited is a summary the generator has to
    repeat from memory — the failure this whole index exists to fix.
    """

    summary_id: UUID
    document_id: UUID
    document_name: str | None
    section_id: UUID | None
    kind: str
    ord: int
    heading_path: str
    text: str
    vector_score: float | None
    bm25_score: float | None
    fused_score: float
    rerank_score: float | None = None

    def with_rerank(self, score: float) -> ScoredSummary:
        return replace(self, rerank_score=score)


def summaries_allowed_for(intent: str, *, corrective: bool = False) -> bool:
    """Whether this retrieval may include summaries at all.

    **First retrieval:** a gist intent only. A `lookup` never sees a summary,
    because a summary is the model's own words about a section rather than the
    section, and a lookup that cited one would put a paraphrase in the
    citation trail the user clicks.

    **Corrective retrieval:** any intent. This is the one place the rule
    loosens, and deliberately: the corrective pass is the last chance a run
    gets after the gate failed, it is already the case where the evidence was
    too thin, and a summary is ordinary in-scope evidence retrieved under
    ordinary ownership rules. A failed lookup that finds the answer in a
    document summary has answered a question the corpus could answer; the
    alternative is an abstention that says it could not.

    An intent this function has never heard of is a lookup on the first
    retrieval (see `GIST_INTENTS`).
    """
    return True if corrective else intent in GIST_INTENTS


async def search_summaries(
    session: AsyncSession,
    *,
    query_text: str,
    query_embedding: list[float],
    ownership: Ownership,
    filters: ClientFilters | None = None,
    lexical_weight: float = 0.5,
) -> list[ScoredSummary]:
    """The §9.2 query over `summaries`, under the chunks' own scope.

    Returns an empty list when nothing is in scope, which is the normal state
    for a document ingested before the backfill reached it — not an error.
    """
    settings = get_settings()
    vec_limit = int(runtime_value("retrieval.vec_limit", VEC_LIMIT))
    lex_limit = int(runtime_value("retrieval.lex_limit", LEX_LIMIT))
    rrf_k = int(runtime_value("retrieval.rrf_k", RRF_K))
    top_n = int(runtime_value("retrieval.summary_top_n", SUMMARY_TOP_N))
    scope, params = build_scope(ownership, filters or ClientFilters(), ScopeTable.SUMMARIES)
    params.update(
        {
            "emb": "[" + ",".join(repr(v) for v in query_embedding) + "]",
            "q": query_text,
            "tok": LEX_TOKENIZER,
            "vec_limit": vec_limit,
            "lex_limit": lex_limit,
            "top_n": top_n,
            "vec_w": 1.0 - lexical_weight,
            "lex_w": lexical_weight,
        }
    )
    # int() keeps the SET literal injection-safe.
    await session.execute(
        text(f"SET LOCAL statement_timeout = {int(settings.retrieval_statement_timeout_ms)}")
    )
    try:
        rows = await session.execute(text(_SUMMARY_QUERY.format(scope=scope, rrf_k=rrf_k)), params)
    except DBAPIError as exc:
        if isinstance(exc.orig, asyncpg.QueryCanceledError):
            logger.warning("summary retrieval statement timeout")
            raise RetrievalTimeout from exc
        raise
    return [
        ScoredSummary(
            summary_id=row.id,
            document_id=row.document_id,
            document_name=row.document_name,
            section_id=row.section_id,
            kind=row.kind,
            ord=row.ord,
            heading_path=row.heading_path,
            text=row.text,
            vector_score=row.vector_score,
            bm25_score=row.bm25_score,
            fused_score=row.fused_score,
        )
        for row in rows
    ]


__all__ = [
    "GIST_INTENTS",
    "SUMMARY_KINDS",
    "SUMMARY_TOP_N",
    "ScoredSummary",
    "search_summaries",
    "summaries_allowed_for",
]
