"""Chat CRUD ownership, run creation, SSE stream, cancel/partial-save (CH-6),
replay after reconnect (TRD §12)."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from chats.router import _effective_collection_ids
from db.models import Chat, Message
from db.session import get_session_factory
from graph.runner import _finalize
from quota.usage import get_usage_context
from tests.conftest import make_run_row

TOKENS = ["Hello", " ", "world", "!", "!", "!"]
FULL = "".join(TOKENS)


def test_run_collection_filter_cannot_widen_chat_scope() -> None:
    first = UUID("00000000-0000-0000-0000-000000000001")
    second = UUID("00000000-0000-0000-0000-000000000002")

    assert _effective_collection_ids([str(first), str(second)], [second]) == [second]
    assert _effective_collection_ids([str(first)], [second]) == []
    assert _effective_collection_ids([], [second]) == []


async def _auth(client: AsyncClient, email: str = "owner@test.dev") -> dict[str, str]:
    signup = await client.post("/auth/signup", json={"email": email, "password": "password123"})
    body = signup.json()
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _make_chat(client: AsyncClient, headers: dict[str, str]) -> str:
    chat = await client.post("/chats", json={}, headers=headers)
    assert chat.status_code == 201, chat.text
    return str(chat.json()["id"])


def _patch_fast_seams(
    monkeypatch: pytest.MonkeyPatch,
    stream: Any,
    complete_response: str = "rewritten",
    title_response: str = '{"title": "Greeting The World"}',
) -> list[str]:
    title_calls: list[str] = []

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        if metadata.get("role") == "titler":
            title_calls.append(metadata["role"])
            context = get_usage_context()
            if context is not None:
                await context.record_call(
                    model_id=litellm_model, role="titler", tokens_in=7, tokens_out=3
                )
            return title_response
        return complete_response

    async def fake_embed(*, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr("graph.fast.stream_grounded_answer", stream)
    monkeypatch.setattr("graph.fast.complete", fake_complete)
    monkeypatch.setattr("graph.chat_title.complete", fake_complete)
    monkeypatch.setattr("retrieval.cache.embed_batch", fake_embed)
    return title_calls


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(
        *,
        litellm_model: str,
        question: str,
        contexts: list[object],
        history: list[tuple[str, str]],
        metadata: dict[str, str],
    ) -> AsyncIterator[str]:
        for token in TOKENS:
            await asyncio.sleep(0.03)
            yield token

    _patch_fast_seams(monkeypatch, fake_stream)


@pytest.fixture
def fake_llm_slow(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(
        *,
        litellm_model: str,
        question: str,
        contexts: list[object],
        history: list[tuple[str, str]],
        metadata: dict[str, str],
    ) -> AsyncIterator[str]:
        yield "Hello"
        await asyncio.sleep(0.06)  # past the 50 ms coalesce window, forces a flush
        yield " "
        await asyncio.Event().wait()  # holds until the cancel task cancels it

    _patch_fast_seams(monkeypatch, fake_stream)


async def _parse_sse(
    lines: AsyncIterator[str],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield (event_type, data_dict) from an SSE byte stream."""
    event_name: str | None = None
    async for line in lines:
        text_line = line.rstrip("\n")
        if text_line.startswith("event: "):
            event_name = text_line.removeprefix("event: ")
        elif text_line.startswith("data: ") and event_name is not None:
            yield event_name, json.loads(text_line.removeprefix("data: "))
            event_name = None


async def test_chat_crud_and_model_persistence(client: AsyncClient) -> None:
    headers = await _auth(client)
    collection = await client.post(
        "/collections", json={"name": "Scoped corpus"}, headers=headers
    )
    assert collection.status_code == 201, collection.text
    collection_id = collection.json()["id"]

    created = await client.post(
        "/chats", json={"title": "First", "collection_ids": [collection_id]}, headers=headers
    )
    chat_id = created.json()["id"]
    assert created.json()["title"] == "First"
    assert created.json()["collection_ids"] == [collection_id]
    # generator role default
    assert created.json()["model_id"] == "openai/gpt-4o-mini"

    patched = await client.patch(
        f"/chats/{chat_id}",
        json={"model_id": "anthropic/claude-haiku-4.5", "collection_ids": []},
        headers=headers,
    )
    assert patched.json()["model_id"] == "anthropic/claude-haiku-4.5"
    assert patched.json()["collection_ids"] == []

    listed = await client.get("/chats", headers=headers)
    assert [c["id"] for c in listed.json()] == [chat_id]
    assert listed.json()[0]["model_id"] == "anthropic/claude-haiku-4.5"
    assert listed.json()[0]["collection_ids"] == []

    deleted = await client.delete(f"/chats/{chat_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/chats", headers=headers)).json() == []


async def test_model_picker_endpoints(client: AsyncClient) -> None:
    headers = await _auth(client)
    models = await client.get("/models", headers=headers)
    assert models.status_code == 200
    assert [m["model_id"] for m in models.json()] == [
        "anthropic/claude-haiku-4.5",
        "openai/gpt-4o-mini",
    ]
    roles = await client.get("/model-roles", headers=headers)
    assert {r["role"] for r in roles.json()} >= {"generator", "small", "planner", "rewriter"}


async def test_chats_are_isolated_per_user(client: AsyncClient) -> None:
    a = await _auth(client, "a@test.dev")
    b = await _auth(client, "b@test.dev")
    chat_id = await _make_chat(client, a)

    assert (await client.get(f"/chats/{chat_id}", headers=b)).status_code == 404
    assert (
        await client.get(f"/chats/{chat_id}/messages", headers=b)
    ).status_code == 404
    run = await client.post(
        f"/chats/{chat_id}/runs", json={"message": "hi"}, headers=b
    )
    assert run.status_code == 404


async def test_run_streams_to_completion_and_saves_message(
    client: AsyncClient, fake_llm: None
) -> None:
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)

    started = await client.post(
        f"/chats/{chat_id}/runs", json={"message": "say hi"}, headers=headers
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]
    message_id = started.json()["message_id"]

    seen: list[str] = []
    async with client.stream(
        "GET", f"/runs/{run_id}/stream", headers=headers
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for event_type, data in _parse_sse(response.aiter_lines()):
            seen.append(event_type)
            if event_type == "answer.delta":
                assert isinstance(data["text"], str)
            if event_type == "run.completed":
                break
    assert seen[0] == "run.started"
    assert seen[1] == "retrieval"  # Fast mode: retrieval event precedes deltas
    assert "answer.delta" in seen
    assert "metrics" in seen
    assert seen[-1] == "run.completed"

    messages = (await client.get(f"/chats/{chat_id}/messages", headers=headers)).json()
    assistant = messages[-1]
    assert assistant["id"] == message_id
    assert assistant["content"] == FULL
    assert assistant["status"] == "complete"
    assert messages[-2]["role"] == "user"


async def test_first_run_sets_instant_title_then_refines(
    client: AsyncClient, fake_llm: None
) -> None:
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)

    question = (
        "  Explain   adaptive retrieval with citations and reviewer confidence "
        "scoring please  "
    )
    started = await client.post(
        f"/chats/{chat_id}/runs", json={"message": question}, headers=headers
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]

    instant = (await client.get(f"/chats/{chat_id}", headers=headers)).json()["title"]
    assert instant == "Explain adaptive retrieval with citations and reviewer…"

    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        async for event_type, _data in _parse_sse(response.aiter_lines()):
            if event_type == "run.completed":
                break

    chat = (await client.get(f"/chats/{chat_id}", headers=headers)).json()
    assert chat["title"] == "Greeting The World"


async def test_refined_title_does_not_overwrite_user_rename(
    client: AsyncClient, fake_llm: None
) -> None:
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)

    started = await client.post(
        f"/chats/{chat_id}/runs", json={"message": "What is RRF?"}, headers=headers
    )
    run_id = started.json()["run_id"]
    renamed = await client.patch(
        f"/chats/{chat_id}", json={"title": "My saved title"}, headers=headers
    )
    assert renamed.status_code == 200, renamed.text

    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        async for event_type, _data in _parse_sse(response.aiter_lines()):
            if event_type == "run.completed":
                break

    chat = (await client.get(f"/chats/{chat_id}", headers=headers)).json()
    assert chat["title"] == "My saved title"


async def test_title_llm_failure_keeps_instant_title(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_stream(
        *,
        litellm_model: str,
        question: str,
        contexts: list[object],
        history: list[tuple[str, str]],
        metadata: dict[str, str],
    ) -> AsyncIterator[str]:
        yield "Hello"

    _patch_fast_seams(monkeypatch, fake_stream, title_response="not json")
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)

    started = await client.post(
        f"/chats/{chat_id}/runs", json={"message": "What is hybrid search?"}, headers=headers
    )
    run_id = started.json()["run_id"]
    instant = (await client.get(f"/chats/{chat_id}", headers=headers)).json()["title"]

    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        async for event_type, _data in _parse_sse(response.aiter_lines()):
            if event_type == "run.completed":
                break

    chat = (await client.get(f"/chats/{chat_id}", headers=headers)).json()
    assert chat["title"] == instant


async def test_title_usage_lands_before_metrics_and_settle(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_stream(
        *,
        litellm_model: str,
        question: str,
        contexts: list[object],
        history: list[tuple[str, str]],
        metadata: dict[str, str],
    ) -> AsyncIterator[str]:
        yield "Hello"

    title_calls = _patch_fast_seams(monkeypatch, fake_stream)
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)
    run_id = (
        await client.post(f"/chats/{chat_id}/runs", json={"message": "hi"}, headers=headers)
    ).json()["run_id"]

    metrics: dict[str, Any] | None = None
    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        async for event_type, data in _parse_sse(response.aiter_lines()):
            if event_type == "metrics":
                metrics = data
            if event_type == "run.completed":
                break

    assert metrics is not None
    assert title_calls == ["titler"]
    assert metrics["tokens_in"] >= 7
    assert metrics["tokens_out"] >= 3

    async with get_session_factory()() as session:
        chat = (await session.get(Chat, UUID(chat_id)))
        assert chat is not None
        assert chat.title == "Greeting The World"


async def test_run_cancel_mid_stream_saves_partial_text(
    client: AsyncClient, fake_llm_slow: None
) -> None:
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)

    started = await client.post(
        f"/chats/{chat_id}/runs", json={"message": "say hi"}, headers=headers
    )
    run_id = started.json()["run_id"]
    message_id = started.json()["message_id"]

    final_types: list[str] = []
    async with client.stream(
        "GET", f"/runs/{run_id}/stream", headers=headers
    ) as response:
        async for event_type, _data in _parse_sse(response.aiter_lines()):
            final_types.append(event_type)
            if event_type == "answer.delta":
                cancel = await client.post(f"/runs/{run_id}/cancel", headers=headers)
                assert cancel.status_code == 200
            if event_type == "run.cancelled":
                break

    assert "run.cancelled" in final_types
    assert "run.completed" not in final_types

    await asyncio.sleep(0.1)
    messages = (await client.get(f"/chats/{chat_id}/messages", headers=headers)).json()
    assistant = messages[-1]
    assert assistant["id"] == message_id
    assert assistant["status"] == "cancelled"
    assert assistant["content"] == "Hello "


async def test_cancel_finalize_preserves_persisted_partial_text(db: AsyncSession) -> None:
    run_id, message_id = await make_run_row(db)
    message = await db.get(Message, message_id)
    assert message is not None
    message.content = "Hello "
    await db.commit()

    await _finalize(
        get_session_factory(),
        run_id,
        message_id,
        status="cancelled",
        text="",
    )

    db.expire_all()
    saved = await db.get(Message, message_id)
    assert saved is not None
    assert saved.status == "cancelled"
    assert saved.content == "Hello "


async def test_stream_replay_after_completion(client: AsyncClient, fake_llm: None) -> None:
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)
    run_id = (
        await client.post(f"/chats/{chat_id}/runs", json={"message": "hi"}, headers=headers)
    ).json()["run_id"]

    first_pass: list[dict[str, Any]] = []
    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        async for event_type, data in _parse_sse(response.aiter_lines()):
            first_pass.append({"type": event_type, **data})
            if event_type == "run.completed":
                break

    replayed: list[dict[str, Any]] = []
    async with client.stream(
        "GET", f"/runs/{run_id}/stream?after_seq=0", headers=headers
    ) as response:
        async for event_type, data in _parse_sse(response.aiter_lines()):
            replayed.append({"type": event_type, **data})
            if event_type == "run.completed":
                break

    assert [e["seq"] for e in replayed] == [e["seq"] for e in first_pass]
    assert "".join(
        e["text"] for e in replayed if e["type"] == "answer.delta"
    ) == FULL


async def test_active_run_id_surfaces_on_chat(client: AsyncClient, fake_llm: None) -> None:
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)
    run_id = (
        await client.post(f"/chats/{chat_id}/runs", json={"message": "hi"}, headers=headers)
    ).json()["run_id"]

    chat = (await client.get(f"/chats/{chat_id}", headers=headers)).json()
    assert chat["active_run_id"] == run_id

    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        async for event_type, _ in _parse_sse(response.aiter_lines()):
            if event_type == "run.completed":
                break
    await asyncio.sleep(0.05)
    chat_after = (await client.get(f"/chats/{chat_id}", headers=headers)).json()
    assert chat_after["active_run_id"] is None
