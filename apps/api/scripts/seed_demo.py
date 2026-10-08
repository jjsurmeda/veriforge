"""Create the `demo` plan demo accounts run on, and check the corpus (item 4).

Idempotent, and it never touches `free`, `pro` or `internal-eval`. Those are
seeded by migrations; this is an operator action for a beta, in the same
family as `seed_admin.py` — it creates one row and then reports what it found.

The plan's numbers are the budget. A demo account gets no special quota code
path: `gate_and_reserve` reads `plans.credits_5h` like any other account, so
the limit here is the whole enforcement mechanism and there is deliberately no
second one to drift.

- **A few runs.** 12 000 credits in 5 h against an Auto reservation of ~8 000
  (`quota/service.py`'s `DEFAULT_ESTIMATES`) means one or two answers before
  the gate refuses. That is the shape of "a few runs": the visitor sees the
  quota work rather than a wall.
- **Monthly is much larger**, on purpose. The 5 h window is what bounds a
  single visitor; the month exists to stop one address farming accounts all
  afternoon, not to be the limit anyone reaches in a beta week.

Then it checks the Shared library actually holds the books, because a demo
account with nothing to read is a confusing first minute. That is a *report*,
not a fix: seeding the corpus is `make seed-books`, and this script must not
quietly start embedding documents (which spends money).

Usage: `uv run python scripts/seed_demo.py` (or `make seed-demo`).
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from db.models import Collection, Document, Plan
from db.session import get_session_factory

PLAN_NAME = "demo"
# Measured, not guessed. An Auto run reserves ~8 000 credits
# (`quota/service.py`'s DEFAULT_ESTIMATES) against this, so a first pass at
# "a few runs" (12 000) bought exactly one: the tour's second question was
# refused by the gate mid-rehearsal, which is the gate working and the number
# being wrong. 60 000 covers the six tour questions with a little room, and a
# visitor who keeps going still meets the quota wall — which is the better
# demonstration anyway, because it shows the limit is real.
CREDITS_5H = 60_000
CREDITS_MONTH = 400_000

# Only documents a retrieval can return count as "in the library": claiming a
# still-parsing upload would answer with something a visitor cannot search
# yet. The same rule as `chats/scope.py`'s SEARCHABLE_STATUSES.
READY_STATUS = "ready"

# How the seeded corpora are named (`scripts/seed_gutenberg.py`, and the eval
# sets under `evals/`). Used only to warn, never to act.
EVAL_NAME_MARKER = "eval"


async def seed() -> None:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        plan = (
            await session.execute(select(Plan).where(Plan.name == PLAN_NAME))
        ).scalar_one_or_none()
        if plan is None:
            session.add(
                Plan(name=PLAN_NAME, credits_5h=CREDITS_5H, credits_month=CREDITS_MONTH)
            )
            action = "created"
        else:
            # Re-set, so an operator who tuned the limits during the beta gets
            # them back if they rerun — and so a demo plan that was created with
            # the wrong numbers can be fixed without a migration.
            plan.credits_5h = CREDITS_5H
            plan.credits_month = CREDITS_MONTH
            action = "updated"
        await session.flush()
        print(
            f"{action} plan {PLAN_NAME!r}: {CREDITS_5H:,} credits / 5 h, "
            f"{CREDITS_MONTH:,} / month"
        )

    async with factory() as session:
        shared = (
            await session.execute(
                select(Collection).where(Collection.visibility == "shared")
            )
        ).scalars().all()
        if not shared:
            print(
                "\nNo Shared collection exists, so a demo account would have "
                "nothing to read.\n  Fix: make seed-books"
            )
            return
        names = sorted(collection.name for collection in shared)
        ready = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(
                        Document.collection_id.in_([c.id for c in shared]),
                        Document.status == READY_STATUS,
                    )
                )
            ).scalar_one()
        )
        total = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.collection_id.in_([c.id for c in shared]))
                )
            ).scalar_one()
        )
        print(f"\nShared library: {', '.join(names)}")
        print(f"  {ready} of {total} documents ready to search")
        if ready == 0:
            print(
                "  Nothing is searchable yet. Evaluation corpora are private and\n"
                "  stay that way: only this Shared collection is in demo scope."
            )

        # Eval corpora must not be in demo scope, and `resolve_scope` puts
        # every `visibility='shared'` collection in it — so a collection the
        # eval user owns and named for evaluation is in scope for every demo
        # visitor whether or not anybody intended that. Reported rather than
        # fixed: changing a collection's visibility is an operator decision
        # about which corpus the tour should read, not this script's to make.
        leaking = [name for name in names if EVAL_NAME_MARKER in name.lower()]
        if leaking:
            print(
                "\n  WARNING: these shared collections look like evaluation corpora, and"
                "\n  every demo account can read them:"
                f"\n    {', '.join(leaking)}"
                "\n  A tour question about a private eval document would work for a"
                "\n  visitor and leak it. Set visibility='private' on them before the"
                "\n  beta, or say here that this is intended."
            )


if __name__ == "__main__":
    if os.environ.get("DEMO_ALLOW_DEEP", "false").lower() in ("1", "true", "yes"):
        print("DEMO_ALLOW_DEEP is on: demo accounts may run Deep (30k credits a run).")
    asyncio.run(seed())