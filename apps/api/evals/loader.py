"""Seed loader (TRD §15): evals/seed/items.json → eval_datasets/eval_items,
and the seed corpus → a ready corpus collection owned by the eval user.

The corpus collections are `visibility='private'` (KI-24): the AW-2000 fixture
is not product content, and a benchmark corpus every real user searches is not
a benchmark. `build_scope` admits a private collection to the user who owns it,
so the eval runner reaches its own corpus by passing the collection ids; the
HTTP chat path resolves scope from the chat alone and never sees it, so real
users' retrievals are unaffected.

Usage: uv run python -m evals.loader
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.passwords import hash_password
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
# The account that owns the eval corpora, and the identity the eval and
# acceptance runners authenticate as (KI-24).
#
# `example.com`, not a `.local` or `.test` address: the product's own email
# validator (email_validator, via auth/router.py) rejects special-use and
# reserved domains, so an account at `evals@veriforge.local` can be created in
# the database but can never complete `/auth/login` — which is exactly what
# acceptance does. `example.com` is reserved by RFC 2606 for this purpose and
# passes validation. The runner imports this constant rather than reading an env
# var, so there is exactly one place that decides who owns the corpora.
EVAL_USER_EMAIL = "evals@example.com"
CORPUS_NAME = "eval-seed-corpus"

# The counterfactual set (P1b item 2). Its own directory, its own collection,
# its own dataset — never Shared (KI-24). The documents state deliberately
# altered facts, so a model answering them from memory is the failure this set
# exists to catch, and a real user must never be able to read them at all.
COUNTERFACTUAL_DIR = Path(__file__).resolve().parents[3] / "evals" / "counterfactual"
COUNTERFACTUAL_ITEMS = COUNTERFACTUAL_DIR / "items.json"
COUNTERFACTUAL_CORPUS_DIR = COUNTERFACTUAL_DIR / "corpus"
COUNTERFACTUAL_CORPUS_NAME = "eval-counterfactual-corpus"
COUNTERFACTUAL_DATASET = "counterfactual"
# The `corpus` value every counterfactual item carries, which is what the
# runner summarises per corpus (PRD v3 §5).
COUNTERFACTUAL_CORPUS_KEY = "counterfactual"


async def ensure_eval_user(session: AsyncSession, *, password: str | None = None) -> User:
    """The one account that owns the eval corpora. Created on `free`.

    `password` is the sign-in credential for the eval and acceptance runners
    (KI-24). It is optional because the loader itself never signs in — it talks
    to the database — so a CI run needs no credential at all, while
    `scripts/seed_eval_user.py` passes one to make the account usable over HTTP.
    """
    user = (
        await session.execute(select(User).where(User.email == EVAL_USER_EMAIL))
    ).scalar_one_or_none()
    if user is not None:
        if password:
            user.password_hash = hash_password(password)
            user.status = "active"
        return user
    plan_id = (await session.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    user = User(
        email=EVAL_USER_EMAIL,
        password_hash=hash_password(password) if password else None,
        role="user",
        plan_id=plan_id,
        status="active",
    )
    session.add(user)
    await session.flush()
    return user


# Kept as the loader's internal name; the runner imports this symbol.
_eval_user = ensure_eval_user


async def load_items(
    session: AsyncSession, items_file: Path = ITEMS_FILE, default_corpus: str | None = None
) -> EvalDataset:
    payload = json.loads(items_file.read_text(encoding="utf-8"))
    dataset = (
        await session.execute(select(EvalDataset).where(EvalDataset.name == payload["dataset"]))
    ).scalar_one_or_none()
    if dataset is None:
        dataset = EvalDataset(name=payload["dataset"])
        session.add(dataset)
        await session.flush()
    existing = (
        (await session.execute(select(EvalItem).where(EvalItem.dataset_id == dataset.id)))
        .scalars()
        .all()
    )
    by_question = {row.question: row for row in existing}
    for row in payload["items"]:
        # The counterfactual set spells its items `turns`/`expect` (the
        # acceptance shape) rather than `question`/`reference_answer` (the seed
        # shape), so normalise the two fields here rather than making every
        # downstream reader know both.
        question = row.get("question") or row["turns"][-1]
        should_abstain = row.get("should_abstain")
        if should_abstain is None:
            should_abstain = row["expect"] == "not_in_sources"
        reference_answer = row.get("reference_answer") or (
            "forbid=" + ",".join(row["forbid"])
            if row.get("forbid")
            # A should-abstain item has no reference answer by definition, and
            # the column is NOT NULL, so the fact that the corpus does not cover
            # the question is what goes in. The seed set spells this as an empty
            # string; this keeps the two shapes writing the same thing.
            else ""
        )
        # PRD §5: the runner summarises per corpus, so the item has to carry
        # which one. Keyed on the payload's optional `corpus`, falling back to
        # the set's own default — a set with one corpus states it once — and
        # then to NULL, which is honest for a set that predates the column.
        #
        # `cast(Any, ...)` on assignment: mypy reads `EvalItem.corpus`'s
        # attribute type as the ORM expression type (`SQLCoreOperations[str] |
        # str`) rather than the declared `Mapped[str | None]`, so a `str | None`
        # expression is a false incompatibility. The column really is nullable.
        item_corpus: Any = row.get("corpus") or default_corpus
        if question in by_question:
            existing_item = by_question[question]
            existing_item.category = row["category"]
            existing_item.reference_answer = reference_answer
            existing_item.should_abstain = should_abstain
            existing_item.corpus = cast("Any", item_corpus)
            continue
        session.add(
            EvalItem(
                dataset_id=dataset.id,
                category=row["category"],
                question=question,
                reference_answer=reference_answer,
                should_abstain=should_abstain,
                corpus=cast("Any", item_corpus),
            )
        )
    await session.flush()
    return dataset


async def load_corpus(
    session: AsyncSession,
    *,
    name: str = CORPUS_NAME,
    corpus_dir: Path = CORPUS_DIR,
    tag: str = "eval-seed",
) -> UUID:
    """Idempotent: skips when the corpus collection already has chunks.

    The collection is `visibility='private'` and owned by the eval user (KI-24).
    An existing collection is demoted to private on every run, so a database
    seeded before the move is corrected by re-running the loader rather than
    needing a hand edit — otherwise the eval corpus would stay in every real
    user's retrieval scope until someone noticed.
    """
    user = await _eval_user(session)
    collection = (
        await session.execute(
            select(Collection).where(Collection.owner_id == user.id, Collection.name == name)
        )
    ).scalar_one_or_none()
    if collection is None:
        collection = Collection(owner_id=user.id, name=name, visibility="private", kind="library")
        session.add(collection)
        await session.flush()
    elif collection.visibility != "private":
        logger.warning("demoting eval corpus to private", extra={"collection": name})
        collection.visibility = "private"
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
    for path in sorted(corpus_dir.glob("*.md")):
        markdown = path.read_text(encoding="utf-8")
        document = Document(
            collection_id=collection.id,
            name=path.name,
            mime="text/markdown",
            sha256=hashlib.sha256(markdown.encode()).hexdigest(),
            s3_key=f"eval-corpus/{name}/{path.name}",
            status="ready",
            tags=[tag],
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
        cf_dataset = None
        cf_collection_id = None
        if COUNTERFACTUAL_ITEMS.exists():
            cf_dataset = await load_items(
                session,
                COUNTERFACTUAL_ITEMS,
                default_corpus=COUNTERFACTUAL_CORPUS_KEY,
            )
            cf_collection_id = await load_corpus(
                session,
                name=COUNTERFACTUAL_CORPUS_NAME,
                corpus_dir=COUNTERFACTUAL_CORPUS_DIR,
                tag="eval-counterfactual",
            )
    STATE_FILE.write_text(
        json.dumps(
            {
                "corpus_collection_id": str(collection_id),
                "counterfactual_collection_id": (
                    str(cf_collection_id) if cf_collection_id else None
                ),
                "counterfactual_dataset": cf_dataset.name if cf_dataset else None,
            }
        )
    )
    print(f"dataset={dataset.id} corpus_collection={collection_id}")
    if cf_dataset is not None:
        print(f"counterfactual_dataset={cf_dataset.name} corpus_collection={cf_collection_id}")


if __name__ == "__main__":
    asyncio.run(main())
