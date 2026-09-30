"""Library questions (TRD §7 ingress row, `intent='library'`): answered
from the chat scope's document list, never from retrieval.

Jev is a fixture and the generator is a stub — no live model."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chats.scope import list_scope_documents, resolve_scope
from db.models import Chat, Citation, Collection, Message, User
from db.session import get_session_factory
from decisions.engine import DecisionEngine
from graph import auto as auto_module
from graph.auto import AutoRunInput, prepare_auto_run
from graph.generate import build_library_messages
from retrieval.filters import ClientFilters
from schemas.decisions import Answer, Question
from tests.retrieval.conftest import make_collection, make_document, make_user, vec

SCORE_NAMES = {
    "guard_injection",
    "guard_jailbreak",
    "guard_pii",
    "off_topic",
    "lexical_weight",
}


class _LibraryJev:
    def __init__(self, intent: str) -> None:
        self._intent = intent

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
            elif name in SCORE_NAMES or name in {"sufficient", "conflict"}:
                answers[name] = Answer(engine="jev", latency_ms=1, value=0.01, probability=0.01)
            else:
                answers[name] = Answer(
                    engine="jev",
                    latency_ms=1,
                    value="both",
                    probability=0.9,
                    probabilities={"both": 0.9},
                )
        return answers


@pytest.fixture
async def user_a(db: AsyncSession) -> User:
    return await make_user(db, "library-a@test.dev")


@pytest.fixture
def no_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    calls: dict[str, list[str]] = {"retrieve": []}

    async def fake_complete(**kwargs: Any) -> str:
        return str(kwargs["messages"][-1]["content"])

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [vec(1) for _ in texts]

    async def recording_search(*args: Any, **kwargs: Any) -> Any:
        calls["retrieve"].append(str(kwargs.get("query_text", "")))
        return []

    monkeypatch.setattr(auto_module, "complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    monkeypatch.setattr(auto_module, "hybrid_search", recording_search)
    return calls


async def _chat_with_sources(
    db: AsyncSession, user: User, names: list[str]
) -> tuple[Chat, str, Collection]:
    chat = Chat(user_id=user.id, title="Library chat")
    db.add(chat)
    await db.flush()
    container = await make_collection(
        db, user, "chat sources", kind="chat", chat_id=chat.id
    )
    for name in names:
        await make_document(db, container, name=name)
    user_message = Message(chat_id=chat.id, role="user", content="q", status="complete")
    assistant_message = Message(chat_id=chat.id, role="assistant", content="", status=None)
    db.add_all([user_message, assistant_message])
    await db.commit()
    await db.refresh(assistant_message)
    return chat, str(assistant_message.id), container


async def _params(
    db: AsyncSession, chat: Chat, user: User, message_id: str
) -> AutoRunInput:
    from uuid import UUID

    scope = await resolve_scope(db, chat)
    return AutoRunInput(
        run_id=UUID(int=0),
        message_id=UUID(message_id),
        chat_id=chat.id,
        user_id=user.id,
        question="what books do we have?",
        litellm_model="openrouter/some-model",
        small_model="openrouter/some-small-model",
        context_window=128_000,
        source="auto",
        client_filters=ClientFilters(),
        collection_ids=scope,
    )


async def test_library_question_lists_the_chats_scope(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, message_id, _ = await _chat_with_sources(
        db, user_a, ["Pride and Prejudice", "Frankenstein"]
    )
    shared = await make_collection(db, user_a, "Shared", visibility="shared")
    await make_document(db, shared, name="The Time Machine")

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=_LibraryJev("library"), mode="jev_only"),
    )

    assert run.library_names == ["Frankenstein", "Pride and Prejudice", "The Time Machine"]


async def test_library_question_never_lists_another_chats_document(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, message_id, _ = await _chat_with_sources(db, user_a, ["Mine"])
    _, _, other_container = await _chat_with_sources(db, user_a, ["Theirs"])
    assert other_container.id != (await resolve_scope(db, chat))[0]

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=_LibraryJev("library"), mode="jev_only"),
    )

    assert run.library_names == ["Mine"]
    assert "Theirs" not in run.library_names


async def test_library_question_retrieves_nothing_and_cites_nothing(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, message_id, _ = await _chat_with_sources(db, user_a, ["Mine"])

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=_LibraryJev("library"), mode="jev_only"),
    )

    assert run.library_names == ["Mine"]
    assert run.contexts == []
    assert run.retrieval_events == []
    assert no_llm["retrieve"] == []
    rows = (
        await db.execute(
            select(Citation).where(Citation.message_id == run.params.message_id)
        )
    ).scalars().all()
    assert rows == []


async def test_count_question_gets_the_count_from_the_scope(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, message_id, _ = await _chat_with_sources(
        db, user_a, ["One", "Two", "Three", "Four", "Five"]
    )

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=_LibraryJev("library"), mode="jev_only"),
    )

    assert run.library_names is not None
    assert len(run.library_names) == 5
    user_message = build_library_messages(
        "how many documents are in my sources?", run.library_names, []
    )[-1]["content"]
    assert "5 document(s)" in user_message


async def test_a_lookup_question_is_not_treated_as_a_library_question(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, message_id, _ = await _chat_with_sources(db, user_a, ["Mine"])

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=_LibraryJev("lookup"), mode="jev_only"),
    )

    assert run.library_names is None
    assert no_llm["retrieve"]


async def test_unsearchable_documents_are_not_listed(
    db: AsyncSession, user_a: User, no_llm: dict[str, list[str]]
) -> None:
    chat, message_id, container = await _chat_with_sources(db, user_a, ["Mine"])
    pending = await make_document(db, container, name="Still parsing")
    pending.status = "parsing"
    await db.commit()

    run = await prepare_auto_run(
        get_session_factory(),
        await _params(db, chat, user_a, message_id),
        DecisionEngine(jev=_LibraryJev("library"), mode="jev_only"),
    )

    assert run.library_names == ["Mine"]


async def test_list_scope_documents_is_empty_for_an_empty_scope(
    db: AsyncSession, user_a: User
) -> None:
    assert await list_scope_documents(db, []) == []
