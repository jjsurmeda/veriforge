"""Deep mode pipeline tests (TRD §7 row 5, CH-4): DecisionEngine and LLM
calls mocked, retrieval against the real test Postgres."""

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Message, User
from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import deep as deep_module
from graph.deep import DeepRunInput, prepare_deep_run
from retrieval.filters import ClientFilters
from schemas.decisions import Answer, Question
from tests.retrieval.conftest import add_chunk, make_collection, make_document, make_section, vec


class _ScriptedJev:
    """Answers replaying the real decision kinds' shapes: rerank passages as
    rubric-shaped one-hot distributions (the evidence gate is the mean of the
    top three expected levels, TRD §9.6), guard/intent Nouls+Choices as
    pass-through 'no problem', sanitizer chunks as 'keep', entity readings
    per the configured guard answer, and the controller per a scripted
    sequence of sufficient/need_more values (one per controller call)."""

    def __init__(
        self,
        controller_script: list[str],
        *,
        rerank_grade: float = 0.9,
        entity_reading: float = 0.9,
    ) -> None:
        from retrieval.rerank import ANSWER_LEVEL_VALUE, ANSWER_LEVELS

        self._controller_script = list(controller_script)
        self._rerank = self._rubric(ANSWER_LEVEL_VALUE, ANSWER_LEVELS, rerank_grade)
        self._entity_reading = entity_reading

    @staticmethod
    def _rubric(level_values: dict[str, float], levels: tuple[str, ...], score: float) -> Answer:
        """A rerank answer shaped the way the rubric's `Choice` is graded: the
        chosen level plus a one-hot distribution over all four, which is what
        `answer_containment_score` reads."""
        level = min(levels, key=lambda name: abs(level_values[name] - score))
        probabilities = {name: 0.0 for name in levels}
        probabilities[level] = 1.0
        return Answer(
            engine="jev", latency_ms=1, value=level, probability=1.0,
            probabilities=probabilities,
        )

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        kind = state.get("kind") if isinstance(state, dict) else None
        answers: dict[str, Answer] = {}
        for name in questions:
            if name == "controller":
                value = self._controller_script.pop(0) if self._controller_script else "sufficient"
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=value, probability=0.9,
                    probabilities={value: 0.9},
                )
            elif name.startswith("passage_"):
                answers[name] = self._rerank
            elif kind == "entity":
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=self._entity_reading,
                    probability=self._entity_reading,
                )
            elif name.startswith("chunk_injection"):
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
            elif kind == "ingress":
                if name in {
                    "guard_injection", "guard_jailbreak", "guard_pii", "off_topic",
                }:
                    answers[name] = Answer(engine="jev", latency_ms=1, value=0.02, probability=0.02)
                elif name == "lexical_weight":
                    answers[name] = Answer(engine="jev", latency_ms=1, value=0.5, probability=None)
                else:
                    answers[name] = Answer(
                        engine="jev", latency_ms=1, value="both", probability=0.9,
                        probabilities={"both": 0.9},
                    )
            else:
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
        return answers


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    from tests.retrieval.conftest import make_user

    return await make_user(db, "deep-a@test.dev")


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        if "rewrite" in messages[0]["content"].lower() or "standalone" in messages[0][
            "content"
        ].lower():
            return "rewritten question"
        return json.dumps(
            [
                {"id": "q1", "question": "sub question one", "depends_on": []},
                {"id": "q2", "question": "sub question two", "depends_on": []},
            ]
        )

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    monkeypatch.setattr(deep_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)


async def _seed(
    db: AsyncSession, user: User, *, with_chunk: bool = True
) -> tuple[Chat, Message, Any]:
    collection = await make_collection(db, user, "docs")
    document = await make_document(db, collection)
    section = await make_section(db, document)
    if with_chunk:
        await add_chunk(
            db, document=document, section=section, ord=0,
            text_="the AW-2000-XE ships with a 12 month blade warranty",
            embedding=vec(1, bump=1),
        )
    chat = Chat(user_id=user.id, title="t")
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return chat, message, collection


def _params(user: User, chat: Chat, message: Message, collection_id: Any) -> DeepRunInput:
    return DeepRunInput(
        run_id=message.id,
        message_id=message.id,
        chat_id=chat.id,
        user_id=user.id,
        question="Does my AW-2000-XE blade have warranty coverage?",
        litellm_model="openrouter/anthropic/claude-haiku-4.5",
        small_model="openrouter/anthropic/claude-haiku-4.5",
        context_window=128_000,
        source="upload",
        client_filters=ClientFilters(),
        collection_ids=[collection_id],
    )


async def test_deep_run_stops_at_first_sufficient_hop(db: AsyncSession, user_a: User) -> None:
    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(jev=_ScriptedJev(["sufficient"]), mode="jev_only")

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert len(run.plan_event.sub_questions) == 2
    assert len(run.retrieval_events) == 2  # both sub-questions ran in hop 1
    assert run.abstain_event is None
    assert run.contexts
    assert any(d.name == "controller" for d in run.decision_events)


async def test_deep_cap_out_with_evidence_above_the_floor_still_answers(
    db: AsyncSession, user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 Deep review: the controller decides how many hops to spend, not
    whether to answer. A loop that ran out of hops while saying `need_more`
    goes through the same floor and guard as a `sufficient` one; a pool that
    clears them reaches generation, where IsUse is the judge."""
    from config import get_settings

    monkeypatch.setattr(get_settings(), "deep_max_hops", 1)
    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(jev=_ScriptedJev(["need_more", "need_more"]), mode="jev_only")

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert run.abstain_event is None
    assert run.contexts
    assert [d for d in run.decision_events if d.name == "evidence" and d.stage == "gate"]


async def test_deep_cap_out_below_the_floor_abstains(
    db: AsyncSession, user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config import get_settings

    monkeypatch.setattr(get_settings(), "deep_max_hops", 1)
    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(
        jev=_ScriptedJev(["need_more", "need_more"], rerank_grade=0.0), mode="jev_only"
    )

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert run.abstain_event is not None
    assert run.abstain_event.offered_actions == ["web"]
    assert run.contexts == []


async def test_deep_cap_out_with_nothing_gathered_abstains(
    db: AsyncSession, user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No passage at all reads as a failing gate, never as a pass."""
    from config import get_settings

    monkeypatch.setattr(get_settings(), "deep_max_hops", 1)
    chat, message, collection = await _seed(db, user_a, with_chunk=False)
    engine = DecisionEngine(jev=_ScriptedJev(["need_more", "need_more"]), mode="jev_only")

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert run.abstain_event is not None
    assert run.contexts == []


async def test_deep_run_generates_followup_when_plan_exhausted_but_insufficient(
    db: AsyncSession, user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for the bug found via live-key diagnostics: the
    Controller saying `need_more` after the upfront plan is fully answered
    used to abstain immediately, wasting unused hop/credit budget. It must
    now generate one more sub-question and try another hop instead."""

    async def fake_complete_with_followup(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        prompt = messages[0]["content"].lower()
        if "rewrite" in prompt or "standalone" in prompt:
            return "rewritten question"
        if "next sub-question" in prompt:
            return json.dumps({"question": "a follow-up sub question"})
        return json.dumps(
            [
                {"id": "q1", "question": "sub question one", "depends_on": []},
                {"id": "q2", "question": "sub question two", "depends_on": []},
            ]
        )

    monkeypatch.setattr(deep_module, "complete", fake_complete_with_followup)

    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(jev=_ScriptedJev(["need_more", "sufficient"]), mode="jev_only")

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert run.abstain_event is None
    hops_run = {r.hop for r in run.retrieval_events}
    assert hops_run == {1, 2}
    followup_queries = [r.query for r in run.retrieval_events if r.hop == 2]
    assert followup_queries == ["a follow-up sub question"]


async def test_deep_run_below_evidence_floor_abstains(db: AsyncSession, user_a: User) -> None:
    """The evidence floor (ADP-R2b: Deep under the same floor as Auto): the
    Controller said sufficient, but the hop winners' rubric grades are below
    the evidence floor, so the run declines instead of generating. Nothing
    survives for the generator — no contexts, no citations — and the gate's
    own row is in the trace."""
    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(
        jev=_ScriptedJev(["sufficient"], rerank_grade=0.0), mode="jev_only"
    )

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert run.abstain_event is not None
    assert run.contexts == []
    gate = [d for d in run.decision_events if d.name == "evidence" and d.stage == "gate"]
    assert len(gate) == 1
    assert float(gate[0].value) < 0.455


async def test_deep_run_entity_mismatch_abstains(db: AsyncSession, user_a: User) -> None:
    """The sibling guard: the rubric grades clear the floor, but no passage
    the gathered evidence covers the entity the question names, so the run
    abstains rather than answering from the wrong source."""
    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(
        jev=_ScriptedJev(["sufficient"], entity_reading=0.01), mode="jev_only"
    )

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert run.abstain_event is not None
    assert run.contexts == []
    gate = [d for d in run.decision_events if d.name == "evidence" and d.stage == "gate"]
    assert gate and float(gate[0].value) >= 0.455  # the gate passed
    entity_rows = [d for d in run.decision_events if d.stage == "entity"]
    assert entity_rows  # the guard was asked


async def test_deep_run_gate_outage_declines(db: AsyncSession, user_a: User) -> None:
    """KI-57, fail-closed: an unreachable decision layer at the entity guard
    cannot be read as coverage, so the run declines. No entity questions were
    answered, so the outage row explains the decline in the trace."""
    from decisions.engine import DecisionUnavailable

    class _UnreachableJev(_ScriptedJev):
        async def decide(self, *, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
            if isinstance(state, dict) and state.get("kind") == "entity":
                raise DecisionUnavailable("engine down", "engine down for test")
            return await super().decide(state=state, questions=questions)

    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(jev=_UnreachableJev(["sufficient"]), mode="jev_only")

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert run.abstain_event is not None
    assert run.contexts == []
    outage = [d for d in run.decision_events if d.engine == "unavailable" and d.stage == "entity"]
    assert outage


async def test_the_controller_is_shown_the_evidence_grade(db: AsyncSession, user_a: User) -> None:
    """G4: each controller question carries the pooled grade line, computed
    from the passages gathered so far."""
    prompts: list[str] = []

    class _Spy(_ScriptedJev):
        async def decide(self, *, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
            if "controller" in questions:
                prompts.append(getattr(questions["controller"], "prompt", ""))
            return await super().decide(state=state, questions=questions)

    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(jev=_Spy(["sufficient"], rerank_grade=0.9), mode="jev_only")

    await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert len(prompts) == 1
    assert "[evidence]" in prompts[0]
    assert "mean of top 3 = 1.00" in prompts[0]  # the fake rubric is one-hot
    assert "evidence floor 0.455" in prompts[0]


async def _seed_two_documents(db: AsyncSession, user: User) -> tuple[Chat, Message, Any]:
    chat, message, collection = await _seed(db, user)
    other = await make_document(db, collection)
    section = await make_section(db, other)
    await add_chunk(
        db, document=other, section=section, ord=0,
        text_="the AW-2000-XE ships with a 24 month blade warranty",
        embedding=vec(1, bump=2),
    )
    return chat, message, collection


class _ConflictJev(_ScriptedJev):
    def __init__(self, value: float) -> None:
        super().__init__(["sufficient"])
        self.value = value
        self.conflict_calls = 0

    async def decide(self, *, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
        if isinstance(state, dict) and state.get("kind") == "conflict":
            self.conflict_calls += 1
            return {
                name: Answer(engine="jev", latency_ms=1, value=self.value, probability=self.value)
                for name in questions
            }
        return await super().decide(state=state, questions=questions)


async def test_deep_discloses_a_contradiction_between_two_sources(
    db: AsyncSession, user_a: User
) -> None:
    """KI-93: Auto's conflict batch runs over Deep's final evidence and the
    same Conflict event comes out, naming one passage per side."""
    chat, message, collection = await _seed_two_documents(db, user_a)
    jev = _ConflictJev(0.95)

    run = await prepare_deep_run(
        get_session_factory(),
        _params(user_a, chat, message, collection.id),
        DecisionEngine(jev=jev, mode="jev_only"),
    )

    assert run.abstain_event is None
    assert run.conflict_event is not None
    assert run.conflict_event.run_id == str(message.id)
    left, right = run.conflict_event.citation_ids_left, run.conflict_event.citation_ids_right
    assert len(left) == len(right) == 1 and left != right
    assert "conflict" in run.latency_ms


async def test_deep_no_conflict_when_pairs_agree_or_there_is_one_source(
    db: AsyncSession, user_a: User
) -> None:
    chat, message, collection = await _seed_two_documents(db, user_a)
    agree = _ConflictJev(0.01)
    run = await prepare_deep_run(
        get_session_factory(),
        _params(user_a, chat, message, collection.id),
        DecisionEngine(jev=agree, mode="jev_only"),
    )
    assert agree.conflict_calls == 1
    assert run.conflict_event is None

    chat, message, collection = await _seed(db, user_a)  # one document
    single = _ConflictJev(0.95)
    run = await prepare_deep_run(
        get_session_factory(),
        _params(user_a, chat, message, collection.id),
        DecisionEngine(jev=single, mode="jev_only"),
    )
    assert single.conflict_calls == 0
    assert run.conflict_event is None


async def test_deep_abstain_runs_no_conflict_check(db: AsyncSession, user_a: User) -> None:
    chat, message, collection = await _seed_two_documents(db, user_a)
    jev = _ConflictJev(0.95)
    jev._rerank = jev._rubric(*_levels(), 0.0)  # below the floor
    run = await prepare_deep_run(
        get_session_factory(),
        _params(user_a, chat, message, collection.id),
        DecisionEngine(jev=jev, mode="jev_only"),
    )
    assert run.abstain_event is not None
    assert jev.conflict_calls == 0 and run.conflict_event is None


def _levels() -> tuple[dict[str, float], tuple[str, ...]]:
    from retrieval.rerank import ANSWER_LEVEL_VALUE, ANSWER_LEVELS

    return ANSWER_LEVEL_VALUE, ANSWER_LEVELS
