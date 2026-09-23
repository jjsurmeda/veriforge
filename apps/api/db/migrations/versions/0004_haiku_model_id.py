"""Fix stale catalogue seed: anthropic/claude-3.5-haiku retired on OpenRouter.

Implements part of SR-1 (TRD §17 row 2): starter questions call the
catalogue's "small" role, which must resolve to a served model id.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_OLD = "anthropic/claude-3.5-haiku"
_NEW = "anthropic/claude-haiku-4.5"


def _retag(old: str, new: str, price_in: float, price_out: float) -> None:
    op.execute(
        sa.text(
            "UPDATE models SET model_id=:new, price_in=:pin, price_out=:pout"
            " WHERE model_id=:old"
        ).bindparams(new=new, pin=price_in, pout=price_out, old=old)
    )
    op.execute(
        sa.text("UPDATE model_roles SET model_id=:new WHERE model_id=:old").bindparams(
            new=new, old=old
        )
    )
    op.execute(
        sa.text(
            "UPDATE model_roles SET fallback_model_id=:new WHERE fallback_model_id=:old"
        ).bindparams(new=new, old=old)
    )


def upgrade() -> None:
    _retag(_OLD, _NEW, 1.00, 5.00)


def downgrade() -> None:
    _retag(_NEW, _OLD, 0.80, 4.00)
