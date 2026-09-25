"""Server-side scope resolution for a run (ADR-002, TRD §9.2).

A run's scope is derived from the chat alone — the request never carries
collection ids. This is the only place that decides which documents a chat
can see, so every rule about who is in scope lives here.
"""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Collection, User


async def resolve_scope(session: AsyncSession, user: User, chat: Chat) -> list[UUID]:
    """The chat's own container, plus the Library and Shared when included."""
    clauses = [and_(Collection.kind == "chat", Collection.chat_id == chat.id)]
    if chat.include_library:
        clauses.append(
            or_(
                and_(Collection.kind == "library", Collection.owner_id == user.id),
                Collection.visibility == "shared",
            )
        )
    rows = await session.execute(select(Collection.id).where(or_(*clauses)))
    return list(rows.scalars())


async def library_starter_questions(session: AsyncSession, user: User) -> list[str]:
    """The user's Library plus Shared questions, deduped, in one query."""
    rows = await session.execute(
        select(Collection.starter_questions).where(
            Collection.kind == "library",
            or_(Collection.owner_id == user.id, Collection.visibility == "shared"),
        )
    )
    return dedupe(q for questions in rows.scalars() for q in (questions or []))


async def chat_starter_questions(
    session: AsyncSession, user: User, chat: Chat
) -> list[str]:
    """The chat container's questions, falling back to the Library's.

    The fallback is gated on include_library so suggestions only ever point
    at evidence the run can actually reach.
    """
    rows = await session.execute(
        select(Collection.starter_questions).where(
            Collection.kind == "chat", Collection.chat_id == chat.id
        )
    )
    own = dedupe(q for questions in rows.scalars() for q in (questions or []))
    if own or not chat.include_library:
        return own
    return await library_starter_questions(session, user)


def dedupe(questions: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for question in questions:
        if question not in seen:
            seen.add(question)
            out.append(question)
    return out
