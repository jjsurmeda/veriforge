"""PostgresRunBus against real Postgres (Standard tier, testing.md):
publish/subscribe/cancel/replay-after-seq."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from runbus.postgres import PostgresRunBus
from schemas.events import AnswerDelta, RunCompleted, RunStarted, RunStreamEvent
from tests.conftest import make_run_row


async def _collect(
    agen: AsyncIterator[RunStreamEvent], *, count: int, seconds: float = 5.0
) -> list[RunStreamEvent]:
    out: list[RunStreamEvent] = []
    try:
        async with asyncio.timeout(seconds):
            async for event in agen:
                out.append(event)
                if len(out) >= count:
                    return out
    except TimeoutError:
        pass
    return out


async def test_publish_then_replay_from_zero(db: AsyncSession, bus: PostgresRunBus) -> None:
    run_id, _ = await make_run_row(db)
    await bus.publish(run_id, RunStarted(model="openai/gpt-4o-mini"))
    await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text="Hello "))
    await bus.publish(run_id, RunCompleted(message_id="m1"))

    events = await _collect(bus.subscribe(run_id, 0), count=3)
    types = [e.type for e in events]
    assert types == ["run.started", "answer.delta", "run.completed"]
    # terminal event ends iteration without hitting the count guard
    assert events[0].seq == 1
    assert events[1].seq == 2
    assert events[2].seq == 3
    assert isinstance(events[1], AnswerDelta)
    assert events[1].text == "Hello "


async def test_subscribe_after_seq_skips_replayed(db: AsyncSession, bus: PostgresRunBus) -> None:
    run_id, _ = await make_run_row(db)
    await bus.publish(run_id, RunStarted())
    await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text="later"))

    events = await _collect(bus.subscribe(run_id, after_seq=1), count=1)
    assert [e.type for e in events] == ["answer.delta"]


async def test_live_delivery_then_terminal(db: AsyncSession, bus: PostgresRunBus) -> None:
    run_id, _ = await make_run_row(db)
    received: list[RunStreamEvent] = []

    async def reader() -> None:
        async for event in bus.subscribe(run_id, 0):
            received.append(event)

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.05)
    await bus.publish(run_id, RunStarted())
    await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text="live"))
    await bus.publish(run_id, RunCompleted(message_id="m1"))

    await asyncio.wait_for(task, timeout=5)
    assert [e.type for e in received] == ["run.started", "answer.delta", "run.completed"]


async def test_cancel_notifies_handlers(db: AsyncSession, bus: PostgresRunBus) -> None:
    run_id, _ = await make_run_row(db)
    seen = asyncio.Event()
    def handler(rid: UUID) -> None:
        if rid == run_id:
            seen.set()

    bus.on_cancel(handler)

    await bus.cancel(run_id)
    async with asyncio.timeout(5):
        await seen.wait()


async def test_publish_assigns_monotonic_seq(db: AsyncSession, bus: PostgresRunBus) -> None:
    run_id, _ = await make_run_row(db)
    first = await bus.publish(run_id, RunStarted())
    second = await bus.publish(run_id, AnswerDelta(run_id=str(run_id), text="x"))
    assert (first.seq, second.seq) == (1, 2)
