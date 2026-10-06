"""Signup control and throttling (item 4).

The three security properties item 4 asks for, each asserted directly:

- an invite works **once** under two concurrent signups;
- an expired, revoked or unknown code is refused with the **same** message,
  so the endpoint is not an existence oracle;
- the limiter returns 429 with `Retry-After` and recovers.

Plus the mode matrix (`open` / `invite` / `closed`), Google sign-in
following the same rule for first-time accounts, and the admin surface.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from auth import invites, ratelimit
from auth.invites import hash_code
from config import get_settings
from db.models import Invite, User


@pytest.fixture(autouse=True)
def _fresh_limiter() -> Any:
    """A clean limiter, and clean settings, per test.

    Two process-global things leak between tests otherwise, and both produce
    failures with nothing to do with the test that sees them:

    - the limiter, which is deliberately process-global, so a test that does
      not reset it inherits the previous test's buckets;
    - `get_settings()`, which is `lru_cache`d. monkeypatch restores the
      environment when a test ends but does not know about that cache, so a
      test that set `SIGNUP_MODE=invite` leaves every later test reading
      `invite` from the cached Settings — which is how four admin tests
      failed to sign their admin up.
    """
    ratelimit.reset_all()
    get_settings.cache_clear()
    yield
    ratelimit.reset_all()
    get_settings.cache_clear()


def _set_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("SIGNUP_MODE", mode)
    get_settings.cache_clear()


@pytest.fixture
async def auth_client(client: Any) -> Any:
    """A client carrying a normal user's bearer token."""
    from tests.conftest import signup

    auth = await signup(client, f"rl-user-{uuid4().hex[:10]}@test.dev")
    token = auth["access_token"]

    class _Authed:
        def __getattr__(self, name: str) -> Any:
            async def call(*args: Any, **kwargs: Any) -> Any:
                headers = dict(kwargs.pop("headers", {}) or {})
                headers["Authorization"] = f"Bearer {token}"
                return await getattr(client, name)(*args, headers=headers, **kwargs)

            return call

    return _Authed()


@pytest.fixture
async def admin_client(client: Any, db: Any) -> Any:
    """A client carrying an admin's bearer token.

    Built the way `tests/admin/test_admin.py` builds one — sign up, then
    promote the row — because there is deliberately no endpoint that grants
    the role (item 3): an unauthenticated bootstrap would be the attack
    surface the admin runbook exists to avoid.
    """
    from tests.conftest import signup

    email = f"inv-admin-{uuid4().hex[:10]}@test.dev"
    auth = await signup(client, email)
    from sqlalchemy import select

    from db.models import User as _User

    user = (await db.execute(select(_User).where(_User.email == email))).scalar_one()
    user.role = "admin"
    await db.commit()
    token = auth["access_token"]

    class _Admined:
        def __getattr__(self, name: str) -> Any:
            async def call(*args: Any, **kwargs: Any) -> Any:
                headers = dict(kwargs.pop("headers", {}) or {})
                headers["Authorization"] = f"Bearer {token}"
                return await getattr(client, name)(*args, headers=headers, **kwargs)

            return call

    return _Admined()


async def _admin(db: Any) -> Any:
    from db.models import Plan

    plan = (await db.execute(Plan.__table__.select())).first()
    assert plan is not None
    user = User(
        email=f"inv-admin-{uuid4().hex[:10]}@test.dev", role="admin", plan_id=plan.id,
        password_hash="x",
    )
    db.add(user)
    await db.commit()
    return user


async def _mint(db: Any, actor: Any, **kwargs: Any) -> tuple[Invite, str]:
    created = await invites.create(db, actor_id=actor.id, **kwargs)
    await db.commit()
    invite, code = created[0]
    return invite, code


# --- the mode matrix -------------------------------------------------------


class TestSignupModes:
    @pytest.mark.asyncio
    async def test_invite_mode_refuses_a_signup_with_no_code(
        self, client: Any, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "invite")
        response = await client.post(
            "/auth/signup", json={"email": "nocode@test.dev", "password": "password123"}
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == "invite_invalid"

    @pytest.mark.asyncio
    async def test_open_mode_needs_no_code(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "open")
        response = await client.post(
            "/auth/signup", json={"email": "open@test.dev", "password": "password123"}
        )
        assert response.status_code == 201, response.text

    @pytest.mark.asyncio
    async def test_closed_mode_refuses_everyone_with_a_valid_code(
        self, client: Any, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid code must not help: `closed` means closed, and a deployment
        that flips to closed expects zero new accounts, not "accounts with
        the right code"."""
        _set_mode(monkeypatch, "closed")
        admin = await _admin(db)
        _invite, code = await _mint(db, admin)
        response = await client.post(
            "/auth/signup",
            json={
                "email": "closed@test.dev",
                "password": "password123",
                "invite_code": code,
            },
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "signup_closed"

    @pytest.mark.asyncio
    async def test_invite_mode_is_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default is `invite` on purpose: forgetting to set the setting
        is the failure that leaks the deployment."""
        monkeypatch.delenv("SIGNUP_MODE", raising=False)
        get_settings.cache_clear()
        assert get_settings().signup_mode == "invite"


# --- the invite works once ------------------------------------------------


class TestSingleUse:
    @pytest.mark.asyncio
    async def test_an_invite_creates_one_account(
        self, client: Any, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "invite")
        admin = await _admin(db)
        invite, code = await _mint(db, admin)
        response = await client.post(
            "/auth/signup",
            json={"email": "used@test.dev", "password": "password123", "invite_code": code},
        )
        assert response.status_code == 201, response.text
        # Not `db.expire_all()`: that forces lazy IO on the next attribute
        # access, outside a greenlet, and raises MissingGreenlet. A fresh
        # session reads the committed row, which is what is being asserted.
        from db.session import get_session_factory

        async with get_session_factory()() as fresh:
            refreshed = await fresh.get(Invite, invite.id)
            assert refreshed is not None
        assert refreshed.used_by is not None
        assert refreshed.used_at is not None
        assert invites.status_of(refreshed) == "used"

    @pytest.mark.asyncio
    async def test_a_second_signup_with_the_same_code_is_refused(
        self, client: Any, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "invite")
        admin = await _admin(db)
        _invite, code = await _mint(db, admin)
        first = await client.post(
            "/auth/signup",
            json={"email": "first@test.dev", "password": "password123", "invite_code": code},
        )
        assert first.status_code == 201
        second = await client.post(
            "/auth/signup",
            json={"email": "second@test.dev", "password": "password123", "invite_code": code},
        )
        assert second.status_code == 400
        assert second.json()["error_code"] == "invite_invalid"

    @pytest.mark.asyncio
    async def test_two_concurrent_signups_on_one_code_produce_one_account(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reason `consume` is one UPDATE ... RETURNING and not a read
        then a write.

        Two connections, both transactions left open, and the overlap forced
        rather than hoped for. Both attempts see the invite as unused and
        both are still inside their transaction when each tries to claim it;
        exactly one may win, and the loser must get the same error an unknown
        code gets.

        The barrier matters: a version that reads the row and only writes at
        COMMIT has an interleaving window that a plain `asyncio.sleep` will
        usually miss, because the read and the write are separated by the
        commit rather than by an await. So both transactions read first, and
        only then does either attempt the claim. That is deterministic, and
        it is the case that distinguishes the two implementations.
        """
        from db.session import get_session_factory

        _set_mode(monkeypatch, "invite")
        admin = await _admin(db)
        _invite, code = await _mint(db, admin)
        plan_id = await _free_plan_id(db)
        factory = get_session_factory()

        read_counts: list[int] = []
        claimed: list[str] = []

        async def open_and_read(email: str) -> Any:
            """Insert a user, commit nothing, and leave the invite unclaimed."""
            session = factory()
            session.add(
                User(email=email, password_hash="x", role="user", plan_id=plan_id)
            )
            await session.flush()
            user_id = (await session.execute(_user_id_for(email))).scalar_one()
            # The same read `consume` does, in its own transaction: both
            # transactions now hold "this invite is unused".
            await invites.ensure_available(session, code=code)
            read_counts.append(1)
            return session, user_id

        first = await open_and_read("race-a@test.dev")
        second = await open_and_read("race-b@test.dev")
        assert len(read_counts) == 2, "both transactions must read before either writes"

        async def claim(label: str, session: Any, user_id: Any) -> None:
            try:
                await invites.consume(session, code=code, user_id=user_id)
                await session.commit()
                claimed.append(label)
            except invites.InviteInvalid:
                await session.rollback()
            finally:
                await session.close()

        # Simultaneously, not in sequence: a sequential pair lets the first
        # commit before the second even looks, so every implementation looks
        # correct. `gather` is what puts both reads in flight before either
        # write lands.
        await asyncio.gather(
            claim("a", *first),
            claim("b", *second),
        )

        assert len(claimed) == 1, f"both signups claimed the invite: {claimed}"

        from sqlalchemy import select as _select

        from db.models import Invite as _Invite

        row = (await db.execute(_select(_Invite))).scalars().first()
        assert row is not None
        assert invites.status_of(row) == "used"


def _user_id_for(email: str) -> Any:
    from sqlalchemy import select

    from db.models import User

    return select(User.id).where(User.email == email)


# --- no existence oracle --------------------------------------------------


class TestNoExistenceOracle:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", ["unknown", "used", "revoked", "expired"])
    async def test_every_unusable_code_answers_identically(
        self,
        client: Any,
        db: Any,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
    ) -> None:
        """One message for all four ways a code can fail.

        A caller who can tell "expired" from "never existed" can enumerate
        which codes were ever issued — which, for codes an admin mails out by
        hand, is the whole list.
        """
        from datetime import UTC, datetime, timedelta

        _set_mode(monkeypatch, "invite")
        admin = await _admin(db)
        invite, code = await _mint(db, admin)

        if case == "used":
            first = await client.post(
                "/auth/signup",
                json={"email": "oracle-used@test.dev", "password": "password123",
                      "invite_code": code},
            )
            assert first.status_code == 201
        elif case == "revoked":
            await invites.revoke(db, invite_id=invite.id)
            await db.commit()
        elif case == "expired":
            invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()

        response = await client.post(
            "/auth/signup",
            json={
                "email": f"oracle-{case}@test.dev",
                "password": "password123",
                "invite_code": "nonexistent-code" if case == "unknown" else code,
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "invite_invalid"
        assert body["message"] == invites.INVALID_INVITE_MESSAGE

    @pytest.mark.asyncio
    async def test_a_bogus_code_does_not_reveal_whether_an_account_exists(
        self, client: Any, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The oracle that the ordering in `signup` exists to close.

        Found by the test above: with the email lookup before the invite
        check, a bogus code answered 409 `email_taken` for an address that
        has an account and 400 `invite_invalid` for one that does not. That
        is account enumeration on a public endpoint, and it needs no valid
        invite to work.
        """
        _set_mode(monkeypatch, "invite")
        first = await client.post(
            "/auth/signup",
            json={"email": "oracle-probe@test.dev", "password": "password123",
                  "invite_code": "bogus-code"},
        )
        assert first.status_code == 400

        # Now create the account for real, with a valid invite.
        admin_user = await _admin(db)
        _invite, code = await _mint(db, admin_user)
        second = await client.post(
            "/auth/signup",
            json={"email": "oracle-probe@test.dev", "password": "password123",
                  "invite_code": code},
        )
        assert second.status_code == 201, second.text

        # And the same bogus code must now answer exactly as it did before the
        # account existed.
        third = await client.post(
            "/auth/signup",
            json={"email": "oracle-probe@test.dev", "password": "password123",
                  "invite_code": "bogus-code"},
        )
        assert third.status_code == first.status_code
        assert third.json() == first.json()

    @pytest.mark.asyncio
    async def test_a_missing_code_answers_like_an_invalid_one(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "invite")
        missing = await client.post(
            "/auth/signup", json={"email": "a@test.dev", "password": "password123"}
        )
        invalid = await client.post(
            "/auth/signup",
            json={"email": "b@test.dev", "password": "password123", "invite_code": "nope"},
        )
        assert missing.status_code == invalid.status_code == 400
        assert missing.json() == invalid.json()

    @pytest.mark.asyncio
    async def test_the_plaintext_code_is_never_stored(
        self, client: Any, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An invite code is a credential. Storing it in plaintext would put
        every code in the database dump and in the audit log."""
        _set_mode(monkeypatch, "invite")
        admin = await _admin(db)
        invite, code = await _mint(db, admin)
        assert invite.code == "", "the row must not carry the plaintext"
        assert invite.code_hash == hash_code(code)
        rows = (await db.execute(select_all_invites())).scalars().all()
        for row in rows:
            assert code not in f"{row.code}{row.code_hash}{row.note}"


def select_all_invites() -> Any:
    from sqlalchemy import select

    return select(Invite)


# --- the limiter ----------------------------------------------------------


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_signup_returns_429_with_retry_after(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "open")
        monkeypatch.setenv("RATE_LIMIT_SIGNUP", "3")
        monkeypatch.setenv("RATE_LIMIT_SIGNUP_WINDOW_SECONDS", "60")
        get_settings.cache_clear()

        codes = []
        for index in range(5):
            response = await client.post(
                "/auth/signup", json={"email": f"rl{index}@test.dev", "password": "password123"}
            )
            codes.append(response.status_code)
        assert codes[:3] == [201, 201, 201]
        assert codes[3:] == [429, 429], codes

        blocked = (await client.post(
            "/auth/signup", json={"email": "rl9@test.dev", "password": "password123"}
        ))
        assert blocked.status_code == 429
        retry_after = blocked.headers.get("Retry-After")
        assert retry_after is not None, "a 429 without Retry-After tells the client nothing"
        assert 1 <= int(retry_after) <= 60
        assert blocked.json()["detail"]["retry_after"] == int(retry_after)

    @pytest.mark.asyncio
    async def test_login_is_limited_separately_from_signup(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "open")
        monkeypatch.setenv("RATE_LIMIT_SIGNUP", "2")
        monkeypatch.setenv("RATE_LIMIT_LOGIN", "2")
        get_settings.cache_clear()

        for index in range(2):
            await client.post(
                "/auth/signup", json={"email": f"sep{index}@test.dev", "password": "password123"}
            )
        # Signup is exhausted...
        blocked = await client.post(
            "/auth/signup", json={"email": "sep-x@test.dev", "password": "password123"}
        )
        assert blocked.status_code == 429
        # ...and login still works, so one endpoint's traffic cannot lock a
        # user out of the other.
        login = await client.post(
            "/auth/login", json={"email": "sep0@test.dev", "password": "password123"}
        )
        assert login.status_code == 200, login.text

    @pytest.mark.asyncio
    async def test_the_limiter_recovers_after_the_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        limiter = ratelimit.RateLimiter(limit=2, window_seconds=0.05, _now=_FakeClock())
        clock = limiter._now
        for _ in range(2):
            assert limiter.check(("signup", "ip:1.2.3.4")) is None
        assert limiter.check(("signup", "ip:1.2.3.4")) is not None
        clock.advance(0.06)  # type: ignore[attr-defined]
        assert limiter.check(("signup", "ip:1.2.3.4")) is None, "must recover"

    def test_a_sliding_window_does_not_double_at_the_boundary(self) -> None:
        """A fixed window lets a client spend the whole quota at 59s and the
        whole quota again at 61s — twice the intended rate, at the seam."""
        clock = _FakeClock()
        limiter = ratelimit.RateLimiter(limit=3, window_seconds=10, _now=clock)
        clock.advance(9.0)
        for _ in range(3):
            assert limiter.check(("login", "ip:9.9.9.9")) is None
        clock.advance(1.5)  # 10.5s later: a fixed window would have reset
        assert limiter.check(("login", "ip:9.9.9.9")) is not None

    def test_different_ips_have_independent_budgets(self) -> None:
        limiter = ratelimit.RateLimiter(limit=1, window_seconds=60)
        assert limiter.check(("login", "ip:1.1.1.1")) is None
        assert limiter.check(("login", "ip:2.2.2.2")) is None
        assert limiter.check(("login", "ip:1.1.1.1")) is not None

    def test_throttled_attempts_are_still_counted(self) -> None:
        """A client that keeps hammering must not get a fresh budget each time
        the window rolls over."""
        clock = _FakeClock()
        limiter = ratelimit.RateLimiter(limit=2, window_seconds=10, _now=clock)
        assert limiter.check(("signup", "ip:3.3.3.3")) is None
        assert limiter.check(("signup", "ip:3.3.3.3")) is None
        assert limiter.check(("signup", "ip:3.3.3.3")) is not None
        clock.advance(5)
        assert limiter.check(("signup", "ip:3.3.3.3")) is not None
        assert limiter.check(("signup", "ip:3.3.3.3")) is not None

    @pytest.mark.asyncio
    async def test_the_ip_key_is_the_socket_peer_or_uvicorns_rewrite_of_it(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What is actually ours: which address keys the limiter bucket.

        The obvious test here — "a forged X-Forwarded-For does not reset the
        limiter" — is wrong, and asserting it is how this was found. Uvicorn
        runs ProxyHeadersMiddleware by default with forwarded_allow_ips
        defaulting to 127.0.0.1, so by the time a handler runs, a header from
        a trusted peer has ALREADY been folded into request.client.host. The
        header therefore does change the bucket, and it is safe precisely
        because an untrusted peer cannot reach that code path.

        What must hold, and is asserted here, is that `_client_ip` never reads
        the header itself: the trust decision belongs to one configured list,
        not to code that silently believes a header.
        """
        import inspect

        import auth.router as auth_router

        source = inspect.getsource(auth_router._client_ip)
        # The body only: the docstring discusses X-Forwarded-For at length,
        # which is the whole point of the note, so matching it here would
        # make this test fail every time the explanation is improved.
        body = source.split('"""', 2)[2]
        assert "x-forwarded-for" not in body.lower(), (
            "_client_ip must read request.client.host only; trusting a header "
            "here would bypass uvicorn's forwarded_allow_ips allowlist"
        )
        assert "headers" not in body.lower()
        assert "request.client" in body

        _set_mode(monkeypatch, "open")
        monkeypatch.setenv("RATE_LIMIT_SIGNUP", "2")
        get_settings.cache_clear()
        for index in range(2):
            await client.post(
                "/auth/signup", json={"email": f"xff{index}@test.dev", "password": "password123"}
            )
        blocked = await client.post(
            "/auth/signup", json={"email": "xff9@test.dev", "password": "password123"}
        )
        assert blocked.status_code == 429, "the per-IP budget still has to hold"

    def test_an_unknown_client_yields_no_bucket_rather_than_a_shared_one(self) -> None:
        """`None` must not become the string "None" and pool every
        client-less request into one bucket, where one caller would throttle
        everybody."""
        from auth.router import _client_ip

        class _NoClient:
            client = None

        assert _client_ip(_NoClient()) is None  # type: ignore[arg-type]


class _FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


# --- run creation is limited too -------------------------------------------


class TestRunRateLimit:
    """Run creation is rate-limited too (item 4).

    These do NOT drive `POST /chats/{id}/runs` end to end: that route starts a
    real background run, whose worker holds database locks, and the next
    test's `TRUNCATE` then deadlocks against them — measured, not assumed,
    and the same shape as KI-15. The limiter's semantics for the `run` scope
    are covered directly, and the wiring is covered by the source assertion
    below.
    """

    def test_the_run_scope_is_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RATE_LIMIT_RUN", "2")
        monkeypatch.setenv("RATE_LIMIT_RUN_WINDOW_SECONDS", "60")
        get_settings.cache_clear()
        ratelimit.reset_all()
        ratelimit.enforce("run", ip="10.0.0.1")
        ratelimit.enforce("run", ip="10.0.0.1")
        with pytest.raises(ratelimit.RateLimited) as limited:
            ratelimit.enforce("run", ip="10.0.0.1")
        assert limited.value.status_code == 429
        assert limited.value.retry_after >= 1
        detail = limited.value.detail
        assert isinstance(detail, dict)
        assert detail["scope"] == "run"

    def test_the_run_limit_counts_per_user_as_well_as_per_ip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rotating IPs must not buy a fresh budget per account."""
        monkeypatch.setenv("RATE_LIMIT_RUN", "2")
        get_settings.cache_clear()
        ratelimit.reset_all()
        for index in range(2):
            ratelimit.enforce("run", ip=f"10.0.0.{index}", user_id="user-1")
        with pytest.raises(ratelimit.RateLimited):
            ratelimit.enforce("run", ip="10.0.0.99", user_id="user-1")

    def test_the_run_route_calls_the_limiter(self) -> None:
        import inspect

        import chats.router as chats_router

        source = inspect.getsource(chats_router.create_run)
        assert 'ratelimit.enforce("run"' in source, (
            "run creation is no longer rate-limited"
        )
        # Before any work, so a throttled request writes no rows and reserves
        # no credit.
        body = source.split('ratelimit.enforce("run"', 1)[1]
        first_statement = body.lstrip().splitlines()[0]
        assert first_statement.rstrip().endswith(")"), (
            f"the limiter is not the first statement of the route: {first_statement!r}"
        )


# --- google follows the same rule -----------------------------------------


class TestGoogleFirstTime:
    """Google proves the account with Google, not that the person was
    invited. Without this rule `signup_mode=invite` is open to anyone with any
    Google account and the mode is decorative.

    Driven at the service layer rather than through the redirect handler: the
    handler's first branches are the OAuth state check and the token exchange,
    so a test that reaches the invite logic has to fake all of that, and a test
    that fakes all of that is mostly testing its own fakes.
    """

    @pytest.mark.asyncio
    async def test_a_first_time_google_account_consumes_an_invite(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "invite")
        admin = await _admin(db)
        _invite, code = await _mint(db, admin)

        plan_id = await _free_plan_id(db)
        user = User(email="newgoogle@test.dev", password_hash=None, role="user", plan_id=plan_id)
        db.add(user)
        await db.flush()
        await invites.attach_google_first_time(session=db, code=code, user=user)
        await db.commit()

        again = User(email="other@test.dev", password_hash=None, role="user", plan_id=plan_id)
        db.add(again)
        await db.flush()
        with pytest.raises(invites.InviteInvalid):
            await invites.attach_google_first_time(session=db, code=code, user=again)
        await db.rollback()

    @pytest.mark.asyncio
    async def test_the_google_callback_is_gated_before_creating_a_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wiring, asserted on the handler's source.

        A source assertion is weak on its own and is here deliberately: the
        behaviour is covered above, and this pins the one thing a
        service-layer test cannot see — that the route actually calls the
        gate. If someone deletes the call from the handler, this fails and
        the comment above explains why the deletion is a security regression
        even though the helper still exists.
        """
        import inspect

        import auth.router as router

        source = inspect.getsource(router.google_callback)
        assert "attach_google_first_time" in source, (
            "the Google callback no longer gates first-time accounts on an "
            "invite, so signup_mode=invite is bypassable with any Google account"
        )
        assert "signup_closed" in source


async def _free_plan_id(db: Any) -> Any:
    from sqlalchemy import select

    from db.models import Plan

    return (await db.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()


# --- admin surface ---------------------------------------------------------


class TestAdminInvites:
    @pytest.mark.asyncio
    async def test_admin_can_mint_list_and_revoke(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "invite")
        created = await admin_client.post(
            "/admin/invites", json={"count": 3, "note": "for the reviewers"}
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert len(body) == 3
        codes = [row["code"] for row in body]
        assert all(codes), "the minting response must carry the plaintext"
        assert len(set(codes)) == 3, "codes must be distinct"
        assert all(row["status"] == "live" for row in body)

        listed = await admin_client.get("/admin/invites")
        assert listed.status_code == 200
        assert len(listed.json()) == 3
        # A later read carries no plaintext: it is not stored, so there is
        # nothing to show.
        assert all(row["code"] == "" for row in listed.json())

        revoked = await admin_client.post(f"/admin/invites/{body[0]['id']}/revoke")
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"

        after = await admin_client.get("/admin/invites")
        statuses = {row["id"]: row["status"] for row in after.json()}
        assert statuses[body[0]["id"]] == "revoked"
        assert statuses[body[1]["id"]] == "live"

    @pytest.mark.asyncio
    async def test_invite_actions_are_audited(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "invite")
        created = await admin_client.post("/admin/invites", json={"count": 1})
        invite_id = created.json()[0]["id"]
        await admin_client.post(f"/admin/invites/{invite_id}/revoke")

        audit = await admin_client.get("/admin/audit")
        actions = [row["action"] for row in audit.json()]
        assert "invite.create" in actions
        assert "invite.revoke" in actions

    @pytest.mark.asyncio
    async def test_the_audit_row_never_carries_the_code(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The audit log is readable by every admin forever; a credential in
        it defeats storing the code hashed."""
        _set_mode(monkeypatch, "invite")
        created = await admin_client.post("/admin/invites", json={"count": 1, "note": "beta"})
        code = created.json()[0]["code"]
        audit = await admin_client.get("/admin/audit")
        assert code not in audit.text

    @pytest.mark.asyncio
    async def test_a_non_admin_cannot_mint_invites(self, client: Any) -> None:
        response = await client.post("/admin/invites", json={"count": 1})
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_there_is_no_unauthenticated_invite_route(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An endpoint that can mint an account without a credential is the
        attack surface item 4 exists to close."""
        _set_mode(monkeypatch, "invite")
        for path in ("/invites", "/auth/invites", "/admin/invite"):
            response = await client.post(path, json={})
            assert response.status_code in (401, 403, 404, 405), path

    @pytest.mark.asyncio
    async def test_a_batch_count_is_capped(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_mode(monkeypatch, "invite")
        response = await admin_client.post("/admin/invites", json={"count": 5000})
        assert response.status_code == 422


class TestRevokeIsIdempotent:
    @pytest.mark.asyncio
    async def test_revoking_twice_is_not_an_error(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The operator's intent — "this must not work" — is already satisfied,
        and a second revocation usually means a retry."""
        _set_mode(monkeypatch, "invite")
        created = await admin_client.post("/admin/invites", json={"count": 1})
        invite_id = created.json()[0]["id"]
        first = await admin_client.post(f"/admin/invites/{invite_id}/revoke")
        second = await admin_client.post(f"/admin/invites/{invite_id}/revoke")
        assert first.status_code == second.status_code == 200
        assert second.json()["status"] == "revoked"

    @pytest.mark.asyncio
    async def test_revoking_an_unknown_invite_is_404(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4

        _set_mode(monkeypatch, "invite")
        response = await admin_client.post(f"/admin/invites/{uuid4()}/revoke")
        assert response.status_code == 404


class TestStatusPrecedence:
    def test_revoked_reads_as_revoked_even_if_used(self) -> None:
        """Revoking a code someone already used is a legitimate operator
        action and should read as "void", not as "spent"."""
        from datetime import UTC, datetime, timedelta

        invite = Invite(
            code="",
            code_hash="h",
            created_by=uuid4(),
            used_by=None,
            used_at=datetime.now(UTC),
            revoked_at=datetime.now(UTC),
        )
        assert invites.status_of(invite) == "revoked"
        much_later = datetime.now(UTC) + timedelta(days=365)
        assert invites.status_of(invite, now=much_later) == "revoked"