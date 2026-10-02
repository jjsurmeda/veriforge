"""The periodic web-chunk TTL sweep (TRD §13).

`sweep_expired_web_chunks` has existed since the web-retrieval slice and
nothing ever called it, so the 7-day TTL on temp web rows was a comment, not
a behaviour: 1,705 rows sat past their expiry. A purge nobody schedules is
not a purge. The task below is what makes it one.

The task is registered on the `light` queue the worker already runs, so the
periodic deferrer picks it up on worker startup with no extra wiring.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, WebPage
from ingest.queue import app
from ingest.tasks import WEB_SWEEP_CRON
from ingest.tasks import sweep_web_chunks as sweep_task
from tests.retrieval.conftest import make_chat, make_user


async def _seed_web_rows(
    db: AsyncSession, *, chat_id: UUID, expired: bool, count: int = 2
) -> tuple[list[WebPage], list[Chunk]]:
    """`expired` sets the TTL in the past, which is the whole difference
    between a row the sweep must delete and a row it must keep."""
    delta = timedelta(days=-1) if expired else timedelta(days=6)
    pages: list[WebPage] = []
    chunks: list[Chunk] = []
    for index in range(count):
        page = WebPage(
            chat_id=chat_id,
            url=f"https://example.test/{index}",
            title=f"Page {index}",
            expires_at=datetime.now(UTC) + delta,
        )
        db.add(page)
        await db.flush()
        pages.append(page)
        for ord_ in range(2):
            chunk = Chunk(
                document_id=None,
                section_id=None,
                ord=ord_,
                page=None,
                text=f"web passage {index}-{ord_}",
                embedding=None,
                source_type="web",
                chunk_metadata={"web_page_id": str(page.id)},
                expires_at=datetime.now(UTC) + delta,
            )
            db.add(chunk)
            chunks.append(chunk)
    await db.commit()
    return pages, chunks


async def test_the_sweep_task_is_registered_on_a_queue_the_worker_runs() -> None:
    """The defect was not the purge function, it was that nothing called it.
    So the thing under test is the REGISTRATION: a periodic task on a queue
    the worker process already serves. `ingest/worker.py` imports this module,
    and the worker syncs periodic defers on startup."""
    registry = app.periodic_registry.periodic_tasks
    entries = {name: task for (name, _), task in registry.items()}
    assert "ingest.tasks.sweep_web_chunks" in entries, sorted(entries)
    assert entries["ingest.tasks.sweep_web_chunks"].cron == WEB_SWEEP_CRON
    assert entries["ingest.tasks.sweep_web_chunks"].task.queue == "light"


def test_the_sweep_runs_hourly() -> None:
    """Stated on its own so the cadence cannot be changed silently: the TTL is
    7 days, so anything from hourly to daily is defensible, but *some*
    cadence has to be asserted."""
    minute, hour, day, month, weekday = WEB_SWEEP_CRON.split()
    assert (minute, hour, day, month, weekday) == ("17", "*", "*", "*", "*")


async def test_the_sweep_deletes_expired_rows_and_keeps_live_ones(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    user = await make_user(db, "sweep@test.dev")
    chat = await make_chat(db, user)
    expired_pages, expired_chunks = await _seed_web_rows(db, chat_id=chat.id, expired=True)
    live_pages, live_chunks = await _seed_web_rows(db, chat_id=chat.id, expired=False)
    expired_page_ids = {page.id for page in expired_pages}
    live_page_ids = {page.id for page in live_pages}
    expired_chunk_ids = {chunk.id for chunk in expired_chunks}
    live_chunk_ids = {chunk.id for chunk in live_chunks}

    with caplog.at_level(logging.INFO, logger="ingest.tasks"):
        await sweep_task(timestamp=1_700_000_000)

    remaining_pages = {page.id for page in (await db.execute(select(WebPage))).scalars().all()}
    remaining_chunks = {chunk.id for chunk in (await db.execute(select(Chunk))).scalars().all()}
    assert remaining_pages == live_page_ids, "a live page was deleted"
    assert remaining_chunks == live_chunk_ids, "a live chunk was deleted"
    assert not (expired_page_ids & remaining_pages), "an expired page survived"
    assert not (expired_chunk_ids & remaining_chunks), "an expired chunk survived"
    # The count is pages + the orphaned-chunk delete; the chunks reached
    # through a page row are deleted by the per-page statement and not counted
    # (KI-39). What matters is that rows are gone and the hourly log line says
    # so, so an operator can see the sweep is doing something.
    swept = [r for r in caplog.records if r.message == "expired web chunks swept"]
    assert swept, "the sweep must report what it deleted"
    deleted: Any = getattr(swept[-1], "deleted", None)
    assert deleted is not None and deleted >= len(expired_pages)


async def test_the_sweep_is_a_no_op_when_nothing_has_expired(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A sweep that always reports a big number is a sweep that is deleting
    something it should not; run against live rows only, it must report
    nothing deleted."""
    user = await make_user(db, "sweep-clean@test.dev")
    chat = await make_chat(db, user)
    _, live_chunks = await _seed_web_rows(db, chat_id=chat.id, expired=False)

    with caplog.at_level(logging.INFO, logger="ingest.tasks"):
        await sweep_task(timestamp=1_700_000_000)

    swept = [r for r in caplog.records if r.message == "expired web chunks swept"]
    assert swept, "the sweep must report what it deleted"
    assert getattr(swept[-1], "deleted", None) == 0
    assert getattr(swept[-1], "timestamp", None) == 1_700_000_000
    remaining = {chunk.id for chunk in (await db.execute(select(Chunk))).scalars().all()}
    assert remaining == {chunk.id for chunk in live_chunks}
