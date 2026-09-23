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
    """Answers guard/intent Nouls+Choices as pass-through 'no problem',
    sanitizer chunks as 'keep', and the controller per a scripted sequence
    of sufficient/need_more values (one per controller call)."""

    def __init__(self, controller_script: list[str]) -> None:
        self._controller_script = list(controller_script)

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


async def _seed(db: AsyncSession, user: User) -> tuple[Chat, Message, Any]:
    collection = await make_collection(db, user, "docs")
    document = await make_document(db, collection)
    section = await make_section(db, document)
    await add_chunk(
        db, document=document, section=section, ord=0,
        text_="the AW-2000-XE ships with a 12 month blade warranty",
        embedding=vec(1, bump=1),
    )
    chat = Chat(user_id=user.id, title="t", collection_ids=[str(collection.id)])
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


async def test_deep_run_abstains_when_budget_exhausted(
    db: AsyncSession, user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config import get_settings

    monkeypatch.setattr(get_settings(), "deep_max_hops", 1)
    chat, message, collection = await _seed(db, user_a)
    engine = DecisionEngine(jev=_ScriptedJev(["need_more", "need_more"]), mode="jev_only")

    run = await prepare_deep_run(
        get_session_factory(), _params(user_a, chat, message, collection.id), engine
    )

    assert run.abstain_event is not None
    assert run.abstain_event.offered_actions == ["web"]


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
