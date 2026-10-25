from __future__ import annotations

import asyncio
import io
import logging
from typing import cast
from uuid import UUID

import pdfplumber
from procrastinate import RetryDecision
from procrastinate.exceptions import JobRetry
from sqlalchemy import delete, func, select

from config import get_settings
from db.models import Chunk, Document, ModelRole, Run, Section, Summary
from db.session import get_session_factory
from ingest.accept import IngestError, sniff_mime
from ingest.chunk import SectionDraft, chunk_document
from ingest.flags import PageScan, flag_pages
from ingest.ocr import OcrEngine, get_ocr_engine
from ingest.parse import PDF_MIME, ParsedDocument, parse_document
from ingest.storage import get_object_store
from ingest.summarise import SummaryError, summarise_document
from observability import signals
from providers.llm import complete, embed_batch
from runtime import load_active_runtime

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

        parsed = await parse_document(mime, data, engine=await _ocr_engine())
        page_flags = _with_ocr_flags(
            await _page_flags(mime, data, parsed.page_texts), parsed
        )

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
        # TRD §9.1 step 6. After the indexing commit, never before: the document
        # must be readable even if this fails, and it is `_write_summaries`'s
        # own job to swallow a summarisation failure. Ingesting the chunks and
        # then failing the job would leave a ready-to-search document marked
        # failed, which is the worst of both.
        await _write_summaries(document)
        await _defer_starters(document.collection_id, document_id)
    except Exception as exc:
        logger.error("ingest failed", extra={"document_id": str(document_id)}, exc_info=True)
        await _mark_failed(document_id, str(exc)[:1000])


async def _ocr_engine() -> OcrEngine | None:
    """The configured engine, None when OCR is switched off. An unknown engine
    id raises (the document fails with that message); there is no fallback."""
    if not get_settings().ocr_enabled:
        return None
    async with get_session_factory()() as session:
        runtime = await load_active_runtime(session)
    return get_ocr_engine(str(runtime.get("ocr.engine", "tesseract")))


def _with_ocr_flags(
    flags: list[dict[str, object]], parsed: ParsedDocument
) -> list[dict[str, object]]:
    """Add `ocr`, `ocr_low_confidence` and `ocr_skipped` to the per-page flags."""
    by_page = {int(cast(int, f["page"])): list(cast(list[str], f["flags"])) for f in flags}
    for pages, flag in (
        (parsed.ocr_pages, "ocr"),
        (parsed.ocr_low_confidence_pages, "ocr_low_confidence"),
        (parsed.ocr_skipped_pages, "ocr_skipped"),
    ):
        for page in pages:
            by_page.setdefault(page, []).append(flag)
    return [{"page": page, "flags": by_page[page]} for page in sorted(by_page)]


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
        if document is None:
            # Nothing to mark, so nothing to report: a retried job whose
            # document was deleted between attempts is not an ingestion
            # failure, and logging it as one would page on a deletion.
            return
        document.status = "failed"
        document.error = error
        await session.commit()
    # Emitted after the commit, so a line in the log always corresponds to a
    # row that is durably marked failed — the reverse order could log a
    # failure the database then never recorded. `document_id` is the
    # correlation key: an operator sees one bad upload's id here and can read
    # `documents.error` for the reason.
    signals.emit(
        signals.INGEST_FAILED,
        document_id=str(document_id),
        error=error[:500],
    )


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


async def _write_summaries(document: Document) -> None:
    """TRD §9.1 step 6: one summary per section and one per document.

    **A summarisation failure does not fail the ingest.** The document is
    already indexed and fully searchable without this index; the backfill
    (`scripts/backfill_summaries.py`) is resumable and picks it up, and a run
    whose document was ingested before the backfill reached it is the ordinary
    state of the system rather than an error. The alternative — letting the
    failure propagate — turns "this book has no gist summary" into "this book
    cannot be opened", which is a far worse failure for a feature that is an
    enhancement over a search that already works.

    So: logged with the document id and swallowed. Both the `SummaryError` case
    (the model's reply was unusable) and the unexpected one, because a bug that
    raised here would otherwise fail every ingest that reached it.

    The small model is resolved the same way `ingest/starter.py` resolves it —
    the `small` role row — rather than read from settings, so an admin who
    repoints the small role changes this call too.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(Section.id, Section.ord, Section.heading_path, Section.text)
                    .where(Section.document_id == document.id)
                    .order_by(Section.ord)
                )
            )
            .tuples()
            .all()
        )
        role = (
            await session.execute(select(ModelRole).where(ModelRole.role == "small"))
        ).scalar_one_or_none()
    if not rows:
        logger.info("no sections to summarise", extra={"document_id": str(document.id)})
        return
    if role is None:
        logger.warning(
            "summaries skipped: no small model role", extra={"document_id": str(document.id)}
        )
        return

    by_ord = {int(ord_): section_id for section_id, ord_, _h, _t in rows}
    try:
        result = await summarise_document(
            document_title=document.name,
            sections=[(int(ord_), heading, text) for _id, ord_, heading, text in rows],
            small_model=f"openrouter/{role.model_id}",
            complete_fn=complete,
        )
    except SummaryError as exc:
        logger.warning(
            "summarisation failed; the document is indexed without summaries "
            "and the backfill will cover it",
            extra={"document_id": str(document.id), "error": str(exc)[:300]},
        )
        return
    except Exception:
        logger.exception(
            "summarisation raised; the document is indexed without summaries",
            extra={"document_id": str(document.id)},
        )
        return

    texts = [entry.text for entry in result.sections] + [result.document]
    batch_size = get_settings().embedding_batch_size
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        embeddings.extend(await embed_batch(texts=texts[start : start + batch_size]))

    async with session_factory() as session, session.begin():
        for index, entry in enumerate(result.sections):
            session.add(
                Summary(
                    document_id=document.id,
                    section_id=by_ord[entry.section_ord],
                    kind="section",
                    ord=entry.section_ord,
                    heading_path=entry.heading_path,
                    text=entry.text,
                    built_from_summaries=False,
                    embedding=embeddings[index],
                )
            )
        session.add(
            Summary(
                document_id=document.id,
                section_id=None,
                kind="document",
                ord=0,
                heading_path="",
                text=result.document,
                # The one field recording why this row is cheaper than it
                # looks: it was written from the section summaries above, not
                # from the document's text.
                built_from_summaries=True,
                embedding=embeddings[-1],
            )
        )
    logger.info(
        "summaries written",
        extra={
            "document_id": str(document.id),
            "sections": len(result.sections),
            "document_chars": len(result.document),
        },
    )


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
