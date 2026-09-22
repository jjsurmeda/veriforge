"""Heartbeat sweep (TRD §7: 60 s without heartbeat → failed)."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session_factory
from graph.runner import sweep_stale_runs
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
        await db.execute(
            text("SELECT type FROM run_events WHERE run_id = :i ORDER BY seq"), {"i": run_id}
        )
    ).scalars().all()
    assert events == ["run.failed"]


async def test_sweep_leaves_fresh_runs_alone(db: AsyncSession, bus: PostgresRunBus) -> None:
    await make_run_row(db, stale=False)
    swept = await sweep_stale_runs(bus, get_session_factory())
    assert swept == 0


async def test_uuid7_is_version7_and_sortable() -> None:
    from db.ids import uuid7

    a = uuid7()
    await asyncio.sleep(0.002)
    b = uuid7()
    assert a.version == 7
    assert b.version == 7
    assert b > a
