"""Small helpers every stage needs: a Decision event built from an answer, and
the timed no-op that marks a step which legitimately makes no call."""

from __future__ import annotations

from uuid import UUID

from schemas.decisions import Answer
from schemas.events import Decision


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


async def no_call() -> None:
    """A step that legitimately makes no call — a skipped retrieval, or a
    stage whose questions were batched into an earlier one. Timed and
    published like any other step, so it still appears in the trace."""
    return None
