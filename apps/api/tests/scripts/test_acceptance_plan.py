"""Acceptance assigns its run user to the seeded `internal-eval` plan (KI-20).

A full acceptance run costs ~310k quota credits against `free`'s 200k per 5 h
window, so every run so far raised `credits_5h` in the dev database by hand
and restored it afterwards. The runner now moves its throwaway user through
the admin API instead — the product path, audited — and `free`/`pro` are
never written.

These pin the wiring against a fake HTTP surface, no network and no database:
the assignment happens before the first turn, the plan lookup is by name, a
missing credential stops the run instead of falling back to editing a plan,
and no `free`/`pro` value is ever sent.

Seed side: `internal-eval` is a seeded row (migration 0014), and
`free`/`pro` keep their own limits.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts import acceptance

FREE_ID = "11111111-1111-1111-1111-111111111111"
EVAL_ID = "22222222-2222-2222-2222-222222222222"
PRO_ID = "33333333-3333-3333-3333-333333333333"
RUN_USER_ID = "44444444-4444-4444-4444-444444444444"
ADMIN_USER_ID = "55555555-5555-5555-5555-555555555555"

PLANS = [
    {"id": FREE_ID, "name": "free", "credits_5h": 200000, "credits_month": 2000000},
    {"id": EVAL_ID, "name": "internal-eval", "credits_5h": 20000000, "credits_month": 200000000},
    {"id": PRO_ID, "name": "pro", "credits_5h": 200000, "credits_month": 2000000},
]
RUN_EMAIL = "smoke-run@example.com"
ADMIN_EMAIL = "admin@example.com"


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

    def __init__(self, plans: list[dict[str, Any]] = PLANS) -> None:
        self.plans = plans
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        # One entry per stage of the run, in the order they happened, so the
        # ordering assertions read as a trace rather than an index arithmetic.
        self.timeline: list[str] = []

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    def _record(self, method: str, url: str, body: dict[str, Any] | None) -> None:
        self.calls.append((method, url, body))
        if method in ("PATCH", "GET") or url == "/auth/login":
            self.timeline.append(f"{method} {url}")

    async def post(self, url: str, **kwargs: Any) -> _Response:
        body = kwargs.get("json")
        self._record("POST", url, body)
        if url == "/auth/signup":
            return _Response(201, {"access_token": "run-token"})
        if url == "/auth/login":
            email = (body or {}).get("email")
            return _Response(200 if email == ADMIN_EMAIL else 401, {"access_token": "admin-token"})
        if url == "/chats":
            return _Response(200, {"id": "chat-1"})
        raise AssertionError(f"unexpected POST {url}")

    async def get(self, url: str, **kwargs: Any) -> _Response:
        self._record("GET", url, None)
        if url == "/admin/plans":
            return _Response(200, self.plans)
        if url == "/admin/users":
            return _Response(
                200,
                [
                    {"id": ADMIN_USER_ID, "email": ADMIN_EMAIL},
                    {"id": RUN_USER_ID, "email": RUN_EMAIL},
                ],
            )
        raise AssertionError(f"unexpected GET {url}")

    async def patch(self, url: str, **kwargs: Any) -> _Response:
        body = kwargs.get("json")
        self._record("PATCH", url, body)
        if url == f"/admin/users/{RUN_USER_ID}":
            return _Response(200, {"id": RUN_USER_ID, "email": RUN_EMAIL, **(body or {})})
        raise AssertionError(f"unexpected PATCH {url}")


@pytest.fixture
def admin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", "AdminPass!234")


@pytest.fixture
def wired_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """A one-item dataset plus a FakeClient, so run() can be driven offline."""
    item = {
        "id": "a1",
        "expect": "answer",
        "cite": ["Book"],
        "mention": ["Rocinante"],
        "turns": ["Who is Rocinante?"],
    }
    set_file = tmp_path / "books.json"
    set_file.write_text(json.dumps({"items": [item]}))
    client = FakeClient()

    async def sign_up(_c: Any) -> str:
        return RUN_EMAIL

    async def sign_in(_c: Any, _email: str) -> str:
        return "run-token"

    async def run_turn(_c: Any, _t: str, _chat: str, _turn: str) -> dict[str, Any]:
        # Stands in for the turn that POSTs /chats/{id}/runs, where the quota
        # gate reserves against the user's plan.
        client.timeline.append("run_turn")
        return {
            "answer": "Rocinante is Don Quijote's horse [1].",
            "status": "completed",
            "message_status": "complete",
            "citations": ["[1] Book p.3"],
        }

    monkeypatch.setattr(acceptance, "SET_FILE", set_file)
    monkeypatch.setattr(acceptance, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(acceptance.smoke_chat, "sign_up", sign_up)
    monkeypatch.setattr(acceptance.smoke_chat, "sign_in", sign_in)
    monkeypatch.setattr(acceptance.smoke_chat, "run_turn", run_turn)
    fake_httpx = type("H", (), {"AsyncClient": lambda **_kw: client, "Timeout": httpx.Timeout})
    monkeypatch.setattr(acceptance, "httpx", fake_httpx)
    return {"client": client, "item": item}


async def test_the_plan_is_assigned_before_the_first_turn(
    wired_run: dict[str, Any], admin_env: None
) -> None:
    """Ordering is the point: the quota gate reserves on the first run."""
    client: FakeClient = wired_run["client"]
    await acceptance.run()
    assert client.timeline == [
        "POST /auth/login",
        "GET /admin/plans",
        "GET /admin/users",
        f"PATCH /admin/users/{RUN_USER_ID}",
        "run_turn",
    ]


async def test_the_assignment_targets_the_internal_eval_plan_id(
    wired_run: dict[str, Any], admin_env: None
) -> None:
    client: FakeClient = wired_run["client"]
    await acceptance.run()
    bodies = [b for m, url, b in client.calls if m == "PATCH"]
    assert bodies == [{"plan_id": EVAL_ID}]


async def test_no_plan_is_ever_written_through_the_plans_endpoint(
    wired_run: dict[str, Any], admin_env: None
) -> None:
    """`free` and `pro` are rows real users are on: read them, never patch them."""
    client: FakeClient = wired_run["client"]
    await acceptance.run()
    for method, url, body in client.calls:
        assert "/admin/plans/" not in url, f"{method} {url} {body}"
        assert body is None or "credits_5h" not in body
        assert body is None or "credits_month" not in body


async def test_a_missing_admin_credential_stops_the_run(
    wired_run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No fallback to editing the database, and no first turn."""
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    client: FakeClient = wired_run["client"]
    with pytest.raises(SystemExit) as excinfo:
        await acceptance.run()
    assert "ADMIN_EMAIL" in str(excinfo.value)
    assert "run_turn" not in client.timeline


async def test_a_missing_internal_eval_plan_stops_the_run(
    wired_run: dict[str, Any], admin_env: None
) -> None:
    """A missing seed row must not silently fall back to `free`'s limit."""
    client: FakeClient = wired_run["client"]
    client.plans = [p for p in PLANS if p["name"] != "internal-eval"]
    with pytest.raises(SystemExit) as excinfo:
        await acceptance.run()
    assert "internal-eval" in str(excinfo.value)
    assert "run_turn" not in client.timeline


async def test_a_rejected_admin_login_stops_the_run(
    wired_run: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", "someone-else@example.com")
    client: FakeClient = wired_run["client"]
    with pytest.raises(SystemExit) as excinfo:
        await acceptance.run()
    assert "seed-admin" in str(excinfo.value)
    assert "run_turn" not in client.timeline
