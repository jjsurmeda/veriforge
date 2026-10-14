"""Test bootstrap: a real Postgres per session (testing.md — runbus and
anything SQL-adjacent runs against a real database), migrations applied,
tables truncated between tests."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://veriforge:veriforge@localhost:5432/veriforge_test",
)


def _database_name(url: str) -> str:
    """The database name from a DSN, or "" if there isn't one.

    Scheme-relative, so the scheme's own "//" isn't mistaken for the path
    separator: "postgresql://u:p@h:5432" names no database, and neither
    does "postgresql://u:p@h:5432/".
    """
    _, sep, tail = url.partition("://")
    if not sep:
        return ""
    _, _, path = tail.partition("/")
    return path.split("?", 1)[0]


def _assert_safe_test_database(url: str) -> None:
    """Refuse to run the suite against anything but a test database.

    The suite creates the database, migrates it and TRUNCATEs every table
    between tests. If TEST_DATABASE_URL is misconfigured to name anything
    else, that is silent and unrecoverable data loss, so it aborts before
    the first connection rather than before the first write.

    Accepted names end in `_test` (`veriforge_test`, `foo_test`) or start
    with `veriforge_test_` (one database per lane/worktree).
    """
    name = _database_name(url)
    if not name or not (name.endswith("_test") or name.startswith("veriforge_test_")):
        raise RuntimeError(
            f"refusing to run the test suite against database {name!r}: "
            "TEST_DATABASE_URL must name a test database (suffix '_test', "
            "or prefix 'veriforge_test_'). Nothing was created, migrated or "
            "truncated."
        )


# Must land before any app import: module-level engines read it.
_assert_safe_test_database(TEST_DATABASE_URL)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["COOKIE_SECURE"] = "false"  # tests run over plain http
# `signup_mode` defaults to `invite` in the product (item 4: forgetting to
# set it is the failure that leaks the deployment), and the rate limits are
# per-IP in a process that every test in the suite shares. Both are turned
# off here for the same reason the provider keys are blanked below: the
# default is right for production and wrong for a suite, so the suite says
# so explicitly rather than inheriting a surprising one. Tests that exercise
# either set it back per-test.
os.environ["SIGNUP_MODE"] = "open"
for _limit in (
    "RATE_LIMIT_SIGNUP",
    "RATE_LIMIT_LOGIN",
    "RATE_LIMIT_RUN",
):
    os.environ[_limit] = "100000"
os.environ["RATE_LIMIT_RUN_WINDOW_SECONDS"] = "1"
# Never reach live providers from tests (testing.md); .env and Compose
# otherwise leak real keys in, and rerank/web tests hit Cohere/Tavily/Brave.
for _key in (
    "OPENROUTER_API_KEY",
    "COHERE_API_KEY",
    "NVIDIA_API_KEY",
    "TAVILY_API_KEY",
    "BRAVE_API_KEY",
):
    os.environ[_key] = ""

import time  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from httpx import AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from config import get_settings  # noqa: E402
from decisions.breaker import get_breaker  # noqa: E402


def _create_test_database() -> None:
    dsn = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    base, _, dbname = dsn.rpartition("/")

    async def run() -> None:
        conn = await asyncpg.connect(f"{base}/veriforge")
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
            if not exists:
                await conn.execute(f'CREATE DATABASE "{dbname}"')
        finally:
            await conn.close()

    asyncio.run(run())


_create_test_database()
get_settings.cache_clear()
command.upgrade(AlembicConfig("alembic.ini"), "head")

from db.models import (  # noqa: E402
    Base,
    Chat,
    LlmProvider,
    Message,
    Model,
    ModelRole,
    Plan,
    Run,
    User,
)
from db.session import get_session_factory  # noqa: E402
from main import app  # noqa: E402
from runbus.postgres import PostgresRunBus  # noqa: E402

ALL_TABLES = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))

_catalogue: list[tuple[str, int, float, float]] = [
    ("openai/gpt-4o-mini", 128000, 0.15, 0.60),
    ("anthropic/claude-haiku-4.5", 200000, 1.00, 5.00),
    ("typesafe/jev-1.13", 32768, 0.000001, 0.000001),
]


async def seed_base_rows(session: AsyncSession) -> None:
    """plans + catalogue, mirroring migration 0002's seeds."""
    session.add_all(
        [
            Plan(name="free", credits_5h=200000, credits_month=2000000),
            Plan(name="pro", credits_5h=200000, credits_month=2000000),
        ]
    )
    provider = LlmProvider(name="openrouter", kind="openrouter", enabled=True)
    session.add(provider)
    await session.flush()
    for model_id, ctx, price_in, price_out in _catalogue:
        session.add(
            Model(
                provider_id=provider.id,
                model_id=model_id,
                price_in=price_in,
                price_out=price_out,
                context_window=ctx,
                capabilities=(
                    {"decision": True} if model_id == "typesafe/jev-1.13" else {"streaming": True}
                ),
                enabled=True,
            )
        )
    session.add_all(
        [
            ModelRole(
                role="generator",
                model_id="openai/gpt-4o-mini",
                fallback_model_id="anthropic/claude-haiku-4.5",
            ),
            ModelRole(role="small", model_id="anthropic/claude-haiku-4.5"),
            ModelRole(role="planner", model_id="openai/gpt-4o-mini"),
            ModelRole(role="rewriter", model_id="anthropic/claude-haiku-4.5"),
            ModelRole(role="claim_extractor", model_id="anthropic/claude-haiku-4.5"),
            ModelRole(role="suggester", model_id="anthropic/claude-haiku-4.5"),
            ModelRole(role="decision_engine", model_id="typesafe/jev-1.13"),
            ModelRole(role="decision_fallback", model_id="anthropic/claude-haiku-4.5"),
        ]
    )
    await session.commit()


@pytest.fixture(autouse=True)
def reset_default_breaker() -> Iterator[None]:
    get_breaker.cache_clear()
    yield


OPEN_WORK_SQL = text(
    """
    SELECT a.pid, a.state, left(a.query, 120) AS query
    FROM pg_stat_activity a
    WHERE a.datname = current_database()
      AND a.pid <> pg_backend_pid()
      AND a.backend_type = 'client backend'
      AND (
        a.state LIKE 'idle in transaction%'
        OR EXISTS (
          SELECT 1 FROM pg_locks l JOIN pg_class c ON c.oid = l.relation
          WHERE l.pid = a.pid AND c.relnamespace = 'public'::regnamespace
        )
      )
    """
)


async def assert_no_open_db_work(session: AsyncSession) -> None:
    """Fail when another client session holds a transaction open or a lock on
    an app table: either one blocks the next test's TRUNCATE. Autovacuum and
    the RunBus LISTEN connection hold neither and pass."""
    rows = (await session.execute(OPEN_WORK_SQL)).all()
    if rows:
        found = "; ".join(f"pid {r.pid} {r.state}: {r.query}" for r in rows)
        pytest.fail(f"database work left open after the test: {found}", pytrace=False)


@pytest.fixture(autouse=True)
async def clean_db() -> AsyncIterator[None]:
    # Every run task, shadow comparison and settle/judge tail is drained before
    # the TRUNCATE, which takes an exclusive lock on every table. After the
    # test, the same drain runs and any session still holding a transaction or
    # a table lock fails *that* test by name, so a leak shows up in one run
    # instead of as a later deadlock or hang.
    from graph.runner import drain_background_tasks

    await drain_background_tasks()
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SET lock_timeout = '5s'"))
        await session.execute(text(f"TRUNCATE {ALL_TABLES} CASCADE"))
        await seed_base_rows(session)
    yield
    await drain_background_tasks()
    async with factory() as session:
        await assert_no_open_db_work(session)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


@pytest.fixture(scope="session")
async def server() -> AsyncIterator[str]:
    """Real uvicorn on a socket — ASGITransport buffers SSE, sockets stream.

    Port 0, not a fixed one: two suites in two worktrees must not collide on
    it. The kernel picks a free port and we read it back off the
    bound socket, so every session gets its own.
    """
    # The periodic sweepers query the test database on their own clock and
    # would race a test's TRUNCATE; tests call the sweep functions directly.
    import main
    from graph import runner

    async def _no_sweep(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    patches = pytest.MonkeyPatch()
    patches.setattr(runner, "sweep_loop", _no_sweep)
    patches.setattr(main, "sweep_demo_accounts", _no_sweep)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    instance = uvicorn.Server(config)
    serve = asyncio.create_task(instance.serve())
    deadline = time.monotonic() + 10
    while not instance.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server failed to start")
        await asyncio.sleep(0.01)
    servers = instance.servers
    if not servers or not servers[0].sockets:
        instance.should_exit = True
        await serve
        raise RuntimeError("test server bound no socket")
    port = int(servers[0].sockets[0].getsockname()[1])
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    await serve
    patches.undo()


@pytest.fixture
async def client(server: str) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(base_url=server) as http:
        yield http


@pytest.fixture
async def bus() -> AsyncIterator[PostgresRunBus]:
    instance = PostgresRunBus(get_session_factory(), get_settings().database_url)
    await instance.start()
    yield instance
    await instance.stop()


async def make_run_row(session: AsyncSession, *, stale: bool = False) -> tuple[UUID, UUID]:
    """User → chat → messages → one running run, for runbus/sweep tests."""
    from db.ids import uuid7

    plan_id = (await session.execute(text("SELECT id FROM plans WHERE name = 'free'"))).scalar_one()
    user = User(id=uuid7(), email=f"u{uuid7().hex}@test.dev", role="user", plan_id=plan_id)
    chat = Chat(id=uuid7(), user_id=user.id, title="t")
    user_msg = Message(id=uuid7(), chat_id=chat.id, role="user", content="hi", status="complete")
    assistant_msg = Message(id=uuid7(), chat_id=chat.id, role="assistant", content="", status=None)
    # Flush order: parents before children — models have no relationship()
    # declarations, so the ORM does not dependency-sort add_all().
    session.add(user)
    await session.flush()
    session.add(chat)
    await session.flush()
    session.add_all([user_msg, assistant_msg])
    await session.flush()
    heartbeat = datetime.now(UTC) - timedelta(hours=1) if stale else datetime.now(UTC)
    run = Run(
        id=uuid7(),
        message_id=assistant_msg.id,
        status="running",
        heartbeat_at=heartbeat,
        model_id="openai/gpt-4o-mini",
    )
    session.add(run)
    await session.commit()
    return run.id, assistant_msg.id


async def signup(
    client: AsyncClient, email: str, password: str = "password123"
) -> dict[str, object]:
    response = await client.post("/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body
