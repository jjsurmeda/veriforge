from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_run_events_type_created", "run_events", ["type", "created_at"])
    op.create_index("ix_decision_shadow_created", "decision_shadow", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_decision_shadow_created", table_name="decision_shadow")
    op.drop_index("ix_run_events_type_created", table_name="run_events")
