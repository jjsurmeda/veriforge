from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from httpx import AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import Chunk, Document
from ingest.storage import get_object_store


async def test_upload_dedupe_and_stores_object(
    client: AsyncClient,
    user_a_headers: dict[str, str],
    make_collection: Callable[[AsyncClient, dict[str, str], str], Awaitable[str]],
    db: AsyncSession,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[UUID] = []

    async def fake_defer(document_id: UUID) -> None:
        calls.append(document_id)

    monkeypatch.setattr(get_settings(), "object_storage_dir", str(tmp_path))
    get_object_store.cache_clear()
    monkeypatch.setattr("ingest.router.defer_ingest_document", fake_defer)
    collection_id = await make_collection(client, user_a_headers, "uploads")
    payload = b"%PDF-1.4\nbody"

    first = await client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("doc.pdf", payload, "application/pdf")},
        headers=user_a_headers,
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["deduped"] is False
    assert body["status"] == "queued"
    assert len(body["sha256"]) == 64
    assert len(calls) == 1
    stored = await get_object_store().get(f"{collection_id}/{body['sha256']}")
    assert stored == payload

    second = await client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("again.pdf", payload, "application/pdf")},
        headers=user_a_headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["deduped"] is True
    assert second.json()["id"] == body["id"]
    assert len(calls) == 1
    count = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    assert count == 1


async def test_upload_limits_and_unsupported_type(
    client: AsyncClient,
    user_a_headers: dict[str, str],
    make_collection: Callable[[AsyncClient, dict[str, str], str], Awaitable[str]],
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_defer(document_id: UUID) -> None:
        return None

    monkeypatch.setattr("ingest.router.defer_ingest_document", fake_defer)
    settings = get_settings()
    monkeypatch.setattr(settings, "max_upload_bytes", 4)
    collection_id = await make_collection(client, user_a_headers, "uploads")

    too_large = await client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("doc.txt", b"12345", "text/plain")},
        headers=user_a_headers,
    )
    assert too_large.status_code == 413, too_large.text

    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    unsupported = await client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("app.exe", b"MZ", "application/octet-stream")},
        headers=user_a_headers,
    )
    assert unsupported.status_code == 415, unsupported.text


async def test_patch_delete_and_reindex_document(
    client: AsyncClient,
    user_a_headers: dict[str, str],
    make_collection: Callable[[AsyncClient, dict[str, str], str], Awaitable[str]],
    db: AsyncSession,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[UUID] = []

    async def fake_defer(document_id: UUID) -> None:
        calls.append(document_id)

    monkeypatch.setattr(get_settings(), "object_storage_dir", str(tmp_path))
    get_object_store.cache_clear()
    monkeypatch.setattr("ingest.router.defer_ingest_document", fake_defer)
    collection_id = await make_collection(client, user_a_headers, "uploads")
    uploaded = await client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("note.md", b"# hello", "text/markdown")},
        headers=user_a_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]
    document = await db.get(Document, UUID(document_id))
    assert document is not None
    document.status = "failed"
    document.error = "boom"
    await db.commit()

    patch = await client.patch(
        f"/documents/{document_id}", json={"tags": ["alpha", "beta"]}, headers=user_a_headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["tags"] == ["alpha", "beta"]

    reindex = await client.post(f"/documents/{document_id}/reindex", headers=user_a_headers)
    assert reindex.status_code == 200, reindex.text
    assert reindex.json()["status"] == "queued"
    assert reindex.json()["error"] is None
    assert calls == [UUID(document_id), UUID(document_id)]

    delete = await client.delete(f"/documents/{document_id}", headers=user_a_headers)
    assert delete.status_code == 204, delete.text
    db.expire_all()
    assert await db.get(Document, UUID(document_id)) is None
    assert not (tmp_path / collection_id / uploaded.json()["sha256"]).exists()


async def test_chunks_are_ordered_and_include_heading_path(
    client: AsyncClient,
    user_a_headers: dict[str, str],
    make_collection: Callable[[AsyncClient, dict[str, str], str], Awaitable[str]],
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
    make_chunk: Callable[[AsyncSession, Document, int, int], Awaitable[Chunk]],
    db: AsyncSession,
) -> None:
    collection_id = await make_collection(client, user_a_headers, "chunks")
    document = await make_document(db, collection_id, "chunks.txt")
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
