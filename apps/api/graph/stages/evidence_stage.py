"""Evidence stage (TRD §7): is the retrieved evidence clearly absent?

**The floor is the reranker's answer-containment grade** (ADR-006, accepted
2026-10-17): the mean grade of the best three post-sanitize passages, over the
rubric in `retrieval/rerank.py`. That is the whole pre-generation decision — a
computed number, not a second model question. The old `sufficient` Noul is gone
from the path entirely: its threshold, its decision row, its admin key and its
question are all removed, because the one case where it could be checked against
a known label (`cf-k9-charge`) it read "sufficient" while the rubric and the
entity guard both said the passages did not answer.

The entity guard stays beside the floor as a mismatch guard, and the conflict
pairs ride the same post-sanitize call. It is defense-in-depth rather than
load-bearing: the KI-57 sanitizer fix (fail-closed, drop ungraded chunks)
collapsed the once-relevant entity-mismatch readings below the floor, so the
entity guard no longer has to block sets the floor already blocks.

The floor is calibrated, not chosen, and it is NOT a decline classifier
(`decisions/thresholds.py` carries the derivation table): only the clearly-
absent band below 0.455 keeps a run from generating. Everything else generates
and is classified after generation — IsUse (ADR-006) decides whether the
delivered answer answers the question, and `plan_delivery` decides whether it
streams first.

Below the floor the run makes **one** corrective retrieval — a rewritten or
decomposed query, and the section summaries from TRD §9.1 step 6 when the
question is a gist one or when the correction is the second chance — grades
again, and then answers or abstains. Answer-first, so never more than one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from uuid import UUID

from decisions import threshold
from graph import rewrite as rewrite_node
from graph.stages.checks import (
    RETRY_SKIP_RUBRIC_MAX,
    TOP_CHUNKS_FOR_CHECKS,
    _conflict_pair_questions,
    _conflict_sides,
    _entity_passage_decision,
    _entity_passage_questions,
    _evidence_clearly_absent,
    named_entities,
    rubric_gate_passes,
    rubric_grades,
    rubric_mean_top3,
)
from graph.stages.common import decide_or_degrade, unavailable_event
from graph.stages.rerank_stage import add_rerank_scores
from graph.stages.retrieve_stage import retrieve_queries
from graph.stages.sanitize_stage import sanitize
from graph.stages.state import AutoRunState, StageEnv
from retrieval.expand import ExpandedContext, dedupe_adjacent, expand_context
from retrieval.hybrid import ScoredChunk
from retrieval.rerank import RERANK_TOP_N, RerankProvider
from schemas.decisions import Answer, Choice, Noul, Score
from schemas.events import Decision, Retrieval

# Answer-first: one retrieve, and below the gate floor exactly one corrective
# retrieval before abstaining. The corrective loop clamps any admin override to
# this.
MAX_SUFFICIENT_RETRIES = 1


@dataclass
class Attempt:
    """What one pass over the evidence stages produced. The last attempt is
    the one the answer is delivered from, so its conflict sides and its gate
    verdict are the ones that reach the run."""

    winners: list[ScoredChunk]
    expanded: list[ExpandedContext]
    sides: list[ScoredChunk]
    sanitize_dropped: list[ScoredChunk]
    batched_pairs: bool
    batched_conflict_answers: dict[str, Answer] = field(default_factory=dict)
    # The gate's own number, the threshold it was compared against, and the
    # engine whose rubric produced it.
    gate_mean_top3: float | None = None
    gate_floor: float = 0.0
    gate_engine: str = "jev"
    # The batched evidence call (entity + conflict) answered nothing this pass
    # (KI-57). Kept apart from `gate_mean_top3 is None` because the trace needs
    # to say "nobody could check the entities" rather than "the rubric graded it
    # 0", and because the rerank rubric itself may have graded fine.
    gate_unavailable: bool = False
    entity_ok: bool = True
    entity_max: float | None = None
    entity_names: list[str] = field(default_factory=list)

    @property
    def enough(self) -> bool:
        """One gate (ADR-006) and one mismatch guard beside it."""
        return rubric_gate_passes(self.gate_mean_top3, self.gate_floor) and self.entity_ok

    @property
    def clearly_absent(self) -> bool:
        return _evidence_clearly_absent(
            gate_mean_top3=self.gate_mean_top3,
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
        # The next `retrieve_queries` is the corrective one, and that is what
        # lets any intent reach the summary index (TRD §9.1 step 6). Recorded on
        # the state rather than threaded as an argument because the retrieve
        # stage's signature is the fan-out, and a second flag argument there
        # would invite the two call sites to disagree about it.
        state.corrective = True
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
        : int(env.seams.runtime_value("retrieval.top_k", TOP_CHUNKS_FOR_CHECKS))
    ]
    attempt.entity_names = named_entities(loop.current_query)
    entity_questions = _entity_passage_questions(
        loop.current_query, attempt.entity_names, top_for_check
    )
    attempt.sides = _conflict_sides(attempt.winners)
    questions: dict[str, Noul | Choice | Score] = {
        **entity_questions,
        **(
            _conflict_pair_questions(attempt.sides, env.params.question)
            if attempt.batched_pairs
            else {}
        ),
    }
    answers = await env.step(
        "evidence",
        partial(decide_or_degrade, env, "evidence", questions),
    )
    _read_answers(env, state, attempt, loop.reranker, answers, entity_questions)
    return attempt


def _read_answers(
    env: StageEnv,
    state: AutoRunState,
    attempt: Attempt,
    reranker: RerankProvider,
    answers: dict[str, Answer],
    entity_questions: dict[str, Noul],
) -> None:
    """Turn the rerank scores and the batched answers into the attempt's verdicts.

    **The gate is the rubric**, read off `attempt.winners`: `answer_containment_score`
    already turned each passage's distribution into the expected level that
    `rerank_score` carries, so the gate is arithmetic over numbers the reranker
    produced, not a new model question. `sufficient` no longer exists; the only
    things the batched call still asks are the entity guard and the conflict
    pairs.

    **No entity reading at all is a failing guard** (KI-57), not an error. When
    the batched call comes back empty and there were entity questions, the
    decision layer was unreachable: "no passage could be confirmed to cover the
    entity" is not coverage, so the guard fails and the run corrects once and
    then abstains. The gate's own number is unaffected, because the rubric came
    from the rerank call, not this one.
    """
    attempt.batched_conflict_answers = {
        name: answer for name, answer in answers.items() if name.startswith("conflict_")
    }
    attempt.gate_engine = _gate_engine(reranker)
    grades = rubric_grades(attempt.winners)
    attempt.gate_mean_top3 = rubric_mean_top3(grades)
    attempt.gate_floor = threshold("evidence_floor", "jev")
    state.decision_events.append(
        gate_event(
            env.params.run_id, attempt.gate_mean_top3, attempt.gate_floor, attempt.gate_engine
        )
    )

    attempt.gate_unavailable = bool(entity_questions) and not answers
    if attempt.gate_unavailable:
        for name, question in entity_questions.items():
            state.decision_events.append(unavailable_event(env.params.run_id, name, question))
        attempt.entity_ok = False
        attempt.entity_max = None
        return
    if entity_questions:
        attempt.entity_ok, attempt.entity_max = _entity_passage_decision(
            answers,
            entity_questions,
            len(attempt.entity_names),
            threshold("entity_match", "jev"),
        )


def _gate_engine(reranker: RerankProvider) -> str:
    """Which engine's rubric produced the gate number.

    The gate is computed from `rerank_score`, so its engine is the reranker's.
    `JevRerank` records what actually answered each passage; the other providers
    (Cohere, NVIDIA, fused order) have no decision engine and are reported as
    `jev` — the display scale the trace is calibrated for. A rerank outage
    degrades to fused order, and then the sanitizer drops the ungraded chunks so
    a fabricated fused score cannot become a passing gate.
    """
    answered: set[str] = getattr(reranker, "answered_by", set())
    if "fallback" in answered and "jev" not in answered:
        return "fallback"
    return "jev"


def gate_event(
    run_id: UUID,
    mean_top3: float | None,
    floor: float,
    engine: str = "jev",
    reasoning: str | None = None,
) -> Decision:
    """The trace row for the gate itself — the one number that decided.

    Named `evidence` because it is the evidence gate, and its `stage` is `gate`.
    Its `value` is the mean answer-containment grade. Shared with Deep's gate
    (`graph/stages/deep_evidence_stage.py`), which passes its own `reasoning`
    because Deep's corrective mechanism is the next controller hop, not the
    Auto retry loop.
    """
    return Decision(
        run_id=str(run_id),
        name="evidence",
        value=mean_top3 if mean_top3 is not None else 0.0,
        probability=mean_top3,
        probabilities=None,
        engine=engine,
        latency_ms=0,
        stage="gate",
        threshold=floor,
        reasoning=(
            reasoning
            if reasoning is not None
            else (
                "mean answer-containment grade of the best three passages; "
                "below the floor the run corrects once and then abstains"
            )
        ),
    )



def _retry_skipped_event(env: StageEnv, attempt: Attempt) -> Decision:
    """Recorded as a decision so the trace says why this run declined without
    a retry.

    The row carries the **gate's** number, because the gate is what the skip is
    decided against. When the entity check could not be read (KI-57) the row
    says so in both its engine and its reasoning: a `retry_skipped` reading 0.0
    from `jev` says "the evidence was judged clearly absent", and that is not
    what happened.
    """
    value = attempt.gate_mean_top3 if attempt.gate_mean_top3 is not None else 0.0
    if attempt.gate_unavailable:
        return Decision(
            run_id=str(env.params.run_id),
            name="retry_skipped",
            value=value,
            probability=value,
            probabilities=None,
            engine="unavailable",
            latency_ms=0,
            stage="gate",
            threshold=RETRY_SKIP_RUBRIC_MAX,
            reasoning=(
                "the decision layer was unreachable, so the entity guard could "
                "not be read; the corrective re-query would reach the same "
                "outage and 13-15 s later"
            ),
        )
    return Decision(
        run_id=str(env.params.run_id),
        name="retry_skipped",
        value=value,
        probability=value,
        probabilities=None,
        engine=attempt.gate_engine,
        latency_ms=0,
        stage="gate",
        threshold=RETRY_SKIP_RUBRIC_MAX,
        reasoning=(
            "the rubric gate and the entity check were both far below their "
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
