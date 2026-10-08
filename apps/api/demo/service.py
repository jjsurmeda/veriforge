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


def _demo_email() -> str:
    """A random address, so two visitors never collide on one account and the
    address itself says what it is when an operator reads the users table."""
    return f"{DEMO_EMAIL_PREFIX}{secrets.token_hex(8)}@{DEMO_EMAIL_DOMAIN}"


async def create_demo_user(session: AsyncSession, settings: DemoSettings) -> User:
    """One ephemeral demo account on the `demo` plan.

    Commits before returning: the route then issues a refresh token, and a
    refresh cookie outlives the request. Failing the commit afterwards would
    hand a browser a session for a row that is not there.
    """
    plan = (
        await session.execute(select(Plan).where(Plan.name == settings.plan_name))
    ).scalar_one_or_none()
    if plan is None:
        # Named rather than defaulting: an account silently created on `free`
        # would give every demo visitor a 200k-credit budget, which is the
        # opposite of the point of the demo plan.
        raise DemoUnavailable(
            f"plan {settings.plan_name!r} does not exist; run `make seed-demo`"
        )
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