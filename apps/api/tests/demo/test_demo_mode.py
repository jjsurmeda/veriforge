"""Demo mode (lane E item 4, PRD AC-2).

`POST /auth/demo` is the one unauthenticated route in the product that mints an
account and can spend provider credit, so the tests here are mostly about what
it *cannot* do:

- the per-IP limit answers 429, and it answers it before creating anything;
- a demo account cannot ask for Deep, web or an upload;
- its budget is enforced by the ordinary quota gate, not a bespoke one;
- cleanup removes the account and its chats, and leaves other users alone;
- a missing `demo` plan is a 503 naming the fix, never a silent fallback to
  `free`.

No live provider and no live model: the run-creation tests assert on the
refusal, which happens before the model is resolved and before the runner is
started.
"""

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Message, Plan, Run, UsageLedger, User
from db.session import get_session_factory
from demo import service
from demo.settings import DemoSettings, demo_settings
from quota.service import DEFAULT_ESTIMATES, QuotaExceeded, gate_and_reserve
from tests.conftest import make_run_row, signup

# The plan `make seed-demo` creates, and the budget the tour is built around:
# six Auto reservations with room over. `scripts/seed_demo.py` is the
# authority; this mirrors it so a change to one fails the other.
DEMO_PLAN_LIMITS = (60_000, 400_000)

# Resolved at import, where a blocking `pathlib` call belongs: inside the async
# test it would be an ASYNC240 violation for a path that cannot change.
SEED_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"


@pytest.fixture(autouse=True)
def _demo_environment(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The demo ON for every test here, and a clean limiter around each one.

    `DEMO_ENABLED` defaults to **false** — that default is the kill switch, and
    a suite that ran with the demo off would pass every test below without
    exercising a line of them. Tests about the switch itself set it back.
    """
    from demo.router import reset_demo_limiter

    monkeypatch.setenv("DEMO_ENABLED", "true")
    reset_demo_limiter()
    yield
    reset_demo_limiter()


async def _seed_demo_plan(db: AsyncSession) -> Plan:
    """The plan `make seed-demo` creates. Written here rather than run so the
    test does not depend on the seed script's environment."""
    plan = Plan(name="demo", credits_5h=DEMO_PLAN_LIMITS[0], credits_month=DEMO_PLAN_LIMITS[1])
    db.add(plan)
    await db.commit()
    return plan


async def _start_demo(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/auth/demo")
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _demo_user(db: AsyncSession) -> User:
    user = (await db.execute(select(User).where(User.role == "demo"))).scalars().first()
    assert user is not None, "no demo account was created"
    return user


async def _chat(client: AsyncClient, headers: dict[str, str]) -> str:
    created = await client.post("/chats", json={}, headers=headers)
    assert created.status_code in (200, 201), created.text
    return str(created.json()["id"])


def _past_ttl(hours_over: float = 0.02) -> datetime:
    return datetime.now(UTC) + timedelta(hours=demo_settings().ttl_hours + hours_over)


class TestStartingADemo:
    async def test_it_creates_an_ephemeral_account_and_returns_normal_tokens(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        body = await _start_demo(client)

        # The same TokenResponse shape as signup and login, so the frontend's
        # existing auth path is what gets exercised — no demo-only token.
        assert body["access_token"]
        assert body["user"]["role"] == "demo"
        assert body["user"]["plan"]["name"] == "demo"
        # `.test` is a reserved TLD (RFC 6761), so this address cannot receive a
        # password reset even if some future path tried.
        assert body["user"]["email"].startswith("demo-")
        assert body["user"]["email"].endswith("@demo.veriforge.test")

        user = await _demo_user(db)
        # No password: an account that can be logged into later is not
        # ephemeral, and NULL is already how a Google-only account is stored.
        assert user.password_hash is None

    async def test_the_account_cannot_be_logged_into(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """A visitor who loses the tab must not be able to come back to the same
        account by guessing, and a demo address must never be a credential."""
        await _seed_demo_plan(db)
        body = await _start_demo(client)
        response = await client.post(
            "/auth/login",
            json={"email": body["user"]["email"], "password": "guessing123"},
        )
        assert response.status_code == 401

    async def test_two_visitors_get_different_accounts(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        first = await _start_demo(client)
        second = await _start_demo(client)
        assert first["user"]["id"] != second["user"]["id"]
        assert first["user"]["email"] != second["user"]["email"]

    async def test_a_missing_demo_plan_is_a_503_naming_the_fix(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Not a silent fallback to `free`: `free` carries a 200k budget, and an
        account handed that because someone forgot a seed is the failure this
        whole route has to avoid."""
        response = await client.post("/auth/demo")
        assert response.status_code == 503
        assert response.json()["error_code"] == "demo_unavailable"
        assert "seed-demo" in response.json()["message"]


class TestTheKillSwitch:
    """KI-63. `DEMO_ENABLED`, default false.

    The route is unauthenticated and spends money, so "off" has to mean off:
    404, no row, and no per-IP budget consumed — otherwise a disabled demo
    still charges a visitor one of their five tries, and an operator who
    turned it off and back on finds the first visitors refused for reasons
    that have nothing to do with the demo.
    """

    async def test_it_is_off_by_default(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default is what production runs, and forgetting to set a
        variable must not be the thing that turns the demo on."""
        monkeypatch.delenv("DEMO_ENABLED", raising=False)
        assert demo_settings().enabled is False

    async def test_disabled_it_answers_404_and_creates_nothing(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_ENABLED", "false")

        response = await client.post("/auth/demo")

        assert response.status_code == 404
        assert await service.demo_account_count(db) == 0

    async def test_disabled_it_does_not_consume_the_per_ip_budget(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refused request must cost the visitor nothing.

        The limiter is checked before the switch would otherwise matter, so
        without the switch short-circuiting first, five disabled requests
        would exhaust the bucket and the first real visitor after the operator
        turns the demo on would get a 429 instead of a demo. Hammer it well
        past the limit, then turn it on and prove the tour still works."""
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_ENABLED", "false")
        limit = demo_settings().rate_limit

        for _ in range(limit * 3):
            assert (await client.post("/auth/demo")).status_code == 404

        monkeypatch.setenv("DEMO_ENABLED", "true")
        for _ in range(limit):
            assert (await client.post("/auth/demo")).status_code == 201
        assert (await client.post("/auth/demo")).status_code == 429

    async def test_disabled_it_does_not_look_like_a_missing_plan(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """404, not the 503 `demo_unavailable`: a visitor must not be able to
        tell "the demo is off" from "an operator forgot a seed", because only
        one of those is fixed by turning a flag on."""
        monkeypatch.setenv("DEMO_ENABLED", "false")
        response = await client.post("/auth/demo")
        assert response.status_code == 404
        assert "seed-demo" not in response.text

    async def test_the_limits_endpoint_still_answers_when_the_demo_is_off(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The composer's source of truth is not behind the kill switch.

        It is authenticated and readable by any signed-in user (so the
        composer can hide Deep and Web for a demo account), and a beta
        operator turning the demo off is not a reason for every signed-in
        user's composer to start erroring."""
        auth = await signup(client, "composer@test.dev")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        monkeypatch.setenv("DEMO_ENABLED", "false")

        response = await client.get("/auth/demo/limits", headers=headers)
        assert response.status_code == 200


class TestThePerIpLimit:
    async def test_it_answers_429_after_the_configured_number_of_attempts(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        limit = demo_settings().rate_limit

        for _ in range(limit):
            assert (await client.post("/auth/demo")).status_code == 201
        throttled = await client.post("/auth/demo")
        assert throttled.status_code == 429
        assert throttled.json()["error_code"] == "rate_limited"
        # Retry-After without which the honest guess is immediately.
        assert throttled.headers.get("Retry-After")

    async def test_the_default_is_five_an_hour(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The number is the brief's, pinned here because the default is the
        thing that applies when nothing is configured — which is production."""
        settings = demo_settings()
        assert settings.rate_limit == 5
        assert settings.window_seconds == 3600.0

    async def test_a_throttled_request_creates_nothing(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The limiter runs before any write. An account created and then
        discarded would still have reserved a row and burned a plan row."""
        await _seed_demo_plan(db)
        limit = demo_settings().rate_limit
        for _ in range(limit):
            await _start_demo(client)
        assert (await client.post("/auth/demo")).status_code == 429

        assert await service.demo_account_count(db) == limit

    async def test_a_different_source_address_is_not_refused_as_a_role(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The bucket is keyed by the address the server observed. Whether the
        proxy made that address different is `auth/router.py`'s documented
        concern, not this test's — but a forged header must not be able to turn
        a 429 into a role error, which would be a different (and quieter)
        failure."""
        await _seed_demo_plan(db)
        limit = demo_settings().rate_limit
        for _ in range(limit):
            await _start_demo(client)
        assert (await client.post("/auth/demo")).status_code == 429

        other = await client.post("/auth/demo", headers={"x-forwarded-for": "203.0.113.9"})
        assert other.status_code in (201, 429)


class TestTheDailyCap:
    """KI-63, the half of it a kill switch cannot do.

    The per-IP limit is 5 per hour in process memory, so many addresses or a
    restart defeat it entirely. This cap is counted from the database, so
    neither does.
    """

    async def test_the_default_is_fifty_a_day(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pinned because the default is what production runs, and because it
        is the number the runbook's worst-case figure is built on."""
        monkeypatch.delenv("DEMO_DAILY_CAP", raising=False)
        assert demo_settings().daily_cap == 50

    async def test_the_eleventh_demo_in_a_day_is_refused(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_DAILY_CAP", "10")
        # A different address each time, so it is the cap refusing and not the
        # per-IP limiter: this test is only meaningful across addresses.
        for index in range(10):
            response = await client.post(
                "/auth/demo", headers={"x-forwarded-for": f"198.51.100.{index}"}
            )
            assert response.status_code == 201, f"{index}: {response.text}"

        over = await client.post("/auth/demo", headers={"x-forwarded-for": "198.51.100.200"})
        assert over.status_code == 429
        assert over.json()["error_code"] == "demo_capacity"
        # No account created by the refused request.
        assert await service.demo_account_count(db) == 10

    async def test_the_cap_is_counted_from_the_database(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not from process memory, which is what makes it survive a restart
        and hold against a second process.

        The accounts below are written straight to the table with no HTTP
        request and no limiter involved — exactly the state a restart or a
        second api process leaves behind."""
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_DAILY_CAP", "3")
        plan = await db.get(Plan, (await db.scalar(select(Plan.id).where(Plan.name == "demo"))))
        assert plan is not None
        for index in range(3):
            db.add(
                User(
                    email=f"demo-seeded{index}@demo.veriforge.test",
                    password_hash=None,
                    role="demo",
                    plan_id=plan.id,
                )
            )
        await db.commit()

        response = await client.post("/auth/demo", headers={"x-forwarded-for": "203.0.113.7"})
        assert response.status_code == 429
        assert response.json()["error_code"] == "demo_capacity"
        assert await service.demo_account_count(db) == 3

    async def test_accounts_older_than_the_window_do_not_count(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rolling 24 hours, not "since the process started": yesterday's demo
        must not stop today's."""
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_DAILY_CAP", "2")
        plan_id = await db.scalar(select(Plan.id).where(Plan.name == "demo"))
        assert plan_id is not None
        stale = datetime.now(UTC) - timedelta(hours=25)
        for index in range(5):
            db.add(
                User(
                    email=f"demo-old{index}@demo.veriforge.test",
                    password_hash=None,
                    role="demo",
                    plan_id=plan_id,
                    created_at=stale,
                )
            )
        await db.commit()

        for index in range(2):
            response = await client.post(
                "/auth/demo", headers={"x-forwarded-for": f"198.51.100.{index}"}
            )
            assert response.status_code == 201, response.text

    async def test_cleaned_up_accounts_free_capacity(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Capacity has to come back, or the demo silently dies 50 accounts
        into the beta and the operator has no way to tell why.

        The count is of *live* rows, so deleting a demo account returns its
        slot immediately — nothing is memoised. The TTL here is 0.01 h while
        the cap window stays at its 24 h default, so these accounts are inside
        the cap window and outside their TTL at the same time: the sweep can
        remove them while the cap is still full, which is the only way to tell
        "the count reads the rows" apart from "the count reads a clock".

        (At the shipped defaults the two are both 24 h, so a purge and the
        window roll happen at the same moment and this distinction is
        invisible. The separation here is what makes the assertion about rows
        rather than about time.)
        """
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_DAILY_CAP", "2")
        monkeypatch.setenv("DEMO_TTL_HOURS", "0.01")
        for index in range(2):
            assert (
                await client.post(
                    "/auth/demo", headers={"x-forwarded-for": f"198.51.100.{index}"}
                )
            ).status_code == 201
        assert (
            await client.post("/auth/demo", headers={"x-forwarded-for": "198.51.100.9"})
        ).status_code == 429

        # The ordinary sweep, with no help from the test.
        assert await service.purge_expired(db, now=_past_ttl(hours_over=1)) == 2

        freed = await client.post("/auth/demo", headers={"x-forwarded-for": "198.51.100.10"})
        assert freed.status_code == 201, freed.text
        assert await service.demo_account_count(db) == 1

    async def test_the_per_ip_limit_is_still_checked_first(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A throttled request must cost no capacity.

        The order matters: if the cap were checked first, a visitor who
        exhausts their per-IP budget would also burn one of the day's 50
        accounts, and the per-IP limit would be quietly useless."""
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_DAILY_CAP", "50")
        limit = demo_settings().rate_limit
        for _ in range(limit):
            assert (await client.post("/auth/demo")).status_code == 201
        for _ in range(3):
            assert (await client.post("/auth/demo")).status_code == 429

        # Still exactly `limit` accounts: the refused ones created nothing and
        # consumed none of the day's cap.
        assert await service.demo_account_count(db) == limit

    async def test_a_normal_user_does_not_consume_demo_capacity(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The count is of demo-role rows. A busy beta of real users must not
        close the demo."""
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_DAILY_CAP", "1")
        for index in range(4):
            await signup(client, f"beta{index}@test.dev")

        assert (await client.post("/auth/demo")).status_code == 201
        assert (
            await client.post("/auth/demo", headers={"x-forwarded-for": "203.0.113.1"})
        ).status_code == 429

    async def test_the_cap_check_and_the_insert_are_one_atomic_step(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The concurrency proof, and the reason it is built the way it is.

        **A plain `asyncio.gather` of two creations is not enough here**, and
        the branch has the measurements to show why:

        - Two `client.post` calls under `gather` (the obvious version) passed
          **12 runs out of 12 with the lock removed**. Probing the route
          showed the two requests do overlap in the app — 0.7 ms apart at the
          top of `create_demo_user` — but serialise before the database, so
          the second request's first statement returned only after the first
          had committed. The race is real; that test never reached it.
        - Two sessions calling the service directly under `gather` did better
          (8 of 8 with the lock removed) but were still not reliable here,
          because the second session's connection checkout costs ~13 ms and
          A's whole transaction finishes inside that. It reproduced the bug
          roughly 6 runs in 8 — a test that only sometimes catches the defect
          is not holding the fix in place.

        So this test removes the timing instead of hoping for it. The seam is
        `check_daily_capacity`: worker A is held **after its count read and
        before its commit**, which is the exact window in which a
        read-then-write implementation lets a second writer in. If the count
        read and the insert are atomic, worker B cannot even *begin* its read
        while A is paused there — it is waiting on the plan row lock — so B's
        read can only happen after A has committed, by which time it sees the
        new row and refuses.

        Asserted both ways, so the test cannot pass for the wrong reason:

        - while A is paused, **B has not read the count at all** — proof the
          two are serialised rather than merely lucky;
        - after A commits, exactly one account exists and B is the one that
          was refused.

        Measured on this branch with the `SELECT … FOR UPDATE` removed:
        `reads=['A=0', 'B=0']`, `results=['user', 'user']`, **2 rows**. With
        it restored: `reads=['A=0']` while paused, then B reads afterwards and
        `results=['user', 'DemoCapacityReached']`, **1 row**.

        The pause is a deliberate await inside a monkeypatched seam, not a
        `sleep` racing the database: a plain sleep usually does not land
        (agents.md: no instrumentation that changes timing), and it is why
        the gather-based versions were unreliable.
        """
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_DAILY_CAP", "1")
        settings = demo_settings()
        factory = get_session_factory()

        reads: list[str] = []
        a_has_read = asyncio.Event()
        release_a = asyncio.Event()
        real_check = service.check_daily_capacity

        async def _pause_a_after_reading(
            session: AsyncSession, policy: DemoSettings, *, now: datetime | None = None
        ) -> int:
            # The real read, then A stops here — still uncommitted, with the
            # lock held if the implementation takes one.
            used = await real_check(session, policy, now=now)
            reads.append(f"A={used}")
            a_has_read.set()
            await release_a.wait()
            return used

        monkeypatch.setattr(service, "check_daily_capacity", _pause_a_after_reading)
        first, second = factory(), factory()
        tasks: list[asyncio.Task[User]] = []
        try:
            # Warm both connections first, so B's pool checkout does not cost
            # the ~13 ms that let A finish first in the gather-based version.
            for warm in (first, second):
                await warm.scalar(select(func.count()).select_from(User))

            tasks.append(asyncio.create_task(service.create_demo_user(first, settings)))
            await asyncio.wait_for(a_has_read.wait(), timeout=5)
            tasks.append(asyncio.create_task(service.create_demo_user(second, settings)))

            # Give B long enough to have finished its read many times over if
            # nothing were holding it back.
            await asyncio.sleep(1.0)
            assert reads == ["A=0"], (
                "the second creation must not read the cap while the first "
                f"holds an uncommitted read; it read: {reads}"
            )
            assert not tasks[1].done(), "the second creation must be waiting"

            release_a.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Release and drain before closing: a session cannot be closed
            # while a statement is still in flight on it, and an exception
            # from here would replace the real assertion failure above.
            release_a.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for session in (first, second):
                await session.close()

        assert isinstance(results[0], User), f"the first creation must win: {results[0]!r}"
        assert isinstance(results[1], service.DemoCapacityReached), (
            f"the second must be refused once it can read: {results[1]!r}"
        )
        assert await service.demo_account_count(db) == 1

    async def test_two_simultaneous_requests_at_the_cap_do_not_both_win(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same race end to end, through the route.

        This is the wiring — that `DemoCapacityReached` becomes a 429 with
        `demo_capacity` and a `Retry-After`. It is *not* the atomicity proof:
        measured on this branch it passes with or without the lock, because
        two HTTP requests serialise before the database here. The atomicity
        proof is
        `test_the_cap_check_and_the_insert_are_one_atomic_step`, which is
        deterministic; this one keeps the 429 contract honest.
        """
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_DAILY_CAP", "1")

        responses = await asyncio.gather(
            client.post("/auth/demo", headers={"x-forwarded-for": "198.51.100.2"}),
            client.post("/auth/demo", headers={"x-forwarded-for": "198.51.100.3"}),
        )
        statuses = sorted(response.status_code for response in responses)
        assert statuses in ([201, 201], [201, 429]), (
            f"one 201 and at most one 429, got {statuses}: "
            + " ".join(response.text for response in responses)
        )
        if 429 in statuses:
            loser = next(r for r in responses if r.status_code == 429)
            assert loser.json()["error_code"] == "demo_capacity"
            # A 429 without Retry-After tells a client to guess, and the
            # honest guess is immediately.
            assert loser.headers.get("Retry-After")
        assert await service.demo_account_count(db) == statuses.count(201)


class TestWhatADemoAccountCannotDo:
    async def test_it_cannot_ask_for_deep(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        body = await _start_demo(client)
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        chat_id = await _chat(client, headers)

        response = await client.post(
            f"/chats/{chat_id}/runs",
            json={"message": "Compare the two warranty documents", "mode": "deep"},
            headers=headers,
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "demo_not_allowed"

    async def test_deep_is_allowed_when_the_operator_turns_it_on(
        self, client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refusal is the setting, not a hard-coded block, so the beta can
        allow the showcase's sixth question without a code change."""
        await _seed_demo_plan(db)
        monkeypatch.setenv("DEMO_ALLOW_DEEP", "true")
        body = await _start_demo(client)
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        chat_id = await _chat(client, headers)

        response = await client.post(
            f"/chats/{chat_id}/runs",
            json={"message": "Compare the two warranty documents", "mode": "deep"},
            headers=headers,
        )
        # The assertion is about OUR check only. A Deep run then needs a
        # working model, which this suite does not stand up, and that is a
        # different failure the demo check must not be blamed for.
        if response.status_code == 403:
            assert response.json()["error_code"] != "demo_not_allowed"

    async def test_it_cannot_search_the_web(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        body = await _start_demo(client)
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        chat_id = await _chat(client, headers)

        response = await client.post(
            f"/chats/{chat_id}/runs",
            json={"message": "What is the latest news about tariffs?", "source": "web"},
            headers=headers,
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "demo_not_allowed"

    async def test_it_cannot_upload(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Already the product's rule for the demo role (`deny_read_only`), not
        a new one — asserted here so weakening it later is a test failure."""
        await _seed_demo_plan(db)
        body = await _start_demo(client)
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        chat_id = await _chat(client, headers)

        response = await client.post(
            f"/chats/{chat_id}/documents",
            files={"file": ("notes.md", b"# hello", "text/markdown")},
            headers=headers,
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "read_only_account"

    async def test_the_limits_endpoint_matches_the_server(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """So the composer can hide the toggles without a second source of
        truth: these are the same settings the route enforces."""
        await _seed_demo_plan(db)
        body = await _start_demo(client)
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        limits = (await client.get("/auth/demo/limits", headers=headers)).json()
        assert limits["is_demo"] is True
        assert limits["allow_deep"] is False
        assert limits["allow_web"] is False
        assert limits["allow_upload"] is False

    async def test_a_normal_user_is_untouched(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        auth = await signup(client, "ordinary@test.dev")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        limits = (await client.get("/auth/demo/limits", headers=headers)).json()
        assert limits["is_demo"] is False
        assert limits["allow_deep"] is True
        assert limits["allow_upload"] is True


class TestTheBudget:
    async def test_it_is_the_ordinary_quota_gate_on_the_demo_plan(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The plan's limits ARE the budget. A demo-specific quota path would be
        a second implementation, and the wrong one to be wrong in."""
        plan = await _seed_demo_plan(db)
        await _start_demo(client)
        user = await _demo_user(db)

        assert user.plan_id == plan.id
        stored = await db.get(Plan, user.plan_id)
        assert stored is not None
        assert (stored.credits_5h, stored.credits_month) == DEMO_PLAN_LIMITS

    async def test_the_gate_refuses_a_demo_account_that_exhausted_its_plan(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        await _start_demo(client)
        user = await _demo_user(db)

        # Already over the 5 h limit: the gate the run route calls. A settled
        # row, because the window sums both reserved and settled spend.
        run_id, _ = await make_run_row(db)
        db.add(
            UsageLedger(
                user_id=user.id,
                run_id=run_id,
                model="aggregate",
                role="run",
                tokens_in=0,
                tokens_out=0,
                credits=DEMO_PLAN_LIMITS[0] + 1,
                status="settled",
            )
        )
        await db.commit()

        with pytest.raises(QuotaExceeded):
            await gate_and_reserve(db, user_id=user.id, run_id=user.id, mode="auto")

    async def test_the_budget_covers_the_tour_but_not_a_session(
        self, db: AsyncSession
    ) -> None:
        """The tour is six questions, so the budget has to survive six Auto
        reservations or the second question is refused — which is what a first
        pass at 12 000 did, live, mid-rehearsal. And it must still be a demo
        budget rather than a free tier: `free` is 200 000 per 5 h."""
        plan = await _seed_demo_plan(db)
        six_runs = DEFAULT_ESTIMATES["auto"] * 6
        assert plan.credits_5h >= six_runs, "the tour's six questions must fit"
        assert plan.credits_5h < 200_000, "still a small budget, not a free tier"


class TestCleanup:
    async def test_it_removes_an_expired_demo_account_and_its_chats(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        body = await _start_demo(client)
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        chat_id = await _chat(client, headers)
        user = await _demo_user(db)

        assert await service.purge_expired(db, now=_past_ttl()) == 1

        assert await db.get(User, user.id) is None
        chat = (
            await db.execute(select(Chat).where(Chat.id == UUID(chat_id)))
        ).scalar_one_or_none()
        assert chat is None
        # And its messages, through the cascade.
        assert (
            await db.execute(
                select(func.count(Message.id)).where(Message.chat_id == UUID(chat_id))
            )
        ).scalar_one() == 0
        # And nothing referencing a now-absent user is left behind.
        assert (
            await db.execute(
                select(func.count(Run.id)).join(
                    Message, Run.message_id == Message.id
                ).where(Message.chat_id == UUID(chat_id))
            )
        ).scalar_one() == 0

    async def test_it_leaves_a_demo_account_inside_its_ttl(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        await _start_demo(client)
        user = await _demo_user(db)

        assert await service.purge_expired(db) == 0
        assert await db.get(User, user.id) is not None

    async def test_it_never_touches_a_normal_user(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await signup(client, "keep-me@test.dev")
        ordinary = (
            await db.execute(select(User).where(User.email == "keep-me@test.dev"))
        ).scalar_one()

        await _seed_demo_plan(db)
        await _start_demo(client)

        assert await service.purge_expired(db, now=_past_ttl(hours_over=1)) == 1
        assert await db.get(User, ordinary.id) is not None

    async def test_it_is_idempotent(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await _seed_demo_plan(db)
        await _start_demo(client)
        later = _past_ttl(hours_over=1)
        assert await service.purge_expired(db, now=later) == 1
        assert await service.purge_expired(db, now=later) == 0

    async def test_expiry_is_asked_about_the_policy_passed_in(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The TTL comes from the settings object handed in, so the question is
        about a specific policy rather than whatever this process runs with —
        and the naive-timestamp case is answered rather than raised on."""
        await _seed_demo_plan(db)
        await _start_demo(client)
        user = await _demo_user(db)
        generous = DemoSettings(
            enabled=True,
            daily_cap=50,
            cap_window_hours=24.0,
            rate_limit=5,
            window_seconds=3600.0,
            plan_name="demo",
            ttl_hours=10_000.0,
            allow_deep=False,
        )
        assert await service.is_expired(user, generous) is False
        assert (
            await service.is_expired(
                user, generous, now=datetime.now(UTC) + timedelta(days=1000)
            )
            is True
        )


class TestSeedScript:
    async def test_it_is_idempotent_and_leaves_other_plans_alone(
        self, db: AsyncSession
    ) -> None:
        """`make seed-demo` run twice must not double the budget, and must not
        touch a plan an operator tuned (`free`, `pro`, `internal-eval`)."""
        before = {
            row.name: (row.credits_5h, row.credits_month)
            for row in (await db.execute(select(Plan))).scalars().all()
        }
        script = SEED_SCRIPT_PATH
        spec = importlib.util.spec_from_file_location("seed_demo_under_test", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        await module.seed()
        await module.seed()

        after = {
            row.name: (row.credits_5h, row.credits_month)
            for row in (await db.execute(select(Plan))).scalars().all()
        }
        assert "demo" in after
        for name, limits in before.items():
            if name != "demo":
                assert after[name] == limits, name
        assert after["demo"] == (module.CREDITS_5H, module.CREDITS_MONTH)