"""Evidence stage (TRD §7): does the retrieved evidence answer the question?

**One** evidence check (ADR-006): the `sufficient` decision over the reranked
evidence, with the entity guard beside it as a mismatch guard rather than a
third veto. The relevance floor that used to sit between rerank and sufficiency
is gone — the reranker's answer-containment rubric (TRD §9.6) already ranks
passages by whether they answer, so a separate relevance score was a second,
separately calibrated judgement of the same thing, and the one ADR-006 removes.

Below the floor the run makes **one** corrective retrieval — a rewritten or
decomposed query, and the section summaries from TRD §9.1 step 6 for a gist
question — checks again, and then answers or abstains. Answer-first, so never
more than one. The corrective pass is skipped only when the evidence is clearly
absent, and that now needs the sufficiency and entity readings alone.
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
)
from graph.stages.common import decide_or_degrade, decision_event, unavailable_event
from graph.stages.rerank_stage import add_rerank_scores
from graph.stages.retrieve_stage import retrieve_queries
from graph.stages.sanitize_stage import sanitize
from graph.stages.state import AutoRunState, StageEnv
from retrieval.expand import ExpandedContext, dedupe_adjacent, expand_context
from retrieval.hybrid import ScoredChunk
from retrieval.rerank import RERANK_TOP_N, RerankProvider
from schemas.decisions import Answer, Choice, Noul, Score
from schemas.events import Decision, Retrieval

# Answer-first: one retrieve, and below the sufficient_abstain floor exactly
# one corrective retrieval before abstaining. The corrective loop clamps any
# admin override to this.
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
    # The decision layer answered nothing this pass (KI-57). Kept apart from
    # `p_sufficient == 0.0` because a real 0.0 is a judgement and this is an
    # absence of one, and the trace must not read as if it were the first.
    gate_unavailable: bool = False
    entity_ok: bool = True
    entity_max: float | None = None
    entity_names: list[str] = field(default_factory=list)

    @property
    def enough(self) -> bool:
        """One evidence check and one mismatch guard (ADR-006)."""
        return self.p_sufficient >= self.abstain_threshold and self.entity_ok

    @property
    def clearly_absent(self) -> bool:
        return _evidence_clearly_absent(
            p_sufficient=self.p_sufficient,
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
    attempt.expanded = await expand_context(env.session, attempt.winners)
    top_for_check = attempt.expanded[
        : int(env.seams.runtime_value("retrieval.top_k", TOP_CHUNKS_FOR_SUFFICIENT))
    ]
    attempt.entity_names = named_entities(loop.current_query)
    entity_questions = _entity_passage_questions(
        loop.current_query, attempt.entity_names, top_for_check
    )
    attempt.sides = _conflict_sides(attempt.winners)
    questions = {
        "sufficient": _sufficient_question(loop.current_query, top_for_check),
        **entity_questions,
        **(
            _conflict_pair_questions(attempt.sides, env.params.question)
            if attempt.batched_pairs
            else {}
        ),
    }
    answers = await env.step(
        "sufficient",
        partial(decide_or_degrade, env, "sufficient", questions),
    )
    _read_answers(env, state, attempt, answers, entity_questions, questions)
    return attempt


def _read_answers(
    env: StageEnv,
    state: AutoRunState,
    attempt: Attempt,
    answers: dict[str, Answer],
    entity_questions: dict[str, Noul],
    questions: dict[str, Noul | Choice | Score],
) -> None:
    """Turn the batched answers into the attempt's verdicts.

    **No reading at all is a failing gate** (KI-57), not an error. The
    decision layer being unreachable is not evidence that the corpus cannot
    answer, and it is certainly not evidence that it can, so the gate treats it
    the way it treats a low grade: below the floor, into the corrective
    retrieval, and — if the layer is still down — to an abstention that cites
    nothing. The entity guard fails with it, because "no passage could be
    confirmed to cover the entity" cannot be read as coverage.

    Both are recorded as `unavailable` decision rows rather than as low scores,
    so a trace cannot be read as a run that graded the question and got a bad
    grade.
    """
    attempt.batched_conflict_answers = {
        name: answer for name, answer in answers.items() if name.startswith("conflict_")
    }
    sufficient = answers.get("sufficient")
    if sufficient is None:
        state.decision_events.append(
            unavailable_event(env.params.run_id, "sufficient", questions["sufficient"])
        )
        for name, question in entity_questions.items():
            state.decision_events.append(unavailable_event(env.params.run_id, name, question))
        attempt.gate_unavailable = True
        attempt.p_sufficient = 0.0
        # The engine that would have answered is unknown, so the threshold is
        # read on the reference scale; at 0.0 every floor fails, which is the
        # intent.
        attempt.abstain_threshold = threshold("sufficient_abstain", "jev")
        attempt.sufficient_engine = "jev"
        if entity_questions:
            attempt.entity_ok = False
            attempt.entity_max = None
        return
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
    a retry.

    When the decision layer is the reason (KI-57) the row says so in both its
    engine and its reasoning: a `retry_skipped` reading 0.0 from `jev` says
    "the evidence was judged clearly absent", and that is not what happened.
    """
    if attempt.gate_unavailable:
        return Decision(
            run_id=str(env.params.run_id),
            name="retry_skipped",
            value=attempt.p_sufficient,
            probability=attempt.p_sufficient,
            probabilities=None,
            engine="unavailable",
            latency_ms=0,
            stage="sufficient",
            threshold=RETRY_SKIP_SUFFICIENT_MAX,
            reasoning=(
                "the decision layer was unreachable, so the evidence was never "
                "graded; the corrective re-query would reach the same outage and "
                "13-15 s later"
            ),
        )
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
            "sufficiency and the entity check were both far below their "
            "floors; the corrective re-query would not change the outcome"
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
