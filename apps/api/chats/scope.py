"""Server-side scope resolution for a run (ADR-002, TRD §9.2).

A run's scope is derived from the chat alone — the request never carries
collection ids. This is the only place that decides which documents a chat
can see, so every rule about who is in scope lives here.
"""

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Collection, Document

# Only a document retrieval can actually return counts as being in the
# library: claiming a still-parsing or failed upload is "in your sources"
# would answer with something the user cannot search yet.
SEARCHABLE_STATUSES = ("ready",)


async def resolve_scope(
    session: AsyncSession, chat: Chat, extra_collection_ids: Sequence[UUID] = ()
) -> list[UUID]:
    """The chat's own container plus every shared container (ADR-002 addendum).

    A private `library` container is never in scope: with no UI it would be an
    invisible source quietly changing answers. `chats.include_library` stays in
    the schema but is no longer read.

    `extra_collection_ids` is the one caller-side exception, and it exists for
    KI-24: the eval corpora are private collections owned by the eval user, so
    only a caller that already knows their ids can reach them — the eval runner,
    which loaded them. The HTTP chat path never passes it, which is what keeps
    the ADR-002 rule intact for real users. `build_scope` re-checks ownership in
    SQL for every id handed in here (`owner_id = scope_user OR visibility =
    'shared'`, ANDed with the collection-id list), so a wrong id widens nothing.
    """
    rows = await session.execute(
        select(Collection.id).where(
            or_(
                and_(Collection.kind == "chat", Collection.chat_id == chat.id),
                Collection.visibility == "shared",
            )
        )
    )
    ids = list(rows.scalars())
    for extra in extra_collection_ids:
        if extra not in ids:
            ids.append(extra)
    return ids


async def list_scope_documents(session: AsyncSession, collection_ids: list[UUID]) -> list[Document]:
    """The searchable documents in an already-resolved scope.

    Takes collection ids rather than a Chat so it cannot be handed a scope
    built any other way — these are the same ids retrieval was given.
    """
    if not collection_ids:
        return []
    return list(
        (
            await session.execute(
                select(Document)
                .where(
                    Document.collection_id.in_(collection_ids),
                    Document.status.in_(SEARCHABLE_STATUSES),
                )
                .order_by(Document.name)
            )
        )
        .scalars()
        .all()
    )


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
