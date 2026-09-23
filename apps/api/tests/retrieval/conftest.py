"""Fixtures for retrieval tests: real users/collections/documents/chunks in
the test Postgres (testing.md — retrieval tests run against a real DB;
ownership-filter SQL is the thing under test)."""

import random
from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.ids import uuid7
from db.models import Chat, Chunk, Collection, Document, Section, User

EMBEDDING_DIM = 1536


def vec(seed: int, *, bump: float | None = None) -> list[float]:
    """Deterministic unit-ish vector; `bump` nudges one dimension so a chunk
    can be made the nearest neighbour of a query vector."""
    rng = random.Random(seed)
    values = [rng.uniform(-1, 1) for _ in range(EMBEDDING_DIM)]
    if bump is not None:
        values[0] += bump
    return values


async def make_user(db: AsyncSession, email: str) -> User:
    plan_id = (await db.execute(text("SELECT id FROM plans WHERE name = 'free'"))).scalar_one()
    user = User(
        id=uuid7(), email=email, role="user", plan_id=plan_id, status="active"
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def make_collection(
    db: AsyncSession, owner: User, name: str, visibility: str = "private"
) -> Collection:
    collection = Collection(owner_id=owner.id, name=name, visibility=visibility)
    db.add(collection)
    await db.commit()
    await db.refresh(collection)
    return collection


async def make_document(
    db: AsyncSession,
    collection: Collection,
    name: str = "doc.txt",
    *,
    mime: str = "text/plain",
    tags: list[str] | None = None,
) -> Document:
    document = Document(
        collection_id=collection.id,
        name=name,
        mime=mime,
        sha256=uuid7().hex + uuid7().hex,
        s3_key=f"{collection.id}/{uuid7().hex}",
        status="ready",
        tags=tags or [],
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def make_section(
    db: AsyncSession, document: Document, *, tokens: int = 100, ord: int = 0
) -> Section:
    section = Section(
        document_id=document.id,
        heading_path=f"Section {ord}",
        ord=ord,
        text="section text",
        tokens=tokens,
    )
    db.add(section)
    await db.commit()
    await db.refresh(section)
    return section


async def add_chunk(
    db: AsyncSession,
    *,
    document: Document | None,
    section: Section | None,
    ord: int,
    text_: str,
    embedding: list[float] | None,
    page: int | None = None,
    source_type: str = "document",
    chat_id: UUID | None = None,
) -> Chunk:
    chunk = Chunk(
        document_id=document.id if document else None,
        section_id=section.id if section else None,
        ord=ord,
        page=page,
        text=text_,
        embedding=embedding,
        source_type=source_type,
        chat_id=chat_id,
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return chunk


async def make_chat(db: AsyncSession, user: User, collection_ids: list[UUID]) -> Chat:
    chat = Chat(user_id=user.id, title="t", collection_ids=collection_ids)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    return await make_user(db, "retrieval-a@test.dev")


@pytest.fixture
async def user_b(db: AsyncSession) -> User:
    return await make_user(db, "retrieval-b@test.dev")


@pytest.fixture
def seed_document() -> Callable[..., Awaitable[tuple[Document, Section]]]:
    async def create(
        db: AsyncSession, collection: Collection, name: str = "doc.txt", **kwargs: object
    ) -> tuple[Document, Section]:
        document = await make_document(db, collection, name, **kwargs)  # type: ignore[arg-type]
        section = await make_section(db, document)
        return document, section

    return create
