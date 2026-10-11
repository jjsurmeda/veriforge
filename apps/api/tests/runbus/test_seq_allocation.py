"""KI-68: a run's event sequence is allocated by the database, not raced for.

One turn in forty used to die outright. `PostgresRunBus.publish` chose `seq`
as `SELECT COALESCE(MAX(seq),0)+1` in one statement and inserted in another,
so two publishers on the same run could choose the same number; the loser
spent one of `SEQ_RACE_RETRIES` attempts on the primary key. Lane B item 2
made the per-variant searches concurrent and gave each one its own
`step.started`/`step.completed` pair, so contention on one run's counter
stopped being incidental — and with it, all three attempts could be lost
(`01a127f3-9724…`: `duplicate key value violates unique constraint
"run_events_pkey"`, and the run failed before the generator, so the user got
no text and no decline).

What these tests pin is the property that was missing: the number and the
row are written by the same statement, so Postgres — not a retry budget —
decides who gets which number.

**How the overlap is proved, and why the obvious version proves nothing.**
KI-61 and `tests/demo/test_demo_mode.py` both record the same lesson, and
this test is built the way they say to build it:

- N `bus.publish(...)` calls under `asyncio.gather` is **not** enough. It
  passes against the broken implementation — whichever publisher reaches
  its insert first commits before the next one has finished reading, so
  the retries absorb the race and the test reports success.
- Here every publisher opens its transaction, takes its sequence number,
  and then waits on an `asyncio.Event` before its insert can land. All N
  are inside the read-then-write window simultaneously *by construction*,
  not by luck. Nothing here is a sleep racing the database.

Real Postgres with migrations applied (`testing.md`: runbus is
SQL-adjacent, so the database is the thing under test). No provider call.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.session import get_session_factory
from runbus import postgres as runbus_postgres
from runbus.postgres import PostgresRunBus, _event_adapter
from schemas.events import AnswerDelta, RunCompleted, RunStarted, RunStreamEvent
from tests.conftest import make_run_row

PUBLISHERS = 8
# Generous: the assertion it guards is a *negative* one (the other
# publishers must still be waiting), so it has to outlast a slow pool
# checkout on a loaded machine.
OVERLAP_WINDOW_SECONDS = 1.0


def _real_bus() -> PostgresRunBus:
    return PostgresRunBus(get_session_factory(), get_settings().database_url)


class _ReplayResult:
    """Hands the sequence number back a second time.

    Reading a SQLAlchemy result closes it, and `publish` reads the very
    result the probe is watching. So the probe takes the value and gives the
    caller a stand-in that still answers `scalar_one()`. Only the probed
    statement is wrapped; every other statement's result passes through
    untouched.
    """

    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _ProbedSession:
    """A real `AsyncSession` with its first statement observed.

    `publish` takes the sequence number before it writes the row, in the old
    implementation and the fixed one alike, so pausing after the first
    statement drops the publisher into exactly the window the defect is
    about: the number has been chosen and nothing has proved it yet.

    Only the first statement is probed. `pg_notify` is an `execute` too, and
    reading its result the same way would be meaningless.
    """

    def __init__(self, inner: AsyncSession, probe: Callable[[int], Awaitable[None]]) -> None:
        self._inner = inner
        self._probe = probe
        self._probed = False

    async def __aenter__(self) -> "_ProbedSession":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc_info: Any) -> Any:
        return await self._inner.__aexit__(*exc_info)

    def begin(self) -> Any:
        return self._inner.begin()

    async def execute(self, clause: Any, parameters: Any = None) -> Any:
        result = await self._inner.execute(clause, parameters)
        if self._probed:
            return result
        self._probed = True
        allocated = int(result.scalar_one())
        await self._probe(allocated)
        return _ReplayResult(allocated)


class _PublisherProbe:
    """Records the sequence number each publisher allocated, and holds the
    first one open until the test releases it.

    The first publisher to arrive is the one that gets held, which is
    deterministic because the test does not start the others until it has
    seen `held` set.
    """

    def __init__(self) -> None:
        self.allocated: list[int] = []
        self.held = asyncio.Event()
        self.release = asyncio.Event()
        self._held_the_first = False

    async def __call__(self, seq: int) -> None:
        self.allocated.append(seq)
        if self._held_the_first:
            return
        self._held_the_first = True
        self.held.set()
        await self.release.wait()


def _probed_bus(probe: _PublisherProbe) -> PostgresRunBus:
    """A bus whose sessions report their first statement to `probe`.

    The factory is a plain async context manager factory rather than an
    `async_sessionmaker`; `PostgresRunBus` only ever calls it, so that is
    all it has to be.
    """
    inner = get_session_factory()

    @asynccontextmanager
    async def _factory() -> AsyncIterator[_ProbedSession]:
        async with inner() as session:
            yield _ProbedSession(session, probe)

    return PostgresRunBus(_factory, get_settings().database_url)  # type: ignore[arg-type]


def _delta(body: str) -> AnswerDelta:
    return AnswerDelta(text=body)


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


# --- the allocation itself ----------------------------------------------------


async def test_concurrent_publishers_are_serialised_not_raced(db: AsyncSession) -> None:
    """THE KI-68 test: N publishers on one run, all inside the window at once.

    Asserted both ways, so it cannot pass for the wrong reason:

    - while the first publisher is paused **after** choosing its number and
      **before** its row lands, no other publisher may have chosen one.
      That is the serialisation. A read-then-write implementation lets the
      other seven in here, and this is the assertion that fails on it.
    - once released, the eight numbers are exactly 1..8 — no duplicates, and
      no gaps for anything replaying the run to trip over.
    """
    run_id, _ = await make_run_row(db)
    probe = _PublisherProbe()
    bus = _probed_bus(probe)

    tasks: list[asyncio.Task[RunStreamEvent]] = []
    try:
        tasks.append(asyncio.create_task(bus.publish(run_id, RunStarted())))
        await asyncio.wait_for(probe.held.wait(), timeout=5)

        for index in range(PUBLISHERS - 1):
            tasks.append(asyncio.create_task(bus.publish(run_id, _delta(f"chunk-{index}"))))

        # The whole window: if the allocation is not serialised, the other
        # publishers have their numbers by now.
        await asyncio.sleep(OVERLAP_WINDOW_SECONDS)
        assert probe.allocated == [1], (
            "every other publisher must still be waiting for the first to "
            f"commit; the numbers allocated were {probe.allocated}"
        )
        assert not any(task.done() for task in tasks[1:]), (
            "no publisher may finish publishing while the first is paused"
        )

        probe.release.set()
        results = await asyncio.gather(*tasks)
    finally:
        probe.release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bus.stop()

    seqs = sorted(int(event.seq) for event in results)
    assert seqs == list(range(1, PUBLISHERS + 1)), f"gapless and duplicate-free, got {seqs}"


async def test_a_rolled_back_publish_does_not_consume_a_sequence_number(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gapless means the number comes back when the row does not.

    The allocation and the insert are one transaction, so a publish that
    dies after taking its number — the generator blowing up mid-write, a
    cancelled run — must not leave a hole in the run's sequence. A gap here
    is not cosmetic: `subscribe(after_seq=…)` walks the sequence, and a
    permanently missing number is a hole every later reader steps over.
    """
    run_id, _ = await make_run_row(db)
    bus = _real_bus()

    class _FailsOnFirstEvent:
        """Dump everything, except the event that is meant to fail."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def validate_python(self, payload: Any) -> Any:
            return self._inner.validate_python(payload)

        def dump_python(self, value: Any, **kwargs: Any) -> Any:
            if value.type == "run.started":
                raise RuntimeError("simulated failure after the sequence was taken")
            return self._inner.dump_python(value, **kwargs)

    monkeypatch.setattr(runbus_postgres, "_event_adapter", _FailsOnFirstEvent(_event_adapter))

    with pytest.raises(RuntimeError, match="simulated failure"):
        await bus.publish(run_id, RunStarted())
    await bus.stop()

    monkeypatch.undo()
    healthy = _real_bus()
    first = await healthy.publish(run_id, RunStarted())
    await healthy.stop()
    assert first.seq == 1, "the failed publish must not have burned sequence number 1"


# --- what subscribers see -----------------------------------------------------


async def test_subscribers_see_concurrent_publishes_in_sequence_order(
    db: AsyncSession,
) -> None:
    """The ordering half: seq order is the order a subscriber replays in.

    Concurrent publishers return their events in whatever order the database
    granted the numbers, which is not the order `gather` happened to start
    them. What a subscriber is promised is weaker and is what matters: the
    replay carries strictly increasing, gapless sequence numbers, and **each
    publisher's own event arrives at the number that publisher was handed**.
    A run bus that stamped the payload with one number and stored the row
    under another would replay a user's answer text out of order, and every
    test that only checked "the set of seqs is 1..N" would still pass.

    The terminal event is published after the concurrent batch on purpose:
    `_subscribe` returns at the first terminal event, so a `run.completed`
    racing the deltas would legitimately truncate the replay and the test
    would be measuring its own mistake.
    """
    run_id, _ = await make_run_row(db)
    bus = _real_bus()
    await bus.start()

    bodies = [f"chunk-{index}" for index in range(PUBLISHERS - 1)]
    try:
        await bus.publish(run_id, RunStarted())
        published = await asyncio.gather(*(bus.publish(run_id, _delta(body)) for body in bodies))
        await bus.publish(run_id, RunCompleted(message_id="m1"))
        expected = len(bodies) + 2

        replayed = await _collect(bus.subscribe(run_id, 0), count=expected)
    finally:
        await bus.stop()

    seqs = [int(event.seq) for event in replayed]
    assert seqs == list(range(1, expected + 1)), f"gapless and ordered, got {seqs}"
    granted = {event.text: int(event.seq) for event in published if isinstance(event, AnswerDelta)}
    streamed = {event.text: int(event.seq) for event in replayed if isinstance(event, AnswerDelta)}
    assert streamed == granted, "each publisher's granted number is the one its event streams at"
    assert replayed[-1].type == "run.completed", "the terminal event still ends the stream"
