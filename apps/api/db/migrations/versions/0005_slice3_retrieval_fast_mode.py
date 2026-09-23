"""Slice 3: citations, retrieval caches, web pages, eval tables.

Implements: SR-6, TR-1, TX-2 (TRD §13 tables; TRD §17 row 3).

- `citations` per TRD §13, with verdict/p_supported nullable until the
  Reviewer (slice 6) fills them.
- `query_cache` (30-day TTL) and `web_cache` (24 h TTL) per TRD §9.4 —
  TTL is enforced at read time; the nightly sweep lands with the worker
  job that owns expiry.
- `web_pages` groups one fetched page's chat-scoped temp chunks (TRD §9.3);
  `chunks.document_id`/`section_id` go nullable so web chunks need no
  synthetic document. Small-to-big skips parentless (web) chunks.
- `eval_datasets`/`eval_items`/`eval_runs`/`eval_results` per TRD §13/§15.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0005"
down_revision: str | None = "0004"
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
    # Web chunks carry no document/section (TRD §9.3 chat-scoped temp rows).
    op.alter_column("chunks", "document_id", nullable=True)
    op.alter_column("chunks", "section_id", nullable=True)

    op.create_table(
        "citations",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("message_id", UUID(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        # SET NULL: expired web chunks (7-day TTL) must not cascade-delete
        # the citation record; the UI degrades to "source expired".
        sa.Column("chunk_id", UUID(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        # Reviewer fields — null until slice 6 (TRD §10).
        sa.Column("verdict", sa.String(16), nullable=True),
        sa.Column("p_supported", sa.Float(), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "n"),
    )
    op.create_index("ix_citations_message", "citations", ["message_id"])

    op.create_table(
        "query_cache",
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        _ts(),
        sa.PrimaryKeyConstraint("query_hash"),
    )

    op.create_table(
        "web_cache",
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("results", JSONB(), nullable=False),
        _ts(),
        sa.PrimaryKeyConstraint("query_hash"),
    )

    op.create_table(
        "web_pages",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("chat_id", UUID(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_web_pages_chat", "web_pages", ["chat_id"])

    op.create_table(
        "eval_datasets",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        _ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "eval_items",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("dataset_id", UUID(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=False),
        sa.Column("expected_citations", JSONB(), nullable=True),
        sa.Column("should_abstain", sa.Boolean(), server_default="false", nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_items_dataset", "eval_items", ["dataset_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("dataset_id", UUID(), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("settings_version", sa.Integer(), nullable=True),
        sa.Column("is_baseline", sa.Boolean(), server_default="false", nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "eval_results",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("eval_run_id", UUID(), nullable=False),
        sa.Column("item_id", UUID(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("citation_precision", sa.Float(), nullable=True),
        sa.Column("context_precision", sa.Float(), nullable=True),
        sa.Column("context_recall", sa.Float(), nullable=True),
        sa.Column("abstained", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        # Credits are just token counts until slice 7's ledger (TRD §14).
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["eval_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_results_run", "eval_results", ["eval_run_id"])


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_table("eval_runs")
    op.drop_table("eval_items")
    op.drop_table("eval_datasets")
    op.drop_table("web_pages")
    op.drop_table("web_cache")
    op.drop_table("query_cache")
    op.drop_table("citations")
    op.alter_column("chunks", "section_id", nullable=False)
    op.alter_column("chunks", "document_id", nullable=False)
