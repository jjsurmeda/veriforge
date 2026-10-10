"""Beta lane B, item 1: one embedding call for every query variant (TRD §7.1).

`retrieve_queries` used to call `get_query_embedding` once per variant, and
each of those was a cache read plus an `embed_batch` of ONE text — four
variants, four provider round trips inside the stage that dominates the run.

These tests drive the real `prepare_auto_run` (real Postgres, fake providers —
testing.md) and count the calls, because the property that matters is the one
the pipeline has, not the one the helper has: a run with N variants must reach
the embedding provider once, and must still pass each variant its OWN vector.

Fakes: Jev is the recorded ingress fixture, the small LLM is a stub that
returns three phrasings, and `embed_batch` records its texts.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Collection
from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import MULTI_QUERY_VARIANTS, AutoRunInput, prepare_auto_run
from retrieval.filters import ClientFilters
from retrieval.hybrid import ScoredChunk
from tests.graph.test_chitchat import _IngressJev, _seed_chat
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import make_user, vec


@pytest.fixture
async def user_a(db: AsyncSession) -> Any:
    return await make_user(db, "lane-b-embed@test.dev")


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]], chunks: list[ScoredChunk]
) -> None:
    async def fake_complete(**_kwargs: Any) -> str:
        return "\n".join(f"variant {index}" for index in range(1, MULTI_QUERY_VARIANTS))

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        calls["embed"].append(list(texts))
        # One distinct vector per text, so a variant paired with another
        # variant's vector is visible rather than plausible.
        return [vec(index + 1) for index, _ in enumerate(texts)]

    async def fake_search(*_args: Any, **kwargs: Any) -> list[ScoredChunk]:
        calls["search"].append(str(kwargs["query_text"]))
        calls["embeddings"].append(list(kwargs["query_embedding"]))
        return list(chunks)

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", fake_search)


async def _params(db: AsyncSession, chat: Any, user: Any, message_id: UUID) -> AutoRunInput:
    collection_id = (
        await db.execute(
            select(Collection.id).where(Collection.owner_id == user.id).limit(1)
        )
    ).scalar_one()
    return AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user.id,
        question="What does Mr. Darcy say in his first proposal to Elizabeth?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="auto",
        client_filters=ClientFilters(),
        collection_ids=[collection_id],
    )


async def _run_once(
    db: AsyncSession, user_a: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, list[Any]]:
    chat, message_id = await _seed_chat(db, user_a)
    calls: dict[str, list[Any]] = {"embed": [], "search": [], "embeddings": []}
    _patch_pipeline(monkeypatch, calls, [])
    await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=_IngressJev("lookup"), mode="jev_only"),
    )
    return calls


async def test_one_auto_run_embeds_every_variant_in_one_call(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = await _run_once(db, user_a, monkeypatch)

    # The fixture's Jev keeps `sufficient` low, so the run takes its one retry
    # and retrieves twice. Both attempts must still reach the provider once in
    # total — the second reads the cache the first filled.
    assert len(calls["embed"]) == 1, f"one provider call for the whole run: {calls['embed']}"
    assert len(calls["embed"][0]) == MULTI_QUERY_VARIANTS, "one text per variant"
    assert len(calls["search"]) == 2 * MULTI_QUERY_VARIANTS, "both attempts fanned out"


async def test_each_variant_is_searched_with_its_own_vector(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The batch must not hand every search the same (or a shifted) vector —
    that would be a silent retrieval-quality regression traded for latency."""
    calls = await _run_once(db, user_a, monkeypatch)
    vectors = calls["embeddings"]
    first, second = vectors[:MULTI_QUERY_VARIANTS], vectors[MULTI_QUERY_VARIANTS:]

    assert len({_rounded(vector) for vector in first}) == MULTI_QUERY_VARIANTS, (
        "each variant in the batch got a distinct vector"
    )
    # A vector that comes back out of the cache is the same vector: Postgres
    # stores float4, so compare at the precision the column keeps.
    assert [_rounded(vector) for vector in second] == [_rounded(vector) for vector in first]


def _rounded(vector: list[float]) -> tuple[float, ...]:
    return tuple(round(value, 3) for value in vector)