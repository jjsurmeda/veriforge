"""The baseline: today's schema, in one revision.

Every table, type and index the application needs, in the order the
dependencies allow, plus the rows a fresh database starts with. Nothing has
been deployed, so there is no earlier revision to keep readable: this file IS
the schema.

What the model metadata cannot express is written out below — the extensions
(pgvector, ParadeDB's BM25), the `queue` schema Procrastinate owns, the
vector, BM25 and GIN indexes on `chunks` (an operator class and an ICU
tokenizer are not something `create_all` knows), and the seed rows.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

import json
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
    op.execute("CREATE SCHEMA IF NOT EXISTS queue")
    op.create_table(
        "eval_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=True),
        sa.Column("api_key_enc", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "model_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("fallback_model_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role"),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("credits_5h", sa.Integer(), nullable=False),
        sa.Column("credits_month", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "query_cache",
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("query_hash"),
    )
    op.create_table(
        "web_cache",
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("query_hash"),
    )
    op.create_table(
        "eval_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=False),
        sa.Column("expected_citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("should_abstain", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("corpus", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_items_dataset", "eval_items", ["dataset_id"], unique=False)
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("settings_version", sa.Integer(), nullable=True),
        sa.Column("is_baseline", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("price_in", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("price_out", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model_id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("role", sa.Enum("user", "admin", "demo", name="userrole"), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_created", "audit_log", ["created_at"], unique=False)
    op.create_table(
        "chats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("include_library", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chats_user_created", "chats", ["user_id", "created_at"], unique=False)
    op.create_table(
        "eval_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("eval_run_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("citation_precision", sa.Float(), nullable=True),
        sa.Column("context_precision", sa.Float(), nullable=True),
        sa.Column("context_recall", sa.Float(), nullable=True),
        sa.Column("abstained", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stage_ms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("review_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("min_support", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["eval_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_results_run", "eval_results", ["eval_run_id"], unique=False)
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("used_by", sa.Uuid(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        "ix_invites_live",
        "invites",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("used_by IS NULL AND revoked_at IS NULL"),
    )
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hash"),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_table(
        "user_quota_overrides",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("credits_5h", sa.Integer(), nullable=True),
        sa.Column("credits_month", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "visibility", sa.Enum("private", "shared", name="collectionvisibility"), nullable=False
        ),
        sa.Column("starter_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum("chat", "library", name="collectionkind"),
            server_default=sa.text("'library'::collectionkind"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_collections_chat_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # A chat-scoped collection belongs to exactly one chat, and a library
        # collection is not a chat's: both halves in one constraint, so a
        # half-written collection cannot sit in the table.
        sa.CheckConstraint(
            "(kind = 'chat'::collectionkind) = (chat_id IS NOT NULL)",
            name="ck_collections_kind_chat_id",
        ),
        sa.CheckConstraint(
            "(visibility <> 'shared'::collectionvisibility) OR (kind = 'library'::collectionkind)",
            name="ck_collections_shared_is_library",
        ),
    )
    op.create_index("ix_collections_owner", "collections", ["owner_id"], unique=False)
    op.create_index("uq_collections_chat_id", "collections", ["chat_id"], unique=True)
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Enum("user", "assistant", name="messagerole"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("complete", "cancelled", "abstained", "failed", name="messagestatus"),
            nullable=True,
        ),
        sa.Column("revised_from", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["revised_from"],
            ["messages.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_chat_created", "messages", ["chat_id", "created_at"], unique=False)
    op.create_table(
        "web_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_web_pages_chat", "web_pages", ["chat_id"], unique=False)
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("citation_ns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_factual", sa.Boolean(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("p_supported", sa.Numeric(), nullable=True),
        sa.Column("engine", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_message", "claims", ["message_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "parsing", "embedding", "ready", "failed", name="documentstatus"),
            nullable=False,
        ),
        sa.Column("page_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "tags", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "sha256"),
    )
    op.create_index(
        "ix_documents_collection_created",
        "documents",
        ["collection_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.Enum("fast", "auto", "deep", name="runmode"), nullable=False),
        sa.Column(
            "source", sa.Enum("auto", "web", "upload", "both", name="runsource"), nullable=False
        ),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("settings_version", sa.Integer(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("langfuse_trace_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum("running", "completed", "cancelled", "failed", name="runstatus"),
            nullable=False,
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_message", "runs", ["message_id"], unique=False)
    op.create_index("ix_runs_status_heartbeat", "runs", ["status", "heartbeat_at"], unique=False)
    op.create_table(
        "decision_shadow",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("jev_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fallback_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("agree", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_shadow_agree", "decision_shadow", ["agree"], unique=False)
    op.create_index("ix_decision_shadow_created", "decision_shadow", ["created_at"], unique=False)
    op.create_index("ix_decision_shadow_run", "decision_shadow", ["run_id"], unique=False)
    op.create_table(
        "run_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "seq"),
    )
    op.create_index(
        "ix_run_events_type_created", "run_events", ["type", "created_at"], unique=False
    )
    op.create_table(
        "run_seq_counters",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("last_seq", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=False),
        sa.Column("ord", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sections_document", "sections", ["document_id"], unique=False)
    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "credits",
            sa.Numeric(precision=20, scale=6),
            server_default=sa.text("'0'::numeric"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("reserved", "settled", name="usageledgerstatus"),
            server_default=sa.text("'reserved'::usageledgerstatus"),
            nullable=False,
        ),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_usage_ledger_run_status", "usage_ledger", ["run_id", "status"], unique=False
    )
    op.create_index("ix_usage_ledger_user_ts", "usage_ledger", ["user_id", "ts"], unique=False)
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("section_id", sa.Uuid(), nullable=True),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("source_type", sa.Enum("document", "web", name="chunksource"), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chunks_document_section_ord",
        "chunks",
        ["document_id", "section_id", "ord"],
        unique=False,
    )
    op.create_table(
        "citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("p_supported", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "n"),
    )
    op.create_index("ix_citations_message", "citations", ["message_id"], unique=False)
    # ### end Alembic commands ###
    op.create_index(
        "uq_settings_active",
        "settings",
        ["active"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_index("ix_invites_code_hash", "invites", ["code_hash"], unique=True)
    op.execute(
        "COMMENT ON COLUMN invites.code IS"
        " 'what the user types; stored hashed, never in plaintext logs'"
    )
    op.execute(
        "COMMENT ON COLUMN run_seq_counters.last_seq IS"
        " 'the highest seq this run has committed; next is +1'"
    )
    _chunk_indexes()
    _seed_rows()


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS queue CASCADE")


# The three indexes on `chunks` that carry their own operator class: a vector
# similarity index, a BM25 full-text index with the ICU tokenizer (so a CJK
# question is segmented rather than kept as one token), and a GIN index over
# the metadata document. The bm25 index is created last, because it needs the
# pg_search extension and its tokenizer configuration.
def _chunk_indexes() -> None:
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX ix_chunks_metadata_gin ON chunks USING gin (metadata)")
    op.execute(
        "CREATE INDEX ix_chunks_text_bm25 ON chunks USING bm25 (id, text)"
        " WITH (key_field='id',"
        ' text_fields=\'{"text": {"tokenizer": {"type": "icu"}}}\')'
    )


# What a fresh database starts with: the three plans (the internal-eval plan
# carries enough credit for two acceptance runs inside one 5 h window), the
# OpenRouter provider with its catalogue, the role bindings the runtime reads,
# and the active settings version.
SETTINGS = {
    "deep": {"per_run_credit_cap": 40000},
    "retrieval": {
        "rrf_k": 60,
        "top_k": 8,
        "rerank": True,
        "hop_limit": 4,
        "lex_limit": 50,
        "vec_limit": 50,
        "fused_limit": 40,
        "retry_limit": 2,
    },
    "guardrails": {
        "actions": {
            "pii": "warn",
            "secrets": "redact",
            "toxicity": "block",
            "injection": "block",
            "jailbreak": "block",
            "off_topic": "warn",
        },
        "enabled": True,
    },
    "thresholds": {},
    "quota_estimates": {"auto": 8000, "deep": 30000, "fast": 3000},
    "source_priority": "documents_first",
    "trace_sample_rate": 1.0,
    "shadow_sample_rate": 0.02,
    "web_search_provider": "tavily",
    "decision_engine_mode": "auto",
}

CATALOGUE = (
    ("openai/gpt-4o-mini", 0.15, 0.60, 128000, {"streaming": True, "reasoning": False}),
    ("anthropic/claude-haiku-4.5", 1.00, 5.00, 200000, {"streaming": True, "reasoning": False}),
    ("typesafe/jev-1.13", 0.000001, 0.000001, 32768, {"decision": True}),
)

ROLE_BINDINGS = (
    ("generator", "openai/gpt-4o-mini", "anthropic/claude-haiku-4.5"),
    ("small", "anthropic/claude-haiku-4.5", None),
    ("planner", "openai/gpt-4o-mini", "anthropic/claude-haiku-4.5"),
    ("rewriter", "anthropic/claude-haiku-4.5", None),
    ("claim_extractor", "anthropic/claude-haiku-4.5", None),
    ("suggester", "anthropic/claude-haiku-4.5", None),
    ("decision_engine", "typesafe/jev-1.13", None),
    ("decision_fallback", "anthropic/claude-haiku-4.5", None),
)

PLANS = (
    ("free", 200_000, 2_000_000),
    ("pro", 200_000, 2_000_000),
    ("internal-eval", 20_000_000, 200_000_000),
)


# A plan is inserted by name and never overwritten, so replaying the seed
# against a database whose limits have been tuned keeps the tuned values.
INSERT_PLAN = """
    INSERT INTO plans (id, name, credits_5h, credits_month)
    VALUES (gen_random_uuid(), :name, :credits_5h, :credits_month)
    ON CONFLICT (name) DO NOTHING
"""


def _seed_rows() -> None:
    connection = op.get_bind()
    for name, credits_5h, credits_month in PLANS:
        connection.execute(
            sa.text(INSERT_PLAN),
            {"name": name, "credits_5h": credits_5h, "credits_month": credits_month},
        )
    connection.execute(
        sa.text(
            "INSERT INTO llm_providers (id, name, kind, enabled)"
            " VALUES (gen_random_uuid(), 'openrouter', 'openrouter', true)"
        )
    )
    for model_id, price_in, price_out, window, capabilities in CATALOGUE:
        connection.execute(
            sa.text(
                "INSERT INTO models (id, provider_id, model_id, price_in, price_out,"
                " context_window, capabilities, enabled)"
                " SELECT gen_random_uuid(), p.id, :model_id, :price_in, :price_out,"
                " :window, CAST(:capabilities AS jsonb), true"
                " FROM llm_providers p WHERE p.name = 'openrouter'"
            ),
            {
                "model_id": model_id,
                "price_in": price_in,
                "price_out": price_out,
                "window": window,
                "capabilities": json.dumps(capabilities),
            },
        )
    for role, model_id, fallback in ROLE_BINDINGS:
        connection.execute(
            sa.text(
                "INSERT INTO model_roles (id, role, model_id, fallback_model_id)"
                " VALUES (gen_random_uuid(), :role, :model_id, :fallback)"
            ),
            {"role": role, "model_id": model_id, "fallback": fallback},
        )
    connection.execute(
        sa.text(
            "INSERT INTO settings (id, version, data, active)"
            " VALUES (gen_random_uuid(), 1, CAST(:data AS jsonb), true)"
        ),
        {"data": json.dumps(SETTINGS)},
    )
