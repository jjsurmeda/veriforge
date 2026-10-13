"""Auto mode (TRD §7 mode table): the orchestrator.

The pipeline itself lives in `graph/stages/`, one module per stage, in the
order the run goes through them: ingress → rewrite/variants → retrieve →
rerank → sanitize → evidence → generate. This module owns the run's
transaction and binds the seams the stages call, so a test replaces one at
this boundary and every stage sees it.

Auto always runs this single-hop-with-multi-query-fusion path regardless of
ingress's `complexity` verdict — Plan/Hop/Controller multi-hop lives in Deep
mode (graph/deep.py, TRD §17 row 5), which the user reaches directly via the
mode picker rather than through an Auto complexity branch.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import Chat
from decisions import DecisionEngine
from graph import rewrite as rewrite_node
from graph.generate import (
    stream_chitchat_reply,
    stream_grounded_answer,
    stream_library_reply,
)
from graph.stages.checks import (
    CONFLICT_MAX_PAIRS,
    RETRY_SKIP_ENTITY_MAX,
    RETRY_SKIP_RELEVANCE_MAX,
    RETRY_SKIP_SUFFICIENT_MAX,
    SUFFICIENT_EVIDENCE_CHARS,
    TOP_CHUNKS_FOR_SUFFICIENT,
    _conflict_pair_questions,
    _conflict_sides,
    _entity_passage_decision,
    _entity_passage_questions,
    _evidence_clearly_absent,
    _sufficient_question,
    named_entities,
)
from graph.stages.evidence_stage import MAX_SUFFICIENT_RETRIES, run_evidence
from graph.stages.finish_stage import finish
from graph.stages.ingress_stage import (
    GREETING_ALLOWLIST,
    MAX_GREETING_CHARS,
    MAX_GREETING_WORDS,
    greeting_canonical,
    load_state,
    run_ingress_stage,
)
from graph.stages.rerank_stage import _rerank_candidates, add_rerank_scores
from graph.stages.retrieve_stage import (
    EXCERPT_CHARS,
    MULTI_PART_VARIANTS,
    MULTI_PARTS,
    MULTI_QUERY_VARIANTS,
    _entity_queries,
    _fuse_multi_query,
    _generate_query_variants,
    _search_one_variant,
    ensure_web_sources,
    retrieve_queries,
)
from graph.stages.state import (
    AutoRun,
    AutoRunInput,
    AutoRunState,
    StageEnv,
    StageSeams,
)
from graph.timing import EventPublisher, make_step_timer, make_sub_step_timer
from providers.llm import complete
from retrieval.hybrid import hybrid_search
from retrieval.rerank import get_reranker
from runtime import runtime_value

__all__ = [
    "CONFLICT_MAX_PAIRS",
    "EXCERPT_CHARS",
    "GREETING_ALLOWLIST",
    "MAX_GREETING_CHARS",
    "MAX_GREETING_WORDS",
    "MAX_SUFFICIENT_RETRIES",
    "MULTI_PARTS",
    "MULTI_PART_VARIANTS",
    "MULTI_QUERY_VARIANTS",
    "RETRY_SKIP_ENTITY_MAX",
    "RETRY_SKIP_RELEVANCE_MAX",
    "RETRY_SKIP_SUFFICIENT_MAX",
    "SUFFICIENT_EVIDENCE_CHARS",
    "TOP_CHUNKS_FOR_SUFFICIENT",
    "AutoRun",
    "AutoRunInput",
    "_conflict_pair_questions",
    "_conflict_sides",
    "_entity_passage_decision",
    "_entity_passage_questions",
    "_entity_queries",
    "_evidence_clearly_absent",
    "_fuse_multi_query",
    "_generate_query_variants",
    "_rerank_candidates",
    "_search_one_variant",
    "_sufficient_question",
    "add_rerank_scores",
    "ensure_web_sources",
    "finalize_auto_run",
    "greeting_canonical",
    "named_entities",
    "prepare_auto_run",
    "retrieve_queries",
]


def _seams() -> StageSeams:
    """The external functions the stages call, bound from this module's
    namespace so one `monkeypatch.setattr(graph.auto, ...)` reaches them all."""
    return StageSeams(
        complete=complete,
        hybrid_search=hybrid_search,
        get_reranker=get_reranker,
        rerank_candidates=_rerank_candidates,
        runtime_value=runtime_value,
        stream_grounded_answer=stream_grounded_answer,
        stream_chitchat_reply=stream_chitchat_reply,
        stream_library_reply=stream_library_reply,
    )


async def prepare_auto_run(
    session_factory: async_sessionmaker[AsyncSession],
    params: AutoRunInput,
    engine: DecisionEngine,
    *,
    publish: EventPublisher | None = None,
) -> AutoRun:
    """Run the stages in order; returns everything the runner needs to stream
    the answer."""
    latency_ms: dict[str, int] = {}
    async with session_factory() as session, session.begin():
        env = StageEnv(
            params=params,
            session=session,
            session_factory=session_factory,
            engine=engine,
            seams=_seams(),
            step=make_step_timer(
                node="auto", run_id=params.run_id, latency_ms=latency_ms, publish=publish
            ),
            variant_step=make_sub_step_timer(publish, node="auto", run_id=params.run_id),
            publish=publish,
            latency_ms=latency_ms,
        )
        state: AutoRunState = await load_state(env)
        direct = await run_ingress_stage(env, state)
        if direct is not None:
            return direct
        await ensure_web_sources(env, state)
        return await finish(env, state, await run_evidence(env, state))


async def finalize_auto_run(
    session_factory: async_sessionmaker[AsyncSession],
    run: AutoRun,
    *,
    generate_ms: int,
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Post-delivery: refresh the rolling summary if due."""
    async with session_factory() as session, session.begin():
        chat = await session.get(Chat, run.params.chat_id)
        await rewrite_node.maybe_refresh_summary(
            session,
            chat_id=run.params.chat_id,
            summary=chat.summary if chat is not None else None,
            small_model=run.params.small_model,
            complete_fn=complete,
        )
