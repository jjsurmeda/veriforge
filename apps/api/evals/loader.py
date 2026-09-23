"""Seed loader (TRD §15): evals/seed/items.json → eval_datasets/eval_items,
and the seed corpus → a ready corpus collection owned by the eval user.

Usage: uv run python -m evals.loader
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import (
    Chunk,
    Collection,
    Document,
    EvalDataset,
    EvalItem,
    Plan,
    Section,
    User,
)
from db.session import get_session_factory
from ingest.chunk import chunk_document
from providers.llm import embed_batch

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parents[3] / "evals" / "seed"
ITEMS_FILE = SEED_DIR / "items.json"
CORPUS_DIR = SEED_DIR / "corpus"
STATE_FILE = SEED_DIR / ".loaded.json"
EVAL_USER_EMAIL = "evals@veriforge.local"
CORPUS_NAME = "eval-seed-corpus"


async def _eval_user(session: AsyncSession) -> User:
    user = (
        await session.execute(select(User).where(User.email == EVAL_USER_EMAIL))
    ).scalar_one_or_none()
    if user is not None:
        return user
    plan_id = (await session.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    user = User(email=EVAL_USER_EMAIL, role="user", plan_id=plan_id, status="active")
    session.add(user)
    await session.flush()
    return user


async def load_items(session: AsyncSession) -> EvalDataset:
    payload = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
    dataset = (
        await session.execute(select(EvalDataset).where(EvalDataset.name == payload["dataset"]))
    ).scalar_one_or_none()
    if dataset is None:
        dataset = EvalDataset(name=payload["dataset"])
        session.add(dataset)
        await session.flush()
    existing = (
        await session.execute(
            select(EvalItem).where(EvalItem.dataset_id == dataset.id)
        )
    ).scalars().all()
    by_question = {item.question: item for item in existing}
    for row in payload["items"]:
        if row["question"] in by_question:
            item = by_question[row["question"]]
            item.category = row["category"]
            item.reference_answer = row["reference_answer"]
            item.should_abstain = row["should_abstain"]
            continue
        session.add(
            EvalItem(
                dataset_id=dataset.id,
                category=row["category"],
                question=row["question"],
                reference_answer=row["reference_answer"],
                should_abstain=row["should_abstain"],
            )
        )
    await session.flush()
    return dataset


async def load_corpus(session: AsyncSession) -> UUID:
    """Idempotent: skips when the corpus collection already has chunks."""
    user = await _eval_user(session)
    collection = (
        await session.execute(
            select(Collection).where(Collection.owner_id == user.id, Collection.name == CORPUS_NAME)
        )
    ).scalar_one_or_none()
    if collection is None:
        collection = Collection(owner_id=user.id, name=CORPUS_NAME, visibility="shared")
        session.add(collection)
        await session.flush()
    has_chunks = (
        await session.execute(
            select(Chunk.id)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.collection_id == collection.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if has_chunks is not None:
        logger.info("corpus already loaded", extra={"collection_id": str(collection.id)})
        return collection.id

    settings = get_settings()
    for path in sorted(CORPUS_DIR.glob("*.md")):
        markdown = path.read_text(encoding="utf-8")
        document = Document(
            collection_id=collection.id,
            name=path.name,
            mime="text/markdown",
            sha256=hashlib.sha256(markdown.encode()).hexdigest(),
            s3_key=f"eval-corpus/{path.name}",
            status="ready",
            tags=["eval-seed"],
        )
        session.add(document)
        await session.flush()
        sections = chunk_document(markdown, [])
        for section_draft in sections:
            section = Section(
                document_id=document.id,
                heading_path=section_draft.heading_path,
                ord=section_draft.ord,
                text=section_draft.text,
                tokens=section_draft.tokens,
            )
            session.add(section)
            await session.flush()
            drafts = list(section_draft.children)
            if not drafts:
                continue
            embeddings: list[list[float]] = []
            for start in range(0, len(drafts), settings.embedding_batch_size):
                batch = drafts[start : start + settings.embedding_batch_size]
                embeddings.extend(await embed_batch(texts=[d.text for d in batch]))
            for draft, embedding in zip(drafts, embeddings, strict=True):
                session.add(
                    Chunk(
                        document_id=document.id,
                        section_id=section.id,
                        ord=draft.ord,
                        page=draft.page,
                        text=draft.text,
                        embedding=embedding,
                    )
                )
        logger.info("corpus document indexed", extra={"name": path.name})
    await session.flush()
    return collection.id


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        dataset = await load_items(session)
        collection_id = await load_corpus(session)
    STATE_FILE.write_text(json.dumps({"corpus_collection_id": str(collection_id)}))
    print(f"dataset={dataset.id} corpus_collection={collection_id}")


if __name__ == "__main__":
    asyncio.run(main())
