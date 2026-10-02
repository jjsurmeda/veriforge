"""Which corpus each eval item belongs to (PRD v3 §5, TRD §15).

Implements: P1b item 5 — the runner summarises **per corpus**, and a corpus is
only a thing it can summarise if each item declares which one it speaks for.
TRD §15's amended "Corpora and run tiers" and PRD §3 §5's per-corpus table both
assume this.

`corpus` is nullable with no default rather than NOT NULL: the column is added
to a table that already holds 63 rows written before it existed, and a
backfill that guesses would put an unverified label in the data — the same
mistake KI-36 is about. Items with no corpus are counted and reported under
`corpus: null` in the run summary instead of being silently folded into one.

`min_support` is per *result*, not per item, so it is `eval_results.min_support`
alongside `faithfulness` — the reviewer's minimum claim support for that
answer. PRD §5's row is "minimum claim support ≥ 0.6 on ≥ 95% of answers",
which is a share over results.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("eval_items", sa.Column("corpus", sa.String(64), nullable=True))
    op.add_column("eval_results", sa.Column("min_support", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_results", "min_support")
    op.drop_column("eval_items", "corpus")
