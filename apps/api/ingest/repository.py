from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, Collection, Document, Section, User


def _visible_to(user: User) -> ColumnElement[bool]:
    return or_(Collection.owner_id == user.id, Collection.visibility == "shared")


async def visible_collections(
    session: AsyncSession, user: User
) -> Sequence[tuple[Collection, int]]:
    rows = await session.execute(
        select(Collection, func.count(Document.id))
        .outerjoin(Document, Document.collection_id == Collection.id)
        .where(_visible_to(user))
        .group_by(Collection.id)
        .order_by(Collection.created_at.desc())
    )
    return [(collection, count) for collection, count in rows.all()]


async def get_visible_collection(
    session: AsyncSession, user: User, collection_id: UUID
) -> Collection | None:
    return (
        await session.execute(
            select(Collection).where(Collection.id == collection_id, _visible_to(user))
        )
    ).scalar_one_or_none()


async def get_owned_collection(
    session: AsyncSession, user: User, collection_id: UUID
) -> Collection | None:
    return (
        await session.execute(
            select(Collection).where(Collection.id == collection_id, Collection.owner_id == user.id)
        )
    ).scalar_one_or_none()


async def list_collection_documents(
    session: AsyncSession, user: User, collection_id: UUID
) -> Sequence[Document] | None:
    if await get_visible_collection(session, user, collection_id) is None:
        return None
    return (
        await session.execute(
            select(Document)
            .where(Document.collection_id == collection_id)
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()


async def get_visible_document(
    session: AsyncSession, user: User, document_id: UUID
) -> Document | None:
    return (
        await session.execute(
            select(Document)
            .join(Collection, Document.collection_id == Collection.id)
            .where(Document.id == document_id, _visible_to(user))
        )
    ).scalar_one_or_none()


async def get_owned_document(
    session: AsyncSession, user: User, document_id: UUID
) -> Document | None:
    return (
        await session.execute(
            select(Document)
            .join(Collection, Document.collection_id == Collection.id)
            .where(Document.id == document_id, Collection.owner_id == user.id)
        )
    ).scalar_one_or_none()


async def list_document_chunks(
    session: AsyncSession, user: User, document_id: UUID
) -> Sequence[tuple[Chunk, Section]] | None:
    if await get_visible_document(session, user, document_id) is None:
        return None
    rows = (
        await session.execute(
            select(Chunk, Section)
            .join(Section, Chunk.section_id == Section.id)
            .where(Chunk.document_id == document_id)
            .order_by(Section.ord, Chunk.ord)
        )
    ).all()
    return [(chunk, section) for chunk, section in rows]
