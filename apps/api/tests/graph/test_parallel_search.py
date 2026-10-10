"""Beta lane B, item 2: the per-variant hybrid searches run concurrently, each
on its own session (TRD §7.1: "run the hybrid searches in parallel").

The searches used to share the run's single `AsyncSession` and run one after
another, which is both a concurrency limit (one session cannot run two
statements at once) and the other half of the stage's cost.

Real Postgres throughout (testing.md: retrieval is where SQL correctness is the
thing under test) and the REAL `hybrid_search`, so the ownership filter is
exercised as SQL rather than asserted against a mock. Fakes: the embedding
provider, the small LLM (three phrasings) and Jev.

What this holds the change to:

* every concurrent query still carries the server-side ownership filter, so a
  second user's chunks never appear (CLAUDE.md);
* fusion is UNCHANGED — the fused list rerank receives under the concurrent
  fan-out is identical, item for item, to fusing the same searches run one
  after another on one session;
* web chunks this run indexes are visible to the searches, which means they
  have to be committed before the fan-out (a session cannot see another
  session's uncommitted rows).
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import retrieval.hybrid as hybrid_module
import retrieval.web as web_module
from db.models import Chunk, Collection, Message
from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import (
    MULTI_QUERY_VARIANTS,
    AutoRunInput,
    _fuse_multi_query,
    _search_one_variant,
    prepare_auto_run,
)
from graph.ingress import IngressOutcome
from retrieval.filters import ClientFilters, Ownership
from tests.graph.test_chitchat import _IngressJev, _seed_chat
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import (
    add_chunk,
    make_chat,
    make_collection,
    make_document,
    make_section,
    make_user,
    vec,
)

WARRANTY = "The AW-2000 warranty is 24 months from the date of purchase."
OTHER_USERS_PASSAGE = "The Kestrel R-7 handbook states the admin password is hunter2."

_REAL_SEARCH = hybrid_module.hybrid_search
_REAL_RERANK = auto_module._rerank_candidates


@pytest.fixture
async def owner(db: AsyncSession) -> Any:
    return await make_user(db, "lane-b-owner@test.dev")


@pytest.fixture
async def stranger(db: AsyncSession) -> Any:
    return await make_user(db, "lane-b-stranger@test.dev")


async def _seed_corpus(
    db: AsyncSession, owner: Any, stranger: Any
) -> tuple[UUID, UUID, UUID]:
    """A collection the run may search holding the answering passage, and a
    second user's passage carrying the same keywords — which a missing
    ownership filter would return."""
    collection = await make_collection(db, owner, "docs")
    document = await make_document(db, collection, name="warranty.md")
    section = await make_section(db, document)
    mine = await add_chunk(
        db, document=document, section=section, ord=0, text_=WARRANTY, embedding=vec(2)
    )
    other_collection = await make_collection(db, stranger, "docs")
    other_document = await make_document(db, other_collection, name="kestrel.md")
    other_section = await make_section(db, other_document)
    theirs = await add_chunk(
        db,
        document=other_document,
        section=other_section,
        ord=0,
        text_=OTHER_USERS_PASSAGE,
        embedding=vec(2),
    )
    return collection.id, mine.id, theirs.id


def _patch_providers(
    monkeypatch: pytest.MonkeyPatch, searches: list[tuple[str, list[float]]]
) -> None:
    async def fake_complete(**_kwargs: Any) -> str:
        return "\n".join(f"warranty phrasing {index}" for index in range(1, MULTI_QUERY_VARIANTS))

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    async def recording_search(*args: Any, **kwargs: Any) -> Any:
        # Record (query, embedding) per call, then run the REAL search: the
        # ownership filter under test is the SQL one.
        searches.append((str(kwargs["query_text"]), list(kwargs["query_embedding"])))
        return await _REAL_SEARCH(*args, **kwargs)

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", recording_search)


class _PassThroughRerank:
    def __init__(self, *_args: object) -> None:
        pass

    async def rerank(
        self, *, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        return [(index, 1.0 - index / 100) for index in range(min(top_n, len(documents)))]


def _capture_fused(monkeypatch: pytest.MonkeyPatch, seen: list[list[str]]) -> None:
    """Record the fused list rerank receives, in order — the thing fusion
    changes."""

    async def capture(
        reranker: Any, *, query: str, chunks: Any, provenance: Any, limit: int
    ) -> Any:
        seen.append([str(chunk.chunk_id) for chunk in chunks])
        return await _REAL_RERANK(
            reranker, query=query, chunks=chunks, provenance=provenance, limit=limit
        )

    monkeypatch.setattr(auto_module, "_rerank_candidates", capture)


async def _params(
    db: AsyncSession, chat: Any, user: Any, message_id: UUID, collection_id: UUID
) -> AutoRunInput:
    return AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user.id,
        question="How long is the AW-2000 warranty?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="upload",
        client_filters=ClientFilters(),
        collection_ids=[collection_id],
    )


async def _run(
    db: AsyncSession,
    user: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    collection_id: UUID,
    source: str = "upload",
) -> tuple[Any, list[tuple[str, list[float]]], list[list[str]]]:
    chat, message_id = await _seed_chat(db, user)
    searches: list[tuple[str, list[float]]] = []
    fused: list[list[str]] = []
    _patch_providers(monkeypatch, searches)
    _capture_fused(monkeypatch, fused)
    monkeypatch.setattr(auto_module, "get_reranker", _PassThroughRerank)
    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user, message_id, collection_id),
        DecisionEngine(jev=_IngressJev("lookup"), mode="jev_only"),
    )
    return run, searches, fused


async def test_the_ownership_filter_holds_on_every_concurrent_search(
    db: AsyncSession,
    owner: Any,
    stranger: Any,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_id, _, theirs = await _seed_corpus(db, owner, stranger)
    run, searches, _ = await _run(db, owner, monkeypatch, collection_id=collection_id)

    assert len(searches) >= MULTI_QUERY_VARIANTS, "the fan-out really ran"
    assert (await db.get(Chunk, theirs)) is not None, "the stranger's chunk is in the database"
    for event in run.retrieval_events:
        found = {chunk.chunk_id for chunk in event.chunks}
        assert str(theirs) not in found, "another user's chunk leaked through a concurrent query"


async def test_the_concurrent_fusion_is_item_for_item_the_sequential_one(
    db: AsyncSession,
    owner: Any,
    stranger: Any,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parallel fan-out must not reorder or drop anything the sequential
    one produced. The reference is computed here rather than by re-running the
    pipeline: the same recorded (query, embedding) pairs, searched one at a
    time on one session and fused exactly as `retrieve_queries` fuses."""
    collection_id, mine, _ = await _seed_corpus(db, owner, stranger)
    run, searches, fused = await _run(db, owner, monkeypatch, collection_id=collection_id)

    assert fused, "the fused list was captured"
    assert str(mine) in fused[0], "the fixture's passage really is in the fused set"
    params = AutoRunInput(
        run_id=UUID(int=0),
        message_id=UUID(int=0),
        chat_id=UUID(int=0),
        user_id=owner.id,
        question="How long is the AW-2000 warranty?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="upload",
        client_filters=ClientFilters(),
        collection_ids=[collection_id],
    )
    ingress = IngressOutcome(
        intent="lookup",
        source="upload",
        complexity="single",
        risk="low",
        lexical_weight=0.5,
        guard_injection="pass",
        guard_jailbreak="pass",
        guard_pii="pass",
        off_topic="pass",
    )
    assert run.rewritten is not None

    async with get_session_factory()() as session:
        for attempt, seen in enumerate(fused):
            pairs = searches[attempt * MULTI_QUERY_VARIANTS : (attempt + 1) * MULTI_QUERY_VARIANTS]
            assert len(pairs) == MULTI_QUERY_VARIANTS, "one search per variant, in order"
            result_sets = [
                await _search_one_variant(
                    session, query, embedding=embedding, params=params, ingress=ingress
                )
                for query, embedding in pairs
            ]
            sequential = [str(chunk.chunk_id) for chunk in _fuse_multi_query(result_sets)]
            assert seen == sequential, "parallel fusion differs from sequential fusion"


async def test_web_chunks_this_run_indexes_are_visible_to_the_searches(
    db: AsyncSession,
    owner: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The searches run on their own sessions now, and a session cannot see
    another session's uncommitted rows — so web chunks indexed in this run have
    to be committed before the fan-out, or a `source=web` run would not
    retrieve its own web results."""
    chat = await make_chat(db, owner)
    collection = await make_collection(db, owner, "docs")
    user_message = Message(chat_id=chat.id, role="user", content="q", status="complete")
    db.add(user_message)
    await db.commit()

    async def fake_search(_query: str) -> list[web_module.WebResult]:
        return [
            web_module.WebResult(
                url="https://example.test/warranty",
                title="Warranty",
                content="# Warranty\n\nThe AW-2000 warranty is 24 months from purchase.",
            )
        ]

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    async def fake_complete(**_kwargs: Any) -> str:
        return "warranty phrasing"

    monkeypatch.setattr(web_module, "_search", fake_search)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(web_module, "embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr(auto_module, "get_reranker", _PassThroughRerank)

    params = AutoRunInput(
        run_id=UUID(int=0),
        message_id=user_message.id,
        chat_id=chat.id,
        user_id=owner.id,
        question="How long is the AW-2000 warranty?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="web",
        client_filters=ClientFilters(),
        collection_ids=[collection.id],
    )

    run = await prepare_auto_run(
        get_session_factory(), params, DecisionEngine(jev=_IngressJev("lookup"), mode="jev_only")
    )

    web_chunks = [
        chunk
        for event in run.retrieval_events
        for chunk in event.chunks
        if chunk.source_type == "web"
    ]
    assert web_chunks, "the web page this run indexed was not retrieved by the fan-out"


async def test_the_strangers_passage_is_returned_to_its_owner(
    db: AsyncSession,
    owner: Any,
    stranger: Any,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complement of the ownership test: the fixture is only meaningful if
    the un-scoped search DOES return the stranger's chunk. Without this, the
    test above would pass on a corpus where the row is simply unreachable."""

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    await _seed_corpus(db, owner, stranger)
    stranger_collection = (
        await db.execute(
            select(Collection.id).where(Collection.owner_id == stranger.id).limit(1)
        )
    ).scalar_one()
    async with get_session_factory()() as session:
        theirs_view = await _REAL_SEARCH(
            session,
            query_text="AW-2000 warranty",
            query_embedding=vec(1),
            ownership=Ownership(
                user_id=stranger.id,
                collection_ids=[stranger_collection],
                chat_id=None,
            ),
            filters=ClientFilters(),
            lexical_weight=0.5,
        )
    assert [chunk.text for chunk in theirs_view] == [OTHER_USERS_PASSAGE], (
        "the fixture would be worthless if no scope returned this row"
    )