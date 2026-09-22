"""PostgresRunBus: run_events + LISTEN/NOTIFY (TRD §7, ADR-001).

One dedicated listener connection per process multiplexes all runs:
per-run channels `run_<uuid>` carry only the new seq, `run_cancel` carries
the run id to every process. Answer-delta coalescing (50 ms) lives with
the publisher in graph/, not here.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Protocol
from uuid import UUID

import asyncpg
from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from schemas.events import TERMINAL_EVENT_TYPES, RunStreamEvent

_event_adapter: TypeAdapter[RunStreamEvent] = TypeAdapter(RunStreamEvent)

REPLAY_BATCH = 500
POLL_FALLBACK_SECONDS = 15.0
SEQ_RACE_RETRIES = 3


def parse_event(payload: dict[str, object]) -> RunStreamEvent:
    return _event_adapter.validate_python(payload)


def _run_channel(run_id: UUID) -> str:
    return f"run_{run_id}"


async def _fetch_events(
    session: AsyncSession, run_id: UUID, after_seq: int, limit: int
) -> list[tuple[int, str, dict[str, object]]]:
    rows = await session.execute(
        text(
            "SELECT seq, type, payload FROM run_events "
            "WHERE run_id = :run_id AND seq > :after_seq ORDER BY seq LIMIT :limit"
        ),
        {"run_id": run_id, "after_seq": after_seq, "limit": limit},
    )
    return [(int(r.seq), str(r.type), dict(r.payload)) for r in rows]


class RunBus(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def on_cancel(self, handler: Callable[[UUID], None]) -> None: ...

    async def publish(self, run_id: UUID, event: RunStreamEvent) -> RunStreamEvent: ...

    def subscribe(self, run_id: UUID, after_seq: int = 0) -> AsyncIterator[RunStreamEvent]: ...

    async def cancel(self, run_id: UUID) -> None: ...


class PostgresRunBus:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], dsn: str) -> None:
        self._session_factory = session_factory
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        self._listener: asyncpg.Connection | None = None
        self._subscriber_queues: dict[UUID, set[asyncio.Queue[int]]] = {}
        self._cancel_handlers: list[Callable[[UUID], None]] = []

    async def start(self) -> None:
        self._listener = await asyncpg.connect(self._dsn)
        await self._listener.add_listener("run_cancel", self._on_cancel_notification)

    async def stop(self) -> None:
        if self._listener is not None:
            await self._listener.close()
            self._listener = None
        self._subscriber_queues.clear()

    def on_cancel(self, handler: Callable[[UUID], None]) -> None:
        self._cancel_handlers.append(handler)

    def _on_cancel_notification(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        try:
            run_id = UUID(payload)
        except ValueError:
            return
        for handler in list(self._cancel_handlers):
            handler(run_id)

    def _on_run_notification(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        run_id = UUID(channel.removeprefix("run_"))
        for queue in self._subscriber_queues.get(run_id, ()):
            queue.put_nowait(int(payload))

    async def publish(self, run_id: UUID, event: RunStreamEvent) -> RunStreamEvent:
        """Append to run_events, NOTIFY the seq, return the stamped event.

        seq is assigned client-side (SELECT max+1) so the stored payload
        carries its own seq; a same-run write race loses the PK race once
        and retries.
        """
        last_error: Exception | None = None
        for _ in range(SEQ_RACE_RETRIES):
            async with self._session_factory() as session:
                try:
                    async with session.begin():
                        current_max = int(
                            (
                                await session.execute(
                                    text(
                                        "SELECT COALESCE(MAX(seq), 0) FROM run_events "
                                        "WHERE run_id = :run_id"
                                    ),
                                    {"run_id": run_id},
                                )
                            ).scalar_one()
                        )
                        stamped = event.model_copy(
                            update={"run_id": str(run_id), "seq": current_max + 1}
                        )
                        payload = _event_adapter.dump_python(stamped, mode="json")
                        await session.execute(
                            text(
                                "INSERT INTO run_events (run_id, seq, type, payload) "
                                "VALUES (:run_id, :seq, :type, CAST(:payload AS jsonb))"
                            ),
                            {
                                "run_id": run_id,
                                "seq": stamped.seq,
                                "type": stamped.type,
                                "payload": json.dumps(payload),
                            },
                        )
                        await session.execute(
                            text("SELECT pg_notify(:channel, :seq)"),
                            {"channel": _run_channel(run_id), "seq": str(stamped.seq)},
                        )
                        return stamped
                except IntegrityError as exc:  # same-run seq race; retry
                    last_error = exc
        assert last_error is not None
        raise last_error

    def subscribe(self, run_id: UUID, after_seq: int = 0) -> AsyncIterator[RunStreamEvent]:
        return self._subscribe(run_id, after_seq)

    async def _subscribe(self, run_id: UUID, after_seq: int) -> AsyncIterator[RunStreamEvent]:
        """Replay run_events past after_seq, then follow live notifications."""
        queue: asyncio.Queue[int] = asyncio.Queue()
        existing = self._subscriber_queues.setdefault(run_id, set())
        first = not existing
        existing.add(queue)
        if first and self._listener is not None:
            await self._listener.add_listener(_run_channel(run_id), self._on_run_notification)
        last_seq = after_seq
        try:
            while True:
                async with self._session_factory() as session:
                    rows = await _fetch_events(session, run_id, last_seq, REPLAY_BATCH)
                terminal = False
                for seq, event_type, payload in rows:
                    last_seq = seq
                    yield parse_event(payload)
                    if event_type in TERMINAL_EVENT_TYPES:
                        terminal = True
                if terminal:
                    return
                try:
                    await asyncio.wait_for(queue.get(), timeout=POLL_FALLBACK_SECONDS)
                except TimeoutError:
                    # Missed-notification fallback: re-poll so a sweep-failed
                    # run still terminates the stream.
                    continue
        finally:
            queues = self._subscriber_queues.get(run_id)
            if queues is not None:
                queues.discard(queue)
                if not queues:
                    self._subscriber_queues.pop(run_id, None)
                    if self._listener is not None:
                        await self._listener.remove_listener(
                            _run_channel(run_id), self._on_run_notification
                        )

    async def cancel(self, run_id: UUID) -> None:
        # NOTIFY only ships on COMMIT; a bare session.execute() rolls back.
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("SELECT pg_notify('run_cancel', :run_id)"), {"run_id": str(run_id)}
            )
