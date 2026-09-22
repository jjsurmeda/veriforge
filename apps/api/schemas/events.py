"""SSE event union (TRD §12) — slice 1 subset only.

New event types land here first, then the TS union is regenerated; never
invent an event shape ad hoc in a component (CLAUDE.md). Events this slice
does not produce are deliberately absent until their slice ships.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, RootModel


def _now() -> datetime:
    return datetime.now(UTC)


class RunEvent(BaseModel):
    """Every event carries run_id, seq, ts (TRD §12)."""

    # run_id/seq are stamped by the RunBus on publish; defaults are placeholders.
    run_id: str = ""
    seq: int = 0
    ts: datetime = Field(default_factory=_now)


class RunStarted(RunEvent):
    type: Literal["run.started"] = "run.started"
    mode: str = "fast"
    source: str = "auto"
    model: str = ""
    settings_version: int | None = None


class AnswerDelta(RunEvent):
    type: Literal["answer.delta"] = "answer.delta"
    text: str


class Heartbeat(RunEvent):
    type: Literal["heartbeat"] = "heartbeat"


class RunCompleted(RunEvent):
    type: Literal["run.completed"] = "run.completed"
    message_id: str
    status: str = "completed"


class RunCancelled(RunEvent):
    type: Literal["run.cancelled"] = "run.cancelled"
    message_id: str


class RunFailed(RunEvent):
    type: Literal["run.failed"] = "run.failed"
    error_code: str
    message: str = ""


RunStreamEvent = Annotated[
    RunStarted | AnswerDelta | Heartbeat | RunCompleted | RunCancelled | RunFailed,
    Field(discriminator="type"),
]

TERMINAL_EVENT_TYPES = frozenset({"run.completed", "run.cancelled", "run.failed"})


class RunStreamResponse(RootModel[RunStreamEvent]):
    """References the union so it lands in OpenAPI (TRD §12: the TS union is
    generated from the schema, never hand-rolled)."""

    root: RunStreamEvent
