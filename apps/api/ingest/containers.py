"""The two document containers a user can see (ADR-002, TRD §13).

`collections` rows are never surfaced directly any more. A chat owns at
most one `kind='chat'` container (unique on chat_id, cascade-deleted with
the chat); a user owns one or more `kind='library'` containers, and admins
own the `visibility='shared'` one. Everything that needs "where do these
files go" asks here so the rules live in one place.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Collection, User

LIBRARY_NAME = "Library"
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


async def get_or_create_library_collection(
    session: AsyncSession, user: User
) -> Collection:
    existing = (
        await session.execute(
            select(Collection)
            .where(
                Collection.owner_id == user.id,
                Collection.kind == "library",
                Collection.visibility == "private",
            )
            .order_by(Collection.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    collection = Collection(
        owner_id=user.id, name=LIBRARY_NAME, visibility="private", kind="library"
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
