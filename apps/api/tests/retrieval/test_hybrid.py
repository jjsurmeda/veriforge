"""Critical tier (testing.md): the ownership filter is the highest-cost-of-bug
query in the system — cross-user leakage and widen-attempts are covered here
at ~100% branch coverage of build_scope."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document, Section, User
from retrieval.filters import ClientFilters, Ownership
from retrieval.hybrid import ScoredChunk, hybrid_search
from tests.retrieval.conftest import (
    add_chunk,
    make_chat,
    make_collection,
    vec,
)

QUERY_TEXT = "zebra quoll aardvark"
QUERY_VEC = vec(1)


async def _search(
    db: AsyncSession,
    ownership: Ownership,
    filters: ClientFilters | None = None,
    lexical_weight: float | None = None,
) -> list[ScoredChunk]:
    return await hybrid_search(
        db,
        query_text=QUERY_TEXT,
        query_embedding=QUERY_VEC,
        ownership=ownership,
        filters=filters,
        lexical_weight=lexical_weight,
    )


async def test_retrieval_excludes_other_users_chunks(
    db: AsyncSession,
    user_a: User,
    user_b: User,
    seed_document: Callable[..., Awaitable[tuple[Document, Section]]],
) -> None:
    coll_a = await make_collection(db, user_a, "zebra")
    coll_b = await make_collection(db, user_b, "zebra")
    _, section_a = await seed_document(db, coll_a)
    _, section_b = await seed_document(db, coll_b)
    own = await add_chunk(
        db, document=await db.get(Document, section_a.document_id),
        section=section_a, ord=0, text_="unrelated own text",
        embedding=vec(2), page=1,
    )
    # B's chunk is the best possible match on both legs — must still be invisible.
    foreign = await add_chunk(
        db, document=await db.get(Document, section_b.document_id),
        section=section_b, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), page=1,
    )

    results = await _search(db, Ownership(user_id=user_a.id, collection_ids=[coll_a.id]))

    ids = {r.chunk_id for r in results}
    assert own.id in ids
    assert foreign.id not in ids


async def test_retrieval_document_filter_cannot_widen_to_other_users(
    db: AsyncSession,
    user_a: User,
    user_b: User,
    seed_document: Callable[..., Awaitable[tuple[Document, Section]]],
) -> None:
    coll_a = await make_collection(db, user_a, "a")
    coll_b = await make_collection(db, user_b, "b")
    doc_b, section_b = await seed_document(db, coll_b)
    await add_chunk(
        db, document=doc_b, section=section_b, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), page=1,
    )
    # Crafted filter naming B's document AND naming B's collection via scope:
    # the ownership predicate is ANDed inside, so both attempts return nothing.
    by_doc = await _search(
        db,
        Ownership(user_id=user_a.id, collection_ids=[coll_a.id]),
        ClientFilters(document_ids=[doc_b.id]),
    )
    assert by_doc == []
    by_scope = await _search(db, Ownership(user_id=user_a.id, collection_ids=[coll_b.id]))
    assert by_scope == []


async def test_retrieval_includes_shared_collections(
    db: AsyncSession,
    user_a: User,
    user_b: User,
    seed_document: Callable[..., Awaitable[tuple[Document, Section]]],
) -> None:
    coll_b = await make_collection(db, user_b, "shared", visibility="shared")
    doc_b, section_b = await seed_document(db, coll_b)
    hit = await add_chunk(
        db, document=doc_b, section=section_b, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), page=3,
    )

    results = await _search(db, Ownership(user_id=user_a.id, collection_ids=[coll_b.id]))

    assert [r.chunk_id for r in results] == [hit.id]
    assert results[0].document_name == "doc.txt"
    assert results[0].page == 3
    assert results[0].vector_score is not None and results[0].vector_score > 0.99
    assert results[0].bm25_score is not None and results[0].bm25_score > 0
    assert results[0].fused_score > 0


async def test_retrieval_empty_collections_returns_nothing(
    db: AsyncSession, user_a: User
) -> None:
    assert await _search(db, Ownership(user_id=user_a.id, collection_ids=[])) == []


async def test_retrieval_web_chunks_scoped_to_owning_chat(
    db: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    chat_a = await make_chat(db, user_a, [])
    chat_b = await make_chat(db, user_b, [])
    own_web = await add_chunk(
        db, document=None, section=None, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), source_type="web", chat_id=chat_a.id,
    )
    other_web = await add_chunk(
        db, document=None, section=None, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), source_type="web", chat_id=chat_b.id,
    )

    results = await _search(
        db, Ownership(user_id=user_a.id, collection_ids=[], chat_id=chat_a.id)
    )
    ids = {r.chunk_id for r in results}
    assert own_web.id in ids
    assert other_web.id not in ids
    # A web chunk never leaks through the document branch of another user.
    no_chat = await _search(db, Ownership(user_id=user_a.id, collection_ids=[]))
    assert no_chat == []


async def test_rrf_orders_dual_match_above_single_leg(
    db: AsyncSession,
    user_a: User,
    seed_document: Callable[..., Awaitable[tuple[Document, Section]]],
) -> None:
    coll = await make_collection(db, user_a, "a")
    doc, section = await seed_document(db, coll)
    dual = await add_chunk(
        db, document=doc, section=section, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), page=1,
    )
    vec_only = await add_chunk(
        db, document=doc, section=section, ord=1, text_="unrelated prose",
        embedding=vec(1, bump=0.5), page=2,
    )

    results = await _search(db, Ownership(user_id=user_a.id, collection_ids=[coll.id]))

    assert [r.chunk_id for r in results][:2] == [dual.id, vec_only.id]
    assert results[0].fused_score > results[1].fused_score
    assert results[1].bm25_score is None


async def test_lexical_weight_selects_dominant_leg(
    db: AsyncSession,
    user_a: User,
    seed_document: Callable[..., Awaitable[tuple[Document, Section]]],
) -> None:
    coll = await make_collection(db, user_a, "a")
    doc, section = await seed_document(db, coll)
    bm25_hit = await add_chunk(
        db, document=doc, section=section, ord=0, text_=QUERY_TEXT,
        embedding=vec(99), page=1,
    )
    vec_hit = await add_chunk(
        db, document=doc, section=section, ord=1, text_="unrelated prose",
        embedding=vec(1, bump=1), page=2,
    )
    ownership = Ownership(user_id=user_a.id, collection_ids=[coll.id])

    lex_first = await _search(db, ownership, lexical_weight=1.0)
    assert lex_first[0].chunk_id == bm25_hit.id
    vec_first = await _search(db, ownership, lexical_weight=0.0)
    assert vec_first[0].chunk_id == vec_hit.id


async def test_client_filters_only_narrow(
    db: AsyncSession,
    user_a: User,
    seed_document: Callable[..., Awaitable[tuple[Document, Section]]],
) -> None:
    coll = await make_collection(db, user_a, "a")
    doc, section = await seed_document(db, coll, "tagged.pdf", mime="application/pdf",
                                       tags=["spec"])
    hit = await add_chunk(
        db, document=doc, section=section, ord=0, text_=QUERY_TEXT,
        embedding=vec(1, bump=1), page=7,
    )
    ownership = Ownership(user_id=user_a.id, collection_ids=[coll.id])

    async def top_chunk_id(filters: ClientFilters) -> UUID | None:
        results = await _search(db, ownership, filters)
        return results[0].chunk_id if results else None

    assert await top_chunk_id(ClientFilters(mime="application/pdf")) == hit.id
    assert await _search(db, ownership, ClientFilters(mime="text/plain")) == []
    assert await top_chunk_id(ClientFilters(tags=["spec"])) == hit.id
    assert await _search(db, ownership, ClientFilters(tags=["other"])) == []
    assert await top_chunk_id(ClientFilters(page=7)) == hit.id
    assert await _search(db, ownership, ClientFilters(page=8)) == []
    assert await top_chunk_id(ClientFilters(document_ids=[doc.id])) == hit.id
    assert await top_chunk_id(ClientFilters(source_type="document")) == hit.id
    assert await _search(db, ownership, ClientFilters(source_type="web")) == []
    from datetime import UTC, datetime, timedelta

    future = datetime.now(UTC) + timedelta(days=1)
    past = datetime.now(UTC) - timedelta(days=1)
    assert await top_chunk_id(ClientFilters(date_from=past)) == hit.id
    assert await _search(db, ownership, ClientFilters(date_from=future)) == []
    assert await top_chunk_id(ClientFilters(date_to=future)) == hit.id
    assert await _search(db, ownership, ClientFilters(date_to=past)) == []
