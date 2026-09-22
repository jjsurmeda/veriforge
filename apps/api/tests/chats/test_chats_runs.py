"""Chat CRUD ownership, run creation, SSE stream, cancel/partial-save (CH-6),
replay after reconnect (TRD §12)."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient

TOKENS = ["Hello", " ", "world", "!", "!", "!"]
FULL = "".join(TOKENS)


async def _auth(client: AsyncClient, email: str = "owner@test.dev") -> dict[str, str]:
    signup = await client.post("/auth/signup", json={"email": email, "password": "password123"})
    body = signup.json()
    return {"Authorization": f"Bearer {body['access_token']}"}


async def _make_chat(client: AsyncClient, headers: dict[str, str]) -> str:
    chat = await client.post("/chats", json={}, headers=headers)
    assert chat.status_code == 201, chat.text
    return str(chat.json()["id"])


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(
        *,
        litellm_model: str,
        history: list[tuple[str, str]],
        user_message: str,
        metadata: dict[str, str],
    ) -> AsyncIterator[str]:
        for token in TOKENS:
            await asyncio.sleep(0.03)
            yield token

    monkeypatch.setattr("graph.runner.stream_plain_answer", fake_stream)


@pytest.fixture
def fake_llm_slow(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(
        *,
        litellm_model: str,
        history: list[tuple[str, str]],
        user_message: str,
        metadata: dict[str, str],
    ) -> AsyncIterator[str]:
        yield "Hello"
        await asyncio.sleep(0.06)  # past the 50 ms coalesce window, forces a flush
        yield " "
        await asyncio.Event().wait()  # holds until the cancel task cancels it

    monkeypatch.setattr("graph.runner.stream_plain_answer", fake_stream)


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
    created = await client.post("/chats", json={"title": "First"}, headers=headers)
    chat_id = created.json()["id"]
    assert created.json()["title"] == "First"
    # generator role default
    assert created.json()["model_id"] == "openai/gpt-4o-mini"

    patched = await client.patch(
        f"/chats/{chat_id}", json={"model_id": "anthropic/claude-3.5-haiku"}, headers=headers
    )
    assert patched.json()["model_id"] == "anthropic/claude-3.5-haiku"

    listed = await client.get("/chats", headers=headers)
    assert [c["id"] for c in listed.json()] == [chat_id]
    assert listed.json()[0]["model_id"] == "anthropic/claude-3.5-haiku"

    deleted = await client.delete(f"/chats/{chat_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/chats", headers=headers)).json() == []


async def test_model_picker_endpoints(client: AsyncClient) -> None:
    headers = await _auth(client)
    models = await client.get("/models", headers=headers)
    assert models.status_code == 200
    assert [m["model_id"] for m in models.json()] == [
        "anthropic/claude-3.5-haiku",
        "openai/gpt-4o-mini",
    ]
    roles = await client.get("/model-roles", headers=headers)
    assert {r["role"] for r in roles.json()} == {"generator", "small"}


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
    assert "answer.delta" in seen
    assert seen[-1] == "run.completed"

    messages = (await client.get(f"/chats/{chat_id}/messages", headers=headers)).json()
    assistant = messages[-1]
    assert assistant["id"] == message_id
    assert assistant["content"] == FULL
    assert assistant["status"] == "complete"
    assert messages[-2]["role"] == "user"


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
