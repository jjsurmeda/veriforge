"""Beta lane B, item 3: no trace gap over 2 s while the retrieval stage runs
(CH-5, ADR-003 §2 — "progress is a requirement in its own right").

The per-variant sub-step labels already existed; the two steps that ran BEFORE
the first search — the query-variants LLM call and the embedding batch — did
not, so they were a silent gap inside `retrieve`: the client saw `retrieve`
start, then nothing, then a burst of finished searches.

The test drives a real `prepare_auto_run` against a real Postgres with
providers whose durations are SIMULATED (each stage sleeps), and asserts what a
client watching the stream would see:

* every published event arrives within 2 s of the previous one;
* the labels name the work: the variants call, the embedding batch, and one per
  variant.

The durations are simulated so the test is about the SHAPE of what is
published, not about how fast this machine is: a test that passes only when the
provider is quick is not testing the cadence.
"""

import asyncio
import time
from itertools import pairwise
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import MULTI_QUERY_VARIANTS, AutoRunInput, prepare_auto_run
from retrieval.filters import ClientFilters
from schemas.events import RunStreamEvent, StepCompleted, StepStarted
from tests.graph.test_chitchat import _IngressJev, _seed_chat
from tests.graph.test_chitchat import no_llm as no_llm
from tests.graph.test_parallel_search import _PassThroughRerank
from tests.retrieval.conftest import make_user, vec

# CH-5's rule, in seconds. The assertion is against this, not against the
# simulated stage durations below.
MAX_GAP_SECONDS = 2.0
# The two calls that run BEFORE the first search, each simulated at just over
# one second: together they exceed 2 s, so a run that publishes nothing for them
# breaks the rule, and a run that publishes a label for each one does not. The
# margin is what makes this test able to fail — pick durations comfortably under
# the limit on their own and any missing label would hide behind them.
PRE_SEARCH_SECONDS = 1.1


@pytest.fixture
async def user_a(db: AsyncSession) -> Any:
    return await make_user(db, "lane-b-progress@test.dev")


def _patch(monkeypatch: pytest.MonkeyPatch, seconds: float) -> list[float]:
    """Every provider sleeps `seconds`, so each stage's cost shows up as a gap
    between two published events."""
    calls: list[float] = []

    async def fake_complete(**_kwargs: Any) -> str:
        await asyncio.sleep(seconds)
        return "variant\nsecond variant"

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        await asyncio.sleep(seconds)
        calls.append(time.monotonic())
        return [vec(1) for _ in texts]

    async def fake_search(*_args: Any, **_kwargs: Any) -> list[Any]:
        await asyncio.sleep(seconds)
        return []

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", fake_search)
    monkeypatch.setattr(auto_module, "get_reranker", _PassThroughRerank)
    return calls


async def test_an_auto_run_publishes_a_step_within_two_seconds_of_the_last(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat, message_id = await _seed_chat(db, user_a)
    _patch(monkeypatch, PRE_SEARCH_SECONDS)
    published: list[tuple[float, RunStreamEvent]] = []

    async def publish(_run_id: UUID, event: RunStreamEvent) -> None:
        published.append((time.monotonic(), event))

    params = AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user_a.id,
        question="How long is the AW-2000 warranty?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="upload",
        client_filters=ClientFilters(),
        collection_ids=[],
    )
    await prepare_auto_run(
        get_session_factory(),
        params,
        DecisionEngine(jev=_IngressJev("lookup"), mode="jev_only"),
        publish=publish,
    )

    stamps = [stamp for stamp, _ in published]
    gaps = [b - a for a, b in pairwise(stamps)]
    assert published, "the run published nothing"
    assert max(gaps) <= MAX_GAP_SECONDS, (
        f"largest silent gap {max(gaps):.2f}s exceeds {MAX_GAP_SECONDS}s"
    )


async def test_the_published_labels_name_the_variants_call_the_batch_and_each_variant(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat, message_id = await _seed_chat(db, user_a)
    _patch(monkeypatch, 0.0)
    started: list[str] = []

    async def publish(_run_id: UUID, event: RunStreamEvent) -> None:
        if isinstance(event, StepStarted):
            started.append(event.label)

    params = AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user_a.id,
        question="How long is the AW-2000 warranty?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="upload",
        client_filters=ClientFilters(),
        collection_ids=[],
    )
    await prepare_auto_run(
        get_session_factory(),
        params,
        DecisionEngine(jev=_IngressJev("lookup"), mode="jev_only"),
        publish=publish,
    )

    assert "query variants" in started, started
    assert any(label.startswith("embed queries") for label in started), started
    searches = [label for label in started if label.startswith("retrieve: ")]
    assert len(searches) >= MULTI_QUERY_VARIANTS, started
    # Within ONE attempt the order is variants -> embedding batch -> searches.
    # (This fixture takes its one retry, so the labels repeat; only the first
    # attempt's ordering is fixed.)
    embed_at = next(i for i, label in enumerate(started) if label.startswith("embed queries"))
    first_search = next(i for i, label in enumerate(started) if label.startswith("retrieve: "))
    assert started.index("query variants") < embed_at < first_search, started


async def test_every_published_step_is_completed_with_its_duration(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A label that starts and never completes is worse than no label: the
    trace would show work still running after the answer arrived."""
    chat, message_id = await _seed_chat(db, user_a)
    _patch(monkeypatch, 0.0)
    events: list[RunStreamEvent] = []

    async def publish(_run_id: UUID, event: RunStreamEvent) -> None:
        events.append(event)

    params = AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user_a.id,
        question="How long is the AW-2000 warranty?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="upload",
        client_filters=ClientFilters(),
        collection_ids=[],
    )
    await prepare_auto_run(
        get_session_factory(),
        params,
        DecisionEngine(jev=_IngressJev("lookup"), mode="jev_only"),
        publish=publish,
    )

    started = [event.label for event in events if isinstance(event, StepStarted)]
    completed = [event for event in events if isinstance(event, StepCompleted)]
    assert started, "nothing was published"
    assert sorted(started) == sorted(event.label for event in completed)
    assert all(event.duration_ms >= 0 for event in completed)