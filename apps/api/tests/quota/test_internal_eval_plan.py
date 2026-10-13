"""The seeded `internal-eval` plan carries a full acceptance run's headroom.

A full acceptance run costs about 310k quota credits against `free`'s 200k per
5 h window, so a run against `free` runs out mid-run. The plan exists so it
does not have to, and these pin the two facts that make it work: the baseline
seeds it (so a fresh database has it, including the ephemeral one
`make eval-gate-local` builds), and its limits are above a full run — while
`free` and `pro` keep exactly the limits they always had.

The suite's `autouse` fixture truncates `plans` and re-seeds `free`/`pro`, so
these run the baseline's own statement rather than trusting a leftover row.
"""

import importlib
from types import ModuleType

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Plan

# Alembic version modules are named `0001_baseline`, which is not an importable
# identifier, so they are loaded by name.
baseline: ModuleType = importlib.import_module("db.migrations.versions.0001_baseline")

FULL_ACCEPTANCE_COST = 310_000
EVAL_PLAN = next(row for row in baseline.PLANS if row[0] == "internal-eval")


async def _seed(session: AsyncSession) -> None:
    # The baseline's own statement, run through a session instead of alembic's
    # `op`, so this is the SQL that ships rather than a copy of it.
    await session.execute(
        text(baseline.INSERT_PLAN),
        {"name": EVAL_PLAN[0], "credits_5h": EVAL_PLAN[1], "credits_month": EVAL_PLAN[2]},
    )


async def test_the_plan_exists_after_seeding(db: AsyncSession) -> None:
    await _seed(db)
    await db.flush()
    plan = (await db.execute(select(Plan).where(Plan.name == EVAL_PLAN[0]))).scalar_one_or_none()
    assert plan is not None
    assert plan.credits_5h == EVAL_PLAN[1]
    assert plan.credits_month == EVAL_PLAN[2]


async def test_the_seeded_plan_covers_a_full_acceptance_run(db: AsyncSession) -> None:
    """The whole point: the 5 h window has to survive ~310k of spend."""
    await _seed(db)
    await db.flush()
    plan = (await db.execute(select(Plan).where(Plan.name == EVAL_PLAN[0]))).scalar_one()
    assert plan.credits_5h >= FULL_ACCEPTANCE_COST * 2
    assert plan.credits_month >= FULL_ACCEPTANCE_COST * 2


async def test_seeding_is_idempotent_and_keeps_an_edited_limit(db: AsyncSession) -> None:
    """`ON CONFLICT (name) DO NOTHING`: a rerun must not reset a tuned row,
    which is what makes the seed safe to replay on an existing database."""
    await _seed(db)
    await db.flush()
    plan = (await db.execute(select(Plan).where(Plan.name == EVAL_PLAN[0]))).scalar_one()
    plan.credits_5h = 7
    await db.flush()

    await _seed(db)
    await db.flush()
    rows = (await db.execute(select(Plan).where(Plan.name == EVAL_PLAN[0]))).scalars().all()
    assert len(rows) == 1
    assert rows[0].credits_5h == 7


@pytest.mark.parametrize("name", ["free", "pro"])
async def test_free_and_pro_keep_their_documented_limits(db: AsyncSession, name: str) -> None:
    """The real users' rows. The baseline seeds all three plans; nothing in the
    acceptance path writes these two."""
    await _seed(db)
    await db.flush()
    plan = (await db.execute(select(Plan).where(Plan.name == name))).scalar_one()
    assert (plan.credits_5h, plan.credits_month) == (200000, 2000000)


async def test_a_new_signup_still_lands_on_free(db: AsyncSession) -> None:
    """`_default_plan_id` picks `free` by name, so the eval plan is opt-in and
    cannot be signed up onto by accident."""
    from auth.router import _default_plan_id

    await _seed(db)
    await db.flush()
    free = (await db.execute(select(Plan).where(Plan.name == "free"))).scalar_one()
    assert await _default_plan_id(db) == free.id
