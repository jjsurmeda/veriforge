"""The chat history a run's stages read: every message before the one being
answered, oldest first.

One helper for all three modes, because "what did we already say" has one
answer and three copies of the query are three places for it to be wrong.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Message


async def history_messages(
    session: AsyncSession, chat_id: UUID, exclude_message_id: UUID
) -> list[tuple[str, str]]:
    """The turns before this one. The message being answered is excluded, and
    an empty message is dropped rather than answered with a blank turn."""
    messages = (
        (
            await session.execute(
                select(Message)
                .where(Message.chat_id == chat_id, Message.id != exclude_message_id)
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [(m.role, m.content) for m in messages if m.content]
