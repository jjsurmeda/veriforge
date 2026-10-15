#!/usr/bin/env python3
"""Backfill section and document summaries for documents that predate
TRD §9.1 step 6 (R2a-2 item 4).

`ingest/pipeline.py` writes summaries for new documents. The 32 already in the
corpus — 1,723 sections — have none, and a gist question against them reaches
the same passages it always did. This covers them.

**Resumable**, and that is the whole design. A run is a sequence of documents;
each document's summaries are written in one transaction at the end, so a
document is either fully summarised or not summarised at all. `--resume` skips
documents that already have both kinds, which means an interrupted run costs one
document's summaries and not the run. `--limit` exists for the same reason: to
see the cost and the shape of the work on a few documents before committing to
all of them.

**No chunk is re-embedded.** Summaries are embedded on their own text, which is
this script's own `embed_batch` call; nothing touches `chunks`. Re-embedding a
corpus to add a second index is how a backfill turns into an incident.

    DATABASE_URL=... uv run python scripts/backfill_summaries.py --dry-run
    DATABASE_URL=... uv run python scripts/backfill_summaries.py --limit 2
    DATABASE_URL=... uv run python scripts/backfill_summaries.py --resume

Spends provider credit: one summariser call and one embedding batch per
document. Check the balance first (docs/conventions/agents.md).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select

from config import get_settings
from db.models import Document, ModelRole, Section, Summary
from db.session import get_session_factory
from ingest.summarise import SummaryError, summarise_document
from providers.llm import complete, embed_batch

#: Only documents a run could actually retrieve. A `failed` document has no
#: usable sections and a `parsing` one is mid-flight; summarising either wastes
#: a call and writes rows an ingest retry will then have to clean up.
BACKFILLABLE_STATUSES = ("ready",)


async def _pending_documents(
    factory: Any, *, resume: bool, limit: int | None
) -> list[tuple[Any, str, int]]:
    """`(document_id, name, section_count)` for every document to cover."""
    async with factory() as session:
        query = (
            select(Document.id, Document.name, func.count(Section.id))
            .join(Section, Section.document_id == Document.id)
            .where(Document.status.in_(BACKFILLABLE_STATUSES))
            .group_by(Document.id, Document.name)
            .order_by(Document.name)
        )
        rows = (await session.execute(query)).all()
        candidates = [(row[0], row[1], int(row[2])) for row in rows]

        if resume:
            covered = dict(
                (
                    await session.execute(
                        select(
                            Summary.document_id,
                            func.count(Summary.id).filter(Summary.kind == "document"),
                        ).group_by(Summary.document_id)
                    )
                ).all()
            )
            candidates = [
                row
                for row in candidates
                if int(covered.get(row[0], 0)) < 1 or row[2] > 0
            ]
            # A document is done when it has a document summary AND one section
            # summary per section. Anything less is redone.
            done = set()
            for document_id, _name, section_count in candidates:
                kinds = (
                    await session.execute(
                        select(Summary.kind, func.count(Summary.id))
                        .where(Summary.document_id == document_id)
                        .group_by(Summary.kind)
                    )
                ).all()
                by_kind = {str(k): int(c) for k, c in kinds}
                if by_kind.get("document", 0) >= 1 and by_kind.get("section", 0) >= section_count:
                    done.add(document_id)
            candidates = [row for row in candidates if row[0] not in done]

    if limit is not None:
        candidates = candidates[:limit]
    return candidates


async def _sections_for(factory: Any, document_id: Any) -> list[tuple[Any, int, str, str]]:
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(Section.id, Section.ord, Section.heading_path, Section.text)
                    .where(Section.document_id == document_id)
                    .order_by(Section.ord)
                )
            )
            .tuples()
            .all()
        )
    return [(r[0], int(r[1]), str(r[2]), str(r[3])) for r in rows]


async def _small_model(factory: Any) -> str | None:
    async with factory() as session:
        role = (
            await session.execute(select(ModelRole).where(ModelRole.role == "small"))
        ).scalar_one_or_none()
    return f"openrouter/{role.model_id}" if role is not None else None


async def _write(
    factory: Any,
    *,
    document_id: Any,
    sections: list[tuple[Any, int, str, str]],
    result: Any,
) -> None:
    """One document's summaries, in one transaction.

    The delete-then-insert is what makes a re-run idempotent: re-running a
    document whose previous attempt was interrupted between the embed and the
    commit would otherwise double its rows, and two section summaries for one
    section is a row retrieval can rank twice.
    """
    texts = [entry.text for entry in result.sections] + [result.document]
    batch_size = get_settings().embedding_batch_size
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        embeddings.extend(await embed_batch(texts=texts[start : start + batch_size]))

    by_ord = {ord_: section_id for section_id, ord_, _h, _t in sections}
    async with factory() as session, session.begin():
        await session.execute(delete(Summary).where(Summary.document_id == document_id))
        for index, entry in enumerate(result.sections):
            session.add(
                Summary(
                    document_id=document_id,
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
                document_id=document_id,
                section_id=None,
                kind="document",
                ord=0,
                heading_path="",
                text=result.document,
                built_from_summaries=True,
                embedding=embeddings[-1],
            )
        )


async def run(*, resume: bool, limit: int | None, dry_run: bool) -> int:
    factory = get_session_factory()
    pending = await _pending_documents(factory, resume=resume, limit=limit)
    total_sections = sum(count for _id, _name, count in pending)
    print(
        f"==> {len(pending)} document(s), {total_sections} section(s) to summarise"
        + ("  [dry run: no writes]" if dry_run else "")
    )
    if not pending:
        return 0
    if dry_run:
        for _id, name, count in pending:
            print(f"    {name}  ({count} sections)")
        return 0

    small_model = await _small_model(factory)
    if small_model is None:
        print("no small model role; run scripts/seed_models.py first", file=sys.stderr)
        return 1

    written = failed = 0
    for index, (document_id, name, _count) in enumerate(pending, start=1):
        sections = await _sections_for(factory, document_id)
        if not sections:
            continue
        try:
            result = await summarise_document(
                document_title=name,
                sections=[(ord_, heading, text) for _sid, ord_, heading, text in sections],
                small_model=small_model,
                complete_fn=complete,
            )
            await _write(
                factory,
                document_id=document_id,
                sections=sections,
                result=result,
            )
        except SummaryError as exc:
            # One document's failure is not the run's: the rest still get
            # covered, and `--resume` will come back for this one.
            failed += 1
            print(f"  [{index}/{len(pending)}] {name}: {exc}", file=sys.stderr)
            continue
        written += 1
        print(f"  [{index}/{len(pending)}] {name}: {len(result.sections)} sections + document")
    print(f"==> done: {written} written, {failed} failed")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip documents that already have a document summary and one per section",
    )
    parser.add_argument("--limit", type=int, default=None, help="stop after N documents")
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would be summarised, write nothing"
    )
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is not set; this reads a real corpus")
    return asyncio.run(run(resume=args.resume, limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
