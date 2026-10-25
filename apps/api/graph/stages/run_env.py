"""What a mode needs from the run it is executing, and what it hands the
shared review tail.

One object instead of twenty keyword arguments, so a mode stage reads as the
stage it is and nothing else. `finish` is the shared tail that only
`graph/runner.py` can supply — it holds the seams the tests replace.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decisions import DecisionCall, DecisionEngine
from retrieval.expand import ExpandedContext
from retrieval.filters import ClientFilters
from runbus.postgres import PostgresRunBus
from schemas.decisions import Answer

EmitDecision = Callable[[str, Answer, DecisionCall], Awaitable[None]]


@dataclass
class RunState:
    """What this run has delivered so far. The failure paths need it: a run
    that dies halfway has already streamed part of its answer, and that text
    is what the message ends up holding."""

    text: str = ""


@dataclass(frozen=True)
class FinishRequest:
    """The per-mode half of the review tail; the run's identity comes from
    the environment."""

    question: str
    text: str
    contexts: list[ExpandedContext]
    latency_ms: dict[str, int]
    context_used: int
    tokens_in: int
    generate_ms: int
    abstained: bool
    plan: str
    chitchat: bool = False
    revert_title: bool = False
    # IsUse (ADR-006): when the usefulness check failed — or could not be
    # asked, which is treated as failing — the delivered text is replaced by
    # the TR-4 decline, so the tail persists it and records the message as an
    # abstention without running the reviewer over the decline itself.
    decline_text: str | None = None
    # The generator's provider finish_reason, kept in runs.metrics only.
    finish_reason: str | None = None


FinishRun = Callable[["FinishRequest"], Awaitable[None]]


@dataclass(frozen=True)
class RunEnv:
    bus: PostgresRunBus
    session_factory: async_sessionmaker[AsyncSession]
    engine: DecisionEngine
    run_id: UUID
    message_id: UUID
    chat_id: UUID
    user_id: UUID
    litellm_model: str
    small_model: str
    context_window: int
    mode: str
    source: str
    user_message: str
    client_filters: ClientFilters
    collection_ids: list[UUID]
    instant_title: str | None
    heartbeat_interval_seconds: float
    coalesce_seconds: float
    touch_heartbeat: Callable[[], Awaitable[None]]
    emit_decision: EmitDecision
    mark_first_delta: Callable[[], None]
    first_token_ms: Callable[[], int | None]
    state: RunState
    finish: FinishRun
