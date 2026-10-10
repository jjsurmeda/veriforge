"""Beta lane B, item 5: skip the retry when the evidence is clearly absent.

A decline runs the full second pass (rewrite + retrieve + rerank + sanitize +
sufficient, about 13-15 s). When every signal is far below its floor, that
pass abstains too — the recorded runs say so: of 238 Auto runs that took the
retry, 231 still abstained, and of the 7 that did not, none sat inside the
band these bounds describe.

The bounds are NOT a matter of taste. `_evidence_clearly_absent`'s comment
carries the replay table they came from; the short version is that sufficiency
alone separates nothing (a rescued run scored 0.01), so the skip needs a
relevance reading too, and a run with no relevance reading never skips.

`_evidence_clearly_absent` is tested directly (it is the decision, and the data
it encodes is the whole point), and then through the real pipeline: one
attempt instead of two, a `retry_skipped` decision in the trace, and a decline
that still carries what was found.

Real Postgres; Jev, the reranker and the small LLM are fakes.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import (
    RETRY_SKIP_ENTITY_MAX,
    RETRY_SKIP_RELEVANCE_MAX,
    RETRY_SKIP_SUFFICIENT_MAX,
    AutoRunInput,
    _evidence_clearly_absent,
    prepare_auto_run,
)
from retrieval.filters import ClientFilters
from retrieval.rerank import JevRerank
from runtime import RuntimeSettings, reset_runtime_settings, set_runtime_settings
from schemas.decisions import Answer, Question
from tests.graph.test_chitchat import _IngressJev, _seed_chat
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import make_user, vec

# --- the decision, directly ---------------------------------------------------


def _absent(**overrides: Any) -> bool:
    """A run with every signal far below its floor."""
    kwargs: dict[str, Any] = {
        "p_sufficient": 0.01,
        "relevance_max": 0.10,
        "relevance_measured": True,
        "entity_max": 0.05,
        "entity_measured": False,
        "entity_ok": True,
    }
    kwargs.update(overrides)
    return _evidence_clearly_absent(**kwargs)


def test_every_signal_far_below_its_floor_skips_the_retry() -> None:
    assert _absent() is True


def test_sufficiency_near_its_floor_retries() -> None:
    """0.05 is the floor and the lowest sufficiency any answering run
    recorded. "Near" means the retry still happens — the failure direction
    here is a decline that could have been an answer."""
    assert _absent(p_sufficient=0.05) is False
    assert _absent(p_sufficient=0.04) is False


def test_relevance_near_its_floor_retries() -> None:
    """The floor is 0.60 and the lowest relevance among runs the retry
    rescued is 0.47. Above the bound the retry happens."""
    assert _absent(relevance_max=0.47) is False
    assert _absent(relevance_max=0.41) is False


def test_the_boundary_itself_is_inside_the_band() -> None:
    assert _absent(p_sufficient=RETRY_SKIP_SUFFICIENT_MAX) is True
    assert _absent(relevance_max=RETRY_SKIP_RELEVANCE_MAX) is True


def test_a_run_with_no_relevance_reading_never_skips() -> None:
    """The replay's clearest finding: sufficiency alone separates nothing — a
    run the retry rescued scored 0.01. Without a relevance reading there is
    nothing to corroborate it, so the retry runs."""
    assert _absent(relevance_measured=False) is False
    assert _absent(relevance_max=None) is False


def test_a_matched_entity_still_retries() -> None:
    """A passage the entity check says IS about the question's entity is
    evidence, however low the other two readings are."""
    assert _absent(entity_measured=True, entity_ok=True) is False
    assert _absent(entity_measured=True, entity_ok=False, entity_max=0.05) is True


def test_an_entity_reading_above_its_bound_still_retries() -> None:
    assert _absent(entity_measured=True, entity_ok=False, entity_max=0.9) is False
    assert (
        _absent(entity_measured=True, entity_ok=False, entity_max=RETRY_SKIP_ENTITY_MAX)
        is True
    )


# --- the setting is admin-overridable (AD-4) ----------------------------------


def test_an_admin_can_widen_or_turn_off_the_skip() -> None:
    def with_settings(data: dict[str, Any]) -> Any:
        settings = RuntimeSettings.from_data(99, {"retrieval": data})
        token = set_runtime_settings(settings)
        try:
            return _absent(p_sufficient=0.04, relevance_max=0.45)
        finally:
            reset_runtime_settings(token)

    assert with_settings({}) is False, "the shipped defaults"
    # Both readings must clear their bound, so widening one at a time is not
    # enough — the test that matters is widening them TOGETHER.
    assert with_settings({"retry_skip_sufficient_max": 0.05}) is False, "relevance still above"
    assert with_settings({"retry_skip_relevance_max": 0.50}) is False, "sufficiency still above"
    assert (
        with_settings({"retry_skip_sufficient_max": 0.05, "retry_skip_relevance_max": 0.50})
        is True
    )
    assert with_settings({"retry_skip_sufficient_max": None}) is False, "null turns it off"
    assert with_settings({"retry_skip_relevance_max": None}) is False


# --- through the pipeline -----------------------------------------------------


class _AbsentJev(_IngressJev):
    """Sufficiency and relevance both far below their floors, and every
    attempt answers the same way — which is the premise the skip rests on: a
    second pass cannot rescue evidence that is not there.

    Rerank passages go through the real `JevRerank`, because the relevance
    gate applies only to Jev-scaled scores (KI-26): a fake reranker of our own
    would leave the gate — and so the skip — unexercised."""

    def __init__(self, relevance: float = 0.10) -> None:
        super().__init__("lookup")
        self._relevance = relevance
        self.sufficient_calls: list[float] = []

    async def decide(
        self, *, state: Any, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        answers = await super().decide(state=state, questions=questions)
        for name in questions:
            if name == "sufficient":
                self.sufficient_calls.append(0.01)
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
            elif name.startswith("passage_"):
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=self._relevance, probability=None
                )
            elif name.startswith("chunk_injection"):
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
        return answers


@pytest.fixture
async def user_a(db: AsyncSession) -> Any:
    return await make_user(db, "lane-b-skip@test.dev")


async def _run(
    db: AsyncSession,
    user: Any,
    jev: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    chunks: list[Any] | None = None,
) -> Any:
    chat, message_id = await _seed_chat(db, user)
    from sqlalchemy import select

    from db.models import Collection
    from tests.retrieval.conftest import add_chunk, make_document, make_section

    collection_id = (
        await db.execute(
            select(Collection.id).where(Collection.owner_id == user.id).limit(1)
        )
    ).scalar_one()
    collection = await db.get(Collection, collection_id)
    assert collection is not None
    document = await make_document(db, collection, name="thin.md")
    section = await make_section(db, document)
    await add_chunk(
        db,
        document=document,
        section=section,
        ord=0,
        text_="A short note about an unrelated topic.",
        embedding=vec(3),
    )

    async def fake_complete(**_kwargs: Any) -> str:
        return "the question, standalone"

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    async def fake_search(*_args: Any, **_kwargs: Any) -> list[Any]:

        if chunks is not None:
            return list(chunks)
        return []

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", fake_search)
    # The real JevRerank: its scores are the ones the relevance gate reads.
    monkeypatch.setattr(
        auto_module, "get_reranker", lambda engine=None, run_id="": JevRerank(engine, run_id)
    )

    params = AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user.id,
        question="What is the capital of the Ridgeline R-7?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="upload",
        client_filters=ClientFilters(),
        collection_ids=[collection_id],
    )
    return await prepare_auto_run(
        get_session_factory(), params, DecisionEngine(jev=jev, mode="jev_only")
    )


def _chunk(text: str, index: int) -> Any:
    from retrieval.hybrid import ScoredChunk

    return ScoredChunk(
        chunk_id=UUID(int=index + 1),
        document_id=UUID(int=100 + index),
        document_name=f"doc{index}.md",
        section_id=None,
        ord=0,
        page=None,
        text=text,
        heading_path=None,
        source_type="document",
        vector_score=1.0,
        bm25_score=None,
        fused_score=1.0,
    )


async def test_a_clearly_absent_run_declines_in_one_attempt(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    jev = _AbsentJev()
    run = await _run(db, user_a, jev, monkeypatch, chunks=[_chunk("thin evidence", 0)])

    assert len(jev.sufficient_calls) == 1, "the rewrite + full re-retrieve was skipped"
    assert run.retry_skipped is True
    assert run.abstain_event is not None, "it still declines — faster, not differently"
    assert run.contexts == [], "an abstention carries no citations (KI-25)"


async def test_the_skip_is_recorded_in_the_trace(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A decline that skipped its retry must say so, or the trace reads as a
    run that gave up early for no reason."""
    jev = _AbsentJev()
    run = await _run(db, user_a, jev, monkeypatch, chunks=[_chunk("thin evidence", 0)])

    skipped = [d for d in run.decision_events if d.name == "retry_skipped"]
    assert len(skipped) == 1
    assert skipped[0].threshold == RETRY_SKIP_SUFFICIENT_MAX
    assert "far below their floors" in (skipped[0].reasoning or "")


async def test_a_borderline_run_still_retries(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sufficiency far below its floor but relevance at 0.45 — above the 0.40
    bound, below the 0.60 floor. The retry runs: this is the case the bounds
    exist for, and it is the direction that costs an answer if it is wrong."""
    jev = _AbsentJev(relevance=0.45)
    run = await _run(db, user_a, jev, monkeypatch, chunks=[_chunk("thin", 0)])

    assert len(jev.sufficient_calls) == 2, "the retry happened"
    assert run.retry_skipped is False
    assert not any(d.name == "retry_skipped" for d in run.decision_events)


async def test_an_admin_override_brings_the_retry_back(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AD-4: the bounds are settings, not constants in the stone. Setting
    `retry_skip_sufficient_max` to null turns the skip off, and a run that
    would have skipped now retries."""
    settings = RuntimeSettings.from_data(100, {"retrieval": {"retry_skip_sufficient_max": None}})
    token = set_runtime_settings(settings)
    try:
        jev = _AbsentJev()
        run = await _run(db, user_a, jev, monkeypatch, chunks=[_chunk("thin evidence", 0)])
    finally:
        reset_runtime_settings(token)

    assert len(jev.sufficient_calls) == 2, "the retry is back"
    assert run.retry_skipped is False