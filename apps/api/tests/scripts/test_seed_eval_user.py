"""`seed_eval_user` must commit, must verify the password, and must assign the
`internal-eval` plan once (KI-24).

The AW-2000 and counterfactual corpora are private collections owned by
`evals@example.com`, so acceptance signs in as that account. The account has
no HTTP path to its own creation — signup always mints a new address — so this
script is how the credential exists at all, exactly as `seed_admin.py` is how
the local admin does.

The same failure `seed_admin.py` had is worth guarding here: `flush()` without a
commit prints success and leaves no row. Both assertions are made against a
*fresh* session, the only thing that can tell a committed row from a flushed one.
"""

import importlib

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Plan, User
from evals.loader import EVAL_USER_EMAIL

seed_eval_user = importlib.import_module("scripts.seed_eval_user")

EVAL_PASSWORD = "SeededEvalUser!234"


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_USER_PASSWORD", EVAL_PASSWORD)
    monkeypatch.delenv("EVAL_USER_EMAIL", raising=False)


@pytest.fixture(autouse=True)
async def internal_eval_plan(db: AsyncSession) -> str:
    """Migration 0014 seeds `internal-eval`, but the suite TRUNCATEs `plans`
    between tests and re-seeds only `free` and `pro` — so the row the script
    looks for is gone unless a test puts it back. That is a property of the
    harness, not of the script."""
    from db.models import Plan

    existing = (
        await db.execute(select(Plan).where(Plan.name == "internal-eval"))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Plan(name="internal-eval", credits_5h=20000000, credits_month=200000000))
        await db.commit()
    return "internal-eval"


async def test_seeding_creates_a_committed_account_whose_password_verifies(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auth.passwords import verify_password
    from db.session import get_session_factory

    await seed_eval_user.seed()

    factory = get_session_factory()
    async with factory() as verify:
        user = (
            await verify.execute(select(User).where(User.email == EVAL_USER_EMAIL))
        ).scalar_one_or_none()
    assert user is not None, "seed_eval_user reported success but committed no row"
    assert user.password_hash is not None
    assert verify_password(EVAL_PASSWORD, user.password_hash)
    assert user.status == "active"


async def test_the_plan_is_the_seeded_internal_eval_row(db: AsyncSession) -> None:
    """Not `free` and not `pro`: those are rows real users are on (KI-20)."""
    from db.session import get_session_factory

    await seed_eval_user.seed()

    factory = get_session_factory()
    async with factory() as verify:
        user = (
            await verify.execute(select(User).where(User.email == EVAL_USER_EMAIL))
        ).scalar_one()
        plan = (await verify.execute(select(Plan).where(Plan.id == user.plan_id))).scalar_one()
    assert plan.name == "internal-eval"


async def test_seeding_is_idempotent_and_resets_a_rotated_password(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second run must not duplicate the account, and re-setting the password
    is the credential-rotation path — the eval user is now persistent."""
    from auth.passwords import verify_password
    from db.session import get_session_factory

    await seed_eval_user.seed()
    monkeypatch.setenv("EVAL_USER_PASSWORD", "RotatedEvalUser!234")
    await seed_eval_user.seed()

    factory = get_session_factory()
    async with factory() as verify:
        count = (
            await verify.execute(
                select(func.count()).select_from(User).where(User.email == EVAL_USER_EMAIL)
            )
        ).scalar_one()
        user = (
            await verify.execute(select(User).where(User.email == EVAL_USER_EMAIL))
        ).scalar_one()
    assert count == 1
    assert user.password_hash is not None
    assert verify_password("RotatedEvalUser!234", user.password_hash)


async def test_a_missing_credential_stops_instead_of_inventing_one(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVAL_USER_PASSWORD", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        await seed_eval_user.seed()
    assert "EVAL_USER_PASSWORD" in str(excinfo.value)


async def test_an_email_override_that_is_not_the_corpus_owner_is_refused(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner resolves the corpus owner by `EVAL_USER_EMAIL` in
    evals/loader.py, so a second address here would own nothing and the run
    would silently score an empty scope."""
    monkeypatch.setenv("EVAL_USER_EMAIL", "someone-else@example.com")
    with pytest.raises(SystemExit) as excinfo:
        await seed_eval_user.seed()
    assert "someone-else@example.com" in str(excinfo.value)


async def test_seeding_writes_no_credit_limits(db: AsyncSession) -> None:
    before = {
        p.name: (p.credits_5h, p.credits_month) for p in (await db.execute(select(Plan))).scalars()
    }
    await seed_eval_user.seed()
    after = {
        p.name: (p.credits_5h, p.credits_month) for p in (await db.execute(select(Plan))).scalars()
    }
    assert after == before


def test_the_eval_user_address_can_actually_be_signed_in_with() -> None:
    """The account's address must pass the product's own email validation.

    `evals@veriforge.local` did not: `email_validator` rejects special-use and
    reserved domains, so the account was creatable in the database but could
    never complete `/auth/login`, which is precisely what acceptance does. The
    failure surfaced only on the first live acceptance run, after the whole
    stack was standing — a fixture that looks fine until the one call that
    matters.
    """
    from email_validator import EmailNotValidError, validate_email

    try:
        validate_email(EVAL_USER_EMAIL, check_deliverability=False)
    except EmailNotValidError as exc:  # pragma: no cover - the failure itself
        pytest.fail(f"{EVAL_USER_EMAIL} cannot be signed in with: {exc}")
