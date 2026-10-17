"""IsUse (ADR-006): the post-generation usefulness stage.

Covers the stage contract (`run_usefulness`) with a fake engine, the shared
tail's decline handling (`_finish_answer` with `decline_text`), and the eval
harness calling the same stage. An IsUse failure — or an outage, which is
treated as failing (KI-57) — replaces the drafted answer with the TR-4
decline, drops the citations, records the message as an abstention, and still
ends the run through the normal tail (a completed run, no run.failed).
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Citation, Message, User
from db.session import get_session_factory
from decisions.engine import DecisionUnavailable
from decisions.output_guard import OutputGuardResult
from graph import runner as runner_module
from graph.review import ReviewResult
from graph.stages.usefulness_stage import (
    IS_USE_NAME,
    IS_USE_PROMPT,
    KIND,
    is_use_question,
    run_usefulness,
    usefulness_decline,
)
from schemas.decisions import Answer, Question
from schemas.events import AnswerDelta, Decision, Metrics, RunCompleted
from tests.retrieval.conftest import make_user

RUN_ID = UUID(int=7)


# ---------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------


class _UsefulnessEngine:
    """Fake DecisionEngine that answers every question with `value`, writes
    the engine name it is told to use, or raises like a dead decision layer."""

    def __init__(self, value: float = 0.9, *, engine: str = "jev", out: bool = False) -> None:
        self.value = value
        self.engine = engine
        self.out = out
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        kind = state.get("kind") if isinstance(state, dict) else None
        if self.out:
            raise DecisionUnavailable("decision_unavailable", "down for test")
        self.calls.append((str(kind), tuple(sorted(questions))))
        return {
            name: Answer(
                engine=self.engine, latency_ms=1, value=self.value, probability=self.value
            )
            for name in questions
        }


class _Context:
    """An `ExpandedContext`-shaped stub for the decline template."""

    def __init__(self, text: str, document_name: str = "warranty.md") -> None:
        self.context_text = text
        self.chunk = type(
            "Chunk",
            (),
            {
                "document_name": document_name,
                "source_type": "document",
                "page": 3,
                "heading_path": "H",
            },
        )()


def _context(index: int = 1) -> _Context:
    return _Context("The AW-2000 warranty is 24 months.", f"doc-{index}.md")


@pytest.fixture
def decisions() -> list[Decision]:
    return []


async def test_a_pass_delivers_and_records_the_row(decisions: list[Decision]) -> None:
    engine = _UsefulnessEngine(0.9)
    outcome = await run_usefulness(
        engine,
        run_id=str(RUN_ID),
        question="How long is the warranty?",
        answer="The warranty is 24 months [1].",
        contexts=[_context()],
        decisions=decisions,
    )

    assert outcome.state == "pass"
    assert outcome.decision_row is not None
    assert outcome.decision_row.name == IS_USE_NAME
    assert outcome.decision_row.stage == KIND
    row = outcome.decision_row
    assert row.value == 0.9
    assert row.engine == "jev"
    assert row.threshold == pytest.approx(0.47)
    assert decisions == [row]
    # The probe's exact call shape, so a threshold derived on the probe still
    # measures the same thing here: kind `isuse`, one Noul named `is_use`.
    assert engine.calls == [("isuse", ("is_use",))]


async def test_a_fail_declines_with_the_found_missing_template(
    decisions: list[Decision],
) -> None:
    engine = _UsefulnessEngine(0.2)
    outcome = await run_usefulness(
        engine,
        run_id=str(RUN_ID),
        question="How long is the warranty?",
        answer="The sources discuss torque specs.",
        contexts=[_context()],
        decisions=decisions,
    )

    assert outcome.state == "fail"
    decline = usefulness_decline(str(RUN_ID), [_context()])
    # TR-4: found, missing, offered actions — the same shape a pre-generation
    # abstention renders.
    assert "What I found:" in decline
    assert "doc-1.md" in decline
    assert "What is missing:" in decline
    assert "the drafted answer was not delivered" in decline
    assert "Turn on the Web search toggle" in decline
    assert decisions[0].value == 0.2


async def test_an_outage_is_a_failing_check_with_an_unavailable_row(
    decisions: list[Decision],
) -> None:
    """KI-57, fail-closed: the check did not happen, so the answer cannot be
    delivered as verified. The row says `unavailable`, never 0.0-as-a-reading,
    and the callback is what puts that row on the bus (an answered call's row
    is the engine emitter's job)."""
    engine = _UsefulnessEngine(out=True)
    published: list[Decision] = []

    async def publish_row(row: Decision) -> None:
        published.append(row)

    outcome = await run_usefulness(
        engine,
        run_id=str(RUN_ID),
        question="q",
        answer="a",
        contexts=[_context()],
        decisions=decisions,
        on_unavailable=publish_row,
    )

    assert outcome.state == "unavailable"
    assert outcome.value is None
    assert engine.calls == []
    row = decisions[0]
    assert row.engine == "unavailable"
    assert row.value == 0.0
    assert row.threshold is None
    assert published == [row]


async def test_the_threshold_boundary_is_0_47(decisions: list[Decision]) -> None:
    """The calibrated boundary, both sides: 0.47 exactly passes (the stage
    compares `>=`), and a reading 0.0001 below it fails — the probe's
    answerables sit at 0.56+ while its should-declines top out at 0.37, so
    nothing measured should ever decide on this razor, but the comparison's
    direction must never flip."""
    for value, expected in ((0.47, "pass"), (0.469_999, "fail"), (0.37, "fail")):
        outcome = await run_usefulness(
            _UsefulnessEngine(value),
            run_id=str(RUN_ID),
            question="q",
            answer="a",
            contexts=[_context()],
            decisions=[],
        )
        assert outcome.state == expected, value
        assert outcome.threshold == pytest.approx(0.47)


async def test_the_prompt_is_the_probe_s_byte_for_byte() -> None:
    """The thresholds were calibrated-. Changing the wording invalidates both
    the `is_use` threshold and the evidence floor, so the stage pin is here."""
    question = is_use_question("How long is the warranty?", "It is 24 months.", [_context()])
    sources = "[1] The AW-2000 warranty is 24 months."
    expected = IS_USE_PROMPT.format(
        q="How long is the warranty?", a="It is 24 months.", s=sources
    )
    assert question.prompt == expected


async def test_sources_are_truncated_like_the_probe() -> None:
    long_text = "x" * 2000
    question = is_use_question("q", "a", [_Context(long_text)])
    assert question.prompt.count("x" * 1200) == 1
    assert "x" * 1201 not in question.prompt


# ---------------------------------------------------------------------------
# The shared tail
# ---------------------------------------------------------------------------


class _Bus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, run_id: UUID, event: Any) -> None:
        self.events.append(event)


def _event(bus: _Bus, type_: str) -> list[Any]:
    return [e for e in bus.events if e.type == type_]


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    return await make_user(db, "isuse-decline@test.dev")


async def _seed_message(db: AsyncSession, user: User) -> tuple[Chat, Message]:
    chat = Chat(user_id=user.id, title="New chat")
    db.add(chat)
    await db.flush()
    message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    db.add(message)
    await db.commit()
    return chat, message


def _patch_review_tail(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the review's LLM work: a decline tail must never reach it."""
    scoring: dict[str, Any] = {"called": False}

    async def fake_review_answer(**_: Any) -> ReviewResult:
        return ReviewResult()

    async def fake_suggestions(**_: Any) -> list[str]:
        return []

    async def fake_guard(engine: Any, *, run_id: str, text: str) -> OutputGuardResult:
        return OutputGuardResult(redacted_text=text)

    async def fake_score(**kwargs: Any) -> None:
        scoring["called"] = True

    async def fake_refine(**_: Any) -> None:
        return None

    monkeypatch.setattr(runner_module, "review_answer", fake_review_answer)
    monkeypatch.setattr(runner_module, "generate_suggestions", fake_suggestions)
    monkeypatch.setattr(runner_module, "guard_output", fake_guard)
    monkeypatch.setattr(runner_module, "score_run_async", fake_score)
    monkeypatch.setattr(runner_module, "refine_chat_title", fake_refine)
    return scoring


async def _finish(
    db: AsyncSession,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str,
    decline_text: str | None,
    plan: str = "hold",
    mode: str = "auto",
) -> tuple[_Bus, dict[str, Any], Message]:
    chat, message = await _seed_message(db, user)
    for n in range(1, 3):
        db.add(Citation(message_id=message.id, n=n, chunk_id=None, rerank_score=0.9))
    await db.commit()

    seen: dict[str, Any] = {}

    async def fake_finalize(
        session_factory: object,
        run_id: UUID,
        message_id: UUID,
        *,
        status: str,
        text: str,
        metrics: dict[str, object] | None = None,
        settle_usage: bool = True,
    ) -> None:
        seen["status"] = status
        seen["text"] = text
        seen["metrics"] = metrics

    monkeypatch.setattr(runner_module, "_finalize", fake_finalize)
    scoring = _patch_review_tail(monkeypatch)

    bus = _Bus()
    await runner_module._finish_answer(
        bus=bus,  # type: ignore[arg-type]
        session_factory=get_session_factory(),
        engine=_UsefulnessEngine(),  # type: ignore[arg-type]
        run_id=RUN_ID,
        message_id=message.id,
        question="How long is the warranty?",
        text=text,
        contexts=[],
        latency_ms={},
        context_used=0,
        context_window=1_000,
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        tokens_in=1,
        generate_ms=5,
        abstained=False,
        plan=plan,
        chat_id=chat.id,
        instant_title=None,
        decline_text=decline_text,
        mode=mode,
    )
    seen["scoring"] = scoring
    return bus, seen, message


async def _citation_rows(message_id: UUID) -> list[Citation]:
    async with get_session_factory()() as session:
        return list(
            (
                await session.execute(select(Citation).where(Citation.message_id == message_id))
            ).scalars()
        )


DECLINE =(
    "I could not find enough evidence to answer that question.\n\n"
    "What I found:\n(no sources found)\n\nWhat is missing:\n"
    "The retrieved sources do not directly state what the question asks for, "
    "so the drafted answer was not delivered.\n\nYou can try:\n"
)


async def test_a_failed_isuse_replaces_the_text_and_abstains(
    db: AsyncSession, user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hold plan: the drafted answer was never delivered, so the decline is
    the one delta, the persisted text is the decline, and the run is an
    abstention without citations, chips or scoring."""
    bus, seen, message = await _finish(
        db, user_a, monkeypatch, text="The warranty is 24 months.", decline_text=DECLINE
    )

    assert seen["status"] == "abstained"
    assert seen["text"] == DECLINE
    deltas = _event(bus, "answer.delta")
    assert [d.text for d in deltas] == [DECLINE]
    assert all(isinstance(d, AnswerDelta) for d in deltas)
    assert await _citation_rows(message.id) == []
    metrics = _event(bus, "metrics")[0]
    assert isinstance(metrics, Metrics)
    assert metrics.faithfulness is None
    assert metrics.min_support is None
    assert _event(bus, "review.claim") == []
    assert seen["scoring"]["called"] is False
    # The run still ends through the normal tail: RunCompleted, never failed.
    statuses = [e.status for e in _event(bus, "run.completed")]
    assert statuses == ["abstained"]
    assert all(isinstance(e, RunCompleted) for e in _event(bus, "run.completed"))
    assert _event(bus, "run.failed") == []


async def test_a_passing_isuse_changes_nothing(
    db: AsyncSession, user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus, seen, message = await _finish(
        db, user_a, monkeypatch,
        # mode != "auto" skips the prose-decline Noul: the fake engine would
        # answer it with 0.9 and turn this pass-tail test into a decline.
        text="The warranty is 24 months.", decline_text=None, mode="deep",
    )

    assert seen["status"] == "complete"
    assert seen["text"] == "The warranty is 24 months."
    assert len(await _citation_rows(message.id)) == 2
    assert _event(bus, "run.completed")[0].status == "completed"
