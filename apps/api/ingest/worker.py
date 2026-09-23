"""Worker entrypoint: `procrastinate --app=ingest.worker.app worker <queue>`.

Importing tasks registers them on the shared app.
"""

from ingest.queue import app
from ingest.tasks import ingest_document, regenerate_starter_questions

__all__ = ["app", "ingest_document", "regenerate_starter_questions"]
