"""The runner reuses its access token instead of logging in per request.

`RATE_LIMIT_LOGIN` is 10 per 60 s per address and this runner used to log in
twice per item — so a 57-item run needed ~115 logins and died on item 5 with a
429, a harness fault that reads as a product failure. The same trap
`probe_generator_latency.py` documents for the latency probe. These pin the
fix where it belongs: one login, refreshed from the token's own `exp`.

No network and no api: a fake client counts logins and records the tokens each
request was sent.
"""

import base64
import json
import time
from typing import Any

import httpx
import pytest

from scripts import acceptance


def _jwt(expires_in: float) -> str:
    """A JWT-shaped string with an `exp` claim. Never verified by anything here."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": time.time() + expires_in}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=None, response=None  # type: ignore[arg-type]
            )

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload)


class CountingClient:
    """Counts logins; hands out a token per login with a 15-minute life."""

    def __init__(self, lifetime: float = 15 * 60) -> None:
        self.lifetime = lifetime
        self.logins = 0
        self.authorized: list[str] = []

    async def __aenter__(self) -> "CountingClient":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def get(self, url: str, **_kwargs: Any) -> _Response:
        return _Response(200, {"status": "ok", "served_commit": "a" * 40})

    async def post(self, url: str, **kwargs: Any) -> _Response:
        if url == "/auth/login":
            self.logins += 1
            return _Response(200, {"access_token": _jwt(self.lifetime)})
        if url == "/chats":
            self.authorized.append(kwargs["headers"]["Authorization"])
            return _Response(200, {"id": f"chat-{len(self.authorized)}"})
        raise AssertionError(f"unexpected POST {url}")


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> dict[str, Any]:
    """Twelve answer items, so a per-request login would be obvious."""
    items = [
        {
            "id": f"a{index}",
            "expect": "answer",
            "cite": ["Book"],
            "mention": ["Rocinante"],
            "turns": ["Who is Rocinante?"],
        }
        for index in range(12)
    ]
    set_file = tmp_path / "books.json"
    set_file.write_text(json.dumps({"items": items}))
    client = CountingClient()

    async def run_turn(
        _c: Any, token: str, _chat: str, _turn: str, *, mode: str = "auto"
    ) -> dict[str, Any]:
        client.authorized.append(f"Bearer {token}")
        return {
            "answer": "Rocinante is Don Quijote's horse [1].",
            "status": "completed",
            "message_status": "complete",
            "citations": ["[1] Book p.3"],
        }

    async def eval_sign_in(_client: Any) -> tuple[str, str]:
        return "evals@example.com", "pw"

    monkeypatch.setattr(acceptance, "eval_sign_in", eval_sign_in)
    monkeypatch.setattr(acceptance, "SET_FILE", set_file)
    monkeypatch.setattr(acceptance, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(acceptance.smoke_chat, "run_turn", run_turn)
    monkeypatch.setattr(
        acceptance,
        "httpx",
        type(
            "H",
            (),
            {
                "AsyncClient": lambda **_kw: client,
                "Timeout": httpx.Timeout,
                "HTTPError": httpx.HTTPError,
            },
        ),
    )
    return {"client": client, "items": items}


async def test_a_twelve_item_run_logs_in_once(wired: dict[str, Any]) -> None:
    """24 authenticated calls (chat + turn per item), 1 login. Per-request
    logins would be 24 and would 429 a real api at item 5."""
    await acceptance.run()

    assert wired["client"].logins == 1


async def test_the_same_token_is_reused_across_items(wired: dict[str, Any]) -> None:
    """Reuse is visible in what was sent, not just in the count."""
    await acceptance.run()

    sent = wired["client"].authorized
    assert len(sent) == 24  # one POST /chats and one turn per item
    assert len(set(sent)) == 1


async def test_a_short_lived_token_is_refreshed_before_it_expires(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A token with 30 s left is inside the refresh margin and gets a new one;
    the point is that expiry, not the item count, drives re-login."""
    items = [{"id": "a0", "expect": "answer", "cite": ["B"], "mention": ["R"], "turns": ["q?"]}]
    set_file = tmp_path / "books.json"
    set_file.write_text(json.dumps({"items": items}))
    client = CountingClient(lifetime=30.0)

    async def run_turn(
        _c: Any, token: str, _chat: str, _turn: str, *, mode: str = "auto"
    ) -> dict[str, Any]:
        client.authorized.append(f"Bearer {token}")
        return {
            "answer": "Rocinante [1].",
            "status": "completed",
            "message_status": "complete",
            "citations": ["[1] B p.1"],
        }

    async def eval_sign_in(_client: Any) -> tuple[str, str]:
        return "evals@example.com", "pw"

    monkeypatch.setattr(acceptance, "eval_sign_in", eval_sign_in)
    monkeypatch.setattr(acceptance, "SET_FILE", set_file)
    monkeypatch.setattr(acceptance, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(acceptance.smoke_chat, "run_turn", run_turn)
    monkeypatch.setattr(
        acceptance,
        "httpx",
        type(
            "H",
            (),
            {
                "AsyncClient": lambda **_kw: client,
                "Timeout": httpx.Timeout,
                "HTTPError": httpx.HTTPError,
            },
        ),
    )

    await acceptance.run()

    # eval_sign_in is stubbed, so the only login is the runner's own: one for
    # the chat, one for the turn, because the 30 s token is inside the margin.
    assert client.logins == 2


def test_a_token_with_a_long_life_is_used_for_its_lifetime() -> None:
    assert acceptance._token_lifetime(_jwt(15 * 60)) > 14 * 60


@pytest.mark.parametrize(
    "token",
    [
        "opaque-token",
        "a.b",
        "a.!!!.c",
        "",
    ],
)
def test_an_unreadable_token_falls_back_to_logging_in_every_time(token: str) -> None:
    """An expiry this code cannot read must never be mistaken for a long-lived
    one: the fallback is the old, slow, correct behaviour."""
    assert acceptance._token_lifetime(token) == acceptance.TOKEN_LIFETIME_FALLBACK_SECONDS


def test_an_expired_token_falls_back_to_logging_in_every_time() -> None:
    """`exp` in the past reads as 0 remaining, not as a negative duration that
    would make the refresh condition true for ever."""
    assert acceptance._token_lifetime(_jwt(-10)) == acceptance.TOKEN_LIFETIME_FALLBACK_SECONDS


def test_the_refresh_margin_is_positive() -> None:
    """A zero margin would let a token expire between the chat and its turn."""
    assert acceptance.TOKEN_REFRESH_MARGIN_SECONDS > 0