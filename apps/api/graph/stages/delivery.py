"""Delivery: where a generated token goes.

Every mode streams through the same three moves — batch the tokens, publish
them coalesced, and touch the heartbeat while the answer is streaming — so a
mode never grows its own copy of the loop. Coalescing is ADR-001's: a client
must see a delta at least every `delta_coalesce_ms`, and the heartbeat has to
keep flowing during a long generation or the sweeper kills a healthy run.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from graph.stages.run_env import RunState
from runbus.postgres import PostgresRunBus
from schemas.events import AnswerDelta, Heartbeat


class DeltaBatcher:
    """Coalesces answer text; flushed at least every delta_coalesce_ms
    (ADR-001)."""

    def __init__(self, *, coalesce_seconds: float) -> None:
        self.buffer: list[str] = []
        self.last_flush = time.monotonic()
        self._coalesce_seconds = coalesce_seconds

    def add(self, token: str) -> None:
        self.buffer.append(token)

    def due(self) -> bool:
        return bool(self.buffer) and (
            time.monotonic() - self.last_flush >= self._coalesce_seconds
        )

    def take(self) -> str:
        text = "".join(self.buffer)
        self.buffer.clear()
        self.last_flush = time.monotonic()
        return text


class Delivery:
    """The answer stream's sink for one run.

    `streamed` is False for a hold plan, where the whole reviewed answer goes
    out as one delta after the review rather than as it is generated.
    """

    def __init__(
        self,
        *,
        bus: PostgresRunBus,
        run_id: UUID,
        heartbeat_interval_seconds: float,
        coalesce_seconds: float,
        on_heartbeat: Callable[[], Awaitable[None]],
        mark_first_delta: Callable[[], None],
        streamed: bool,
        state: RunState,
    ) -> None:
        self._bus = bus
        self._run_id = run_id
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._on_heartbeat = on_heartbeat
        self._mark_first_delta = mark_first_delta
        self._streamed = streamed
        self._state = state
        self._batcher = DeltaBatcher(coalesce_seconds=coalesce_seconds)
        self._last_heartbeat = time.monotonic()

    async def push(self, token: str) -> None:
        """One generated token. Every `answer.delta` goes through here, in
        all three modes, so the first-token clock cannot miss a path."""
        self._state.text += token
        self._batcher.add(token)
        if self._streamed and self._batcher.due():
            await self._publish()

    async def flush(self) -> None:
        if self._batcher.buffer and self._streamed:
            await self._publish()

    async def _publish(self) -> None:
        self._mark_first_delta()
        await self._bus.publish(
            self._run_id,
            AnswerDelta(run_id=str(self._run_id), text=self._batcher.take()),
        )
        if time.monotonic() - self._last_heartbeat >= self._heartbeat_interval_seconds:
            await self._bus.publish(self._run_id, Heartbeat(run_id=str(self._run_id)))
            await self._on_heartbeat()
            self._last_heartbeat = time.monotonic()
