"""Ephemeral demo accounts (lane E item 4, PRD AC-2).

A visitor can try the product without signing up. That is one unauthenticated
endpoint that mints an account and can spend provider credit, so everything
about it is deliberately small and everything about it is bounded by the
existing machinery rather than a new mechanism:

- **Rate limit, per IP**, from `demo/settings.py`. Enforced before any write,
  like every other limited route (chats/router.py).
- **A plan, not a bespoke budget.** The demo account is put on the `demo`
  plan, so its quota is enforced by the existing gate (`gate_and_reserve`) —
  the same code path a real user's is. A special case here would be a second
  quota implementation, and the wrong one to be wrong in.
- **A role the product already understands.** `demo` exists in the enum and
  `deny_read_only` (ingest/upload.py) already refuses it uploads, so "no
  uploads" is the product's existing rule, not a new one. Deep and web are
  refused here for the same reason and by the same shape of check.
- **A cleanup task**, because an account that is never deleted is a pile of
  rows nobody will look at again.

The account has no password, so it cannot be logged into later: `password_hash`
is NULL, which is already how Google-only accounts are represented, and login
already refuses them (`auth/router.py`: `user.password_hash is None`).

What this module does NOT do, stated so the omission is deliberate:

- **It does not create the plan.** `make seed-demo` does. A route that created
  its own plan on demand would let a typo in a plan name mint an unlimited
  account, and the plan's limits would then depend on request timing.
- **It does not check the Shared library has the books.** Also the seed's job.
  A demo account with nothing to read is a confusing first minute, but it is
  not a safety problem, and this route is the wrong place to diagnose the
  corpus.
- **It does not promise the sixth question (a Deep run).** Whether a demo
  account may use Deep is `DEMO_ALLOW_DEEP`, off by default, and the plan's
  credit limit is what actually bounds it either way.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Plan, RefreshToken, UsageLedger, User
from demo.settings import DemoSettings, demo_settings

DEMO_EMAIL_PREFIX = "demo-"
# `.test` (RFC 6761) is a reserved TLD that can never be registered, so the
# address cannot receive a password reset even if some future code path tried.
# `.invalid` would read better and is equally reserved, but `email_validator`
# — which `schemas/auth.py` uses, and rightly — rejects special-use domains
# outright, so the response model would 500 on a valid user.
DEMO_EMAIL_DOMAIN = "demo.veriforge.test"


class DemoUnavailable(Exception):
    """The `demo` plan is missing — `make seed-demo` has not been run."""


class DemoCapacityReached(Exception):
    """The rolling 24 h cap on new demo accounts is already spent.

    Carries `retry_after` so the route can set `Retry-After` the way the
    per-IP limiter does, rather than answering 429 with no idea when.
    """

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _demo_email() -> str:
    """A random address, so two visitors never collide on one account and the
    address itself says what it is when an operator reads the users table."""
    return f"{DEMO_EMAIL_PREFIX}{secrets.token_hex(8)}@{DEMO_EMAIL_DOMAIN}"


async def create_demo_user(session: AsyncSession, settings: DemoSettings) -> User:
    """One ephemeral demo account on the `demo` plan, within the daily cap.

    Commits before returning: the route then issues a refresh token, and a
    refresh cookie outlives the request. Failing the commit afterwards would
    hand a browser a session for a row that is not there.

    **The cap check and the insert are one atomic step** (KI-63), and the
    mechanism is a `SELECT … FOR UPDATE` on the demo *plan* row. Why that row:

    - The cap is a single global number, so it needs a single global lock. A
      per-IP or per-user lock would bound nothing: the thing being stopped is
      many different addresses at once, which is the whole failure mode.
    - The plan row is exactly one row, it always exists (the plan is
      referenced, and a missing plan is already a loud 503 above), and it is
      never deleted while the demo is on — `purge_expired` deletes users, and
      the seeder only inserts the plan `ON CONFLICT DO NOTHING`.
    - It reuses the shape `quota/service.py` already uses for the same job
      (`_limits(..., lock=True)`), so there is no new locking idiom to learn.

    A plain `SELECT count(*)` then `INSERT` cannot work: two requests at
    cap-1 both read cap-1, both decide there is room, and both insert. The
    lock makes the second one wait, and it re-reads the count *after* the
    first has committed — so it sees the new row and refuses.

    Proven by `tests/demo/test_demo_mode.py::test_the_cap_check_and_the_
    insert_are_one_atomic_step`, which holds one creator between its count
    read and its commit and shows the other cannot read until the first has
    committed. Both `asyncio.gather` formulations that look equivalent were
    measured on this branch and neither held: two HTTP requests passed 12 runs
    out of 12 without the lock, and two service-level sessions managed about
    6 in 8. A concurrency test that cannot fail without the fix is decoration
    (KI-61).
    """
    plan = (
        await session.execute(
            select(Plan).where(Plan.name == settings.plan_name).with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None:
        # Named rather than defaulting: an account silently created on `free`
        # would give every demo visitor a 200k-credit budget, which is the
        # opposite of the point of the demo plan.
        raise DemoUnavailable(
            f"plan {settings.plan_name!r} does not exist; run `make seed-demo`"
        )
    await check_daily_capacity(session, settings)
    user = User(
        email=_demo_email(),
        password_hash=None,
        role="demo",
        plan_id=plan.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def check_daily_capacity(
    session: AsyncSession, settings: DemoSettings, *, now: datetime | None = None
) -> int:
    """How many demo accounts exist in the window; raise if the cap is spent.

    Takes `now` for the same reason `is_expired` does — so a test can ask
    about a specific instant instead of the one this process happens to be
    running at, and so the rolling window is answerable without a fixture
    that lies about the clock.

    Called with the plan row already locked by `create_demo_user`; calling it
    standalone is safe (it only reads) but then the check is not atomic with
    any insert.
    """
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(hours=settings.cap_window_hours)
    used = await demo_accounts_in_window(session, cutoff=cutoff)
    if used >= settings.daily_cap:
        raise DemoCapacityReached(
            f"{used} demo account(s) already created in the last "
            f"{settings.cap_window_hours:g}h; the cap is {settings.daily_cap}",
            retry_after=await seconds_until_capacity(
                session, settings, now=current
            ),
        )
    return used


async def seconds_until_capacity(
    session: AsyncSession, settings: DemoSettings, *, now: datetime | None = None
) -> int:
    """Seconds until the oldest account in the window ages out of it.

    That is the earliest moment the next request can be served, so it is the
    honest `Retry-After`: the cap frees up from the *front* of the window, not
    all at once, and the front is what is nearly expired.

    At least 1, never 0 — a `Retry-After: 0` reads as "immediately", which is
    the opposite of true and invites exactly the hammering the cap exists to
    stop.
    """
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(hours=settings.cap_window_hours)
    oldest = await session.scalar(
        select(func.min(User.created_at)).where(User.role == "demo", User.created_at >= cutoff)
    )
    if oldest is None:
        return 1
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    frees_at = oldest + timedelta(hours=settings.cap_window_hours)
    return max(1, round((frees_at - current).total_seconds()))


async def demo_accounts_in_window(
    session: AsyncSession, *, cutoff: datetime
) -> int:
    """Demo-role accounts created at or after `cutoff`.

    `role == 'demo'` rather than an email pattern: the role is what the
    product enforces everywhere else, and matching on the address would miss
    an account whose row was written by the seeder or an admin script.
    """
    return int(
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "demo", User.created_at >= cutoff)
        )
        or 0
    )


async def is_expired(user: User, settings: DemoSettings, *, now: datetime | None = None) -> bool:
    """Whether this demo account is past its TTL.

    Takes the settings explicitly rather than reading the environment inside,
    so a test can ask the question about a specific TTL instead of the one
    this process happens to be running with.
    """
    current = now or datetime.now(UTC)
    created = user.created_at
    if created.tzinfo is None:
        # Postgres returns naive timestamps for `timestamptz` on some paths;
        # comparing a naive value to an aware one raises rather than answering.
        created = created.replace(tzinfo=UTC)
    return current - created > timedelta(hours=settings.ttl_hours)


async def purge_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete demo accounts past their TTL, with everything that hangs off them.

    Returns the number of users removed, so the caller can log it. Idempotent
    and safe to run twice: it only ever matches accounts that are already too
    old to be in use.

    `ondelete=CASCADE` on the foreign keys does the chat, message, citation,
    run, run_event, document, chunk and token rows — `documents` is included so
    a demo upload, if the role check is ever weakened, does not leave chunks
    behind. Usage ledger rows are deleted explicitly rather than relying on the
    cascade, because they are how the operator sees what the tour cost.
    """
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(hours=demo_settings().ttl_hours)
    expired = list(
        (
            await session.execute(
                select(User.id).where(User.role == "demo", User.created_at < cutoff)
            )
        )
        .scalars()
        .all()
    )
    if not expired:
        return 0
    await session.execute(delete(UsageLedger).where(UsageLedger.user_id.in_(expired)))
    await session.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(expired)))
    await session.execute(delete(User).where(User.id.in_(expired)))
    await session.commit()
    # The count of what we selected, not a rowcount: this reads the same on
    # every driver, and the SELECT above already decided the answer.
    return len(expired)


async def demo_account_count(session: AsyncSession) -> int:
    """How many demo accounts exist now. Used by tests that need to assert the
    sweep removed exactly the right ones."""
    return int(
        await session.scalar(select(func.count()).select_from(User).where(User.role == "demo")) or 0
    )