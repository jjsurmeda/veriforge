from __future__ import annotations

import asyncio
import io
import logging
from uuid import UUID

import pdfplumber
from procrastinate import RetryDecision
from procrastinate.exceptions import JobRetry
from sqlalchemy import delete, func, select

from config import get_settings
from db.models import Chunk, Document, Run, Section
from db.session import get_session_factory
from ingest.accept import IngestError, sniff_mime
from ingest.chunk import SectionDraft, chunk_document
from ingest.flags import PageScan, flag_pages
from ingest.parse import PDF_MIME, parse_document
from ingest.storage import get_object_store
from providers.llm import embed_batch

logger = logging.getLogger(__name__)


async def run_pipeline(document_id: UUID) -> None:
    await _pause_if_busy()
    settings = get_settings()
    try:
        document = await _mark_parsing(document_id)
        if document is None:
            return

        logger.info("ingest parsing", extra={"document_id": str(document_id)})
        data = await get_object_store().get(document.s3_key)
        mime = sniff_mime(document.name, data)
        if mime is None:
            raise IngestError("Unsupported or unreadable document type")

        parsed = await parse_document(mime, data)
        page_flags = await _page_flags(mime, data, parsed.page_texts)

        await _mark_embedding(document_id, mime)
        logger.info("ingest embedding", extra={"document_id": str(document_id)})
        sections = chunk_document(parsed.markdown, parsed.page_texts)
        embeddings: list[list[float]] = []
        texts = [
            f"{section.heading_path}\n{child.text}" if section.heading_path else child.text
            for section in sections
            for child in section.children
        ]
        for batch_start in range(0, len(texts), settings.embedding_batch_size):
            embeddings.extend(
                await embed_batch(
                    texts=texts[batch_start : batch_start + settings.embedding_batch_size]
                )
            )

        logger.info("ingest indexing", extra={"document_id": str(document_id)})
        await _index_document(document_id, page_flags, sections, embeddings)
        await _defer_starters(document.collection_id, document_id)
    except Exception as exc:
        logger.error("ingest failed", extra={"document_id": str(document_id)}, exc_info=True)
        await _mark_failed(document_id, str(exc)[:1000])


async def _pause_if_busy() -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        active_runs = (
            await session.execute(select(func.count(Run.id)).where(Run.status == "running"))
        ).scalar_one()
    if active_runs > settings.ingest_pause_active_runs:
        raise JobRetry(RetryDecision(retry_in={"seconds": settings.ingest_pause_retry_seconds}))


async def _mark_parsing(document_id: UUID) -> Document | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None or document.status != "queued":
            return None
        document.status = "parsing"
        document.error = None
        await session.commit()
        return document


async def _mark_embedding(document_id: UUID, mime: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is not None:
            document.mime = mime
            document.status = "embedding"
            await session.commit()


async def _mark_failed(document_id: UUID, error: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is not None:
            document.status = "failed"
            document.error = error
            await session.commit()


async def _index_document(
    document_id: UUID,
    page_flags: list[dict[str, object]],
    section_drafts: list[SectionDraft],
    embeddings: list[list[float]],
) -> None:
    session_factory = get_session_factory()
    embedding_index = 0
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return
        await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        await session.execute(delete(Section).where(Section.document_id == document_id))
        for draft in section_drafts:
            section = Section(
                document_id=document_id,
                heading_path=draft.heading_path,
                ord=draft.ord,
                text=draft.text,
                tokens=draft.tokens,
            )
            session.add(section)
            await session.flush()
            for child in draft.children:
                session.add(
                    Chunk(
                        document_id=document_id,
                        section_id=section.id,
                        ord=child.ord,
                        page=child.page,
                        text=child.text,
                        embedding=embeddings[embedding_index],
                        chunk_metadata={},
                        source_type="document",
                    )
                )
                embedding_index += 1
        document.page_flags = page_flags
        document.status = "ready"
        document.error = None
        await session.commit()


async def _page_flags(mime: str, data: bytes, page_texts: list[str]) -> list[dict[str, object]]:
    if mime != PDF_MIME or not page_texts:
        return []
    table_counts = await asyncio.to_thread(_pdf_table_counts, data)
    scans = [
        PageScan(
            text=text,
            table_cell_count=table_counts[index] if index < len(table_counts) else 0,
            pipe_count=text.count("|"),
        )
        for index, text in enumerate(page_texts)
    ]
    return flag_pages(scans)


def _pdf_table_counts(data: bytes) -> list[int]:
    counts: list[int] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            counts.append(sum(len(row) for table in tables for row in table))
    return counts


async def _defer_starters(collection_id: UUID, document_id: UUID) -> None:
    try:
        from ingest.tasks import defer_starter_questions

        await defer_starter_questions(collection_id)
    except Exception:
        logger.error(
            "starter question defer failed",
            extra={"document_id": str(document_id), "collection_id": str(collection_id)},
            exc_info=True,
        )
