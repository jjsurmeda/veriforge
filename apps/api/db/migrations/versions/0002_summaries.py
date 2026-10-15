"""summaries: the whole-document / gist-question index (TRD §9.1 step 6).

One migration on top of the `0001` baseline. Additive only: a new table and its
three indexes, nothing altered, so a document ingested before this migration
keeps working and simply has no summary rows yet — which is the state the
resumable backfill (`scripts/backfill_summaries.py`) starts from.

**The indexes are not optional.** Two arms query this table:

* the vector arm needs an HNSW index, exactly as `ix_chunks_embedding_hnsw`
  does for chunks, or the cosine ordering is a sequential scan over the whole
  table — and this table grows one row per *section*, so it is larger than
  chunks, not smaller;
* the BM25 arm needs a `bm25` index with the ICU tokenizer, exactly as
  `ix_chunks_text_bm25`, or the lexical half of the hybrid query silently
  matches nothing (the tokenizer mismatch is the bug migration 0013 exists for).

`built_from_summaries` is a boolean rather than a count because there is exactly
one thing it distinguishes — a document summary assembled from its section
summaries versus one written in a single call — and nothing reads a number.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ord", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "built_from_summaries",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # CASCADE on both, matching chunks: deleting a document takes its
        # summaries with it, and so does deleting a section. A summary left
        # behind is a row retrieval can still reach.
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_summaries_document_kind", "summaries", ["document_id", "kind"], unique=False
    )
    op.create_index("ix_summaries_section", "summaries", ["section_id"], unique=False)
    # The two query indexes, created the same way the chunk ones are. `paradedb`
    # ships with ParadeDB, so `CREATE INDEX ... USING bm25` is available on it;
    # on plain Postgres `downgrade()` drops this and `upgrade()` would need it
    # again, which is why the block is explicit rather than an op.create_index
    # with a dialect kwarg.
    op.execute(
        "CREATE INDEX ix_summaries_embedding_hnsw ON summaries "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    # Same BM25 + ICU tokenizer configuration as `ix_chunks_text_bm25`, because
    # the query names `tokenizer := '{"type": "icu"}'`. An index built on the
    # default tokenizer and a query asking for ICU is a silent no-op: the
    # lexical arm matches nothing and nothing says so. Migration 0013 exists
    # because of exactly this.
    op.execute(
        "CREATE INDEX ix_summaries_text_bm25 ON summaries USING bm25 (id, text)"
        " WITH (key_field='id',"
        ' text_fields=\'{"text": {"tokenizer": {"type": "icu"}}}\')'
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_summaries_text_bm25")
    op.execute("DROP INDEX IF EXISTS ix_summaries_embedding_hnsw")
    op.drop_index("ix_summaries_section", table_name="summaries")
    op.drop_index("ix_summaries_document_kind", table_name="summaries")
    op.drop_table("summaries")
