"""Slice 2: collections, documents, sections, chunks (+ pgvector/pg_search).

Implements: SR-1, SR-2 (TRD §13 tables; TRD §17 row 2).

HNSW and BM25 indexes are created now and populated at ingest; they are
queried from slice 3 (TRD §9.2). `queue` schema hosts Procrastinate's
tables (TRD §13: library tables live in separate schemas).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

collectionvisibility = sa.Enum("private", "shared", name="collectionvisibility")
documentstatus = sa.Enum(
    "queued", "parsing", "embedding", "ready", "failed", name="documentstatus"
)
chunksource = sa.Enum("document", "web", name="chunksource")


def _ts() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),  # type: ignore[arg-type]
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
    op.execute("CREATE SCHEMA IF NOT EXISTS queue")

    op.create_table(
        "collections",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("owner_id", UUID(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("visibility", collectionvisibility, nullable=False),
        sa.Column("starter_questions", JSONB(), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collections_owner", "collections", ["owner_id"])

    op.create_table(
        "documents",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("collection_id", UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("s3_key", sa.String(512), nullable=False),
        sa.Column("status", documentstatus, nullable=False),
        sa.Column("page_flags", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("tags", JSONB(), server_default="[]", nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "sha256"),
    )
    op.create_index(
        "ix_documents_collection_created", "documents", ["collection_id", "created_at"]
    )

    op.create_table(
        "sections",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("document_id", UUID(), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=False),
        sa.Column("ord", sa.Integer(), server_default="0", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sections_document", "sections", ["document_id"])

    op.create_table(
        "chunks",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("document_id", UUID(), nullable=False),
        sa.Column("section_id", UUID(), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("metadata", JSONB(), server_default="{}", nullable=False),
        sa.Column("source_type", chunksource, nullable=False),
        sa.Column("chat_id", UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chunks_document_section_ord", "chunks", ["document_id", "section_id", "ord"]
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks"
        " USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_chunks_text_bm25 ON chunks"
        " USING bm25 (id, text) WITH (key_field='id')"
    )
    op.execute("CREATE INDEX ix_chunks_metadata_gin ON chunks USING gin (metadata)")


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("sections")
    op.drop_table("documents")
    op.drop_table("collections")
    for type_name in ("chunksource", "documentstatus", "collectionvisibility"):
        op.execute(f"DROP TYPE {type_name}")
    op.execute("DROP SCHEMA IF EXISTS queue")
    # The vector/pg_search extensions are left installed: other databases on
    # the same cluster may rely on them and re-adding is cheap.
