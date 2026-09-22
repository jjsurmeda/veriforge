"""Slice 1: auth, chats, messages, runs, run_events + model catalogue.

Implements: AC-1, AC-2, CH-6, CH-8 (TRD §13 tables; TRD §17 row 1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

userrole = sa.Enum("user", "admin", "demo", name="userrole")
messagerole = sa.Enum("user", "assistant", name="messagerole")
messagestatus = sa.Enum("complete", "cancelled", "abstained", "failed", name="messagestatus")
runstatus = sa.Enum("running", "completed", "cancelled", "failed", name="runstatus")
runmode = sa.Enum("fast", "auto", "deep", name="runmode")
runsource = sa.Enum("auto", "web", "collections", name="runsource")


def _ts() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),  # type: ignore[arg-type]
        server_default=sa.text("now()"),
        nullable=False,
    )



def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("credits_5h", sa.Integer(), nullable=False),
        sa.Column("credits_month", sa.Integer(), nullable=False),
        _ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("role", userrole, nullable=False),
        sa.Column("plan_id", UUID(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "oauth_accounts",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hash"),
    )
    op.create_table(
        "chats",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=True),
        sa.Column("collection_ids", JSONB(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chats_user_created", "chats", ["user_id", "created_at"])
    op.create_table(
        "messages",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("chat_id", UUID(), nullable=False),
        sa.Column("role", messagerole, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", messagestatus, nullable=True),
        sa.Column("revised_from", UUID(), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revised_from"], ["messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_chat_created", "messages", ["chat_id", "created_at"])
    op.create_table(
        "runs",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("message_id", UUID(), nullable=False),
        sa.Column("mode", runmode, nullable=False),
        sa.Column("source", runsource, nullable=False),
        sa.Column("model_id", sa.String(128), nullable=True),
        sa.Column("settings_version", sa.Integer(), nullable=True),
        sa.Column("metrics", JSONB(), nullable=True),
        sa.Column("langfuse_trace_id", sa.String(64), nullable=True),
        sa.Column("status", runstatus, nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_status_heartbeat", "runs", ["status", "heartbeat_at"])
    op.create_index("ix_runs_message", "runs", ["message_id"])
    op.create_table(
        "run_events",
        sa.Column("run_id", UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "seq"),
    )
    op.create_table(
        "llm_providers",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=True),
        sa.Column("api_key_enc", sa.String(512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "models",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("provider_id", UUID(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("price_in", sa.Numeric(12, 8), nullable=True),
        sa.Column("price_out", sa.Numeric(12, 8), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("capabilities", JSONB(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model_id"),
    )
    op.create_table(
        "model_roles",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("fallback_model_id", sa.String(128), nullable=True),
        _ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role"),
    )

    # Seed data: default plans (deliverable: two rows, 200k/2M credits),
    # one OpenRouter provider and the starter model catalogue (CH-8 picker).
    # ponytail: identical credit rows — real per-plan limits arrive with the
    # admin plan CRUD in slice 7.
    op.execute(
        sa.text(
            """
            INSERT INTO plans (id, name, credits_5h, credits_month)
            VALUES
              (gen_random_uuid(), 'free', 200000, 2000000),
              (gen_random_uuid(), 'pro', 200000, 2000000)
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO llm_providers (id, name, kind, enabled)
            VALUES (gen_random_uuid(), 'openrouter', 'openrouter', true)
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO models (id, provider_id, model_id, price_in, price_out,
                                context_window, capabilities, enabled)
            SELECT gen_random_uuid(), p.id, m.model_id, m.pin, m.pout, m.ctx, m.caps, true
            FROM llm_providers p
            JOIN (VALUES
              ('openai/gpt-4o-mini', 0.15, 0.60, 128000,
                 '{"streaming": true, "reasoning": false}'::jsonb),
              ('anthropic/claude-3.5-haiku', 0.80, 4.00, 200000,
                 '{"streaming": true, "reasoning": false}'::jsonb)
            ) AS m(model_id, pin, pout, ctx, caps) ON true
            WHERE p.name = 'openrouter'
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO model_roles (id, role, model_id, fallback_model_id)
            VALUES
              (gen_random_uuid(), 'generator', 'openai/gpt-4o-mini',
               'anthropic/claude-3.5-haiku'),
              (gen_random_uuid(), 'small', 'anthropic/claude-3.5-haiku', NULL)
            """
        )
    )


def downgrade() -> None:
    op.drop_table("model_roles")
    op.drop_table("models")
    op.drop_table("llm_providers")
    op.drop_table("run_events")
    op.drop_index("ix_runs_message", table_name="runs")
    op.drop_index("ix_runs_status_heartbeat", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_messages_chat_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_chats_user_created", table_name="chats")
    op.drop_table("chats")
    op.drop_table("refresh_tokens")
    op.drop_table("oauth_accounts")
    op.drop_table("users")
    op.drop_table("plans")
    runsource.drop(op.get_bind(), checkfirst=True)
    runmode.drop(op.get_bind(), checkfirst=True)
    runstatus.drop(op.get_bind(), checkfirst=True)
    messagestatus.drop(op.get_bind(), checkfirst=True)
    messagerole.drop(op.get_bind(), checkfirst=True)
    userrole.drop(op.get_bind(), checkfirst=True)
