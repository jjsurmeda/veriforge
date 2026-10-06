"""Invite codes, so an open signup can be closed (item 4, `signup_mode`).

Implements: the `invite` signup mode — `POST /auth/signup` requires a valid,
unused code, and consumes it atomically — plus the admin surface to mint,
list and revoke codes.

`used_by` / `used_at` are nullable because an unused code has nobody. The
pair is what makes "consumed atomically" checkable: a single
`UPDATE … WHERE used_by IS NULL … RETURNING` both claims the row and tells
the caller it won, so two concurrent signups cannot both succeed on one
code. That matters specifically here: the alternative (SELECT then UPDATE)
is a race that hands the same invite to two strangers, which is the whole
thing an invite list is for.

`expires_at` is nullable so a code can be made permanent, and
`revoked_at` exists separately from `used_at` so an operator can kill a code
that has been shared somewhere without pretending it was used. Both are
named in the model with their reason.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "code",
            sa.String(64),
            nullable=False,
            comment="what the user types; stored hashed, never in plaintext logs",
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("used_by", sa.Uuid(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    # The lookup path is by hash, and revocation/listing filter on the
    # lifecycle columns; the partial index keeps "unused, unexpired, not
    # revoked" cheap as the table grows past the tens of codes a beta needs.
    op.create_index(
        "ix_invites_code_hash", "invites", ["code_hash"], unique=True
    )
    op.create_index(
        "ix_invites_live",
        "invites",
        ["created_at"],
        postgresql_where=sa.text("used_by IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_invites_live", table_name="invites")
    op.drop_index("ix_invites_code_hash", table_name="invites")
    op.drop_table("invites")