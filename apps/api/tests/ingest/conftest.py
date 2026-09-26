from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from auth.passwords import hash_password
from db.models import Chat, Chunk, Collection, Document, Section, User
from tests.conftest import signup


async def _headers(client: AsyncClient, email: str) -> dict[str, str]:
    body = await signup(client, email)
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture
async def user_a_headers(client: AsyncClient) -> dict[str, str]:
    return await _headers(client, "source-a@test.dev")


@pytest.fixture
async def user_b_headers(client: AsyncClient) -> dict[str, str]:
    return await _headers(client, "source-b@test.dev")


@pytest.fixture
async def admin_headers(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    plan_id = (await db.execute(text("SELECT id FROM plans WHERE name = 'free'"))).scalar_one()
    db.add(
        User(
            email="source-admin@test.dev",
            password_hash=hash_password("password123"),
            role="admin",
            plan_id=plan_id,
            status="active",
        )
    )
    await db.commit()
    response = await client.post(
        "/auth/login",
        json={"email": "source-admin@test.dev", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def make_document() -> Callable[[AsyncSession, str, str], Awaitable[Document]]:
    async def create(db: AsyncSession, collection_id: str, name: str = "doc.txt") -> Document:
        digest = uuid4().hex + uuid4().hex
        document = Document(
            collection_id=collection_id,
            name=name,
            mime="text/plain",
            sha256=digest,
            s3_key=f"{collection_id}/{digest}",
            status="ready",
            tags=[],
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        return document

    return create


@pytest.fixture
def make_chunk() -> Callable[[AsyncSession, Document, int, int], Awaitable[Chunk]]:
    async def create(
        db: AsyncSession, document: Document, section_ord: int, chunk_ord: int
    ) -> Chunk:
        section = Section(
            document_id=document.id,
            heading_path=f"Section {section_ord}",
            ord=section_ord,
            text="section text",
            tokens=2,
        )
        db.add(section)
        await db.flush()
        chunk = Chunk(
            document_id=document.id,
            section_id=section.id,
            ord=chunk_ord,
            page=section_ord,
            text=f"chunk {section_ord}.{chunk_ord}",
            chunk_metadata={"n": chunk_ord},
        )
        db.add(chunk)
        await db.commit()
        await db.refresh(chunk)
        return chunk

    return create


@pytest.fixture
def direct_collection() -> Callable[..., Awaitable[Collection]]:
    async def create(
        db: AsyncSession,
        owner: User,
        name: str,
        visibility: str = "private",
        *,
        kind: str = "library",
        chat_id: UUID | None = None,
    ) -> Collection:
        collection = Collection(
            owner_id=owner.id,
            name=name,
            visibility=visibility,
            kind=kind,
            chat_id=chat_id,
        )
        db.add(collection)
        await db.commit()
        await db.refresh(collection)
        return collection

    return create


@pytest.fixture
def make_chat() -> Callable[..., Awaitable[Chat]]:
    async def create(db: AsyncSession, owner: User) -> Chat:
        chat = Chat(user_id=owner.id, title="t")
        db.add(chat)
        await db.commit()
        await db.refresh(chat)
        return chat

    return create


@pytest.fixture
async def user_a(
    db: AsyncSession, user_a_headers: dict[str, str]
) -> User:
    return await _user(db, "source-a@test.dev")


@pytest.fixture
async def user_b(
    db: AsyncSession, user_b_headers: dict[str, str]
) -> User:
    return await _user(db, "source-b@test.dev")


async def _user(db: AsyncSession, email: str) -> User:
    return (await db.execute(select(User).where(User.email == email))).scalar_one()
