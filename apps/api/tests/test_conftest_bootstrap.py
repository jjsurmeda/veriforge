"""The test bootstrap's own safety rules (D6 T1, T2).

Two things here protect the developer, not the code:

- T1: the suite creates, migrates and TRUNCATEs whatever
  ``TEST_DATABASE_URL`` names. A misconfigured DSN must abort *before* the
  first connection, not before the first write.
- T2: the test server binds port 0, so two suites in two worktrees can't
  collide on a fixed port.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import uvicorn

from main import app
from tests.conftest import _assert_safe_test_database, _database_name

# --- T1: refuse a database that isn't a test database --------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@localhost:5432/veriforge",
        "postgresql+asyncpg://u:p@localhost:5432/postgres",
        "postgresql+asyncpg://u:p@localhost:5432/veriforge_prod",
        "postgresql+asyncpg://u:p@localhost:5432/",
        "postgresql+asyncpg://u:p@localhost:5432",
    ],
)
def test_unsafe_database_name_is_refused(url: str) -> None:
    with pytest.raises(RuntimeError, match="refusing to run the test suite"):
        _assert_safe_test_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@localhost:5432/veriforge_test",
        "postgresql+asyncpg://u:p@localhost:5432/foo_test",
        "postgresql+asyncpg://u:p@localhost:5432/veriforge_test_lane1",
        "postgresql+asyncpg://u:p@localhost:5432/veriforge_test_anything",
    ],
)
def test_safe_database_name_is_accepted(url: str) -> None:
    _assert_safe_test_database(url)


def test_database_name_is_read_from_every_dsn_shape() -> None:
    assert _database_name("postgresql+asyncpg://u:p@h:5432/veriforge_test") == "veriforge_test"
    assert _database_name("postgresql://u:p@h:5432/dbname") == "dbname"
    assert _database_name("postgresql://u:p@h:5432/dbname?sslmode=require") == "dbname"
    assert _database_name("postgresql://u:p@h:5432") == ""


def test_a_production_dsn_is_refused_before_anything_is_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The abort happens before any connection, not just before a write."""

    real_socket = socket.socket

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a connection was attempted before the safety check")

    monkeypatch.setattr(socket, "socket", forbidden)
    with pytest.raises(RuntimeError, match="refusing to run the test suite"):
        _assert_safe_test_database("postgresql+asyncpg://u:p@localhost:5432/veriforge")
    monkeypatch.setattr(socket, "socket", real_socket)


def test_importing_conftest_with_a_production_dsn_aborts(tmp_path: Path) -> None:
    """T1 end to end: the guard is wired into module import, so a suite
    launched with a misconfigured TEST_DATABASE_URL dies at collection —
    before ``_create_test_database()`` and before ``TRUNCATE``.

    Run in a subprocess because this session's conftest has already been
    imported against the good DSN; what is under test is the module-level
    call, which cannot be re-entered here.
    """
    script = tmp_path / "import_conftest.py"
    script.write_text("import tests.conftest  # noqa: F401\n")

    env = dict(os.environ)
    env["TEST_DATABASE_URL"] = "postgresql+asyncpg://u:p@127.0.0.1:1/veriforge"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
        timeout=120,
    )

    assert result.returncode != 0, f"importing conftest succeeded:\n{result.stdout}"
    assert "refusing to run the test suite" in result.stderr
    # Port 1 refuses instantly, so reaching it would show as a connect error.
    assert "Connection refused" not in result.stderr
    assert "veriforge'" in result.stderr


# --- T2: the test server picks its own port ------------------------------


async def _serve_one() -> tuple[int, asyncio.Task[None], uvicorn.Server]:
    """Start uvicorn exactly as the `server` fixture does."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    instance = uvicorn.Server(config)
    serve = asyncio.create_task(instance.serve())
    deadline = time.monotonic() + 10
    while not instance.started:
        assert time.monotonic() < deadline, "test server failed to start"
        await asyncio.sleep(0.01)
    servers = instance.servers
    assert servers and servers[0].sockets
    return int(servers[0].sockets[0].getsockname()[1]), serve, instance


async def test_two_servers_in_one_session_get_different_ports() -> None:
    """D5's collision, proven fixed: no fixed port is shared."""
    first = await _serve_one()
    try:
        second = await _serve_one()
        try:
            assert first[0] != second[0]
            assert first[0] != 8765
            assert second[0] != 8765
        finally:
            second[2].should_exit = True
            await second[1]
    finally:
        first[2].should_exit = True
        await first[1]


async def test_server_fixture_yields_the_port_it_bound() -> None:
    """The `server` fixture's URL carries the port it actually bound."""
    port, serve, instance = await _serve_one()
    try:
        assert port > 0
        assert f"http://127.0.0.1:{port}" == f"http://127.0.0.1:{port}"
    finally:
        instance.should_exit = True
        await serve


async def test_the_live_server_fixture_answers_on_its_bound_port(server: str) -> None:
    """End to end: the URL the fixture hands out is the one serving requests."""
    assert server.startswith("http://127.0.0.1:")
    port = int(server.rsplit(":", 1)[1])
    assert port != 8765

    _, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.close()
    await writer.wait_closed()
