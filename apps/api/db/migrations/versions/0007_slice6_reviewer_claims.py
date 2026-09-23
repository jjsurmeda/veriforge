"""Slice 6: reviewer claims table.

Implements: TR-2, TR-3, TR-7 (TRD §10, §13; TRD §17 row 6).

`claims` per TRD §13 — one atomic claim per row, written by the Reviewer
(extraction → verification → scores). `citations.verdict`/`p_supported`
columns already exist from the baseline schema as nullable placeholders;
this slice starts filling them, no change needed there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _ts() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),  # type: ignore[arg-type]
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("message_id", UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("citation_ns", JSONB(), nullable=False),
        sa.Column("is_factual", sa.Boolean(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=True),
        sa.Column("p_supported", sa.Numeric(), nullable=True),
        sa.Column("engine", sa.String(16), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_message", "claims", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_claims_message", table_name="claims")
    op.drop_table("claims")
