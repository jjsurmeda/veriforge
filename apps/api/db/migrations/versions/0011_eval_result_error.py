"""Record why an eval item failed (KI-6).

Implements: TRD §15 (eval gate).

`run_eval`'s `except` branch used to build an `EvalResult` and keep it only
in memory, so a failed item left no row in `eval_results` and still entered
`aggregate()` with `latency_ms=0` and every score `None` — a zero that pulled
the median down, so a green p50 could hide a run where half the items died.
An errored item is not a measurement, so the reason it failed has to survive
the process. Nullable: `NULL` means the item ran and was scored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("eval_results", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_results", "error")
