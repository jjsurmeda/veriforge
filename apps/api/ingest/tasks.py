"""Ingestion jobs, maintenance jobs and their defer helpers (TRD §9.1).

`ingest` queue: one document-ingestion job at a time. `light` queue:
starter-question regeneration and the periodic TTL sweep. Task bodies are
implemented in the worker slice; routes defer through the helpers below.

Periodic tasks are registered here rather than in the package that owns the
work, because the Procrastinate app is an `ingest` concern and `retrieval`
must not import it (python.md: the dependency direction is one-way). The
worker process syncs periodic defers on startup, so a task registered on a
queue the worker already runs needs no other wiring — `ingest/worker.py`
imports this module, and Compose runs `--queues=light`.
"""

import logging
from uuid import UUID

from db.session import get_session_factory
from ingest.pipeline import run_pipeline
from ingest.queue import app
from ingest.starter import run_starter_questions
from retrieval.web import sweep_expired_web_chunks

logger = logging.getLogger(__name__)

# Hourly, at 17 past. Not :00 — every other scheduled thing in the stack is
# on the hour, and a purge that lands with them competes for the same
# connections. The TTL is 7 days (retrieval/web.py), so hourly is far more
# often than the data needs; the cost is one indexed DELETE on `chunks`
# against a table whose web rows are a small fraction.
WEB_SWEEP_CRON = "17 * * * *"


@app.task(queue="ingest")
async def ingest_document(document_id: str) -> None:
    await run_pipeline(UUID(document_id))


@app.task(queue="light")
async def regenerate_starter_questions(collection_id: str) -> None:
    await run_starter_questions(UUID(collection_id))


@app.periodic(cron=WEB_SWEEP_CRON)
@app.task(queue="light")
async def sweep_web_chunks(timestamp: int) -> None:
    """Delete expired web chunks and their page rows (TRD §13).

    `sweep_expired_web_chunks` has existed since the web-retrieval slice and
    nothing ever called it, so the temp rows accumulated for as long as the
    stack was up — 1,705 rows past their TTL at the time this was found. A
    purge that is never scheduled is not a purge; this is the schedule.

    `timestamp` is the scheduled slot the periodic deferrer computed; it is
    passed to every periodic task and is only logged here, because it is what
    lets two runs in the trace panel be told apart.

    One session per task invocation, not a shared one (python.md): tasks run
    concurrently.
    """
    async with get_session_factory()() as session, session.begin():
        deleted = await sweep_expired_web_chunks(session)
    logger.info("expired web chunks swept", extra={"deleted": deleted, "timestamp": timestamp})


async def defer_ingest_document(document_id: UUID) -> None:
    await ingest_document.defer_async(document_id=str(document_id))


async def defer_starter_questions(collection_id: UUID) -> None:
    await regenerate_starter_questions.defer_async(collection_id=str(collection_id))
