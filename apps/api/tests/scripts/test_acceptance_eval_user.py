"""Acceptance signs in as the fixed eval account (KI-24), never signs up.

The AW-2000 seed corpus and the counterfactual corpus are `visibility='private'`
collections owned by `evals@example.com`. A private collection is in scope
only for its owner, so a throwaway signup cannot see the corpus it is being
scored against — which is precisely the leak KI-24 recorded: the fixture was
reachable by every user because it sat in Shared. Acceptance therefore
authenticates as that account. The books stay `visibility='shared'`, so the
demo library a real user sees is unchanged.

These pin the wiring against a fake HTTP surface, no network and no database:
no signup happens, the credential comes from `EVAL_USER_EMAIL` /
`EVAL_USER_PASSWORD`, a missing or rejected credential stops the run before the
first turn, no admin endpoint is touched at all any more, and each item still
gets its own fresh chat.

Seed side (tests/scripts/test_seed_eval_user.py) covers the plan assignment,
which is now done once by `make seed-eval-user` rather than per run.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts import acceptance

RUN_USER_ID = "44444444-4444-4444-4444-444444444444"
EVAL_EMAIL = "evals@example.com"
EVAL_PASSWORD = "EvalUser!234"


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload)


class FakeClient:
    """Records every call so the test can assert on method, path and body."""

    def __init__(self, *, login_status: int = 200) -> None:
        self.login_status = login_status
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.timeline: list[str] = []
        self.chats: list[dict[str, Any] | None] = []

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    def _record(self, method: str, url: str, body: dict[str, Any] | None) -> None:
        self.calls.append((method, url, body))
        self.timeline.append(f"{method} {url}")

    async def post(self, url: str, **kwargs: Any) -> _Response:
        body = kwargs.get("json")
        self._record("POST", url, body)
        if url == "/auth/signup":
            raise AssertionError("acceptance must not sign up a throwaway user any more")
        if url == "/auth/login":
            if self.login_status != 200:
                return _Response(self.login_status, {"detail": "bad credentials"})
            email = (body or {}).get("email")
            if email != EVAL_EMAIL:
                return _Response(401, {"detail": "bad credentials"})
            return _Response(200, {"access_token": "eval-token"})
        if url == "/chats":
            self.chats.append(body)
            return _Response(200, {"id": f"chat-{len(self.chats)}"})
        raise AssertionError(f"unexpected POST {url}")

    async def get(self, url: str, **kwargs: Any) -> _Response:
        raise AssertionError(f"acceptance must not GET anything, got {url}")

    async def patch(self, url: str, **kwargs: Any) -> _Response:
        raise AssertionError(f"acceptance must not PATCH anything, got {url}")


@pytest.fixture
def eval_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_USER_EMAIL", EVAL_EMAIL)
    monkeypatch.setenv("EVAL_USER_PASSWORD", EVAL_PASSWORD)


@pytest.fixture
def wired_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """A two-item dataset plus a FakeClient, so run() can be driven offline."""
    items = [
        {
            "id": "a1",
            "expect": "answer",
            "cite": ["Book"],
            "mention": ["Rocinante"],
            "turns": ["Who is Rocinante?"],
        },
        {
            "id": "a2",
            "expect": "answer",
            "cite": ["Book"],
            "mention": ["Rocinante"],
            "turns": ["And who rides Rocinante?"],
        },
    ]
    set_file = tmp_path / "books.json"
    set_file.write_text(json.dumps({"items": items}))
    client = FakeClient()

    async def run_turn(_c: Any, _t: str, chat: str, _turn: str) -> dict[str, Any]:
        client.timeline.append(f"run_turn {chat}")
        return {
            "answer": "Rocinante is Don Quijote's horse [1].",
            "status": "completed",
            "message_status": "complete",
            "citations": ["[1] Book p.3"],
        }

    monkeypatch.setattr(acceptance, "SET_FILE", set_file)
    monkeypatch.setattr(acceptance, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(acceptance.smoke_chat, "run_turn", run_turn)
    fake_httpx = type("H", (), {"AsyncClient": lambda **_kw: client, "Timeout": httpx.Timeout})
    monkeypatch.setattr(acceptance, "httpx", fake_httpx)
    return {"client": client, "items": items}


async def test_the_run_signs_in_as_the_eval_account_and_never_signs_up(
    wired_run: dict[str, Any], eval_env: None
) -> None:
    client: FakeClient = wired_run["client"]
    await acceptance.run()
    logins = [b for m, url, b in client.calls if url == "/auth/login" and b is not None]
    assert logins, "acceptance must authenticate"
    assert {b["email"] for b in logins} == {EVAL_EMAIL}
    assert all(b["password"] == EVAL_PASSWORD for b in logins)
    assert not [url for _, url, _ in client.calls if url == "/auth/signup"]


async def test_the_password_is_re_read_for_every_token(
    wired_run: dict[str, Any], eval_env: None
) -> None:
    """The access token is a 15-minute TTL and a full run outlives it."""
    client: FakeClient = wired_run["client"]
    await acceptance.run()
    logins = [b for m, url, b in client.calls if url == "/auth/login" and b is not None]
    assert len(logins) >= 3, f"expected a login per chat and per turn, got {len(logins)}"


async def test_each_item_still_gets_a_fresh_chat(wired_run: dict[str, Any], eval_env: None) -> None:
    """Only the identity persists. A shared chat would leak context between items."""
    client: FakeClient = wired_run["client"]
    await acceptance.run()
    created = [t for t in client.timeline if t == "POST /chats"]
    ran = [t for t in client.timeline if t.startswith("run_turn")]
    assert len(created) == 2, client.timeline
    assert ran == ["run_turn chat-1", "run_turn chat-2"], client.timeline


async def test_no_admin_endpoint_is_touched(wired_run: dict[str, Any], eval_env: None) -> None:
    """The plan is assigned once by `make seed-eval-user`, not per run."""
    client: FakeClient = wired_run["client"]
    await acceptance.run()
    assert not [url for _, url, _ in client.calls if url.startswith("/admin")]


async def test_a_missing_eval_credential_stops_the_run_before_the_first_turn(
    wired_run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVAL_USER_EMAIL", raising=False)
    monkeypatch.delenv("EVAL_USER_PASSWORD", raising=False)
    client: FakeClient = wired_run["client"]
    with pytest.raises(SystemExit) as excinfo:
        await acceptance.run()
    assert "EVAL_USER_EMAIL" in str(excinfo.value)
    assert not [t for t in client.timeline if t.startswith("run_turn")]


async def test_a_rejected_eval_login_stops_the_run(
    wired_run: dict[str, Any], eval_env: None
) -> None:
    client: FakeClient = wired_run["client"]
    client.login_status = 401
    with pytest.raises(SystemExit) as excinfo:
        await acceptance.run()
    assert "seed-eval-user" in str(excinfo.value)
    assert not [t for t in client.timeline if t.startswith("run_turn")]


async def test_a_wrong_email_is_not_a_credential(
    wired_run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointing EVAL_USER_EMAIL elsewhere must fail, not silently score nothing."""
    monkeypatch.setenv("EVAL_USER_EMAIL", "someone-else@example.com")
    client: FakeClient = wired_run["client"]
    with pytest.raises(SystemExit):
        await acceptance.run()
    assert not [t for t in client.timeline if t.startswith("run_turn")]
