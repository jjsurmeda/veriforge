"""Beta lane B, item 5: skip the corrective retrieval when the evidence is
clearly absent.

A decline runs the full second pass (corrective re-query + retrieve + rerank +
sanitize + sufficient, about 13-15 s). When every signal is far below its
floor, that pass abstains too — the recorded runs say so: of 238 Auto runs that
took the retry, 231 still abstained, and of the 7 that did not, none sat inside
the band these bounds describe.

**Two readings, not three.** The third was a relevance score, and it went with
the relevance floor (ADR-006, R2a item 4). The bound below is therefore the
sufficiency bound plus the entity bound, and the skip needs both — which is the
same shape it had, one reading narrower. `_evidence_clearly_absent`'s comment
carries where the sufficiency bound came from: a run the retry rescued scored
0.01, so sufficiency alone separates nothing and a run with no entity reading
corroborating it still retries.

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
        "p_sufficient": 0.002,
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


def test_the_known_rescue_reading_still_retries() -> None:
    """The bound is 0.005 because **0.01 is the lowest sufficiency the
    corrective retrieval has ever been recorded rescuing** (KI-70's replay: of
    238 runs that took the correction, 231 still abstained, and 7 were
    rescued, the lowest at 0.01).

    Before ADR-006 the skip also demanded a corroborating relevance score, so
    the sufficiency bound was never the last word. With the relevance floor
    gone it is, and this is the test that pins the bound where the evidence
    puts it rather than where it used to sit."""
    assert _absent(p_sufficient=0.01) is False, "a reading the correction has rescued"
    assert _absent(p_sufficient=0.006) is False
    assert _absent(p_sufficient=RETRY_SKIP_SUFFICIENT_MAX) is True, "the boundary is inside"


def test_the_boundary_itself_is_inside_the_band() -> None:
    assert _absent(p_sufficient=RETRY_SKIP_SUFFICIENT_MAX) is True
    assert (
        _absent(entity_measured=True, entity_ok=False, entity_max=RETRY_SKIP_ENTITY_MAX)
        is True
    )


def test_a_matched_entity_still_retries() -> None:
    """A passage the entity check says IS about the question's entity is
    evidence, however low the sufficiency reading is."""
    assert _absent(entity_measured=True, entity_ok=True) is False
    assert _absent(entity_measured=True, entity_ok=False, entity_max=0.05) is True


def test_an_entity_reading_above_its_bound_still_retries() -> None:
    assert _absent(entity_measured=True, entity_ok=False, entity_max=0.9) is False


def test_a_matched_entity_retries_even_when_sufficiency_is_bottomed_out() -> None:
    """The one reading that contradicts "clearly absent" directly. Sufficiency
    at 0.00 is not enough on its own to skip a run whose evidence the entity
    check says is about the right thing."""
    assert _absent(p_sufficient=0.0, entity_measured=True, entity_ok=True) is False


# --- the setting is admin-overridable (AD-4) ----------------------------------


def test_an_admin_can_widen_or_turn_off_the_skip() -> None:
    def with_settings(data: dict[str, Any]) -> Any:
        settings = RuntimeSettings.from_data(99, {"retrieval": data})
        token = set_runtime_settings(settings)
        try:
            return _absent(p_sufficient=0.04)
        finally:
            reset_runtime_settings(token)

    assert with_settings({}) is False, "the shipped defaults"
    assert with_settings({"retry_skip_sufficient_max": 0.05}) is True, "widened to the floor"
    assert with_settings({"retry_skip_sufficient_max": None}) is False, "null turns it off"
    # Widening the entity bound alone cannot enable a skip while sufficiency is
    # under its own bound — both have to clear.
    assert with_settings({"retry_skip_entity_max": 1.0}) is False, "sufficiency still above"
    assert (
        with_settings({"retry_skip_sufficient_max": 0.05, "retry_skip_entity_max": 1.0}) is True
    )
    assert with_settings({"retry_skip_entity_max": None}) is False


# --- through the pipeline -----------------------------------------------------


class _AbsentJev(_IngressJev):
    """Sufficiency far below its floor, and every attempt answers the same way —
    which is the premise the skip rests on: a second pass cannot rescue evidence
    that is not there.

    `sufficiency` is per-attempt, so the corrective pass can be pinned to a
    different reading from the first and the rescue case can be exercised.

    Rerank passages go through the real `JevRerank`, so the run exercises the
    answer-containment rubric the reranker actually ships with."""

    def __init__(
        self, sufficiency: float = 0.002, sufficiency_retry: float | None = None
    ) -> None:
        super().__init__("lookup")
        self._sufficiency = sufficiency
        self._sufficiency_retry = sufficiency_retry
        self.sufficient_calls: list[float] = []

    async def decide(
        self, *, state: Any, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        answers = await super().decide(state=state, questions=questions)
        for name in questions:
            if name == "sufficient":
                # The first call is the first attempt; the corrective pass, if
                # it runs at all, is the second.
                attempt = len(self.sufficient_calls)
                value = (
                    self._sufficiency_retry
                    if attempt and self._sufficiency_retry is not None
                    else self._sufficiency
                )
                self.sufficient_calls.append(value)
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=value, probability=value
                )
            elif name.startswith("passage_"):
                answers[name] = Answer(
                    engine="jev",
                    latency_ms=1,
                    value="off-topic",
                    probability=1.0,
                    probabilities={"off-topic": 1.0},
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
    chunk_text: str | None = None,
) -> Any:
    """A run over one real chunk in the database.

    The chunk is real, not a hand-built `ScoredChunk`, because the answering
    case writes a `citations` row with a foreign key to it — a fake chunk id
    fails the moment the run does not decline, which is precisely the case the
    corrective retrieval exists to produce.
    """
    chat, message_id = await _seed_chat(db, user)
    from sqlalchemy import select

    from db.models import Collection
    from retrieval.hybrid import ScoredChunk
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
    stored = await add_chunk(
        db,
        document=document,
        section=section,
        ord=0,
        text_=chunk_text or "A short note about an unrelated topic.",
        embedding=vec(3),
    )

    found = [
        ScoredChunk(
            chunk_id=stored.id,
            document_id=document.id,
            document_name=document.name,
            section_id=section.id,
            ord=0,
            page=None,
            text=stored.text,
            heading_path=section.heading_path,
            source_type="document",
            vector_score=1.0,
            bm25_score=None,
            fused_score=1.0,
        )
    ]

    async def fake_complete(**_kwargs: Any) -> str:
        return "the question, standalone"

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    async def fake_search(*_args: Any, **_kwargs: Any) -> list[Any]:
        return list(found)

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", fake_search)
    # The real JevRerank: the run exercises the shipped answer-containment
    # rubric rather than a hand-rolled fake.
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


async def test_a_clearly_absent_run_declines_in_one_attempt(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    jev = _AbsentJev()
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin evidence")

    assert len(jev.sufficient_calls) == 1, "the rewrite + full re-retrieve was skipped"
    assert run.retry_skipped is True
    assert run.abstain_event is not None, "it still declines — faster, not differently"
    assert run.contexts == [], "an abstention carries no citations"


async def test_the_skip_is_recorded_in_the_trace(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A decline that skipped its retry must say so, or the trace reads as a
    run that gave up early for no reason."""
    jev = _AbsentJev()
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin evidence")

    skipped = [d for d in run.decision_events if d.name == "retry_skipped"]
    assert len(skipped) == 1
    assert skipped[0].threshold == RETRY_SKIP_SUFFICIENT_MAX
    assert "far below their floors" in (skipped[0].reasoning or "")


async def test_a_borderline_run_still_retries(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sufficiency at 0.03 — above the 0.02 skip bound, below the 0.05 floor.
    The corrective retrieval runs: this is the case the bound exists for, and
    it is the direction that costs an answer if the bound is wrong."""
    jev = _AbsentJev(sufficiency=0.03)
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin")

    assert len(jev.sufficient_calls) == 2, "the corrective retrieval happened"
    assert run.retry_skipped is False
    assert not any(d.name == "retry_skipped" for d in run.decision_events)


async def test_an_insufficient_run_that_the_correction_rescues_answers(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the whole corrective shape exists for, and ADR-006's: one
    evidence check, one corrective retrieval, then answer rather than decline.

    Sufficiency is under the floor on the first attempt (0.03, which is also
    above the skip bound so the correction is not skipped) and over it on the
    second (0.61). The run must answer, with contexts, after exactly two
    checks."""
    jev = _AbsentJev(sufficiency=0.03, sufficiency_retry=0.61)
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="the evidence")

    assert jev.sufficient_calls == [0.03, 0.61], "exactly one corrective retrieval"
    assert run.abstain_event is None, "the correction rescued it"
    assert run.contexts, "an answer with no evidence behind it"
    assert run.retry_skipped is False


async def test_an_insufficient_run_that_the_correction_cannot_rescue_declines(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the same rule. Two insufficient checks and the run
    declines — one correction, never two (answer-first, so the retry loop
    clamps any admin override to one)."""
    jev = _AbsentJev(sufficiency=0.03, sufficiency_retry=0.04)
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin")

    assert jev.sufficient_calls == [0.03, 0.04]
    assert run.abstain_event is not None
    assert run.contexts == [], "an abstention carries no citations"


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
        run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin evidence")
    finally:
        reset_runtime_settings(token)

    assert len(jev.sufficient_calls) == 2, "the retry is back"
    assert run.retry_skipped is False