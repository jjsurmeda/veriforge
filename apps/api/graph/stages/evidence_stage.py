"""Evidence stage (TRD §7): does the retrieved evidence answer the question?

One attempt is rerank → sanitize → relevance veto → sufficiency → entity
check, with the conflict pairs batched into the same DecisionEngine call as
sufficiency. Below the floors the run retries once with a fresh rewrite and a
full re-retrieve — answer-first, so never more than one — and skips the retry
only when every signal sits far below its floor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import Literal
from uuid import UUID

from decisions import threshold
from graph import rewrite as rewrite_node
from graph.stages.checks import (
    RETRY_SKIP_SUFFICIENT_MAX,
    TOP_CHUNKS_FOR_SUFFICIENT,
    _conflict_pair_questions,
    _conflict_sides,
    _entity_passage_decision,
    _entity_passage_questions,
    _evidence_clearly_absent,
    _sufficient_question,
    named_entities,
    relevance_decision_event,
)
from graph.stages.common import decision_event
from graph.stages.rerank_stage import add_rerank_scores
from graph.stages.retrieve_stage import retrieve_queries
from graph.stages.sanitize_stage import sanitize
from graph.stages.state import AutoRunState, StageEnv
from retrieval.expand import ExpandedContext, dedupe_adjacent, expand_context
from retrieval.hybrid import ScoredChunk
from retrieval.rerank import RERANK_TOP_N, JevRerank, RerankProvider
from schemas.decisions import Answer, Noul
from schemas.events import Decision, Retrieval

# Answer-first: one retrieve, and below the sufficient_abstain floor exactly
# one rewrite + retry before abstaining. The retry loop clamps any admin
# override to this.
MAX_SUFFICIENT_RETRIES = 1


@dataclass
class Attempt:
    """What one pass over the evidence stages produced. The last attempt is
    the one the answer is delivered from, so its conflict sides and its
    sufficiency verdict are the ones that reach the run."""

    winners: list[ScoredChunk]
    expanded: list[ExpandedContext]
    sides: list[ScoredChunk]
    sanitize_dropped: list[ScoredChunk]
    batched_pairs: bool
    batched_conflict_answers: dict[str, Answer] = field(default_factory=dict)
    p_sufficient: float = 0.0
    abstain_threshold: float = 0.0
    sufficient_engine: Literal["jev", "fallback"] = "jev"
    relevance_ok: bool = True
    relevance_max: float | None = None
    relevance_measured: bool = False
    entity_ok: bool = True
    entity_max: float | None = None
    entity_names: list[str] = field(default_factory=list)

    @property
    def enough(self) -> bool:
        """One bar: every signal must clear."""
        return (
            self.p_sufficient >= self.abstain_threshold
            and self.relevance_ok
            and self.entity_ok
        )

    @property
    def clearly_absent(self) -> bool:
        return _evidence_clearly_absent(
            p_sufficient=self.p_sufficient,
            relevance_max=self.relevance_max,
            relevance_measured=self.relevance_measured,
            entity_max=self.entity_max,
            entity_measured=bool(self.entity_names),
            entity_ok=self.entity_ok,
        )


@dataclass
class _Loop:
    """What the retry loop carries between attempts."""

    current_query: str
    reranker: RerankProvider
    retries_left: int


async def run_evidence(env: StageEnv, state: AutoRunState) -> Attempt:
    """Retrieve, grade the evidence, and retry once when the evidence is thin
    but not clearly absent. Returns the last attempt."""
    loop = _Loop(
        current_query=state.rewritten,
        reranker=env.seams.get_reranker(env.engine, str(env.params.run_id)),
        retries_left=min(
            int(env.seams.runtime_value("retrieval.retry_limit", MAX_SUFFICIENT_RETRIES)), 1
        ),
    )
    while True:
        fused, events, provenance = await env.step(
            "retrieve", partial(retrieve_queries, env, state, loop.current_query)
        )
        state.retrieval_events.extend(events)
        attempt = await _evaluate_attempt(env, state, loop, fused, provenance, events)
        if attempt.enough or loop.retries_left <= 0:
            return attempt
        if attempt.clearly_absent:
            state.retry_skipped = True
            state.decision_events.append(_retry_skipped_event(env, attempt))
            return attempt
        loop.retries_left -= 1
        loop.current_query = await _retry_rewrite(env, state)


async def _evaluate_attempt(
    env: StageEnv,
    state: AutoRunState,
    loop: _Loop,
    fused: list[ScoredChunk],
    provenance: dict[UUID, str],
    events: list[Retrieval],
) -> Attempt:
    """One pass: rerank, sanitize, then every evidence question in one call."""
    reranked = await env.step(
        "rerank",
        partial(
            env.seams.rerank_candidates,
            loop.reranker,
            query=loop.current_query,
            chunks=fused,
            provenance=provenance,
            limit=int(env.seams.runtime_value("retrieval.top_k", RERANK_TOP_N)),
        ),
    )
    add_rerank_scores(events, reranked)
    winners = dedupe_adjacent(reranked)
    winners, sanitize_dropped = await sanitize(env, state, winners)
    state.dropped_chunks.extend(sanitize_dropped)
    attempt = Attempt(
        winners=winners,
        expanded=[],
        sides=[],
        sanitize_dropped=sanitize_dropped,
        # The batched conflict questions were built over the pre-sanitize
        # winners, so a drop invalidates them and the pairs are re-asked over
        # what survived, in their own call after the loop.
        batched_pairs=not sanitize_dropped,
    )
    _apply_relevance_gate(env, state, loop, attempt)
    attempt.expanded = await expand_context(env.session, attempt.winners)
    top_for_check = attempt.expanded[
        : int(env.seams.runtime_value("retrieval.top_k", TOP_CHUNKS_FOR_SUFFICIENT))
    ]
    attempt.entity_names = named_entities(loop.current_query)
    entity_questions = _entity_passage_questions(
        loop.current_query, attempt.entity_names, top_for_check
    )
    attempt.sides = _conflict_sides(attempt.winners)
    answers = await env.step(
        "sufficient",
        partial(
            env.engine.decide,
            state={"run_id": str(env.params.run_id), "kind": "sufficient"},
            questions={
                "sufficient": _sufficient_question(loop.current_query, top_for_check),
                **entity_questions,
                **(
                    _conflict_pair_questions(attempt.sides, env.params.question)
                    if attempt.batched_pairs
                    else {}
                ),
            },
        ),
    )
    _read_answers(env, state, attempt, answers, entity_questions)
    return attempt


def _apply_relevance_gate(
    env: StageEnv, state: AutoRunState, loop: _Loop, attempt: Attempt
) -> None:
    """The second abstain signal, read off the rerank scores.

    `sufficient` can't separate answerable from unanswerable evidence, but the
    max rerank score of the post-sanitize winners can. Gated only on scores
    JevRerank answered: NVIDIA/Cohere use other scales, and fused order's top
    score is always 1.0. An outage (no passage got a real answer) skips the
    gate so it can never abstain.
    """
    reranker = loop.reranker
    if not isinstance(reranker, JevRerank):
        return
    relevance_engine = reranker.relevance_engine()
    if relevance_engine is None:
        return
    scores = [c.rerank_score for c in attempt.winners if c.rerank_score is not None]
    if not scores:
        return
    attempt.relevance_max = max(scores)
    attempt.relevance_measured = True
    relevance_threshold = threshold("rerank_abstain", relevance_engine)
    attempt.relevance_ok = attempt.relevance_max >= relevance_threshold
    # The gate measures question-to-passage *lexical overlap*, and "give me the
    # gist of X" matches no single passage. For a gist question the overlap
    # signal is not evidence of irrelevance, so the veto is waived and
    # `sufficient` and the entity check decide alone.
    exempt = state.ingress.intent == "summarize"
    if exempt:
        attempt.relevance_ok = True
    state.decision_events.append(
        relevance_decision_event(
            str(env.params.run_id),
            relevance_max=attempt.relevance_max,
            engine=relevance_engine,
            threshold_value=relevance_threshold,
            scored=len(scores),
            exempt=exempt,
        )
    )


def _read_answers(
    env: StageEnv,
    state: AutoRunState,
    attempt: Attempt,
    answers: dict[str, Answer],
    entity_questions: dict[str, Noul],
) -> None:
    """Turn the batched answers into the attempt's three verdicts."""
    attempt.batched_conflict_answers = {
        name: answer for name, answer in answers.items() if name.startswith("conflict_")
    }
    sufficient = answers["sufficient"]
    state.decision_events.append(decision_event(env.params.run_id, "sufficient", sufficient))
    attempt.p_sufficient = float(sufficient.value)
    attempt.abstain_threshold = threshold("sufficient_abstain", sufficient.engine)
    attempt.sufficient_engine = sufficient.engine
    if entity_questions:
        attempt.entity_ok, attempt.entity_max = _entity_passage_decision(
            answers,
            entity_questions,
            len(attempt.entity_names),
            threshold("entity_match", sufficient.engine),
        )


def _retry_skipped_event(env: StageEnv, attempt: Attempt) -> Decision:
    """Recorded as a decision so the trace says why this run declined without
    a retry."""
    return Decision(
        run_id=str(env.params.run_id),
        name="retry_skipped",
        value=attempt.p_sufficient,
        probability=attempt.p_sufficient,
        probabilities=None,
        engine=attempt.sufficient_engine,
        latency_ms=0,
        stage="sufficient",
        threshold=RETRY_SKIP_SUFFICIENT_MAX,
        reasoning=(
            "sufficiency, relevance and the entity check were all far below "
            f"their floors (relevance {attempt.relevance_max}); the rewrite + "
            "retry would not change the outcome"
        ),
    )


async def _retry_rewrite(env: StageEnv, state: AutoRunState) -> str:
    return await rewrite_node.rewrite_query(
        question=env.params.question,
        history=state.history,
        summary=state.summary,
        small_model=env.params.small_model,
        complete_fn=env.seams.complete,
    )
