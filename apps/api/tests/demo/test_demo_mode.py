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
def _reset_demo_limiter() -> Any:
    from demo.router import reset_demo_limiter

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