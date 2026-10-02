"""Heartbeat sweep (TRD §7: 60 s without heartbeat → failed)."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import Run
from db.session import get_session_factory
from graph.runner import _heartbeat_loop, sweep_stale_runs
from runbus.postgres import PostgresRunBus
from tests.conftest import make_run_row


async def test_sweep_marks_stale_run_failed(db: AsyncSession, bus: PostgresRunBus) -> None:
    run_id, message_id = await make_run_row(db, stale=True)

    swept = await sweep_stale_runs(bus, get_session_factory())
    assert swept == 1

    status = (
        await db.execute(text("SELECT status FROM runs WHERE id = :i"), {"i": run_id})
    ).scalar_one()
    message_status = (
        await db.execute(text("SELECT status FROM messages WHERE id = :i"), {"i": message_id})
    ).scalar_one()
    assert status == "failed"
    assert message_status == "failed"

    events = (
        (
            await db.execute(
                text("SELECT type FROM run_events WHERE run_id = :i ORDER BY seq"), {"i": run_id}
            )
        )
        .scalars()
        .all()
    )
    assert events == ["run.failed"]


async def test_sweep_leaves_fresh_runs_alone(db: AsyncSession, bus: PostgresRunBus) -> None:
    await make_run_row(db, stale=False)
    swept = await sweep_stale_runs(bus, get_session_factory())
    assert swept == 0


async def test_sweep_does_not_fail_a_run_that_heartbeats_after_the_select(
    db: AsyncSession, bus: PostgresRunBus
) -> None:
    """The live-worker race (review S7).

    The sweeper SELECTed stale rows and then UPDATEd each by id alone, so a
    heartbeat landing in between was ignored: the run was marked failed, its
    message failed, its usage settled and a false `run.failed` published. Here
    the heartbeat is written on a second connection at exactly that point, so
    the sweep's UPDATE has to re-check staleness rather than trust its SELECT.
    """
    run_id, message_id = await make_run_row(db, stale=True)
    factory = get_session_factory()
    landed: list[int] = []
    racing_factory = _factory_that_heartbeats_after_the_first_select(factory, run_id, landed)

    swept = await sweep_stale_runs(bus, racing_factory)

    assert landed == [1], "the heartbeat never landed between the select and the update"
    assert swept == 0, "the sweeper failed a run that was heartbeating"
    status = (
        await db.execute(text("SELECT status FROM runs WHERE id = :i"), {"i": run_id})
    ).scalar_one()
    message_status = (
        await db.execute(text("SELECT status FROM messages WHERE id = :i"), {"i": message_id})
    ).scalar_one()
    assert status == "running", "a live run was marked failed"
    assert message_status is None, "a live run's message was marked failed"
    events = (
        (
            await db.execute(
                text("SELECT type FROM run_events WHERE run_id = :i ORDER BY seq"), {"i": run_id}
            )
        )
        .scalars()
        .all()
    )
    assert events == [], f"a false terminal event was published: {events}"


def _factory_that_heartbeats_after_the_first_select(
    factory: async_sessionmaker[AsyncSession], run_id: UUID, landed: list[int]
) -> async_sessionmaker[AsyncSession]:
    """A session factory whose sessions heartbeat the run after their SELECT.

    The sweeper's window is between reading the stale rows and writing
    `status = 'failed'`, so that is where a live worker's heartbeat has to
    land. It is written on a separate connection and committed, exactly as
    `_heartbeat_loop` does; the sweeper's transaction has only read at that
    point, so it holds no lock and does not block the write.
    """

    async def beat() -> None:
        async with factory() as other:
            await other.execute(
                update(Run).where(Run.id == run_id).values(heartbeat_at=datetime.now(UTC))
            )
            await other.commit()
        landed.append(1)

    class _Session(AsyncSession):
        _selected = False

        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            result = await super().execute(*args, **kwargs)
            if not _Session._selected and _is_select(args, kwargs):
                _Session._selected = True
                await beat()
            return result

    return async_sessionmaker(factory.kw["bind"], class_=_Session, expire_on_commit=False)


def _is_select(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
    statement = args[0] if args else kwargs.get("statement")
    return isinstance(statement, Select)


async def test_heartbeat_loop_keeps_a_waiting_run_from_being_swept(
    db: AsyncSession, bus: PostgresRunBus
) -> None:
    run_id, _ = await make_run_row(db, stale=True)
    heartbeat = asyncio.create_task(
        _heartbeat_loop(bus, get_session_factory(), run_id, interval=0.01)
    )
    try:
        # Wait for the condition, not a fixed sleep: poll until the
        # heartbeat row is actually refreshed. A fixed 20 ms sleep races
        # under suite load (passes alone, fails in the full run).
        refreshed = False
        for _ in range(500):
            heartbeat_at = (
                await db.execute(
                    text("SELECT heartbeat_at FROM runs WHERE id = :i"), {"i": run_id}
                )
            ).scalar_one()
            if heartbeat_at > datetime.now(UTC) - timedelta(minutes=1):
                refreshed = True
                break
            await asyncio.sleep(0.005)
        assert refreshed, "heartbeat loop never refreshed the row"
        assert await sweep_stale_runs(bus, get_session_factory()) == 0
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


async def test_uuid7_is_version7_and_sortable() -> None:
    from db.ids import uuid7

    a = uuid7()
    await asyncio.sleep(0.002)
    b = uuid7()
    assert a.version == 7
    assert b.version == 7
    assert b > a
