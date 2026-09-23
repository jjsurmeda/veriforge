"""Ingestion jobs and their defer helpers (TRD §9.1).

`ingest` queue: one document-ingestion job at a time. `light` queue:
starter-question regeneration. Task bodies are implemented in the worker
slice; routes defer through the helpers below.
"""

from uuid import UUID

from ingest.pipeline import run_pipeline
from ingest.queue import app
from ingest.starter import run_starter_questions


@app.task(queue="ingest")
async def ingest_document(document_id: str) -> None:
    await run_pipeline(UUID(document_id))


@app.task(queue="light")
async def regenerate_starter_questions(collection_id: str) -> None:
    await run_starter_questions(UUID(collection_id))


async def defer_ingest_document(document_id: UUID) -> None:
    await ingest_document.defer_async(document_id=str(document_id))


async def defer_starter_questions(collection_id: UUID) -> None:
    await regenerate_starter_questions.defer_async(collection_id=str(collection_id))
