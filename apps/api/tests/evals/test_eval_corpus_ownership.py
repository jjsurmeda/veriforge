"""Critical tier: the eval corpora are invisible to real users (KI-24).

The AW-2000 seed corpus and the counterfactual corpus are
`visibility='private'` collections owned by `evals@veriforge.local`. Before
this move they were `visibility='shared'`, which put a benchmark fixture in
every user's retrieval scope for every question in every mode — and meant a
`not_in_sources` item could pass only because the out-of-scope answer was
sitting right there.

Two facts are pinned here, end to end through the real SQL:

- a **normal** user's retrieval never returns an eval-corpus chunk, even when
  the collection id is handed to `resolve_scope` explicitly;
- the **eval** user's does, because `build_scope` admits a collection the user
  owns.

The second half is not decoration: it is the whole reason acceptance can sign in
as the eval account instead of a throwaway signup. If this file ever fails,
either the eval numbers are measuring nothing or the corpus has leaked back to
every user — both are worse than the state it replaced.
"""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chats.scope import resolve_scope
from db.ids import uuid7
from db.models import Chat, Chunk, Collection, Document, Plan, User
from evals.loader import CORPUS_NAME, EVAL_USER_EMAIL
from retrieval.filters import ClientFilters, Ownership
from retrieval.hybrid import hybrid_search
from tests.chats.test_scope import _chunk, _document
from tests.retrieval.conftest import make_chat, make_collection, vec

QUERY_TEXT = "AW-2000 torque retaining screw"
QUERY_VEC = vec(7)


async def make_eval_owner(db: AsyncSession) -> User:
    """The account `evals/loader.py::ensure_eval_user` creates."""
    plan_id = (await db.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    user = User(id=uuid7(), email=EVAL_USER_EMAIL, role="user", plan_id=plan_id, status="active")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def make_eval_corpus(db: AsyncSession, owner: User, name: str = CORPUS_NAME) -> Collection:
    """A private collection owned by the eval user, holding one matching chunk."""
    collection = await make_collection(db, owner, name, visibility="private")
    document = await _document(db, collection, "manual.md")
    await _chunk(db, document.id, QUERY_TEXT, vec(7, bump=1))
    return collection


async def chunk_ids_in(db: AsyncSession, collection: Collection) -> set[UUID]:
    document_ids = (
        (await db.execute(select(Document.id).where(Document.collection_id == collection.id)))
        .scalars()
        .all()
    )
    rows = (
        (await db.execute(select(Chunk.id).where(Chunk.document_id.in_(document_ids))))
        .scalars()
        .all()
    )
    return set(rows)


async def search(db: AsyncSession, user: User, chat: Chat, scope: list[UUID]) -> set[UUID]:
    ownership = Ownership(user_id=user.id, collection_ids=scope, chat_id=chat.id)
    results = await hybrid_search(
        db,
        query_text=QUERY_TEXT,
        query_embedding=QUERY_VEC,
        ownership=ownership,
        filters=ClientFilters(),
        lexical_weight=0.5,
    )
    return {result.chunk_id for result in results}


async def test_a_real_users_own_scope_excludes_the_eval_corpus(
    db: AsyncSession, user_a: User
) -> None:
    owner = await make_eval_owner(db)
    corpus = await make_eval_corpus(db, owner)
    chat = await make_chat(db, user_a)

    assert corpus.id not in await resolve_scope(db, chat)


async def test_the_ownership_sql_refuses_an_eval_corpus_id_handed_to_a_stranger(
    db: AsyncSession, user_a: User, user_b: User
) -> None:
    """`resolve_scope` accepts caller-supplied ids, so the ownership predicate
    in `build_scope` is the only thing between a bug there and a cross-user
    leak. Prove the SQL holds even when the id is passed deliberately.

    A Shared control collection carries the same text, so an empty result can
    only mean the eval corpus was excluded — not that the query matched nothing.
    """
    owner = await make_eval_owner(db)
    corpus = await make_eval_corpus(db, owner)
    control = await make_collection(db, user_b, "Shared", visibility="shared")
    control_doc = await _document(db, control, "public.md")
    await _chunk(db, control_doc.id, QUERY_TEXT, vec(7, bump=2))

    chat = await make_chat(db, user_a)
    scope = [*await resolve_scope(db, chat), corpus.id]
    assert corpus.id in scope, "the id should be offered; the SQL must refuse it"

    found = await search(db, user_a, chat, scope)

    assert found.isdisjoint(await chunk_ids_in(db, corpus)), "a real user saw eval content"
    assert found & await chunk_ids_in(db, control), "the control chunk was missed"


async def test_the_eval_user_reaches_its_own_private_corpus(db: AsyncSession) -> None:
    """Private is not unreachable. Without this half the runners score nothing."""
    owner = await make_eval_owner(db)
    corpus = await make_eval_corpus(db, owner)
    chat = await make_chat(db, owner)

    scope = [*await resolve_scope(db, chat), corpus.id]

    assert await chunk_ids_in(db, corpus) <= await search(db, owner, chat, scope)


async def test_a_private_library_stays_out_of_scope_by_default(
    db: AsyncSession, user_a: User
) -> None:
    """The ADR-002 rule the design leans on: a private library is in nobody's
    chat scope unless a caller asks for it by id. If this changed, every
    private collection in the product would quietly start changing answers."""
    private = await make_collection(db, user_a, "A private library", visibility="private")
    shared = await make_collection(db, user_a, "Shared", visibility="shared")
    chat = await make_chat(db, user_a)

    scope = set(await resolve_scope(db, chat))

    assert private.id not in scope
    assert shared.id in scope


@pytest.mark.parametrize("corpus_name", [CORPUS_NAME, "eval-counterfactual-corpus"])
async def test_every_eval_corpus_collection_is_private_by_construction(
    db: AsyncSession, corpus_name: str
) -> None:
    """The loader is what a fresh setup runs, so the guarantee belongs to the
    loader's output rather than to a hand edit someone has to remember."""
    owner = await make_eval_owner(db)
    collection = await make_eval_corpus(db, owner, corpus_name)

    reloaded = (await db.get(Collection, collection.id)).visibility

    assert reloaded == "private"
