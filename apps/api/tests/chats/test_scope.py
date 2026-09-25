"""Critical tier (testing.md): who is in a chat's scope (ADR-002, TRD §9.2).

Every container is seeded for real and the last test goes all the way
through build_scope + hybrid_search, because the scope list is only
meaningful once the ownership SQL has consumed it.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from chats.scope import chat_starter_questions, library_starter_questions, resolve_scope
from db.ids import uuid7
from db.models import Chat, Chunk, Collection, Document, Section, User
from retrieval.filters import ClientFilters, Ownership
from retrieval.hybrid import hybrid_search
from tests.retrieval.conftest import add_chunk, make_collection, vec

QUERY_TEXT = "zebra quoll aardvark"
QUERY_VEC = vec(1)


async def make_chat(db: AsyncSession, user: User, *, include_library: bool = True) -> Chat:
    chat = Chat(user_id=user.id, title="t", include_library=include_library)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


async def make_chat_container(db: AsyncSession, user: User, chat: Chat) -> Collection:
    return await make_collection(db, user, "chat", kind="chat", chat_id=chat.id)


async def test_other_users_chat_and_private_library_are_never_in_scope(
    db: AsyncSession, user_a: User, user_b: User
) -> None:
    chat_a = await make_chat(db, user_a)
    own = await make_chat_container(db, user_a, chat_a)
    library_a = await make_collection(db, user_a, "A library")
    chat_b = await make_chat(db, user_b)
    chat_container_b = await make_chat_container(db, user_b, chat_b)
    library_b = await make_collection(db, user_b, "B library")

    scope = set(await resolve_scope(db, user_a, chat_a))

    assert own.id in scope
    assert library_a.id in scope
    assert chat_container_b.id not in scope
    assert library_b.id not in scope


async def test_shared_is_included_only_when_include_library_is_on(
    db: AsyncSession, user_a: User, user_b: User
) -> None:
    chat_on = await make_chat(db, user_a)
    chat_off = await make_chat(db, user_a, include_library=False)
    shared = await make_collection(db, user_b, "shared", visibility="shared")

    assert shared.id in await resolve_scope(db, user_a, chat_on)
    assert shared.id not in await resolve_scope(db, user_a, chat_off)


async def test_include_library_off_leaves_only_the_chats_own_container(
    db: AsyncSession, user_a: User
) -> None:
    chat = await make_chat(db, user_a, include_library=False)
    own = await make_chat_container(db, user_a, chat)
    library = await make_collection(db, user_a, "library")

    assert await resolve_scope(db, user_a, chat) == [own.id]
    assert library.id not in await resolve_scope(db, user_a, chat)


async def test_chat_without_a_container_resolves_to_its_library_only(
    db: AsyncSession, user_a: User
) -> None:
    chat = await make_chat(db, user_a)
    library = await make_collection(db, user_a, "library")

    assert await resolve_scope(db, user_a, chat) == [library.id]


async def test_web_chunks_stay_reachable_with_include_library_off(
    db: AsyncSession, user_a: User
) -> None:
    chat = await make_chat(db, user_a, include_library=False)
    web_chunk = await add_chunk(
        db, document=None, section=None, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), source_type="web", chat_id=chat.id,
    )
    ownership = Ownership(
        user_id=user_a.id, collection_ids=await resolve_scope(db, user_a, chat), chat_id=chat.id
    )

    results = await hybrid_search(
        db,
        query_text=QUERY_TEXT,
        query_embedding=QUERY_VEC,
        ownership=ownership,
        filters=ClientFilters(),
        lexical_weight=0.5,
    )

    assert web_chunk.id in {result.chunk_id for result in results}


async def test_retrieval_returns_only_documents_inside_the_resolved_scope(
    db: AsyncSession, user_a: User, user_b: User
) -> None:
    chat = await make_chat(db, user_a)
    own_container = await make_chat_container(db, user_a, chat)
    library = await make_collection(db, user_a, "library")
    foreign_container = await make_chat_container(db, user_b, await make_chat(db, user_b))
    foreign_library = await make_collection(db, user_b, "library")

    expected = {
        (await _document(db, own_container, "chat.txt")).id,
        (await _document(db, library, "library.txt")).id,
    }
    excluded = {
        (await _document(db, foreign_container, "b-chat.txt")).id,
        (await _document(db, foreign_library, "b-library.txt")).id,
    }
    for document_id in expected | excluded:
        await _chunk(db, document_id, QUERY_TEXT, vec(1, bump=1))

    ownership = Ownership(
        user_id=user_a.id, collection_ids=await resolve_scope(db, user_a, chat), chat_id=chat.id
    )
    results = await hybrid_search(
        db,
        query_text=QUERY_TEXT,
        query_embedding=QUERY_VEC,
        ownership=ownership,
        filters=ClientFilters(),
        lexical_weight=0.5,
    )

    document_ids = {result.document_id for result in results}
    assert document_ids == expected
    assert not document_ids & excluded


async def _document(db: AsyncSession, container: Collection, name: str) -> Document:
    document = Document(
        collection_id=container.id,
        name=name,
        mime="text/plain",
        sha256=uuid7().hex + uuid7().hex,
        s3_key=f"{container.id}/{uuid7().hex}",
        status="ready",
        tags=[],
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def _chunk(db: AsyncSession, document_id: UUID, text: str, embedding: list[float]) -> None:
    section = Section(
        document_id=document_id, heading_path="h", ord=0, text=text, tokens=len(text) // 4
    )
    db.add(section)
    await db.flush()
    db.add(
        Chunk(
            document_id=document_id,
            section_id=section.id,
            ord=0,
            page=1,
            text=text,
            embedding=embedding,
            source_type="document",
        )
    )
    await db.commit()


async def test_starter_questions_prefer_the_chat_then_the_library(
    db: AsyncSession, user_a: User, user_b: User
) -> None:
    chat = await make_chat(db, user_a)
    library = await make_collection(db, user_a, "library")
    library.starter_questions = ["What is the policy?", "How do I start?"]
    shared = await make_collection(db, user_b, "shared", visibility="shared")
    shared.starter_questions = ["What is the policy?", "Who owns this?"]
    await db.commit()

    assert await library_starter_questions(db, user_a) == [
        "What is the policy?",
        "How do I start?",
        "Who owns this?",
    ]
    assert await chat_starter_questions(db, user_a, chat) == await library_starter_questions(
        db, user_a
    )

    own = await make_chat_container(db, user_a, chat)
    own.starter_questions = ["What did this chat upload?"]
    await db.commit()

    assert await chat_starter_questions(db, user_a, chat) == ["What did this chat upload?"]


async def test_starter_questions_skip_the_library_when_it_is_excluded(
    db: AsyncSession, user_a: User
) -> None:
    chat = await make_chat(db, user_a, include_library=False)
    library = await make_collection(db, user_a, "library")
    library.starter_questions = ["What is the policy?"]
    await db.commit()

    assert await chat_starter_questions(db, user_a, chat) == []
