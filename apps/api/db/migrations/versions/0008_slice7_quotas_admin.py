"""Slice 7: quota ledger, overrides, audit log, and admin defaults.

Implements: AC-3, AC-4, AD-1-AD-6, AD-8, AD-9 (TRD §13, §14, §17 row 7).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

usage_status = sa.Enum("reserved", "settled", name="usageledgerstatus")


def _ts() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),  # type: ignore[arg-type]
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "user_quota_overrides",
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("credits_5h", sa.Integer(), nullable=True),
        sa.Column("credits_month", sa.Integer(), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "usage_ledger",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("run_id", UUID(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credits", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("status", usage_status, nullable=False, server_default="reserved"),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _ts(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_ledger_user_ts", "usage_ledger", ["user_id", "ts"])
    op.create_index("ix_usage_ledger_run_status", "usage_ledger", ["run_id", "status"])

    op.create_table(
        "audit_log",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("actor_id", UUID(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("before", JSONB(), nullable=True),
        sa.Column("after", JSONB(), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_created", "audit_log", ["created_at"])

    # Jev is a catalogue row too: its real (near-zero) prices are used by the
    # same price-weighted accounting path as every other model.
    op.execute(
        """
        INSERT INTO models (id, provider_id, model_id, price_in, price_out,
                            context_window, capabilities, enabled)
        SELECT gen_random_uuid(), p.id, 'typesafe/jev-1.13', 0.000001, 0.000001,
               32768, '{"decision": true}'::jsonb, true
        FROM llm_providers p
        WHERE p.name = 'openrouter'
        ON CONFLICT (provider_id, model_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO model_roles (id, role, model_id, fallback_model_id)
        VALUES
          (gen_random_uuid(), 'planner', 'openai/gpt-4o-mini', 'anthropic/claude-haiku-4.5'),
          (gen_random_uuid(), 'rewriter', 'anthropic/claude-haiku-4.5', NULL),
          (gen_random_uuid(), 'claim_extractor', 'anthropic/claude-haiku-4.5', NULL),
          (gen_random_uuid(), 'suggester', 'anthropic/claude-haiku-4.5', NULL),
          (gen_random_uuid(), 'decision_engine', 'typesafe/jev-1.13', NULL),
          (gen_random_uuid(), 'decision_fallback', 'anthropic/claude-haiku-4.5', NULL)
        ON CONFLICT (role) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE settings
        SET data = data || '{
          "quota_estimates": {"fast": 3000, "auto": 8000, "deep": 30000},
          "retrieval": {
            "top_k": 8, "fused_limit": 40, "vec_limit": 50, "lex_limit": 50,
            "rrf_k": 60, "rerank": true, "hop_limit": 4, "retry_limit": 2
          },
          "deep": {"per_run_credit_cap": 40000},
          "guardrails": {
            "enabled": true,
            "actions": {"injection": "block", "jailbreak": "block", "pii": "warn",
                        "off_topic": "warn", "toxicity": "block", "secrets": "redact"}
          },
          "web_search_provider": "tavily",
          "source_priority": "documents_first",
          "trace_sample_rate": 1.0
        }'::jsonb
        WHERE active
        """
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_usage_ledger_run_status", table_name="usage_ledger")
    op.drop_index("ix_usage_ledger_user_ts", table_name="usage_ledger")
    op.drop_table("usage_ledger")
    op.drop_table("user_quota_overrides")
    usage_status.drop(op.get_bind(), checkfirst=True)
