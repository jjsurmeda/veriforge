"""Persist the reviewer's per-claim verdicts and the contexts behind them.

Implements: TRD §10 (claim extraction → verification → faithfulness), TRD §15
(the eval gate).

Faithfulness is a mean over the reviewer's per-claim verdicts, so when the
faithfulness number moves between two runs the mean alone cannot say *why*. The
four candidate sources — a different answer, a different extraction, the same
claim judged differently, a different citation or context — are only separable
from the claims themselves. `eval-gate-local` drops its database on exit, so
without a column to hold them that evidence is destroyed before it is read
(D4 item 3; this is why D3 could only name `multihop-05` and `lookup-01` and
not the claim that moved inside them).

One nullable JSONB column, `{"claims": [...], "contexts": [...]}`. Contexts are
stored as a digest of the passage rather than the passage: the comparison only
needs to know whether two runs retrieved the same chunks, and the text is
already in `chunks`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_results",
        sa.Column("review_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_results", "review_detail")
