"""SSE event union (TRD §12) — slices 1+3 subsets.

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


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str | None = None
    document_name: str | None = None
    page: int | None = None
    heading_path: str | None = None
    source_type: str = "document"
    excerpt: str = ""
    vector_score: float | None = None
    bm25_score: float | None = None
    fused_score: float = 0.0
    rerank_score: float | None = None
    # Always false until the sanitizer exists (slice 4) — never faked.
    dropped: bool = False


class Retrieval(RunEvent):
    type: Literal["retrieval"] = "retrieval"
    hop: int = 0
    query: str
    chunks: list[RetrievedChunk] = []


class AnswerDelta(RunEvent):
    type: Literal["answer.delta"] = "answer.delta"
    text: str


class Metrics(RunEvent):
    type: Literal["metrics"] = "metrics"
    latency_ms: dict[str, int] = {}
    tokens_in: int = 0
    tokens_out: int = 0
    # Token counts until the ledger lands (slice 7, TRD §14).
    credits: int = 0
    context_used: int = 0
    context_window: int = 0
    faithfulness: float | None = None
    min_support: float | None = None


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
    RunStarted
    | Retrieval
    | AnswerDelta
    | Metrics
    | Heartbeat
    | RunCompleted
    | RunCancelled
    | RunFailed,
    Field(discriminator="type"),
]

TERMINAL_EVENT_TYPES = frozenset({"run.completed", "run.cancelled", "run.failed"})


class RunStreamResponse(RootModel[RunStreamEvent]):
    """References the union so it lands in OpenAPI (TRD §12: the TS union is
    generated from the schema, never hand-rolled)."""

    root: RunStreamEvent
