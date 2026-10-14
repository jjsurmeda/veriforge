"""P2a item 3: a prose decline becomes an abstention (KI-25 shape).

When the generated reply itself says the sources cannot answer (the
`says_not_in_sources` shape), the auto-mode run is recorded as `abstained`
and its citations are dropped. The decision is a post-delivery Noul that
rides alongside the review (no added latency), and it fires in auto mode
only. Partial answers that state what is missing (TR-4) stay complete, and
a normal answer makes no call beyond the Noul.
"""

import asyncio
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Citation, Message, User
from db.session import get_session_factory
from decisions.output_guard import OutputGuardResult
from decisions.thresholds import threshold
from graph import runner as runner_module
from graph.review import ExtractedClaim, ReviewResult, ReviewScores, VerifiedClaim
from schemas.decisions import Answer, Question
from schemas.events import Metrics, RunCompleted
from tests.retrieval.conftest import make_user

RUN_ID = UUID(int=1)
FULL_DECLINE = (
    "I could not find enough evidence in your sources to answer which model "
    "the AW-2000 ships with. No such specification is in the documents."
)
PARTIAL_ANSWER = (
    "The AW-2000 supports up to 8 Gbps on port 1 [1]. Which ports are 10 Gbps "
    "the sources do not say."
)


class _DeclineEngine:
    """Fake DecisionEngine: records every decide call, answers the
    prose-decline Noul with `p`, and answers everything else 'no'."""

    def __init__(self, p: float = 0.0, fail: bool = False) -> None:
        self.p = p
        self.fail = fail
        self.calls: list[dict[str, str | None]] = []

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        if self.fail:
            raise RuntimeError("decision engine down")
        self.calls.append(
            {
                "kind": state.get("kind") if isinstance(state, dict) else None,
                "questions": ",".join(questions),
            }
        )
        return {
            name: Answer(engine="jev", latency_ms=1, value=self.p, probability=self.p)
            for name in questions
        }


class _Bus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, run_id: UUID, event: Any) -> None:
        self.events.append(event)


def _event(bus: _Bus, type_: str) -> list[Any]:
    return [e for e in bus.events if e.type == type_]


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    return await make_user(db, "prose-decline@test.dev")


async def _seed_message(db: AsyncSession, user: User) -> tuple[Chat, Message]:
    chat = Chat(user_id=user.id, title="New chat")
    db.add(chat)
    await db.flush()
    message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    db.add(message)
    await db.commit()
    return chat, message


def _patch_review_tail(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the review's LLM work; the engine fake then only sees the
    prose-decline Noul, which is the call under test."""
    scoring: dict[str, Any] = {"called": False}

    async def fake_review_answer(**_: Any) -> ReviewResult:
        return ReviewResult(
            claims=[
                VerifiedClaim(
                    ExtractedClaim("c1", "The blade is titanium.", [1], True),
                    "supported",
                    0.9,
                    "jev",
                )
            ],
            scores=ReviewScores(faithfulness=0.4, min_support=0.3, citation_precision=0.5),
        )

    async def fake_suggestions(**_: Any) -> list[str]:
        return []

    async def fake_guard(engine: Any, *, run_id: str, text: str) -> OutputGuardResult:
        return OutputGuardResult(redacted_text=text)

    async def fake_score(**kwargs: Any) -> None:
        scoring["called"] = True
        scoring.update(kwargs)

    async def fake_refine(**_: Any) -> None:
        return None

    monkeypatch.setattr(runner_module, "review_answer", fake_review_answer)
    monkeypatch.setattr(runner_module, "generate_suggestions", fake_suggestions)
    monkeypatch.setattr(runner_module, "guard_output", fake_guard)
    monkeypatch.setattr(runner_module, "score_run_async", fake_score)
    monkeypatch.setattr(runner_module, "refine_chat_title", fake_refine)
    return scoring


async def _finish(
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    user: User,
    *,
    text: str,
    engine: _DeclineEngine,
    mode: str = "auto",
    citations: int = 2,
    plan: str = "hold",
) -> tuple[_Bus, dict[str, Any], Message]:
    chat, message = await _seed_message(db, user)
    for n in range(1, citations + 1):
        # chunk_id is nullable (web chunks expire with a 7-day TTL, SET NULL);
        # a decline's citations point at no chunk the test would have to seed.
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
        engine=engine,  # type: ignore[arg-type]
        run_id=RUN_ID,
        message_id=message.id,
        question="Which model does the AW-2000 ship with?",
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


async def test_full_decline_is_abstained_with_no_citations(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, user_a: User
) -> None:
    """The KI-25 shape: the reply text still lands (hold plan), but the run
    is an abstention — no citations, no scores, no scoring task, no chips."""
    bus, seen, message = await _finish(
        monkeypatch, db, user_a, text=FULL_DECLINE, engine=_DeclineEngine(p=0.92)
    )

    assert seen["status"] == "abstained"
    assert seen["text"] == FULL_DECLINE
    # The hold-plan AnswerDelta still delivers the decline prose.
    deltas = _event(bus, "answer.delta")
    assert [d.text for d in deltas] == [FULL_DECLINE]
    # An abstention carries no citations.
    assert await _citation_rows(message.id) == []
    # No review scores, no claim chips.
    metrics = _event(bus, "metrics")[0]
    assert isinstance(metrics, Metrics)
    assert metrics.faithfulness is None
    assert metrics.min_support is None
    assert seen["metrics"]["faithfulness"] is None
    assert seen["metrics"]["min_support"] is None
    assert _event(bus, "review.claim") == []
    # No scoring task.
    assert seen["scoring"]["called"] is False
    # Terminal event is the abstained one.
    completed = _event(bus, "run.completed")
    assert [e.status for e in completed] == ["abstained"]
    assert all(isinstance(e, RunCompleted) for e in completed)


async def test_partial_answer_that_states_what_is_missing_stays_complete(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, user_a: User
) -> None:
    """TR-4 allows a partial answer to name what is missing; that is not a
    whole-question decline, so the Noul answers no (p below the floor)."""
    bus, seen, message = await _finish(
        monkeypatch,
        db,
        user_a,
        text=PARTIAL_ANSWER,
        engine=_DeclineEngine(p=0.2),
    )

    assert seen["status"] == "complete"
    assert len(await _citation_rows(message.id)) == 2
    metrics = _event(bus, "metrics")[0]
    assert isinstance(metrics, Metrics)
    assert metrics.faithfulness == 0.4
    assert metrics.min_support == 0.3
    assert _event(bus, "review.claim") != []
    assert seen["scoring"]["called"] is True
    completed = _event(bus, "run.completed")
    assert completed[0].status == "completed"


async def test_normal_answer_makes_no_call_beyond_the_noul(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, user_a: User
) -> None:
    engine = _DeclineEngine(p=0.05)
    bus, seen, _message = await _finish(
        monkeypatch,
        db,
        user_a,
        text="The AW-2000 ships with the RC-2 motor [1].",
        engine=engine,
    )

    assert seen["status"] == "complete"
    # The review's LLM work is stubbed, so the only decide call the engine
    # sees is the prose-decline Noul itself.
    assert engine.calls == [{"kind": "prose_decline", "questions": "prose_decline"}]
    assert _event(bus, "run.completed")[0].status == "completed"


async def test_threshold_boundary_and_admin_floor(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, user_a: User
) -> None:
    """p at the floor flips; just under it does not. Mutation: renaming the
    threshold lookup or hard-coding the comparison breaks the override test
    below."""
    floor = threshold("prose_decline", "jev")

    _bus, seen, _message = await _finish(
        monkeypatch, db, user_a, text=FULL_DECLINE, engine=_DeclineEngine(p=floor)
    )
    assert seen["status"] == "abstained"

    _bus, seen, _message = await _finish(
        monkeypatch, db, user_a, text=FULL_DECLINE, engine=_DeclineEngine(p=floor - 0.001)
    )
    assert seen["status"] == "complete"

    # Admin-overridable: the runner looks the threshold up by name, so a
    # raised floor holds even a near-certain decline.
    looked_up: list[tuple[str, str]] = []

    def fake_threshold(name: str, engine_name: str) -> float:
        looked_up.append((name, engine_name))
        return 0.99

    monkeypatch.setattr(runner_module, "threshold", fake_threshold)
    _bus, seen, _message = await _finish(
        monkeypatch, db, user_a, text=FULL_DECLINE, engine=_DeclineEngine(p=0.92)
    )
    assert seen["status"] == "complete"
    assert ("prose_decline", "jev") in looked_up


async def test_noul_rides_alongside_the_review(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, user_a: User
) -> None:
    """No added latency: the Noul must be running while the review is. The
    fake review blocks until the Noul has started — if the Noul ran
    sequentially after the review it would never start and the test hangs
    into its timeout."""
    decline_started = asyncio.Event()
    review_started = asyncio.Event()
    both = asyncio.Event()

    async def fake_review_answer(**_: Any) -> ReviewResult:
        await asyncio.wait_for(decline_started.wait(), timeout=2)
        review_started.set()
        both.set()
        return ReviewResult()

    async def fake_suggestions(**_: Any) -> list[str]:
        return []

    async def fake_guard(engine: Any, *, run_id: str, text: str) -> OutputGuardResult:
        return OutputGuardResult(redacted_text=text)

    async def fake_score(**_: Any) -> None:
        return None

    async def fake_refine(**_: Any) -> None:
        return None

    monkeypatch.setattr(runner_module, "review_answer", fake_review_answer)
    monkeypatch.setattr(runner_module, "generate_suggestions", fake_suggestions)
    monkeypatch.setattr(runner_module, "guard_output", fake_guard)
    monkeypatch.setattr(runner_module, "score_run_async", fake_score)
    monkeypatch.setattr(runner_module, "refine_chat_title", fake_refine)

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

    monkeypatch.setattr(runner_module, "_finalize", fake_finalize)

    class _Engine:
        async def decide(
            self, *, state: dict[str, Any] | str, questions: dict[str, Question]
        ) -> dict[str, Answer]:
            decline_started.set()
            await asyncio.wait_for(both.wait(), timeout=2)
            return {"prose_decline": Answer(engine="jev", latency_ms=1, value=0.0, probability=0.0)}

    chat, message = await _seed_message(db, user_a)
    bus = _Bus()
    await runner_module._finish_answer(
        bus=bus,  # type: ignore[arg-type]
        session_factory=get_session_factory(),
        engine=_Engine(),  # type: ignore[arg-type]
        run_id=RUN_ID,
        message_id=message.id,
        question="Which model does the AW-2000 ship with?",
        text=FULL_DECLINE,
        contexts=[],
        latency_ms={},
        context_used=0,
        context_window=1_000,
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        tokens_in=1,
        generate_ms=5,
        abstained=False,
        plan="hold",
        chat_id=chat.id,
        instant_title=None,
        mode="auto",
    )

    assert decline_started.is_set()
    assert review_started.is_set()
    assert seen["status"] == "complete"


async def test_noul_failure_keeps_the_answer(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, user_a: User
) -> None:
    """A classification error must not fail the run or strip citations:
    the reply is already on the way."""
    bus, seen, message = await _finish(
        monkeypatch, db, user_a, text=FULL_DECLINE, engine=_DeclineEngine(p=0.92, fail=True)
    )

    assert seen["status"] == "complete"
    assert len(await _citation_rows(message.id)) == 2
    assert _event(bus, "run.completed")[0].status == "completed"


@pytest.mark.parametrize("mode", ["deep", "fast"])
async def test_other_modes_make_no_decline_call(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession, user_a: User, mode: str
) -> None:
    """The Noul is an auto-mode gate (the broad-question declines were auto
    runs): deep and fast never call it, and a decline-shaped reply there is
    left to the reviewer as before."""
    engine = _DeclineEngine(p=0.92)
    _bus, seen, message = await _finish(
        monkeypatch, db, user_a, text=FULL_DECLINE, engine=engine, mode=mode
    )

    assert engine.calls == []
    assert seen["status"] == "complete"
    assert len(await _citation_rows(message.id)) == 2
