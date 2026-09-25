"""Small-talk branch (TRD §7 ingress row): intent chitchat skips retrieval,
the reviewer and abstention. Jev is a fixture, the generator is a stub — no
live model."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Collection, Message, User
from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import AutoRunInput, prepare_auto_run
from retrieval.filters import ClientFilters
from schemas.decisions import Answer, Question
from tests.retrieval.conftest import make_collection, make_user, vec

SCORE_NAMES = {"guard_injection", "guard_jailbreak", "guard_pii", "off_topic", "lexical_weight"}
CHOICE_ANSWERS = {
    "source": ("both", {"upload": 0.05, "web": 0.05, "both": 0.9}),
    "complexity": ("single", {"single": 0.9, "multi": 0.1}),
    "risk": ("low", {"low": 0.95, "high": 0.05}),
}


class _IngressJev:
    """Mirrors the recorded ingress fixture from tests/fixtures/jev with the
    intent swapped, so the branch is exercised through the real parsing."""

    def __init__(self, intent: str, off_topic: float = 0.01) -> None:
        self._intent = intent
        self._off_topic = off_topic

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        answers: dict[str, Answer] = {}
        for name in questions:
            if name == "intent":
                answers[name] = Answer(
                    engine="jev",
                    latency_ms=1,
                    value=self._intent,
                    probability=0.95,
                    probabilities={self._intent: 0.95},
                )
            elif name == "off_topic":
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=self._off_topic, probability=self._off_topic
                )
            elif name in SCORE_NAMES:
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=0.01, probability=0.01
                )
            elif name in CHOICE_ANSWERS:
                value, probabilities = CHOICE_ANSWERS[name]
                answers[name] = Answer(
                    engine="jev",
                    latency_ms=1,
                    value=value,
                    probability=probabilities[value],
                    probabilities=probabilities,
                )
            else:
                answers[name] = Answer(
                    engine="jev", latency_ms=1, value=0.01, probability=0.01
                )
        return answers


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    return await make_user(db, "chitchat@test.dev")


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    calls: dict[str, list[str]] = {"complete": [], "retrieval": []}

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        calls["complete"].append(messages[-1]["content"][:40])
        return "the question, standalone"

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    async def recording_search(*args: Any, **kwargs: Any) -> Any:
        calls["retrieval"].append(str(kwargs.get("query_text", "")))
        return []

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", recording_search)
    return calls


async def _seed_chat(db: AsyncSession, user: User) -> tuple[Chat, UUID]:
    await make_collection(db, user, "docs")
    chat = Chat(user_id=user.id, title="New chat")
    db.add(chat)
    await db.flush()
    user_message = Message(chat_id=chat.id, role="user", content="hi there!", status="complete")
    assistant_message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    db.add_all([user_message, assistant_message])
    await db.commit()
    return chat, assistant_message.id


async def _params(db: AsyncSession, chat: Chat, user: User, message_id: UUID) -> AutoRunInput:
    collection_id = (
        await db.execute(select(Collection.id).where(Collection.owner_id == user.id))
    ).scalar_one()
    return AutoRunInput(
        run_id=UUID(int=0),
        message_id=message_id,
        chat_id=chat.id,
        user_id=user.id,
        question="hi there!",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="auto",
        client_filters=ClientFilters(),
        collection_ids=[collection_id],
    )


def _engine(intent: str, off_topic: float = 0.01) -> DecisionEngine:
    return DecisionEngine(jev=_IngressJev(intent, off_topic), mode="jev_only")


async def test_chitchat_skips_retrieval_and_streams_a_direct_reply(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat, assistant_message_id = await _seed_chat(db, user_a)
    streamed: list[str] = []

    async def fake_chitchat(
        *,
        litellm_model: str,
        message: str,
        history: list[tuple[str, str]],
        metadata: dict[str, str],
    ) -> AsyncIterator[str]:
        streamed.append(message)
        yield "Hey - what can I dig up for you?"

    monkeypatch.setattr(auto_module, "stream_chitchat_reply", fake_chitchat)

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, assistant_message_id),
        _engine("chitchat"),
    )

    assert run.chitchat is True
    assert run.ingress.intent == "chitchat"
    assert run.contexts == []
    assert run.kept_chunks == []
    assert run.retrieval_events == []
    assert run.abstain_event is None
    assert no_llm["retrieval"] == []
    assert "Small talk: skipped retrieval" in run.latency_ms

    tokens = [token async for token in run.stream_answer()]
    assert tokens == ["Hey - what can I dig up for you?"]
    assert streamed == ["hi there!"]


async def test_lookup_still_retrieves(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, assistant_message_id = await _seed_chat(db, user_a)

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, assistant_message_id),
        _engine("lookup"),
    )

    assert run.chitchat is False
    assert run.ingress.intent == "lookup"
    assert "Small talk: skipped retrieval" not in run.latency_ms
    assert no_llm["retrieval"] != []


async def test_low_confidence_intent_falls_back_to_the_safe_default(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, assistant_message_id = await _seed_chat(db, user_a)

    class _UnsureJev(_IngressJev):
        async def decide(
            self, *, state: dict[str, Any] | str, questions: dict[str, Question]
        ) -> dict[str, Answer]:
            answers = await super().decide(state=state, questions=questions)
            answers["intent"] = Answer(
                engine="jev",
                latency_ms=1,
                value="chitchat",
                probability=0.01,
                probabilities={"chitchat": 0.01, "lookup": 0.01},
            )
            return answers

    engine = DecisionEngine(jev=_UnsureJev("chitchat"), mode="jev_only")
    run = await prepare_auto_run(
        get_session_factory(), await _params(db, chat, user_a, assistant_message_id), engine
    )

    assert run.ingress.intent == "lookup"
    assert run.chitchat is False


async def test_mixed_message_keeps_the_lookup_path(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, assistant_message_id = await _seed_chat(db, user_a)
    params = await _params(db, chat, user_a, assistant_message_id)
    mixed = AutoRunInput(**{**params.__dict__, "question": "hi! who is Mr. Darcy?"})

    run = await prepare_auto_run(
        get_session_factory(), mixed, _engine("lookup")
    )

    assert run.chitchat is False
    assert no_llm["retrieval"] != []


async def test_an_off_topic_warn_does_not_divert_small_talk(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    """off_topic is thresholded with no block name, so it can only ever warn.
    A greeting that Jev also calls off-topic relative to the corpus must still
    be answered as small talk, or the most common opening turn breaks."""
    chat, assistant_message_id = await _seed_chat(db, user_a)

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, assistant_message_id),
        _engine("chitchat", off_topic=0.99),
    )

    assert run.ingress.off_topic == "warn"
    assert run.chitchat is True
    assert "Small talk: skipped retrieval" in run.latency_ms
    assert no_llm["retrieval"] == []
