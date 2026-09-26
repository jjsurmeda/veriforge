from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Collection, Document, WebPage


async def _no_defer(document_id: UUID) -> None:
    return None


async def test_library_upload_is_admin_only_and_always_lands_in_shared(
    client: AsyncClient,
    user_a_headers: dict[str, str],
    admin_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("ingest.upload.defer_ingest_document", _no_defer)

    forbidden = await client.post(
        "/library/documents",
        files={"file": ("mine.txt", b"alpha", "text/plain")},
        headers=user_a_headers,
    )
    assert forbidden.status_code == 403, forbidden.text

    published = await client.post(
        "/library/documents",
        files={"file": ("policy.txt", b"policy", "text/plain")},
        headers=admin_headers,
    )
    assert published.status_code == 201, published.text

    shared = (
        await db.execute(select(Collection).where(Collection.visibility == "shared"))
    ).scalar_one()
    document = (
        await db.execute(select(Document).where(Document.id == UUID(published.json()["id"])))
    ).scalar_one()
    assert document.collection_id == shared.id


async def test_library_listing_shows_shared_documents_and_questions_only(
    client: AsyncClient,
    user_a_headers: dict[str, str],
    admin_headers: dict[str, str],
    db: AsyncSession,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("ingest.upload.defer_ingest_document", _no_defer)
    published = await client.post(
        "/library/documents",
        files={"file": ("policy.txt", b"policy", "text/plain")},
        headers=admin_headers,
    )
    assert published.status_code == 201, published.text

    user_id = (
        await db.execute(text("SELECT id FROM users WHERE email = 'source-a@test.dev'"))
    ).scalar_one()
    db.add(
        Collection(
            owner_id=user_id,
            name="Library",
            visibility="private",
            kind="library",
            starter_questions=["What is in my library?"],
        )
    )
    shared = (
        await db.execute(select(Collection).where(Collection.visibility == "shared"))
    ).scalar_one()
    shared.starter_questions = ["What is the policy?"]
    await db.commit()

    listing = await client.get("/library", headers=user_a_headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert [row["name"] for row in body["documents"]] == ["policy.txt"]
    assert all(row["shared"] is True for row in body["documents"])
    assert body["starter_questions"] == ["What is the policy?"]


async def test_pinning_a_web_source_into_the_library_is_rejected(
    client: AsyncClient, user_a_headers: dict[str, str], db: AsyncSession
) -> None:
    chat = (await client.post("/chats", json={}, headers=user_a_headers)).json()
    page = WebPage(
        chat_id=UUID(chat["id"]),
        url="https://example.test",
        title="Example",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(page)
    await db.commit()

    response = await client.post(
        f"/web-sources/{page.id}/pin", json={"target": "library"}, headers=user_a_headers
    )
    assert response.status_code == 422, response.text
