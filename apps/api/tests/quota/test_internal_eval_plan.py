"""The seeded `internal-eval` plan carries a full acceptance run's headroom.

A full acceptance run costs about 310k quota credits (KI-20) against `free`'s
200k per 5 h window, which is why runs used to raise `free`'s limit by hand.
The plan exists so they stop, and these pin the two facts that make it work:
it is seeded by migration (so a fresh database has it, including the
ephemeral one `make eval-gate-local` builds), and its limits are above a full
run — while `free` and `pro` keep exactly the limits they always had.

The suite's `autouse` fixture truncates `plans` and re-seeds `free`/`pro`, so
these run the migration's own statements rather than trusting a leftover row.
"""

import importlib
from types import ModuleType

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Plan

# Alembic version modules are named `0014_…`, which is not an importable
# identifier, so they are loaded by path.
migration: ModuleType = importlib.import_module("db.migrations.versions.0014_internal_eval_plan")

# KI-20's measured cost of one full 47-item acceptance run, with room over it.
FULL_ACCEPTANCE_COST = 310_000


async def _seed(session: AsyncSession) -> None:
    # The migration's own statements, run through a session instead of
    # alembic's `op`, so this is the SQL that ships rather than a copy of it.
    await session.execute(text(migration.INSERT_PLAN))


async def test_the_plan_exists_after_seeding(db: AsyncSession) -> None:
    await _seed(db)
    await db.flush()
    plan = (
        await db.execute(select(Plan).where(Plan.name == migration.PLAN_NAME))
    ).scalar_one_or_none()
    assert plan is not None
    assert plan.credits_5h == migration.CREDITS_5H
    assert plan.credits_month == migration.CREDITS_MONTH


async def test_the_seeded_plan_covers_a_full_acceptance_run(db: AsyncSession) -> None:
    """The whole point: the 5 h window has to survive ~310k of spend."""
    await _seed(db)
    await db.flush()
    plan = (await db.execute(select(Plan).where(Plan.name == migration.PLAN_NAME))).scalar_one()
    assert plan.credits_5h >= FULL_ACCEPTANCE_COST * 2
    assert plan.credits_month >= FULL_ACCEPTANCE_COST * 2


async def test_seeding_is_idempotent_and_keeps_an_edited_limit(db: AsyncSession) -> None:
    """`ON CONFLICT (name) DO NOTHING`: a rerun must not reset a tuned row,
    which is what makes the migration safe to replay on an existing database."""
    await _seed(db)
    await db.flush()
    plan = (await db.execute(select(Plan).where(Plan.name == migration.PLAN_NAME))).scalar_one()
    plan.credits_5h = 7
    await db.flush()

    await _seed(db)
    await db.flush()
    rows = (await db.execute(select(Plan).where(Plan.name == migration.PLAN_NAME))).scalars().all()
    assert len(rows) == 1
    assert rows[0].credits_5h == 7


@pytest.mark.parametrize("name", ["free", "pro"])
async def test_free_and_pro_keep_their_documented_limits(db: AsyncSession, name: str) -> None:
    """The real users' rows. Migration 0014 adds a plan; it does not retune
    these, and nothing in the acceptance path writes them."""
    await _seed(db)
    await db.flush()
    plan = (await db.execute(select(Plan).where(Plan.name == name))).scalar_one()
    assert (plan.credits_5h, plan.credits_month) == (200000, 2000000)


async def test_a_new_signup_still_lands_on_free(db: AsyncSession) -> None:
    """`_default_plan_id` picks `free` by name, so the new plan is opt-in and
    cannot be signed up onto by accident."""
    from auth.router import _default_plan_id

    await _seed(db)
    await db.flush()
    free = (await db.execute(select(Plan).where(Plan.name == "free"))).scalar_one()
    assert await _default_plan_id(db) == free.id
