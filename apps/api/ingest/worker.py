"""Worker entrypoint: `procrastinate --app=ingest.worker.app worker <queue>`.

Importing tasks registers them on the shared app, including the periodic
ones — the worker syncs periodic defers on startup, so anything registered
here on a queue the worker runs is scheduled with no further wiring.
"""

from ingest.queue import app
from ingest.tasks import (
    WEB_SWEEP_CRON,
    ingest_document,
    regenerate_starter_questions,
    sweep_web_chunks,
)

__all__ = [
    "WEB_SWEEP_CRON",
    "app",
    "ingest_document",
    "regenerate_starter_questions",
    "sweep_web_chunks",
]
