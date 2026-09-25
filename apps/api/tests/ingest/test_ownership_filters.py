"""Critical tier (testing.md): cross-user visibility across the chat-sources
and Library endpoints (ADR-002, TRD §11).

Collections are no longer addressable, so the leak surfaces are the chat
document routes, the Library list, and the document routes that are
unchanged.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Collection, Document, User
from ingest.repository import get_owned_collection, get_visible_collection

Container = Callable[..., Awaitable[Collection]]


async def test_repository_visibility_branches(
    db: AsyncSession,
    user_a: User,
    user_b: User,
    direct_collection: Container,
) -> None:
    own = await direct_collection(db, user_a, "own")
    shared = await direct_collection(db, user_b, "shared", visibility="shared")
    private = await direct_collection(db, user_b, "private")

    assert (await get_visible_collection(db, user_a, own.id)) is not None
    assert (await get_visible_collection(db, user_a, shared.id)) is not None
    assert await get_visible_collection(db, user_a, private.id) is None
    assert await get_owned_collection(db, user_a, shared.id) is None


async def test_library_lists_own_and_shared_only(
    db: AsyncSession,
    client: AsyncClient,
    user_a: User,
    user_a_headers: dict[str, str],
    user_b: User,
    direct_collection: Container,
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
    make_chunk: Callable[[AsyncSession, Document, int, int], Awaitable[object]],
) -> None:
    own = await direct_collection(db, user_a, "A private")
    other_shared = await direct_collection(db, user_b, "B shared", visibility="shared")
    other_private = await direct_collection(db, user_b, "B private")
    await make_document(db, str(other_shared.id), "shared.txt")
    await make_document(db, str(other_private.id), "leak.txt")
    await make_document(db, str(own.id), "mine.txt")

    listing = await client.get("/library", headers=user_a_headers)
    assert listing.status_code == 200, listing.text
    names = {row["name"] for row in listing.json()["documents"]}
    assert names == {"shared.txt", "mine.txt"}


async def test_chat_documents_are_owner_only(
    client: AsyncClient,
    db: AsyncSession,
    user_a: User,
    user_a_headers: dict[str, str],
    user_b: User,
    make_chat: Callable[..., Awaitable[Chat]],
    direct_collection: Container,
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
    make_chunk: Callable[[AsyncSession, Document, int, int], Awaitable[object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def noop_defer(document_id: UUID) -> None:
        return None

    monkeypatch.setattr("ingest.upload.defer_ingest_document", noop_defer)
    chat_b = await make_chat(db, user_b)
    container = await direct_collection(db, user_b, "B chat", kind="chat", chat_id=chat_b.id)
    document = await make_document(db, str(container.id), "b.txt")
    await make_chunk(db, document, 1, 1)

    chat = await client.get(f"/chats/{chat_b.id}", headers=user_a_headers)
    assert chat.status_code == 404, chat.text
    listing = await client.get(f"/chats/{chat_b.id}/documents", headers=user_a_headers)
    assert listing.status_code == 404, listing.text
    upload = await client.post(
        f"/chats/{chat_b.id}/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
        headers=user_a_headers,
    )
    assert upload.status_code == 404, upload.text
    own_doc = await make_document(db, str(container.id), "b2.txt")
    checks = [
        await client.get(f"/documents/{own_doc.id}", headers=user_a_headers),
        await client.patch(
            f"/documents/{own_doc.id}", json={"tags": ["x"]}, headers=user_a_headers
        ),
        await client.delete(f"/documents/{own_doc.id}", headers=user_a_headers),
        await client.post(f"/documents/{own_doc.id}/reindex", headers=user_a_headers),
        await client.get(f"/documents/{own_doc.id}/chunks", headers=user_a_headers),
    ]
    assert [response.status_code for response in checks] == [404, 404, 404, 404, 404]
    assert await db.get(Document, own_doc.id) is not None


async def test_shared_documents_are_readable_but_not_editable(
    client: AsyncClient,
    db: AsyncSession,
    user_a_headers: dict[str, str],
    user_b: User,
    direct_collection: Container,
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
    make_chunk: Callable[[AsyncSession, Document, int, int], Awaitable[object]],
) -> None:
    shared = await direct_collection(db, user_b, "B shared", visibility="shared")
    document = await make_document(db, str(shared.id), "shared.txt")
    await make_chunk(db, document, 1, 1)

    document_id = document.id
    read = await client.get(f"/documents/{document_id}", headers=user_a_headers)
    assert read.status_code == 200, read.text
    chunks = await client.get(f"/documents/{document_id}/chunks", headers=user_a_headers)
    assert chunks.status_code == 200, chunks.text
    assert chunks.json()[0]["heading_path"] == "Section 1"
    patch = await client.patch(
        f"/documents/{document_id}", json={"tags": ["x"]}, headers=user_a_headers
    )
    assert patch.status_code == 404, patch.text
    delete = await client.delete(f"/documents/{document_id}", headers=user_a_headers)
    assert delete.status_code == 404, delete.text
    reindex = await client.post(f"/documents/{document_id}/reindex", headers=user_a_headers)
    assert reindex.status_code == 404, reindex.text


async def test_chat_containers_never_leak_into_the_library(
    client: AsyncClient,
    db: AsyncSession,
    user_a: User,
    user_a_headers: dict[str, str],
    make_chat: Callable[..., Awaitable[Chat]],
    direct_collection: Container,
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
) -> None:
    chat = await make_chat(db, user_a)
    container = await direct_collection(db, user_a, "chat", kind="chat", chat_id=chat.id)
    await make_document(db, str(container.id), "chat-only.txt")

    listing = await client.get("/library", headers=user_a_headers)
    assert [row["name"] for row in listing.json()["documents"]] == []


async def test_unauthenticated_sources_requests_are_401(client: AsyncClient) -> None:
    chat_id = "018f0000-0000-7000-8000-000000000001"
    document_id = "018f0000-0000-7000-8000-000000000002"
    responses = [
        await client.get("/library"),
        await client.post("/library/documents"),
        await client.get(f"/chats/{chat_id}/documents"),
        await client.post(f"/chats/{chat_id}/documents"),
        await client.get(f"/documents/{document_id}"),
        await client.get(f"/documents/{document_id}/chunks"),
    ]
    assert [response.status_code for response in responses] == [401] * 6


async def test_removed_collection_routes_are_gone(
    client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    headers = user_a_headers
    collection_id = "018f0000-0000-7000-8000-000000000003"
    responses = [
        await client.get("/collections", headers=headers),
        await client.post("/collections", json={"name": "x"}, headers=headers),
        await client.get(f"/collections/{collection_id}", headers=headers),
        await client.patch(f"/collections/{collection_id}", json={"name": "x"}, headers=headers),
        await client.delete(f"/collections/{collection_id}", headers=headers),
        await client.get(f"/collections/{collection_id}/documents", headers=headers),
        await client.post(
            f"/collections/{collection_id}/documents",
            files={"file": ("a.txt", b"a", "text/plain")},
            headers=headers,
        ),
    ]
    assert [response.status_code for response in responses] == [404] * 7
