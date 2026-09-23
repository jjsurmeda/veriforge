from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Collection, Document, User


async def _user_by_email(db: AsyncSession, email: str) -> User:
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    return user


async def test_repository_visibility_branches(
    db: AsyncSession,
    client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
    make_collection: Callable[[AsyncClient, dict[str, str], str], Awaitable[str]],
) -> None:
    from ingest.repository import get_owned_collection, get_visible_collection

    user_a = await _user_by_email(db, "source-a@test.dev")
    own_id = UUID(await make_collection(client, user_a_headers, "own"))
    shared_id = UUID(await make_collection(client, user_b_headers, "shared"))
    private_id = UUID(await make_collection(client, user_b_headers, "private"))
    shared = await db.get(Collection, shared_id)
    assert shared is not None
    shared.visibility = "shared"
    await db.commit()

    assert (await get_visible_collection(db, user_a, own_id)) is not None
    assert (await get_visible_collection(db, user_a, shared_id)) is not None
    assert await get_visible_collection(db, user_a, private_id) is None
    assert await get_owned_collection(db, user_a, shared_id) is None


async def test_collection_visibility_and_mutation_rules(
    db: AsyncSession,
    client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
    admin_headers: dict[str, str],
    make_collection: Callable[[AsyncClient, dict[str, str], str], Awaitable[str]],
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
    make_chunk: Callable[[AsyncSession, Document, int, int], Awaitable[object]],
) -> None:
    own_id = await make_collection(client, user_a_headers, "A private")
    other_private_id = await make_collection(client, user_b_headers, "B private")
    other_shared_id = await make_collection(client, user_b_headers, "B shared")
    other_shared = await db.get(Collection, UUID(other_shared_id))
    assert other_shared is not None
    other_shared.visibility = "shared"
    await db.commit()
    other_shared_doc = await make_document(db, other_shared_id, "shared.txt")
    await make_chunk(db, other_shared_doc, 1, 1)

    listing = await client.get("/collections", headers=user_a_headers)
    assert listing.status_code == 200, listing.text
    listed_ids = {row["id"] for row in listing.json()}
    assert own_id in listed_ids
    assert other_shared_id in listed_ids
    assert other_private_id not in listed_ids

    private_get = await client.get(f"/collections/{other_private_id}", headers=user_a_headers)
    assert private_get.status_code == 404, private_get.text
    private_patch = await client.patch(
        f"/collections/{other_private_id}", json={"name": "leak"}, headers=user_a_headers
    )
    assert private_patch.status_code == 404, private_patch.text
    private_delete = await client.delete(
        f"/collections/{other_private_id}", headers=user_a_headers
    )
    assert private_delete.status_code == 404, private_delete.text

    docs = await client.get(f"/collections/{other_shared_id}/documents", headers=user_a_headers)
    assert docs.status_code == 200, docs.text
    assert [row["id"] for row in docs.json()] == [str(other_shared_doc.id)]

    chunks = await client.get(f"/documents/{other_shared_doc.id}/chunks", headers=user_a_headers)
    assert chunks.status_code == 200, chunks.text
    assert chunks.json()[0]["heading_path"] == "Section 1"

    upload = await client.post(
        f"/collections/{other_shared_id}/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
        headers=user_a_headers,
    )
    assert upload.status_code == 404, upload.text
    patch_shared = await client.patch(
        f"/collections/{other_shared_id}", json={"name": "x"}, headers=user_a_headers
    )
    assert patch_shared.status_code == 404, patch_shared.text
    delete_shared = await client.delete(f"/collections/{other_shared_id}", headers=user_a_headers)
    assert delete_shared.status_code == 404, delete_shared.text

    forbidden = await client.patch(
        f"/collections/{own_id}", json={"visibility": "shared"}, headers=user_a_headers
    )
    assert forbidden.status_code == 403, forbidden.text
    admin_collection = await make_collection(client, admin_headers, "admin owned")
    published = await client.patch(
        f"/collections/{admin_collection}", json={"visibility": "shared"}, headers=admin_headers
    )
    assert published.status_code == 200, published.text
    assert published.json()["visibility"] == "shared"


async def test_document_private_other_user_is_not_visible_or_mutable(
    db: AsyncSession,
    client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
    make_collection: Callable[[AsyncClient, dict[str, str], str], Awaitable[str]],
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
    make_chunk: Callable[[AsyncSession, Document, int, int], Awaitable[object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def noop_defer(document_id: UUID) -> None:
        return None

    monkeypatch.setattr("ingest.router.defer_ingest_document", noop_defer)
    other_collection_id = await make_collection(client, user_b_headers, "B private")
    other_doc = await make_document(db, other_collection_id, "b.txt")
    await make_chunk(db, other_doc, 1, 1)

    checks = [
        await client.get(f"/documents/{other_doc.id}", headers=user_a_headers),
        await client.patch(
            f"/documents/{other_doc.id}", json={"tags": ["x"]}, headers=user_a_headers
        ),
        await client.delete(f"/documents/{other_doc.id}", headers=user_a_headers),
        await client.post(f"/documents/{other_doc.id}/reindex", headers=user_a_headers),
        await client.get(f"/documents/{other_doc.id}/chunks", headers=user_a_headers),
    ]
    assert [response.status_code for response in checks] == [404, 404, 404, 404, 404]
    assert await db.get(Document, other_doc.id) is not None


async def test_unauthenticated_sources_requests_are_401(client: AsyncClient) -> None:
    collection_id = "018f0000-0000-7000-8000-000000000001"
    document_id = "018f0000-0000-7000-8000-000000000002"
    responses = [
        await client.get("/collections"),
        await client.post("/collections", json={"name": "x"}),
        await client.get(f"/collections/{collection_id}/documents"),
        await client.get(f"/documents/{document_id}"),
        await client.get(f"/documents/{document_id}/chunks"),
    ]
    assert [response.status_code for response in responses] == [401, 401, 401, 401, 401]


async def test_shared_collection_private_transition_is_owner_only(
    db: AsyncSession,
    client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
    make_collection: Callable[[AsyncClient, dict[str, str], str], Awaitable[str]],
) -> None:
    shared_id = await make_collection(client, user_b_headers, "B shared")
    await db.execute(
        text("UPDATE collections SET visibility = 'shared' WHERE id = :id"), {"id": shared_id}
    )
    await db.commit()

    not_owner = await client.patch(
        f"/collections/{shared_id}", json={"visibility": "private"}, headers=user_a_headers
    )
    assert not_owner.status_code == 404, not_owner.text
    owner = await client.patch(
        f"/collections/{shared_id}", json={"visibility": "private"}, headers=user_b_headers
    )
    assert owner.status_code == 200, owner.text
    assert owner.json()["visibility"] == "private"
