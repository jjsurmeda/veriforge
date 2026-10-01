"""`seed_admin` must commit, and must not touch a plan's credits.

There is no admin bootstrap in the product (signup hardcodes `role="user"`,
and only an admin can grant the role), so this script is how the local admin
`make acceptance` signs in as exists.

The commit test is here because the first version of the script called
`flush()` and printed "created admin" while the transaction was thrown away
with the session — the row never landed. It only showed up because the login
that follows failed. So: the assertion is on a *fresh* session, which is the
only thing that can tell a committed row from a flushed one.
"""

import importlib

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Plan, User

seed_admin = importlib.import_module("scripts.seed_admin")

ADMIN_EMAIL = "seeded-admin@example.com"
ADMIN_PASSWORD = "SeededAdmin!234"


async def _seed(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", env.get("email", ADMIN_EMAIL))
    if "password" in env:
        monkeypatch.setenv("ADMIN_PASSWORD", env["password"])
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    await seed_admin.seed()


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)


async def test_seeding_creates_an_admin_that_survives_the_session(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row must be committed, not merely flushed."""
    from db.session import get_session_factory

    await _seed(monkeypatch)

    factory = get_session_factory()
    async with factory() as verify:
        user = (
            await verify.execute(select(User).where(User.email == ADMIN_EMAIL))
        ).scalar_one_or_none()
    assert user is not None, "seed_admin reported success but committed no row"
    assert user.role == "admin"
    assert user.status == "active"


async def test_the_password_verifies_against_the_committed_hash(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed row with the wrong hash is the same failure wearing a
    different hat, so check the hash the way the login path does."""
    from auth.passwords import verify_password
    from db.session import get_session_factory

    await _seed(monkeypatch)

    factory = get_session_factory()
    async with factory() as verify:
        user = (await verify.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one()
        assert user.password_hash is not None
        assert verify_password(ADMIN_PASSWORD, user.password_hash)


async def test_seeding_is_idempotent_and_promotes_an_existing_user(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second run must not create a duplicate, and must fix an account that
    exists but is not an admin — that is the password-rotation path."""
    from db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session, session.begin():
        plan = (await session.execute(select(Plan).where(Plan.name == "free"))).scalar_one()
        session.add(
            User(
                email=ADMIN_EMAIL,
                password_hash="not-a-real-hash",
                role="user",
                status="active",
                plan_id=plan.id,
            )
        )

    await _seed(monkeypatch)
    await _seed(monkeypatch)

    async with factory() as verify:
        count = (
            await verify.execute(
                select(func.count()).select_from(User).where(User.email == ADMIN_EMAIL)
            )
        ).scalar_one()
        user = (await verify.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one()
    assert count == 1
    assert user.role == "admin"


async def test_a_missing_credential_stops_instead_of_inventing_one(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No admin without a credential: the script must not guess an address or
    a password, because the next thing to happen is a login attempt."""
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        await seed_admin.seed()
    assert "ADMIN_PASSWORD" in str(excinfo.value)


async def test_seeding_writes_no_plan(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`free` and `pro` are rows real users are on, and this script exists so
    the acceptance path stops touching them."""
    before = {
        name: (credits_5h, credits_month)
        for name, credits_5h, credits_month in (
            (p.name, p.credits_5h, p.credits_month)
            for p in (await db.execute(select(Plan))).scalars()
        )
    }
    await _seed(monkeypatch)
    after = {
        name: (credits_5h, credits_month)
        for name, credits_5h, credits_month in (
            (p.name, p.credits_5h, p.credits_month)
            for p in (await db.execute(select(Plan))).scalars()
        )
    }
    assert after == before
