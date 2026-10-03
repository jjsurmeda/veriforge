"""Give the eval owner account a password, so acceptance can sign in as it.

KI-24: the AW-2000 seed corpus and the counterfactual corpus are
`visibility='private'` collections owned by `evals@veriforge.local`. A private
collection is in scope only for the user that owns it, so the eval and
acceptance runners have to *be* that user — a throwaway signup has no access to
the corpus it is meant to measure, which is how the fixture became
user-visible product content in the first place.

The books stay `visibility='shared'`: they are the demo library every real user
sees, and measuring acceptance against them there is the realistic thing to do.
Only the eval-only corpora move.

Idempotent, like `seed_admin.py`: it creates the account if it is missing and
re-sets the password if it is not, so it is also the fix for a rotated
credential. It assigns the seeded `internal-eval` plan once, here, rather than
on every acceptance run — the account persists now, so a per-run assignment
would be a mutation of the same row 48 times.

Reads `EVAL_USER_PASSWORD` (and optionally `EVAL_USER_EMAIL`). Talks to the
database directly for the same reason `seed_admin.py` does: there is no HTTP
surface that can mint a password for an account the product will never sign up.

Usage: `uv run python scripts/seed_eval_user.py` (or `make seed-eval-user`).
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from db.models import Plan
from db.session import get_session_factory
from evals.loader import EVAL_USER_EMAIL, ensure_eval_user

MISSING = (
    "seed-eval-user needs EVAL_USER_PASSWORD (put it in .env, next to "
    "ADMIN_EMAIL/ADMIN_PASSWORD, then rerun). Refusing to invent a credential."
)

EVAL_PLAN_NAME = "internal-eval"


async def seed() -> None:
    password = os.environ.get("EVAL_USER_PASSWORD")
    if not password:
        raise SystemExit(MISSING)
    email = os.environ.get("EVAL_USER_EMAIL") or EVAL_USER_EMAIL

    factory = get_session_factory()
    # `session.begin()` commits on exit; `flush()` alone would leave the row in
    # a transaction the script throws away.
    async with factory() as session, session.begin():
        user = await ensure_eval_user(session, password=password)
        if user.email != email:
            # The loader owns the identity (the runner imports it), so a
            # mismatched override is refused rather than silently creating a
            # second account that owns nothing.
            raise SystemExit(
                f"EVAL_USER_EMAIL={email} does not match the loader's "
                f"{user.email}; the runner resolves the corpus owner by that "
                f"constant. Change it in evals/loader.py, not here."
            )
        plan = (
            await session.execute(select(Plan).where(Plan.name == EVAL_PLAN_NAME))
        ).scalar_one_or_none()
        if plan is None:
            raise SystemExit(
                f"no {EVAL_PLAN_NAME} plan; run the migrations "
                "(`docker compose restart api`) so migration 0014 has run"
            )
        if user.plan_id != plan.id:
            user.plan_id = plan.id
        await session.flush()
        print(f"eval user {user.email} ({user.id}) on the {EVAL_PLAN_NAME} plan")


if __name__ == "__main__":
    asyncio.run(seed())
