from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from httpx import AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import Chunk, Collection, Document, User
from ingest.storage import get_object_store


async def test_upload_dedupe_and_stores_object(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[UUID] = []

    async def fake_defer(document_id: UUID) -> None:
        calls.append(document_id)

    monkeypatch.setattr(get_settings(), "object_storage_dir", str(tmp_path))
    get_object_store.cache_clear()
    monkeypatch.setattr("ingest.upload.defer_ingest_document", fake_defer)
    payload = b"%PDF-1.4\nbody"

    first = await client.post(
        "/library/documents",
        files={"file": ("doc.pdf", payload, "application/pdf")},
        headers=admin_headers,
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["deduped"] is False
    assert body["status"] == "queued"
    assert len(body["sha256"]) == 64
    assert len(calls) == 1
    shared = (
        await db.execute(select(Collection).where(Collection.visibility == "shared"))
    ).scalar_one()
    container_id = str(shared.id)
    stored = await get_object_store().get(f"{container_id}/{body['sha256']}")
    assert stored == payload

    second = await client.post(
        "/library/documents",
        files={"file": ("again.pdf", payload, "application/pdf")},
        headers=admin_headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["deduped"] is True
    assert second.json()["id"] == body["id"]
    assert len(calls) == 1
    count = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    assert count == 1


async def test_library_uploads_land_in_one_container(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_defer(document_id: UUID) -> None:
        return None

    monkeypatch.setattr("ingest.upload.defer_ingest_document", fake_defer)

    first = await client.post(
        "/library/documents",
        files={"file": ("a.txt", b"alpha", "text/plain")},
        headers=admin_headers,
    )
    second = await client.post(
        "/library/documents",
        files={"file": ("b.txt", b"beta", "text/plain")},
        headers=admin_headers,
    )
    assert first.status_code == 201 and second.status_code == 201

    listing = await client.get("/library", headers=admin_headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert {row["name"] for row in body["documents"]} == {"a.txt", "b.txt"}
    assert all(row["shared"] is True for row in body["documents"])


async def test_upload_limits_and_unsupported_type(
    client: AsyncClient,
    admin_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_defer(document_id: UUID) -> None:
        return None

    monkeypatch.setattr("ingest.upload.defer_ingest_document", fake_defer)
    settings = get_settings()
    monkeypatch.setattr(settings, "max_upload_bytes", 4)

    too_large = await client.post(
        "/library/documents",
        files={"file": ("doc.txt", b"12345", "text/plain")},
        headers=admin_headers,
    )
    assert too_large.status_code == 413, too_large.text

    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    unsupported = await client.post(
        "/library/documents",
        files={"file": ("app.exe", b"MZ", "application/octet-stream")},
        headers=admin_headers,
    )
    assert unsupported.status_code == 415, unsupported.text


async def test_demo_role_can_read_the_library_but_not_upload(
    client: AsyncClient,
    db: AsyncSession,
    admin_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_defer(document_id: UUID) -> None:
        return None

    monkeypatch.setattr("ingest.upload.defer_ingest_document", fake_defer)
    published = await client.post(
        "/library/documents",
        files={"file": ("demo.txt", b"demo corpus", "text/plain")},
        headers=admin_headers,
    )
    assert published.status_code == 201, published.text

    demo = await client.post(
        "/auth/signup", json={"email": "demo-role@test.dev", "password": "password123"}
    )
    assert demo.status_code == 201, demo.text
    await db.execute(
        text("UPDATE users SET role = 'demo' WHERE email = :email"),
        {"email": "demo-role@test.dev"},
    )
    await db.commit()
    login = await client.post(
        "/auth/login", json={"email": "demo-role@test.dev", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    listing = await client.get("/library", headers=headers)
    assert listing.status_code == 200, listing.text
    assert [row["name"] for row in listing.json()["documents"]] == ["demo.txt"]

    blocked = await client.post(
        "/library/documents",
        files={"file": ("mine.txt", b"nope", "text/plain")},
        headers=headers,
    )
    assert blocked.status_code == 403, blocked.text

    chat = await client.post("/chats", json={}, headers=headers)
    chat_upload = await client.post(
        f"/chats/{chat.json()['id']}/documents",
        files={"file": ("mine.txt", b"nope", "text/plain")},
        headers=headers,
    )
    assert chat_upload.status_code == 403, chat_upload.text


async def test_patch_delete_and_reindex_document(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[UUID] = []

    async def fake_defer(document_id: UUID) -> None:
        calls.append(document_id)

    monkeypatch.setattr(get_settings(), "object_storage_dir", str(tmp_path))
    get_object_store.cache_clear()
    monkeypatch.setattr("ingest.upload.defer_ingest_document", fake_defer)
    monkeypatch.setattr("ingest.router.defer_ingest_document", fake_defer)
    uploaded = await client.post(
        "/library/documents",
        files={"file": ("note.md", b"# hello", "text/markdown")},
        headers=admin_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]
    shared = (
        await db.execute(select(Collection).where(Collection.visibility == "shared"))
    ).scalar_one()
    container_id = str(shared.id)
    document = await db.get(Document, UUID(document_id))
    assert document is not None
    document.status = "failed"
    document.error = "boom"
    await db.commit()

    patch = await client.patch(
        f"/documents/{document_id}", json={"tags": ["alpha", "beta"]}, headers=admin_headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["tags"] == ["alpha", "beta"]

    reindex = await client.post(f"/documents/{document_id}/reindex", headers=admin_headers)
    assert reindex.status_code == 200, reindex.text
    assert reindex.json()["status"] == "queued"
    assert reindex.json()["error"] is None
    assert calls == [UUID(document_id), UUID(document_id)]

    delete = await client.delete(f"/documents/{document_id}", headers=admin_headers)
    assert delete.status_code == 204, delete.text
    db.expire_all()
    assert await db.get(Document, UUID(document_id)) is None
    assert not (tmp_path / container_id / uploaded.json()["sha256"]).exists()


async def test_chat_documents_are_created_listed_and_cascade_deleted(
    client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_defer(document_id: UUID) -> None:
        return None

    monkeypatch.setattr(get_settings(), "object_storage_dir", str(tmp_path))
    get_object_store.cache_clear()
    monkeypatch.setattr("ingest.upload.defer_ingest_document", fake_defer)
    chat = await client.post("/chats", json={"title": "Sources"}, headers=user_a_headers)
    chat_id = chat.json()["id"]

    assert (await client.get(f"/chats/{chat_id}/documents", headers=user_a_headers)).json() == []

    uploaded = await client.post(
        f"/chats/{chat_id}/documents",
        files={"file": ("chat.txt", b"chat bytes", "text/plain")},
        headers=user_a_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]

    listed = await client.get(f"/chats/{chat_id}/documents", headers=user_a_headers)
    assert [row["id"] for row in listed.json()] == [document_id]

    foreign_list = await client.get(f"/chats/{chat_id}/documents", headers=user_b_headers)
    assert foreign_list.status_code == 404, foreign_list.text
    other = await client.post(
        f"/chats/{chat_id}/documents",
        files={"file": ("b.txt", b"b", "text/plain")},
        headers=user_b_headers,
    )
    assert other.status_code == 404, other.text

    containers = (
        await db.execute(select(Collection).where(Collection.chat_id == UUID(chat_id)))
    ).scalars().all()
    assert len(containers) == 1
    assert containers[0].kind == "chat"

    assert (await client.delete(f"/chats/{chat_id}", headers=user_a_headers)).status_code == 204
    db.expire_all()
    assert await db.get(Document, UUID(document_id)) is None
    assert (
        await db.execute(select(Collection).where(Collection.chat_id == UUID(chat_id)))
    ).scalars().all() == []


async def test_chunks_are_ordered_and_include_heading_path(
    client: AsyncClient,
    user_a_headers: dict[str, str],
    direct_collection: Callable[..., Awaitable[Collection]],
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
    make_chunk: Callable[[AsyncSession, Document, int, int], Awaitable[Chunk]],
    db: AsyncSession,
    user_a: User,
) -> None:
    container = await direct_collection(db, user_a, "chunks")
    document = await make_document(db, str(container.id), "chunks.txt")
    await make_chunk(db, document, 2, 1)
    await make_chunk(db, document, 1, 2)
    await make_chunk(db, document, 1, 1)

    response = await client.get(f"/documents/{document.id}/chunks", headers=user_a_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [(row["heading_path"], row["ord"]) for row in rows] == [
        ("Section 1", 1),
        ("Section 1", 2),
        ("Section 2", 1),
    ]
    assert rows[0]["metadata"] == {"n": 1}
