"""Chat-scoped sources and a Library, no user-facing collections (ADR-002).

Implements: SR-1, SR-5, SR-6, CH-9 (PRD); TRD §9.1-§9.2, §12, §13.

`collections` stays as the hidden container the ownership filter and
retrieval SQL already depend on. Two kinds:

  kind='chat'    chat_id set (unique, cascade)  -> the chat's own sources
  kind='library'  chat_id null                   -> a user's Library, or Shared

Existing rows all become kind='library' via the server default, so no data
rewrite is needed and old chats keep a scope at least as wide as before
(the Library is in every chat's scope unless include_library is off).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

collectionkind = sa.Enum("chat", "library", name="collectionkind")

_KIND_CHAT_CHAT_ID = "ck_collections_kind_chat_id"
_SHARED_IS_LIBRARY = "ck_collections_shared_is_library"


def upgrade() -> None:
    collectionkind.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "collections",
        sa.Column("kind", collectionkind, nullable=False, server_default="library"),
    )
    op.add_column("collections", sa.Column("chat_id", UUID(), nullable=True))
    op.create_foreign_key(
        "fk_collections_chat_id", "collections", "chats", ["chat_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("uq_collections_chat_id", "collections", ["chat_id"], unique=True)
    op.create_check_constraint(
        _KIND_CHAT_CHAT_ID,
        "collections",
        "(kind = 'chat') = (chat_id IS NOT NULL)",
    )
    op.create_check_constraint(
        _SHARED_IS_LIBRARY, "collections", "visibility <> 'shared' OR kind = 'library'"
    )

    op.add_column(
        "chats",
        sa.Column("include_library", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.drop_column("chats", "collection_ids")


def downgrade() -> None:
    op.add_column(
        "chats", sa.Column("collection_ids", JSONB(), nullable=True)
    )
    op.drop_column("chats", "include_library")

    op.drop_constraint(_SHARED_IS_LIBRARY, "collections", type_="check")
    op.drop_constraint(_KIND_CHAT_CHAT_ID, "collections", type_="check")
    op.drop_index("uq_collections_chat_id", table_name="collections")
    op.drop_constraint("fk_collections_chat_id", "collections", type_="foreignkey")
    op.drop_column("collections", "chat_id")
    op.drop_column("collections", "kind")
    collectionkind.drop(op.get_bind(), checkfirst=True)
