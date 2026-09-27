"""Persist the per-stage timing breakdown for an eval item (KI-6).

Implements: TRD §15 (eval gate).

`eval_results.latency_ms` is one number per item, and the run's
`latency_ms` stage dict never left the process, so a red p50 could not be
attributed to a stage — batch 4 and batch 5 each guessed a cause and each
guess was wrong. Storing the dict per item makes the attribution a query.

`latency_ms` keeps its meaning: it still stops at the end of generation.
The Reviewer's cost lands in `stage_ms["review"]` and is not added to it,
so a stored baseline stays comparable. Nullable: `NULL` means the row
predates this column or the item raised before any stage ran.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("eval_results", sa.Column("stage_ms", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_results", "stage_ms")
