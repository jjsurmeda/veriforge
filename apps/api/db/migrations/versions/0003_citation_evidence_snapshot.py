"""citations keep a document, section and excerpt of their own.

A summary citation carries no chunk (the summary is not a row of `chunks`), so
`chunk_id` is NULL, and the messages endpoint resolved a citation's document,
heading and excerpt only through that chunk: after a reload a summary-backed
answer showed no document name, no excerpt and no document id (third-party
review, 2026-10-18). These three columns are the reference a chunk-less
citation resolves through. Additive, nullable: existing rows keep working.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "citations",
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
    )
    op.add_column(
        "citations",
        sa.Column("section_id", sa.Uuid(), sa.ForeignKey("sections.id", ondelete="SET NULL")),
    )
    op.add_column("citations", sa.Column("excerpt", sa.Text()))


def downgrade() -> None:
    op.drop_column("citations", "excerpt")
    op.drop_column("citations", "section_id")
    op.drop_column("citations", "document_id")
