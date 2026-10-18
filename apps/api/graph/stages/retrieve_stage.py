"""Retrieve stage (TRD §7): the multi-query fan-out.

One embedding call for every query, then one hybrid search per query on its
own session, fused by reciprocal rank. Each of those steps publishes its own
label inside the outer `retrieve` step, so the trace shows the work as it
happens rather than after the fact.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace as dc_replace
from functools import partial
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from graph.ingress import IngressOutcome
from graph.rewrite import CompleteFn, is_query_shape
from graph.stages.state import AutoRunInput, AutoRunState, StageEnv
from retrieval.cache import get_query_embeddings
from retrieval.filters import Ownership
from retrieval.hybrid import ScoredChunk, hybrid_search
from retrieval.summaries import ScoredSummary, search_summaries, summaries_allowed_for
from retrieval.web import ensure_web_chunks
from schemas.events import Retrieval, RetrievedChunk

EXCERPT_CHARS = 240

#: How a summary candidate identifies itself in the pool. Not a `chunks`
#: `source_type` (it is not a passage and must never be confused with one in a
#: citation), and its own string so a filter or a UI can tell the two apart.
SUMMARY_SOURCE_TYPE = "summary"

#: UUIDv5 namespace for the synthetic candidate id of a summary row. Fixed for
#: ever: changing it would change every summary's id, and the ids are written
#: into trace events.
NAMESPACE_SUMMARY = NAMESPACE_URL
MULTI_QUERY_VARIANTS = 3
# A multi-part question ("... and how does she answer?") retrieves on the
# whole question as one query, so the part after the "and" is out of the
# question the embedding encodes and its chunks never surface. One extra
# small-role call lists the parts; each becomes its own retrieval and, through
# `provenance`, its own equal share of the top-k in the rerank stage.
# Parts-only instruction: the phrasings call above already produced the
# compound rephrasings, so asking for them again here made compliant models
# emit phrasings first and parts last — and a parser that stopped at the
# phrasings brought every "part" back compound.
MULTI_PART_VARIANTS = 3
MULTI_PARTS = (
    "The question above has more than one part. List each part of the "
    "question restated as a standalone search query that keeps that part's "
    "own subject, one per line. Do not answer them and do not merge them. "
    "No commentary."
)


async def ensure_web_sources(env: StageEnv, state: AutoRunState) -> None:
    """Index web chunks for a web/both source, in their own committed
    transaction.

    It must commit before the fan-out below: those searches run on their own
    sessions, and a session cannot see another session's uncommitted rows — so
    web chunks this run indexes inside the run's transaction would be invisible
    to every one of them.
    """
    source_filter = env.params.source
    if env.params.source == "auto":
        source_filter = state.ingress.source
    if source_filter not in {"web", "both"}:
        return
    async with env.session_factory() as web_session, web_session.begin():
        await ensure_web_chunks(
            web_session,
            query=env.params.question,
            chat_id=env.params.chat_id,
            optional=source_filter == "both",
        )


async def retrieve_queries(
    env: StageEnv, state: AutoRunState, query: str
) -> tuple[list[ScoredChunk], list[Retrieval], dict[UUID, str]]:
    """Every query for this attempt, their searches, and the fused set.

    Returns the fused chunks, one `Retrieval` event per query, and the
    provenance map that tells the rerank stage which query surfaced each chunk.
    """
    variants, part_queries = await _queries_for(env, state, query)
    # TRD §9.1 step 6: the gist-question index joins the pool for a `summarize`
    # question, and for the corrective retrieval of any question (see
    # `summaries_allowed_for`). `loop.current_query` changes between attempts,
    # so this is re-decided per attempt rather than once per run — the first
    # attempt of a gist question and its corrective pass want the same index.
    with_summaries = summaries_allowed_for(state.ingress.intent, corrective=state.corrective)
    # TRD §7.1: one embedding call for every query, and the searches
    # themselves in parallel. Each search runs on its OWN session from the
    # factory — one AsyncSession cannot run concurrent statements.
    embeddings = await env.variant_step(
        f"embed queries ({len(variants)})",
        partial(get_query_embeddings, env.session, variants),
    )
    result_sets: list[list[ScoredChunk]] = await asyncio.gather(
        *(
            # One published sub-step per query, so the trace shows the fan-out
            # as it runs rather than one opaque `retrieve` that appears only
            # when it is already over.
            env.variant_step(
                f"retrieve: {variant}",
                partial(
                    _search_one_variant_on_own_session,
                    env.session_factory,
                    variant,
                    embedding=embedding,
                    env=env,
                    state=state,
                    with_summaries=with_summaries,
                ),
            )
            for variant, embedding in zip(variants, embeddings, strict=True)
        )
    )
    events: list[Retrieval] = []
    provenance: dict[UUID, str] = {}
    for variant, fused in zip(variants, result_sets, strict=True):
        if variant in part_queries:
            for chunk in fused:
                provenance.setdefault(chunk.chunk_id, variant)
        events.append(_retrieval_event(env, variant, fused))
    return _fuse_multi_query(result_sets), events, provenance


async def _queries_for(
    env: StageEnv, state: AutoRunState, query: str
) -> tuple[list[str], list[str]]:
    """The queries to retrieve on, and the subset that came from a part or a
    named entity rather than from the rewriter.

    There is deliberately no setting to skip the phrasings call: the measured
    variant of that switch collapsed fast20's answer rate from 0.917 to 0.083
    while every confidence metric went up, so no eval gate would have caught
    it. A single-hop lookup does not "already retrieve well" on this corpus.
    """
    variants = await env.variant_step(
        "query variants",
        partial(
            _generate_query_variants,
            query,
            env.params.small_model,
            env.seams.complete,
            MULTI_QUERY_VARIANTS,
        ),
    )
    parts: list[str] = []
    if state.ingress.intent == "multi-part":
        parts = await env.variant_step(
            "query parts",
            partial(
                _generate_query_variants,
                query,
                env.params.small_model,
                env.seams.complete,
                MULTI_PART_VARIANTS,
                instruction=MULTI_PARTS,
            ),
        )
    part_queries = [
        candidate
        for candidate in (
            *_entity_queries(env.params.question, state.ingress.intent),
            *parts,
        )
        if candidate not in variants
    ]
    return [*variants, *part_queries], part_queries


async def _generate_query_variants(
    question: str,
    small_model: str,
    complete_fn: CompleteFn,
    n: int,
    instruction: str | None = None,
) -> list[str]:
    """Multi-query rewrite (TRD §7 mode table, Auto only). n variants in
    one LLM call; first variant is the rewritten query itself. With
    `instruction` the call asks for that shape instead (see MULTI_PARTS),
    so the parsed lines are returned as-is, without the question seeded."""
    if n <= 1 and instruction is None:
        return [question]
    from prompts.load import load_prompt

    prompt_template = load_prompt("rewrite.md")
    prompt = prompt_template.format(
        summary="(none — query-variant generation)",
        history="(none)",
        question=question,
    )
    if instruction is None:
        prompt += (
            f"\n\nProduce {n} alternative phrasings of the rewritten question, "
            f"one per line. Each should target a different retrieval angle "
            f"(synonyms, narrower scope, broader scope). No commentary."
        )
    else:
        prompt += f"\n\n{instruction}"
    response = await complete_fn(
        litellm_model=small_model,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": question}],
        metadata={"role": "rewriter"},
    )
    variants = [question] if instruction is None else []
    for line in response.strip().splitlines():
        line = line.strip().lstrip("0123456789.-) ")
        # Every line of a rewriter reply is rewriter output, so the rewrite's
        # output contract (graph/rewrite.is_query_shape) applies to each of
        # them. KI-73's run put TWO prose replies into the retrieval set from
        # this parser, not one from `rewrite_query` alone, so checking only the
        # rewrite would have left the recorded failure half-open.
        if line and is_query_shape(line) and line not in variants:
            variants.append(line)
        if len(variants) >= n:
            break
    return variants[:n]


def _entity_queries(question: str, intent: str) -> list[str]:
    """One retrieval per named entity in a compare question.

    The capitalised-noun regex misses ALL-CAPS titles, quoted names and
    lowercase proper nouns, and treats a sentence-initial word as a name; the
    entities the evidence stage finds are the better source when compare
    coverage matters.
    """
    if intent != "compare":
        return []
    entities = [
        re.sub(r"^(?:Compare|How|What|Why|When|Where|Who)\s+", "", entity)
        for entity in re.findall(r"\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|the))*(?=\b)", question)
        if entity not in {"Compare", "How", "What", "Why", "When", "Where", "Who"}
    ]
    return list(dict.fromkeys(entities))


def _fuse_multi_query(result_sets: list[list[ScoredChunk]]) -> list[ScoredChunk]:
    """Reciprocal-rank fusion across query results."""
    if not result_sets:
        return []
    if len(result_sets) == 1:
        return result_sets[0]
    rrf_k = 60
    fused: dict[UUID, tuple[ScoredChunk, float]] = {}
    for chunks in result_sets:
        for rank, chunk in enumerate(chunks, start=1):
            score = 1.0 / (rrf_k + rank)
            if chunk.chunk_id in fused:
                existing, existing_score = fused[chunk.chunk_id]
                fused[chunk.chunk_id] = (existing, existing_score + score)
            else:
                fused[chunk.chunk_id] = (chunk, score)
    ordered = sorted(fused.values(), key=lambda item: item[1], reverse=True)
    return [dc_replace(chunk, fused_score=score) for chunk, score in ordered]


def _ownership(params: AutoRunInput) -> Ownership:
    """The scope every search of this run runs under (ADR-002)."""
    return Ownership(
        user_id=params.user_id,
        collection_ids=list(params.collection_ids),
        chat_id=params.chat_id,
    )


async def _search_one_variant(
    session: AsyncSession,
    variant: str,
    *,
    embedding: list[float],
    params: AutoRunInput,
    ingress: IngressOutcome,
) -> list[ScoredChunk]:
    """One query's hybrid search, with the ownership filter injected here
    (CLAUDE.md: every retrieval query gets its ownership filter server-side,
    and `params.client_filters` may only narrow it)."""
    return await hybrid_search(
        session,
        query_text=variant,
        query_embedding=embedding,
        ownership=_ownership(params),
        filters=params.client_filters,
        lexical_weight=ingress.lexical_weight,
    )


async def _search_one_variant_on_own_session(
    session_factory: async_sessionmaker[AsyncSession],
    variant: str,
    *,
    embedding: list[float],
    env: StageEnv,
    state: AutoRunState,
    with_summaries: bool,
) -> list[ScoredChunk]:
    """One query's search on its OWN session, so the fan-out can run
    concurrently (one AsyncSession cannot run two statements at once).

    Read-only, so it needs no explicit transaction: the `async with` rolls
    back on the way out and there is nothing to commit. The rest of the run
    keeps its single transaction.

    `with_summaries` adds the gist-question index (TRD §9.1 step 6) to the same
    candidate pool, not as a second result set — the reranker grades one pool,
    and two pools would mean two gates. See `as_candidates` for how a summary
    row becomes something the rest of the pipeline can carry.
    """
    async with session_factory() as session:
        chunks = await env.seams.hybrid_search(
            session,
            query_text=variant,
            query_embedding=embedding,
            ownership=_ownership(env.params),
            filters=env.params.client_filters,
            lexical_weight=state.ingress.lexical_weight,
        )
        if not with_summaries:
            return chunks
        summaries = await search_summaries(
            session,
            query_text=variant,
            query_embedding=embedding,
            ownership=_ownership(env.params),
            filters=env.params.client_filters,
            lexical_weight=state.ingress.lexical_weight,
        )
        return _merge_summaries(chunks, summaries)


def _merge_summaries(
    chunks: list[ScoredChunk], summaries: list[ScoredSummary]
) -> list[ScoredChunk]:
    """Summaries into the chunk pool, at the fused score they earned.

    **A summary is a candidate, not a citation target.** It is presented to the
    reranker (so the rubric can grade whether it answers the question) and to
    the gate, and it appears in the trace — but its synthetic `chunk_id` matches
    no row in `chunks`, so if the generator cites one the citation's
    `chunk_id` is written NULL and the Sources tab names the document and
    section from the citation's own columns.

    That is a real trade and it is the price of the index: RAPTOR's answer is
    that the summary *is* the evidence, and a system that refuses to let it be
    cited cannot use it for a gist question. The alternative — summaries that
    inform the gate but never reach the generator — would leave every
    `broad-*` item declining for the same reason it does today.

    Interleaved by fused score rather than appended, so a strong summary
    outranks a weak passage and a weak one does not displace the passages a
    lookup needed.
    """
    if not summaries:
        return chunks
    pool = list(chunks)
    for summary in summaries:
        pool.append(
            ScoredChunk(
                chunk_id=summary_candidate_id(summary.summary_id),
                document_id=summary.document_id,
                document_name=summary.document_name,
                section_id=summary.section_id,
                ord=summary.ord,
                page=None,
                text=summary.text,
                heading_path=summary.heading_path or None,
                source_type=SUMMARY_SOURCE_TYPE,
                vector_score=summary.vector_score,
                bm25_score=summary.bm25_score,
                fused_score=summary.fused_score,
            )
        )
    return sorted(pool, key=lambda c: c.fused_score, reverse=True)


def summary_candidate_id(summary_id: UUID) -> UUID:
    """A stable synthetic chunk id for a summary candidate.

    Derived, not random, so the same summary has the same id across the run's
    two retrieval attempts and across a re-run — otherwise the reranker's
    per-candidate bookkeeping and the multi-query fusion would each treat one
    summary as several different passages.
    """
    return uuid5(NAMESPACE_SUMMARY, str(summary_id))


def _retrieval_event(env: StageEnv, variant: str, chunks: list[ScoredChunk]) -> Retrieval:
    return Retrieval(
        run_id=str(env.params.run_id),
        hop=0,
        query=variant,
        chunks=[
            RetrievedChunk(
                chunk_id=str(chunk.chunk_id),
                document_id=str(chunk.document_id) if chunk.document_id else None,
                document_name=chunk.document_name,
                page=chunk.page,
                heading_path=chunk.heading_path,
                source_type=chunk.source_type,
                excerpt=chunk.text[:EXCERPT_CHARS],
                vector_score=chunk.vector_score,
                bm25_score=chunk.bm25_score,
                fused_score=chunk.fused_score,
                rerank_score=chunk.rerank_score,
                dropped=False,
            )
            for chunk in chunks
        ],
    )
