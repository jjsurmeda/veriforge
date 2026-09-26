"""The two document containers a run can reach (ADR-002 addendum, TRD §13).

`collections` rows are never surfaced directly any more. A chat owns at most
one `kind='chat'` container (unique on chat_id, cascade-deleted with the
chat); admins own the `visibility='shared'` one. A user's own private
`library` containers are unreachable by design. Everything that needs "where
do these files go" asks here so the rules live in one place.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Collection, User

SHARED_NAME = "Shared"


async def get_chat_collection(
    session: AsyncSession, chat_id: UUID
) -> Collection | None:
    return (
        await session.execute(
            select(Collection).where(
                Collection.kind == "chat", Collection.chat_id == chat_id
            )
        )
    ).scalar_one_or_none()


async def get_or_create_chat_collection(
    session: AsyncSession, user: User, chat: Chat
) -> Collection:
    existing = await get_chat_collection(session, chat.id)
    if existing is not None:
        return existing
    collection = Collection(
        owner_id=user.id,
        name=chat.title or "Chat sources",
        visibility="private",
        kind="chat",
        chat_id=chat.id,
    )
    session.add(collection)
    await session.flush()
    return collection


async def get_or_create_shared_collection(
    session: AsyncSession, admin: User
) -> Collection:
    existing = (
        await session.execute(
            select(Collection).where(
                Collection.owner_id == admin.id, Collection.visibility == "shared"
            )
            .order_by(Collection.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    collection = Collection(
        owner_id=admin.id, name=SHARED_NAME, visibility="shared", kind="library"
    )
    session.add(collection)
    await session.flush()
    return collection
