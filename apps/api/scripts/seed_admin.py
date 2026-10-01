"""Create or promote the local admin that `make acceptance` authenticates as.

There is no admin bootstrap in the product: signup hardcodes `role="user"`
(`auth/router.py:108`) and only an admin can grant the role
(`PATCH /admin/users/{id}`), so a fresh local database has no way in. Until
D4 item 1 the acceptance runner bypassed that by editing `plans` in the dev
database; it now goes through the admin API, which needs an admin to exist.

This is the local-dev equivalent of the one manual promotion an operator does
once. It reads `ADMIN_EMAIL` / `ADMIN_PASSWORD` and is idempotent: an existing
account is promoted and its password re-set, so it is also the fix for a
rotated password. It writes no plan and never touches `free` or `pro`.

It talks to the database directly (like `seed_models.py` and
`seed_gutenberg.py`) because there is no HTTP surface that can create the
first admin — that is the bootstrapping problem, not something to work
around inside the script.

Usage: `uv run python scripts/seed_admin.py` (or `make seed-admin`).
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from auth.passwords import hash_password
from db.models import Plan, User
from db.session import get_session_factory

MISSING = (
    "seed-admin needs ADMIN_EMAIL and ADMIN_PASSWORD (put them in .env, "
    "then rerun). Refusing to invent an admin credential."
)


async def seed() -> None:
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        raise SystemExit(MISSING)

    factory = get_session_factory()
    # `session.begin()` commits on exit — `flush()` alone leaves the row in a
    # transaction the script throws away, which is how the first version of
    # this printed "created admin" and left no user behind.
    async with factory() as session, session.begin():
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            # Lands on `free` like any signup; the plan is irrelevant for an
            # admin, and creating it here would be the mutation this whole
            # item exists to remove.
            plan = (await session.execute(select(Plan).where(Plan.name == "free"))).scalar_one()
            user = User(
                email=email,
                password_hash=hash_password(password),
                role="admin",
                plan_id=plan.id,
            )
            session.add(user)
            action = "created"
        else:
            user.role = "admin"
            user.status = "active"
            user.password_hash = hash_password(password)
            action = "promoted"
        await session.flush()
        print(f"{action} admin {user.email} ({user.id})")


if __name__ == "__main__":
    asyncio.run(seed())
