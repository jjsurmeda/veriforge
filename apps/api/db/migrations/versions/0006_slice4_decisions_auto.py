"""Slice 4: decision layer support tables.

Implements: SR-5, CH-2, TX-1 (TRD §13; TRD §17 row 4).

- `decision_shadow` per TRD §13 — Jev vs fallback disagreements recorded
  asynchronously for the 2% shadow-mode sample. Surfaced on the admin
  eval page in slice 7/8.
- `settings` per TRD §13 — versioned, one active row. Slice 4 seeds v1
  with `decision_engine_mode` (auto|jev_only|fallback_only),
  `shadow_sample_rate` (0.02), and per-engine threshold overrides
  (empty dict — defaults from TRD §8 apply until admin overrides).

Deferral note (slice 8 hardening): no `rate_limits` table — TRD §11 calls
for per-IP/per-email login/signup limits; slice 1 merge flagged this gap.
Logged here so the deferral isn't lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0006"
down_revision: str | None = "0005"
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
    # TRD §7 source Choice values are upload|web|both; slice 1's enum used
    # "collections" for upload and had no "both". Rename + extend to match.
    # ALTER TYPE ADD VALUE is non-transactional-safe on older PG; using
    # rename + add + map + drop pattern instead.
    op.execute("ALTER TYPE runsource RENAME VALUE 'collections' TO 'upload'")
    op.execute("ALTER TYPE runsource ADD VALUE IF NOT EXISTS 'both'")

    op.create_table(
        "decision_shadow",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("run_id", UUID(), nullable=False),
        sa.Column("decision", sa.String(64), nullable=False),
        sa.Column("jev_answer", JSONB(), nullable=False),
        sa.Column("fallback_answer", JSONB(), nullable=False),
        sa.Column("agree", sa.Boolean(), nullable=False),
        _ts(),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_shadow_run", "decision_shadow", ["run_id"])
    op.create_index("ix_decision_shadow_agree", "decision_shadow", ["agree"])

    op.create_table(
        "settings",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", JSONB(), nullable=False),
        sa.Column("created_by", UUID(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="false"),
        _ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    # One row only can be active — enforced with a partial unique index.
    op.create_index(
        "uq_settings_active",
        "settings",
        ["active"],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    # Seed v1: slice-4 defaults. Per-engine threshold overrides start empty
    # — TRD §8 defaults apply until an admin changes them via slice 7's
    # settings UI.
    op.execute(
        """
        INSERT INTO settings (id, version, data, active)
        VALUES (
          gen_random_uuid(),
          1,
          '{"decision_engine_mode": "auto", "shadow_sample_rate": 0.02, "thresholds": {}}'::jsonb,
          true
        )
        """
    )


def downgrade() -> None:
    # Enum value removal is destructive (requires rewriting dependent rows);
    # the rename is reversible, the 'both' add is not. Accepting that.
    op.execute("ALTER TYPE runsource RENAME VALUE 'upload' TO 'collections'")
    op.drop_index("uq_settings_active", table_name="settings")
    op.drop_table("settings")
    op.drop_index("ix_decision_shadow_agree", table_name="decision_shadow")
    op.drop_index("ix_decision_shadow_run", table_name="decision_shadow")
    op.drop_table("decision_shadow")
