"""Seed an `internal-eval` plan so acceptance runs stop editing `free`.

Implements: TRD §14 (reserve/settle) — the gate itself is unchanged, only
the limit it reserves against.

A full acceptance run costs about 310k quota credits (KI-20) against the
`free` plan's 200k per 5 h window, so every run so far raised `credits_5h`
in the dev database by hand and restored it afterwards. That mutates a row
real users are on, which is not a thing a measurement harness gets to do.

This adds a third plan with headroom instead. `free` and `pro` are never
touched: the acceptance runner assigns its throwaway user to
`internal-eval` through the admin API (audited), and a real user signing up
still lands on `free` (`auth/router.py::_default_plan_id`).

`ON CONFLICT (name) DO NOTHING` so the migration is idempotent and so a
plan an operator has already tuned keeps its values.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

PLAN_NAME = "internal-eval"
# ~2x a full acceptance run (310k) so two runs fit inside one 5 h window,
# and ~1.5x the monthly figure for the same reason.
CREDITS_5H = 20_000_000
CREDITS_MONTH = 200_000_000

INSERT_PLAN = f"""
    INSERT INTO plans (id, name, credits_5h, credits_month)
    VALUES (gen_random_uuid(), '{PLAN_NAME}', {CREDITS_5H}, {CREDITS_MONTH})
    ON CONFLICT (name) DO NOTHING
"""  # noqa: S608  (module constants, no user input)

DELETE_PLAN = f"DELETE FROM plans WHERE name = '{PLAN_NAME}'"  # noqa: S608


def upgrade() -> None:
    op.execute(INSERT_PLAN)


def downgrade() -> None:
    # Refuses while a user is on it: the FK has no ON DELETE action, so this
    # is the database telling us to move the user first, not a silent loss.
    op.execute(DELETE_PLAN)
