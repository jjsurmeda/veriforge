"""`/healthz` names the commit this process is serving.

`make acceptance` talks to a running api, and the dev api is a hot-reloading
process off whatever checkout started it — so an acceptance run on a worktree can
be scored against the main checkout's code with nothing looking wrong. These pin
the field that makes it visible, and its `unknown` fallback: a run that cannot
name its commit has to say so rather than look fine.
"""

import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from build_info import UNKNOWN, served_commit
from db.session import get_session
from main import app


async def _override_session_ok() -> AsyncIterator[AsyncSession]:
    """The same stub test_health.py uses: /healthz only needs SELECT 1 to work."""
    session = AsyncMock(spec=AsyncSession)
    yield session


def test_healthz_reports_the_served_commit() -> None:
    app.dependency_overrides[get_session] = _override_session_ok
    try:
        client = TestClient(app)
        body = client.get("/healthz").json()
        assert body["served_commit"] == served_commit()
    finally:
        app.dependency_overrides.clear()


def test_served_commit_is_this_checkouts_head() -> None:
    """The honest value: read from the repository this code was loaded from."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[3],
    ).stdout.strip()

    assert served_commit() == head


def test_served_commit_is_cached_because_the_answer_cannot_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-reading git per request would report the checkout's *current* HEAD
    rather than the commit the code was loaded from, which is the value that has
    to be checked: a hot-reloading dev api is exactly that case."""
    calls: list[object] = []

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(1)
        return subprocess.CompletedProcess([], 0, stdout="e" * 40 + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    served_commit.cache_clear()

    try:
        assert served_commit() == "e" * 40
        assert served_commit() == "e" * 40
        assert len(calls) == 1
    finally:
        served_commit.cache_clear()


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        (subprocess.CompletedProcess([], 0, stdout="f" * 40 + "\n", stderr=""), "f" * 40),
        # A non-zero exit with no sha is not a commit, and reporting the empty
        # string would make the step's comparison read as "matches nothing".
        (subprocess.CompletedProcess([], 128, stdout="", stderr="not a repo"), UNKNOWN),
        (subprocess.CompletedProcess([], 0, stdout="   \n", stderr=""), UNKNOWN),
    ],
)
def test_served_commit_falls_back_to_unknown(
    monkeypatch: pytest.MonkeyPatch,
    completed: subprocess.CompletedProcess[str],
    expected: str,
) -> None:
    """An image built without a checkout has no commit to report. `unknown` is
    deliberately not a silent pass: the step compares it with HEAD and fails."""
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: completed)
    served_commit.cache_clear()

    try:
        assert served_commit() == expected
    finally:
        served_commit.cache_clear()


def test_served_commit_is_unknown_when_git_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    served_commit.cache_clear()

    try:
        assert served_commit() == UNKNOWN
    finally:
        served_commit.cache_clear()


def test_served_commit_is_unknown_when_git_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung `git` must not hang a health check."""
    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(subprocess, "run", timeout)
    served_commit.cache_clear()

    try:
        assert served_commit() == UNKNOWN
    finally:
        served_commit.cache_clear()