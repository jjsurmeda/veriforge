"""Backfill section and document summaries for existing documents.

Usage (from apps/api):

    DATABASE_URL=postgresql+asyncpg://... uv run python scripts/backfill_summaries.py

The script is resumable: it skips documents that already have a summary row for
the document kind. It writes one `section` summary per section, then one
`document` summary built from those section summaries, and embeds every summary
text for retrieval.

A summarisation failure for one document is logged and skipped; it does not
stop the backfill. That matches the ingest pipeline, where a summary failure is
also non-fatal.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from db.models import Document, Section, Summary
from ingest.summarise import SummaryError, summarise_document
from providers.llm import complete, embed_batch

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DEFAULT_SMALL_MODEL = "openrouter/openai/gpt-4o-mini"
BATCH_SIZE = 16


async def _documents_needing_summaries(
    session: AsyncSession, only_missing: bool
) -> Sequence[Document]:
    """All documents, or only those with no document summary yet."""
    if not only_missing:
        return (await session.execute(select(Document))).scalars().all()
    subq = select(Summary.document_id).where(Summary.kind == "document").distinct()
    stmt = select(Document).where(Document.id.notin_(subq))
    return (await session.execute(stmt)).scalars().all()


async def _sections_for(document_id: Any, session: AsyncSession) -> Sequence[Section]:
    return (
        await session.execute(
            select(Section).where(Section.document_id == document_id).order_by(Section.ord)
        )
    ).scalars().all()


async def _summarise_one(
    document: Document, sections: Sequence[Section], small_model: str
) -> dict[str, Any] | None:
    """Generate summaries and return rows to insert, or None on failure."""
    inputs = [
        (section.ord, section.heading_path, section.text)
        for section in sections
    ]
    try:
        result = await summarise_document(
            document_title=document.name,
            sections=inputs,
            small_model=small_model,
            complete_fn=complete,
        )
    except SummaryError as exc:
        logger.warning("summary failed for %s: %s", document.id, exc)
        return None
    except Exception as exc:
        logger.exception("unexpected summary failure for %s: %s", document.id, exc)
        return None

    section_map = {section.ord: section for section in sections}
    rows: list[Summary] = []
    for section_summary in result.sections:
        section = section_map.get(section_summary.section_ord)
        if section is None:
            continue
        rows.append(
            Summary(
                document_id=document.id,
                section_id=section.id,
                kind="section",
                ord=section_summary.section_ord,
                heading_path=section_summary.heading_path,
                text=section_summary.text,
            )
        )
    rows.append(
        Summary(
            document_id=document.id,
            section_id=None,
            kind="document",
            ord=0,
            heading_path="",
            text=result.document,
            built_from_summaries=True,
        )
    )
    return {"document_id": document.id, "rows": rows}


async def _embed_rows(rows: Sequence[Summary]) -> None:
    """Embed every summary text and write the vector back to the row."""
    if not rows:
        return
    texts = [row.text for row in rows]
    embeddings = await embed_batch(texts=texts)
    for row, embedding in zip(rows, embeddings, strict=True):
        row.embedding = embedding


async def backfill(
    *,
    db_url: str,
    only_missing: bool,
    small_model: str,
    batch_size: int,
) -> dict[str, int]:
    """Backfill summaries for one database. Returns counts."""
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    documents_processed = 0
    documents_failed = 0
    summaries_written = 0

    async with session_factory() as session:
        documents = await _documents_needing_summaries(session, only_missing)
    logger.info("found %d documents to summarise", len(documents))

    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        async with session_factory() as session:
            for document in batch:
                sections = await _sections_for(document.id, session)
                if not sections:
                    logger.info("skipping %s: no sections", document.id)
                    continue

                # Re-check inside the transaction in case a parallel run wrote
                # the summary after we listed documents.
                if only_missing:
                    existing = (
                        await session.execute(
                            select(Summary).where(
                                Summary.document_id == document.id, Summary.kind == "document"
                            )
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        logger.info("skipping %s: already has document summary", document.id)
                        continue

                payload = await _summarise_one(document, sections, small_model)
                if payload is None:
                    documents_failed += 1
                    continue

                rows = payload["rows"]
                await _embed_rows(rows)
                session.add_all(rows)
                await session.commit()

                documents_processed += 1
                summaries_written += len(rows)
                logger.info(
                    "wrote %d summaries for %s (%s)",
                    len(rows),
                    document.id,
                    document.name,
                )

    await engine.dispose()
    return {
        "documents": len(documents),
        "documents_processed": documents_processed,
        "documents_failed": documents_failed,
        "summaries_written": summaries_written,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill section and document summaries.")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL"),
        help="Database URL (defaults to DATABASE_URL env var)",
    )
    parser.add_argument(
        "--small-model",
        default=os.environ.get("SMALL_MODEL", DEFAULT_SMALL_MODEL),
        help=f"Small model for summarisation (default {DEFAULT_SMALL_MODEL})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ.get("BATCH_SIZE", BATCH_SIZE)),
        help="Documents to process per summarisation batch",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_documents",
        help="Re-summarise documents that already have summaries",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List documents that would be summarised and exit",
    )
    args = parser.parse_args()

    if not args.db_url:
        parser.error("Set DATABASE_URL or pass --db-url")

    # Load settings so embedding/complete use the same config as the app.
    get_settings()

    only_missing = not args.all_documents

    async def _run() -> dict[str, int]:
        engine = create_async_engine(args.db_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            documents = await _documents_needing_summaries(session, only_missing)
        await engine.dispose()
        if args.dry_run:
            print(f"would summarise {len(documents)} document(s)")
            return {"documents": len(documents)}
        return await backfill(
            db_url=args.db_url,
            only_missing=only_missing,
            small_model=args.small_model,
            batch_size=args.batch_size,
        )

    counts = asyncio.run(_run())
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    import json

    raise SystemExit(main())
