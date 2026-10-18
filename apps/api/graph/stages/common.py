"""Small helpers every stage needs: a Decision event built from an answer, the
timed no-op that marks a step which legitimately makes no call, and the one
place a stage asks the decision layer for a verdict it can degrade on (KI-57).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from decisions.engine import DecisionUnavailable
from schemas.decisions import Answer, Choice, Noul, Question, Score
from schemas.events import Decision

if TYPE_CHECKING:  # `state` imports this module's siblings, so a runtime import
    from graph.stages.state import StageEnv  # would be circular.

logger = logging.getLogger(__name__)


def decision_event(run_id: UUID, name: str, answer: Answer) -> Decision:
    """The trace row for one decision the engine answered."""
    return Decision(
        run_id=str(run_id),
        name=name,
        value=answer.value,
        probability=answer.probability,
        probabilities=answer.probabilities,
        engine=answer.engine,
        latency_ms=answer.latency_ms,
        reasoning=answer.reasoning,
    )


def unavailable_event(
    run_id: UUID, name: str, question: Question, *, engine: str = "jev"
) -> Decision:
    """The trace row for a decision the engine could not answer at all (KI-57).

    Not a placeholder dressed as a reading: `engine="unavailable"` and a
    reasoning that names the outage, so a trace cannot be mistaken for a run
    that graded the question and got a low score. The stage's own default for a
    *missing* answer decides what the run does next; this row is how a reader
    finds out that is what happened.
    """
    kind = type(question).__name__.lower()
    return Decision(
        run_id=str(run_id),
        name=name,
        value=0.0,
        probability=0.0,
        probabilities=None,
        engine="unavailable",
        latency_ms=0,
        reasoning=(
            f"the decision layer was unreachable for this {kind}; the stage's "
            f"own default for an unanswered question was used (requested from {engine})"
        ),
    )


async def decide_or_degrade(
    env: StageEnv,
    kind: str,
    questions: dict[str, Noul | Choice | Score],
) -> dict[str, Answer]:
    """`engine.decide`, or `{}` when the decision layer is unreachable.

    **A decision outage degrades a stage; it never fails a run** (KI-57, and
    TRD §9.6's "a rerank outage degrades to fused order and never fails the
    run" generalised to every stage). Before this, an unreachable engine raised
    `DecisionUnavailable` out of the graph and the run ended `failed` with
    `decision_unavailable` — the R2a run that aborted at item 25 of 57, on a
    single fallback reply that came back as prose instead of JSON.

    Returning `{}` is not inventing an answer: every caller already has a
    defined behaviour for a question it did not get back, and that behaviour is
    the stage's own — rerank degrades to the fused order (unchanged, it already
    caught the error), the gate treats "no reading" as a failing gate and takes
    the corrective retrieval to an abstention, ingress falls back to its
    defaults, and the sanitizer treats every chunk as unanswered, which is the
    same branch it takes for a passage the grader skipped.

    No step timer of its own: the caller wraps it, so a stage that already
    publishes `env.step("sanitize", …)` does not publish a second step for the
    same call.
    """
    try:
        answers: dict[str, Answer] = await env.engine.decide(
            state={"run_id": str(env.params.run_id), "kind": kind}, questions=questions
        )
        return answers
    except DecisionUnavailable as exc:
        logger.warning(
            "decision layer unavailable at %s (%s); the stage degrades to its own default",
            kind,
            exc,
        )
        return {}


async def no_call() -> None:
    """A step that legitimately makes no call — a skipped retrieval, or a
    stage whose questions were batched into an earlier one. Timed and
    published like any other step, so it still appears in the trace."""
    return None
