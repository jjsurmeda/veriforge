"""Starter questions regenerate per container for both ADR-002 kinds
(TRD §9.1 step 6) — a chat's own sources and a Library each get their own.
"""

import json
from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Collection, Document, User
from ingest.starter import run_starter_questions


@pytest.fixture
def excerpts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        seen.append(messages[-1]["content"])
        return json.dumps({"questions": [f"Q{len(seen)}a", f"Q{len(seen)}b", f"Q{len(seen)}c"]})

    monkeypatch.setattr("ingest.starter.complete", fake_complete)
    return seen


async def questions_for(db: AsyncSession, collection_id: UUID) -> list[str] | None:
    return (
        await db.execute(
            select(Collection.starter_questions).where(Collection.id == collection_id)
        )
    ).scalar_one()


async def test_starter_questions_are_regenerated_per_container(
    db: AsyncSession,
    user_a: User,
    make_chat: Callable[..., Awaitable[Chat]],
    direct_collection: Callable[..., Awaitable[Collection]],
    make_document: Callable[[AsyncSession, str, str], Awaitable[Document]],
    make_chunk: Callable[[AsyncSession, Document, int, int], Awaitable[object]],
    excerpts: list[str],
) -> None:
    chat = await make_chat(db, user_a)
    chat_container = await direct_collection(db, user_a, "Chat", kind="chat", chat_id=chat.id)
    library = await direct_collection(db, user_a, "Library")

    for container, section_ord in ((chat_container, 1), (library, 2)):
        document = await make_document(db, str(container.id), f"doc-{section_ord}.txt")
        await make_chunk(db, document, section_ord, 1)

    await run_starter_questions(chat_container.id)
    await run_starter_questions(library.id)

    assert await questions_for(db, chat_container.id) == ["Q1a", "Q1b", "Q1c"]
    assert await questions_for(db, library.id) == ["Q2a", "Q2b", "Q2c"]
    assert len(excerpts) == 2
    assert "Section 1" in excerpts[0]
    assert "Section 2" in excerpts[1]


async def test_starter_questions_skip_a_container_with_no_chunks(
    db: AsyncSession,
    user_a: User,
    direct_collection: Callable[..., Awaitable[Collection]],
    excerpts: list[str],
) -> None:
    empty = await direct_collection(db, user_a, "Empty")

    await run_starter_questions(empty.id)

    assert await questions_for(db, empty.id) is None
    assert excerpts == []
