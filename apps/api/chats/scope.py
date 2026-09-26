"""Server-side scope resolution for a run (ADR-002, TRD §9.2).

A run's scope is derived from the chat alone — the request never carries
collection ids. This is the only place that decides which documents a chat
can see, so every rule about who is in scope lives here.
"""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Collection


async def resolve_scope(session: AsyncSession, chat: Chat) -> list[UUID]:
    """The chat's own container plus every shared container (ADR-002 addendum).

    A private `library` container is never in scope: with no UI it would be an
    invisible source quietly changing answers. `chats.include_library` stays in
    the schema but is no longer read.
    """
    rows = await session.execute(
        select(Collection.id).where(
            or_(
                and_(Collection.kind == "chat", Collection.chat_id == chat.id),
                Collection.visibility == "shared",
            )
        )
    )
    return list(rows.scalars())


async def library_starter_questions(session: AsyncSession) -> list[str]:
    """Shared questions, deduped, in one query."""
    rows = await session.execute(
        select(Collection.starter_questions).where(Collection.visibility == "shared")
    )
    return dedupe(q for questions in rows.scalars() for q in (questions or []))


async def chat_starter_questions(session: AsyncSession, chat: Chat) -> list[str]:
    """The chat container's questions, falling back to the Shared ones."""
    rows = await session.execute(
        select(Collection.starter_questions).where(
            Collection.kind == "chat", Collection.chat_id == chat.id
        )
    )
    own = dedupe(q for questions in rows.scalars() for q in (questions or []))
    if own:
        return own
    return await library_starter_questions(session)


def dedupe(questions: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for question in questions:
        if question not in seen:
            seen.add(question)
            out.append(question)
    return out
