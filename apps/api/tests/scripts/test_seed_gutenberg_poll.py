"""The Gutenberg seeder re-authenticates when its access token expires.

On 2026-10-12 the books poll died mid-ingest with `KeyError: 'status'` — the
response to `GET /documents/{id}` was a 401 error body, which has no `status`
field. The KeyError was the symptom and the expired 15-minute JWT the cause: a
cold eleven-book ingest runs longer than one token's life.

These pin the recovery, and the part that matters more — that an unexpected
response is *named* rather than unwrapped into a KeyError, because "http 401"
in the operator's log is the difference between a one-line fix and an afternoon.
"""

import json
from typing import Any, cast

import httpx
import pytest

from scripts import seed_gutenberg


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    """A live ingest, with expiry on chosen requests.

    `expire_on` names the 1-based GET numbers that answer 401 — by position
    rather than by token, because a token that expires is one the seeder
    obtained *earlier*: the token issued by the refresh works, and it is the
    next poll round that finds it stale. Expiring by name would also expire the
    retry, which is not a thing that happens.
    """

    def __init__(self, statuses: list[str], *, expire_on: frozenset[int] = frozenset()) -> None:
        self._statuses = statuses
        self._expire_on = expire_on
        self.calls: list[str] = []
        self.logins = 0

    async def get(self, url: str, *, headers: dict[str, str], **_kwargs: Any) -> _Response:
        self.calls.append(headers["Authorization"].removeprefix("Bearer "))
        if len(self.calls) in self._expire_on:
            return _Response(401, {"error_code": "unauthorized", "message": "Invalid token"})
        return _Response(200, {"status": self._statuses.pop(0)})

    async def post(self, url: str, **_kwargs: Any) -> _Response:
        assert url == "/auth/login"
        self.logins += 1
        return _Response(200, {"access_token": f"token-{self.logins}"})


async def _poll(client: _Client, token: str, books: dict[str, str]) -> None:
    """`poll_until_ready` with the fake client, so the call sites stay readable.

    The cast is here rather than at each call: the fixture implements the three
    methods `poll_until_ready` uses and nothing else, which is the point.
    """
    await seed_gutenberg.poll_until_ready(cast(httpx.AsyncClient, client), token, books)


@pytest.fixture(autouse=True)
def short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real waiting: the poll's own timeout is minutes."""
    monkeypatch.setattr(seed_gutenberg, "READY_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(seed_gutenberg, "POLL_SECONDS", 0.0)
    monkeypatch.setenv("GUTENBERG_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("GUTENBERG_ADMIN_PASSWORD", "pw")


async def test_an_expired_token_is_refreshed_and_the_poll_finishes() -> None:
    client = _Client(["ready"], expire_on=frozenset({1}))

    await _poll(client, "old-token", {"Pride and Prejudice": "doc-1"})

    assert client.logins == 1
    assert client.calls == ["old-token", "token-1"]


async def test_the_refreshed_token_is_reused_for_the_remaining_books() -> None:
    """One refresh, not one per document: the books are polled in a loop, and a
    login per document would spend the login rate limit (10/60s) on itself."""
    client = _Client(["ready", "ready", "ready"], expire_on=frozenset({1}))

    await _poll(
        client,
        "old-token",
        {"Pride and Prejudice": "doc-1", "Frankenstein": "doc-2", "Noli": "doc-3"},
    )

    assert client.logins == 1


async def test_a_second_expiry_mid_poll_refreshes_again() -> None:
    """The refresh is a loop invariant, not a one-shot: a run long enough to
    outlive two tokens recovers twice. Three books; the first and the third
    request each land on an expired token."""
    client = _Client(["ready", "ready", "ready"], expire_on=frozenset({1, 4}))

    await _poll(
        client,
        "old-token",
        {"Pride and Prejudice": "doc-1", "Frankenstein": "doc-2", "Noli": "doc-3"},
    )

    assert client.logins == 2
    # Each 401 is answered with a retry under the new token, so the refresh is
    # not a silent re-send of the whole batch: every call after the first is
    # authorised, and the run ends on the most recent token.
    assert client.calls[0] == "old-token"
    assert client.calls[-1] == "token-2"
    assert client.calls.count("old-token") == 1


async def test_an_unexpected_response_is_named_not_unwrapped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-401 error body must not raise a KeyError on `status`. The operator
    sees what the server actually said."""
    class _BrokenClient(_Client):
        async def get(self, url: str, *, headers: dict[str, str], **_kwargs: Any) -> _Response:
            self.calls.append(headers["Authorization"])
            return _Response(500, {"error_code": "internal_error", "message": "boom"})

    client = _BrokenClient([])

    await _poll(client, "token", {"Pride and Prejudice": "doc-1"})

    assert "http 500" in capsys.readouterr().out


async def test_a_failed_document_stops_being_polled() -> None:
    """`failed` is terminal: polling it forever would hold the seeding open for
    `READY_TIMEOUT_SECONDS` on a book that will never be ready."""
    client = _Client(["failed"])

    await _poll(client, "token", {"Pride and Prejudice": "doc-1"})

    assert len(client.calls) == 1