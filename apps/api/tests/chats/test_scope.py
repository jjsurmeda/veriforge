"""Critical tier (testing.md): who is in a chat's scope (ADR-002 addendum,
TRD §9.2). A chat searches its own sources plus every Shared collection — a
private `library` collection drops out of scope entirely.

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


async def make_chat(db: AsyncSession, user: User) -> Chat:
    chat = Chat(user_id=user.id, title="t")
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


async def make_chat_container(db: AsyncSession, user: User, chat: Chat) -> Collection:
    return await make_collection(db, user, "chat", kind="chat", chat_id=chat.id)


async def test_scope_is_the_chats_own_container_plus_every_shared_collection(
    db: AsyncSession, user_a: User, user_b: User
) -> None:
    chat_a = await make_chat(db, user_a)
    own = await make_chat_container(db, user_a, chat_a)
    private_library = await make_collection(db, user_a, "A library")
    shared_b = await make_collection(db, user_b, "shared-b", visibility="shared")
    shared_c = await make_collection(db, user_a, "shared-a", visibility="shared")
    chat_container_b = await make_chat_container(db, user_b, await make_chat(db, user_b))
    library_b = await make_collection(db, user_b, "B library")

    scope = set(await resolve_scope(db, chat_a))

    assert own.id in scope
    assert {shared_b.id, shared_c.id} <= scope
    assert private_library.id not in scope
    assert library_b.id not in scope
    assert chat_container_b.id not in scope


async def test_a_chat_without_a_container_still_reaches_shared(
    db: AsyncSession, user_a: User
) -> None:
    chat = await make_chat(db, user_a)
    shared = await make_collection(db, user_a, "shared", visibility="shared")

    assert await resolve_scope(db, chat) == [shared.id]


async def test_web_chunks_stay_reachable(db: AsyncSession, user_a: User) -> None:
    chat = await make_chat(db, user_a)
    web_chunk = await add_chunk(
        db, document=None, section=None, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), source_type="web", chat_id=chat.id,
    )
    ownership = Ownership(
        user_id=user_a.id, collection_ids=await resolve_scope(db, chat), chat_id=chat.id
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


async def test_retrieval_reaches_shared_and_own_documents_and_nothing_else(
    db: AsyncSession, user_a: User, user_b: User
) -> None:
    chat = await make_chat(db, user_a)
    own_container = await make_chat_container(db, user_a, chat)
    shared = await make_collection(db, user_b, "shared", visibility="shared")
    private_library = await make_collection(db, user_a, "library")
    foreign_container = await make_chat_container(db, user_b, await make_chat(db, user_b))
    foreign_library = await make_collection(db, user_b, "B library")

    expected = {
        (await _document(db, own_container, "chat.txt")).id,
        (await _document(db, shared, "shared.txt")).id,
    }
    excluded = {
        (await _document(db, private_library, "my-library.txt")).id,
        (await _document(db, foreign_container, "b-chat.txt")).id,
        (await _document(db, foreign_library, "b-library.txt")).id,
    }
    for document_id in expected | excluded:
        await _chunk(db, document_id, QUERY_TEXT, vec(1, bump=1))

    ownership = Ownership(
        user_id=user_a.id, collection_ids=await resolve_scope(db, chat), chat_id=chat.id
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


async def test_starter_questions_read_shared_only_and_fall_back_to_it(
    db: AsyncSession, user_a: User, user_b: User
) -> None:
    chat = await make_chat(db, user_a)
    private_library = await make_collection(db, user_a, "library")
    private_library.starter_questions = ["What is my policy?"]
    shared = await make_collection(db, user_b, "shared", visibility="shared")
    shared.starter_questions = ["What is the policy?", "Who owns this?"]
    await db.commit()

    assert await library_starter_questions(db) == ["What is the policy?", "Who owns this?"]
    assert await chat_starter_questions(db, chat) == await library_starter_questions(db)

    own = await make_chat_container(db, user_a, chat)
    own.starter_questions = ["What did this chat upload?"]
    await db.commit()

    assert await chat_starter_questions(db, chat) == ["What did this chat upload?"]
