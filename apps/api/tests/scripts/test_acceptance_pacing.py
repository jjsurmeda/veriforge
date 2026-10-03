"""The acceptance runner's inter-item pacing is opt-in (--pace SECONDS).

The 65 s sleep exists for free-model rate limits (OpenRouter free tier:
20 req/min account-wide). Every role is on paid gpt-4o-mini now, so the
default run must not sleep at all; these pin the wiring — a fake sleeper
and a fake HTTP surface, no network — for default (no sleep) and --pace N
(sleeps N between eligible items), including the skip rules: never after
a smalltalk item and never after the last item.
"""

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from scripts import acceptance

PacedRun = Callable[..., Awaitable[list[float]]]


class Sleeper:
    """Stands in for asyncio.sleep and records the seconds it was asked for."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload)


class _FakeAsyncClient:
    """Same surface run() touches: async context manager, login, POST /chats."""

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def post(self, url: str, **_kwargs: Any) -> _FakeResponse:
        if url == "/auth/login":
            return _FakeResponse({"access_token": "token"})
        return _FakeResponse({"id": "chat-1"})


def _smalltalk_item(item_id: str) -> dict[str, Any]:
    return {"id": item_id, "expect": "smalltalk", "turns": ["Hello there, how are you?"]}


def _answer_item(item_id: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "expect": "answer",
        "cite": ["Book"],
        "mention": ["Rocinante"],
        "turns": ["Who is Rocinante?"],
    }


def _result_for(item: dict[str, Any]) -> dict[str, Any]:
    if item["expect"] == "smalltalk":
        return {
            "answer": "Hello! How can I help?",
            "status": "completed",
            "message_status": "complete",
            "citations": [],
        }
    return {
        "answer": "Rocinante is Don Quijote's horse [1].",
        "status": "completed",
        "message_status": "complete",
        "citations": ["[1] Book p.3"],
    }


@pytest.fixture
def paced_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> PacedRun:
    """Wire run() to a three-item local dataset and fakes, return a runner.

    Items are [smalltalk, answer, answer]: with pacing on, the smalltalk
    item suppresses the 1-2 sleep, so exactly one sleep lands after item 2
    and none after the last.
    """
    items = [_smalltalk_item("st1"), _answer_item("a1"), _answer_item("a2")]
    set_file = tmp_path / "books.json"
    set_file.write_text(json.dumps({"items": items}))

    async def sign_in(_client: Any, _email: str, _password: str) -> str:
        return "token"

    async def run_turn(_client: Any, _token: str, _chat_id: str, turn: str) -> dict[str, Any]:
        # One result per (single-turn) item, looked up by the question text.
        item = next(i for i in items if i["turns"] == [turn])
        return _result_for(item)

    # The eval-user sign-in is KI-24 and has its own tests
    # (test_acceptance_eval_user.py); pacing is not where it belongs.
    async def eval_sign_in(_client: Any) -> tuple[str, str]:
        return "evals@example.com", "EvalUser!234"

    monkeypatch.setattr(acceptance, "eval_sign_in", eval_sign_in)

    monkeypatch.setattr(acceptance, "SET_FILE", set_file)
    monkeypatch.setattr(acceptance, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(acceptance.smoke_chat, "run_turn", run_turn)
    monkeypatch.setattr(
        acceptance, "httpx", SimpleNamespace(AsyncClient=_FakeAsyncClient, Timeout=httpx.Timeout)
    )

    async def run(**kwargs: Any) -> list[float]:
        sleeper = Sleeper()
        await acceptance.run(sleep=sleeper, **kwargs)
        return sleeper.calls

    return run


async def test_the_default_run_performs_no_inter_item_sleep(paced_run: PacedRun) -> None:
    """Pacing is opt-in: pace defaults to 0 and the sleeper is never awaited."""
    assert await paced_run() == []


async def test_pace_n_sleeps_n_seconds_between_eligible_items(paced_run: PacedRun) -> None:
    """--pace N reaches the sleeper verbatim: the smalltalk item suppresses
    the 1-2 sleep, so only the one after the middle answer runs."""
    assert await paced_run(pace=7) == [7.0]


async def test_pace_skips_after_smalltalk_items_and_after_the_last_item(
    paced_run: PacedRun,
) -> None:
    """The skip rules are unchanged from the always-on version: filtered to
    the two answers, exactly one sleep (never after the last item)."""
    assert await paced_run(pace=65, only=["a1", "a2"]) == [65.0]


async def test_a_fractional_pace_is_passed_through(paced_run: PacedRun) -> None:
    """Seconds may be fractional; the value is not rounded away."""
    assert await paced_run(pace=0.5) == [0.5]
