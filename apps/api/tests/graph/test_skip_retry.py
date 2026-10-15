"""Skip the corrective retrieval when the evidence is clearly absent.

A decline runs the full second pass (corrective re-query + retrieve + rerank +
sanitize + gate, about 13-15 s). When the gate is far below its floor and the
entity check does not contradict that, the second pass abstains too.

**The gate reading is the rubric, not `sufficient`** (ADR-006 as corrected).
That changed the bound's derivation, so this file changed with it: under the
`sufficient` reading R2a had to push `RETRY_SKIP_RUBRIC_MAX` down to 0.005,
which made the skip nearly inert — almost nothing scored that low, so it bought
nothing while still carrying a decision. `RETRY_SKIP_RUBRIC_MAX = 0.10` is
re-derived from the gate's own calibration instead, and
`_evidence_clearly_absent`'s comment carries the table it came from.

**Two readings, not three.** The third was a relevance score, and it went with
the relevance floor (ADR-006, R2a item 4).

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
    RETRY_SKIP_RUBRIC_MAX,
    AutoRunInput,
    _evidence_clearly_absent,
    prepare_auto_run,
)
from retrieval.filters import ClientFilters
from retrieval.rerank import ANSWER_LEVELS, JevRerank
from runtime import RuntimeSettings, reset_runtime_settings, set_runtime_settings
from schemas.decisions import Answer, Question
from tests.graph.test_chitchat import _IngressJev, _seed_chat
from tests.graph.test_chitchat import no_llm as no_llm
from tests.retrieval.conftest import make_user, vec

# --- the decision, directly ---------------------------------------------------


def _absent(**overrides: Any) -> bool:
    """A run with every signal far below its floor."""
    kwargs: dict[str, Any] = {
        "gate_mean_top3": 0.01,
        "entity_max": 0.05,
        "entity_measured": False,
        "entity_ok": True,
    }
    kwargs.update(overrides)
    return _evidence_clearly_absent(**kwargs)


def test_every_signal_far_below_its_floor_skips_the_retry() -> None:
    assert _absent() is True


def test_a_gate_reading_near_its_floor_retries() -> None:
    """0.56 is the gate floor. Anything at or above it retries or answers;
    just under it still retries, because the failure direction of a skip is a
    decline that could have been an answer."""
    assert _absent(gate_mean_top3=0.56) is False
    assert _absent(gate_mean_top3=0.11) is False


def test_the_lowest_calibrated_reading_still_retries() -> None:
    """The bound is 0.10 because it sits **below every mean-of-top-3 the
    calibration recorded** and above the 0.0 a run with nothing usable
    produces.

    `scripts/calibrate_gate.py` measured 53 gated books items and 12
    entity-mismatch items. The lowest value there is 0.021 (`cf-rl-axle`, a
    should-decline that should abstain anyway) and the lowest for an item the
    correction could conceivably rescue is 0.224 (`outside-whitman`, an
    answerable item). Everything in between has to keep retrying, which is why
    the bound is 0.10 and not 0.30.

    Under the `sufficient` reading this bound was 0.005 and had to be pushed
    down to 0.005 to stay under a rescue at 0.01; that made it fire on almost
    nothing. This one is derived from the signal that is actually the gate."""
    assert _absent(gate_mean_top3=0.15) is False, "below every calibrated reading"
    assert _absent(gate_mean_top3=0.11) is False
    assert _absent(gate_mean_top3=RETRY_SKIP_RUBRIC_MAX) is True, "the boundary is inside"
    assert _absent(gate_mean_top3=0.02) is True, "nothing usable was retrieved"


def test_no_gate_reading_at_all_is_clearly_absent() -> None:
    """`None` means nothing was graded — nothing retrieved, or no passage
    carried a rubric score. A re-query of the same corpus changes neither, and
    KI-57's outage is exactly this case: the retry would reach the same
    unreachable decision layer 13-15 s later."""
    assert _absent(gate_mean_top3=None) is True


def test_no_gate_reading_still_retries_when_an_entity_matched() -> None:
    """The entity guard is the reading that contradicts "clearly absent", so it
    blocks the skip even when the gate produced nothing at all."""
    assert _absent(gate_mean_top3=None, entity_measured=True, entity_ok=True) is False


def test_the_boundary_itself_is_inside_the_band() -> None:
    assert _absent(gate_mean_top3=RETRY_SKIP_RUBRIC_MAX) is True
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
    assert _absent(gate_mean_top3=0.0, entity_measured=True, entity_ok=True) is False


# --- the setting is admin-overridable (AD-4) ----------------------------------


def test_an_admin_can_widen_or_turn_off_the_skip() -> None:
    def with_settings(data: dict[str, Any]) -> Any:
        settings = RuntimeSettings.from_data(99, {"retrieval": data})
        token = set_runtime_settings(settings)
        try:
            return _absent(gate_mean_top3=0.20)
        finally:
            reset_runtime_settings(token)

    assert with_settings({}) is False, "0.20 is above the shipped 0.10 bound"
    assert with_settings({"retry_skip_rubric_max": 0.25}) is True, "widened past the reading"
    assert with_settings({"retry_skip_rubric_max": None}) is False, "null turns it off"
    # Widening the entity bound alone cannot enable a skip while the gate is
    # under its own bound — both have to clear.
    assert with_settings({"retry_skip_entity_max": 1.0}) is False, "the gate still has to clear"
    assert (
        with_settings({"retry_skip_rubric_max": 0.25, "retry_skip_entity_max": 1.0}) is True
    )
    assert with_settings({"retry_skip_entity_max": None}) is False


# --- through the pipeline -----------------------------------------------------


class _AbsentJev(_IngressJev):
    """The rubric gate far below its floor, and every attempt grades the same
    way — which is the premise the skip rests on: a second pass cannot rescue
    evidence that is not there.

    The grade is pinned **per attempt on the rerank rubric**, not on a
    `sufficient` answer, because the rubric is what the gate reads. `passage_*`
    questions go through the real `JevRerank`, so a two-level distribution over
    the answer levels lands the passage's expected level exactly on the grade
    the test asks for."""

    def __init__(self, grade: float = 0.0, grade_retry: float | None = None) -> None:
        super().__init__("lookup")
        self._grade = grade
        self._grade_retry = grade_retry
        self.gate_calls: list[float] = []

    async def decide(
        self, *, state: Any, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        answers = await super().decide(state=state, questions=questions)
        for name in questions:
            if name.startswith("passage_"):
                # The first attempt is the first grade; the corrective pass, if
                # it runs at all, is the second.
                attempt = len(self.gate_calls)
                value = (
                    self._grade_retry
                    if attempt and self._grade_retry is not None
                    else self._grade
                )
                self.gate_calls.append(value)
                answers[name] = _rubric_answer(value)
            elif name.startswith("chunk_injection"):
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
        return answers


def _rubric_answer(grade: float) -> Answer:
    """An `Answer` whose expected level is exactly `grade`.

    `answer_containment_score` reads the expectation over the four answer
    levels and normalises by the distribution's total, so a two-level
    distribution spanning the grade lands on it exactly.
    """
    scaled = max(0.0, min(1.0, grade)) * (len(ANSWER_LEVELS) - 1)
    low = min(int(scaled), len(ANSWER_LEVELS) - 2)
    fraction = scaled - low
    probabilities = {
        ANSWER_LEVELS[low]: 1.0 - fraction,
        ANSWER_LEVELS[low + 1]: fraction,
    }
    chosen = ANSWER_LEVELS[low + 1] if fraction >= 0.5 else ANSWER_LEVELS[low]
    return Answer(
        engine="jev",
        latency_ms=1,
        value=chosen,
        probability=max(probabilities.values()),
        probabilities=probabilities,
    )


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

    assert len(jev.gate_calls) == 1, "the rewrite + full re-retrieve was skipped"
    assert run.retry_skipped is True
    assert run.abstain_event is not None, "it still declines — faster, not differently"
    assert run.contexts == [], "an abstention carries no citations"


async def test_the_skip_is_recorded_in_the_trace(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A decline that skipped its retry must say so, or the trace reads as a
    run that gave up early for no reason.

    The row carries the **gate's** number and the gate's threshold, not a
    sufficiency reading: the skip is decided against the rubric, and a row that
    reported a different signal's value would make the trace disagree with the
    decision."""
    jev = _AbsentJev()
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin evidence")

    skipped = [d for d in run.decision_events if d.name == "retry_skipped"]
    assert len(skipped) == 1
    assert skipped[0].threshold == RETRY_SKIP_RUBRIC_MAX
    assert skipped[0].stage == "gate"
    assert "far below their floors" in (skipped[0].reasoning or "")


async def test_a_borderline_run_still_retries(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grade of 0.30 — above the 0.10 skip bound, below the 0.56 floor.
    The corrective retrieval runs: this is the case the bound exists for, and
    it is the direction that costs an answer if the bound is wrong."""
    jev = _AbsentJev(grade=0.30)
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin")

    assert len(jev.gate_calls) == 2, "the corrective retrieval happened"
    assert run.retry_skipped is False
    assert not any(d.name == "retry_skipped" for d in run.decision_events)


async def test_an_insufficient_run_that_the_correction_rescues_answers(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the whole corrective shape exists for, and ADR-006's: one
    evidence check, one corrective retrieval, then answer rather than decline.

    The gate is under the floor on the first attempt and over it on the second.
    `_AbsentJev` drives the rubric through the real `JevRerank`, so the first
    attempt's grade is 0.30 and the second's is 0.90. The run must answer, with
    contexts, after exactly two checks."""
    jev = _AbsentJev(grade=0.30, grade_retry=0.90)
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="the evidence")

    assert jev.gate_calls == [0.30, 0.90], "exactly one corrective retrieval"
    assert run.abstain_event is None, "the correction rescued it"
    assert run.contexts, "an answer with no evidence behind it"
    assert run.retry_skipped is False


async def test_an_insufficient_run_that_the_correction_cannot_rescue_declines(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the same rule. Two failing gates and the run declines —
    one correction, never two (answer-first, so the retry loop clamps any admin
    override to one)."""
    jev = _AbsentJev(grade=0.30, grade_retry=0.40)
    run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin")

    assert jev.gate_calls == [0.30, 0.40]
    assert run.abstain_event is not None
    assert run.contexts == [], "an abstention carries no citations"


async def test_an_admin_override_brings_the_retry_back(
    db: AsyncSession, user_a: Any, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AD-4: the bounds are settings, not constants in the stone. Setting
    `retry_skip_rubric_max` to null turns the skip off, and a run that would
    have skipped now retries."""
    settings = RuntimeSettings.from_data(100, {"retrieval": {"retry_skip_rubric_max": None}})
    token = set_runtime_settings(settings)
    try:
        jev = _AbsentJev()
        run = await _run(db, user_a, jev, monkeypatch, chunk_text="thin evidence")
    finally:
        reset_runtime_settings(token)

    assert len(jev.gate_calls) == 2, "the retry is back"
    assert run.retry_skipped is False