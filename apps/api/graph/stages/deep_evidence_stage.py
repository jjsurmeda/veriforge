"""Deep mode's evidence gate and entity guard (R2b item 1).

Deep used to let the Controller's `sufficient` verdict decide everything:
once it said "enough", the run generated from whatever the hop loop had
gathered, with no evidence floor and no mismatch guard. That is one gap
behind Auto (ADR-006): Auto gates on the rerank rubric's answer-containment
mean-of-top-3 before it will generate at all, and keeps the entity guard
beside it. This stage brings Deep under the same floor and the same guard,
so a multi-hop run that collected only off-topic passages declines instead
of generating.

**No threshold is moved and nothing new is calibrated** — this reuses the
evidence floor's own threshold (`evidence_floor`, `jev`) and the entity
guard's (`entity_match`, `jev`), computed by the same pure functions in
`checks.py` that Auto's gate uses.

The gate runs after the Controller's last hop has said `sufficient`: the hop
loop's corrective mechanism when evidence is thin is *another controlled
hop*, not Auto's single re-query retry, so a below-floor reading here
declines rather than looping — the Controller has already spent the hop and
credit budget deciding the evidence was enough, and letting the gate open
the hop loop again would spend it twice.

The guard runs after expansion, over the top passages the run would actually
answer from, in one `entity`-kind DecisionEngine call. An unreachable
decision layer is a failing guard (KI-57, fail-closed): "no reading" is not
coverage, so the run declines with the normal abstention instead of
generating from an uncheckable one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from decisions import threshold
from decisions.engine import DecisionUnavailable, EngineProtocol
from graph.stages.checks import (
    TOP_CHUNKS_FOR_CHECKS,
    _entity_passage_decision,
    _entity_passage_questions,
    named_entities,
    rubric_gate_passes,
    rubric_grades,
    rubric_mean_top3,
)
from graph.stages.common import unavailable_event
from graph.stages.evidence_stage import gate_event
from retrieval.expand import ExpandedContext
from retrieval.hybrid import ScoredChunk
from schemas.decisions import Answer, Question
from schemas.events import Decision

#: The DecisionCall kind the guard's batched call records, so a trace can
#: tell Deep's guard apart from the conflict/evidence batch Auto runs over
#: the same kind of questions.
ENTITY_KIND = "entity"


@dataclass
class GateVerdict:
    """The gate's number and the row that carries it into the trace.

    Published on the bus from `run_deep` (Auto does not publish its computed
    gate row because the retry loop's rows tell the story; Deep has no retry
    rows, so the trace needs this one explicitly).
    """

    passes: bool
    mean_top3: float | None
    floor: float
    decision: Decision


def deep_gate_decision(run_id: UUID, winners: list[ScoredChunk]) -> GateVerdict:
    """The evidence floor over Deep's merged hop winners.

    The same arithmetic as Auto's gate: the mean answer-containment grade of
    the best three post-hop passages (`checks.rubric_mean_top3`), compared
    against the evidence floor. Nothing was gathered (`winners` empty) reads
    as `None`, which is a failing gate the same way an unreadable grade is:
    "the Controller said sufficient but nothing was graded" declines.
    """
    grades = rubric_grades(winners)
    mean_top3 = rubric_mean_top3(grades)
    floor = threshold("evidence_floor", "jev")
    passes = rubric_gate_passes(mean_top3, floor)
    decision = gate_event(
        run_id,
        mean_top3,
        floor,
        reasoning=(
            "mean answer-containment grade of the best three passages across "
            "all hops; below the floor Deep declines instead of generating"
        ),
    )
    return GateVerdict(passes=passes, mean_top3=mean_top3, floor=floor, decision=decision)


@dataclass
class EntityVerdict:
    """The guard's verdict and the trace rows it produced.

    `events` holds the rows the engine emitter could never have published —
    the outage rows (KI-57). An answered call's rows are emitted by the
    engine's own event emitter on the product path, and appended to the run's
    `decision_events` by the caller, so publishing any of them here again
    would double the bus trace.
    """

    ok: bool
    max_reading: float | None
    entity_names: list[str]
    events: list[Decision] = field(default_factory=list)


async def deep_entity_guard(
    engine: EngineProtocol,
    *,
    run_id: str,
    question: str,
    contexts: list[ExpandedContext],
    decisions: list[Decision] | None = None,
) -> EntityVerdict:
    """Does the gathered evidence cover every entity the question names?

    The same guard Auto runs beside its gate, over the same
    (top passage, named entity) Noul questions, batched into one call. No
    named entity, nothing to guard. An outage fails the guard: every question
    it could not read gets an `unavailable` row, appended to `decisions` and
    returned in `events` for the caller to publish.
    """
    entity_names = named_entities(question)
    questions = _entity_passage_questions(
        question, entity_names, contexts[: TOP_CHUNKS_FOR_CHECKS]
    )
    if not questions:
        return EntityVerdict(ok=True, max_reading=None, entity_names=entity_names)
    try:
        # The guard only asks Nouls; the union dict is what `EngineProtocol`
        # takes.
        asked: dict[str, Question] = dict(questions)
        answers = await engine.decide(
            state={"run_id": run_id, "kind": ENTITY_KIND}, questions=asked
        )
    except DecisionUnavailable:
        rows = [
            # `unavailable_event` leaves the stage unset (the kinds Auto's
            # batched evidence call is published under come from elsewhere);
            # the guard's rows are marked `entity` so the trace can tell
            # which stage could not be read.
            unavailable_event(UUID(run_id), name, question) for name, question in questions.items()
        ]
        for row in rows:
            row.stage = ENTITY_KIND
        if decisions is not None:
            decisions.extend(rows)
        return EntityVerdict(
            ok=False, max_reading=None, entity_names=entity_names, events=rows
        )
    ok, max_reading = _entity_passage_decision(
        answers,
        list(questions),
        len(entity_names),
        threshold("entity_match", "jev"),
    )
    if decisions is not None:
        # The answered rows land here for the eval export and any persistence
        # that reads `decision_events`; on the product path the engine's own
        # event emitter is what puts them on the bus (the guard is one
        # `engine.decide` like any other).
        decisions.extend(
            _guard_row(run_id, name, answers[name]) for name in questions
        )
    return EntityVerdict(ok=ok, max_reading=max_reading, entity_names=entity_names)


def _guard_row(run_id: str, name: str, answer: Answer) -> Decision:
    """The per-question guard trace row, its stage marked `entity` — the
    trace's way to tell this call apart from the mixed batch Auto sends as
    `evidence`. The threshold is keyed by the engine that actually answered,
    as `usefulness_stage` does for IsUse."""
    floor = threshold("entity_match", "fallback" if answer.engine == "fallback" else "jev")
    return Decision(
        run_id=run_id,
        name=name,
        value=answer.value,
        probability=answer.probability,
        probabilities=answer.probabilities,
        engine=answer.engine,
        latency_ms=answer.latency_ms,
        reasoning=answer.reasoning,
        stage=ENTITY_KIND,
        threshold=floor,
    )
