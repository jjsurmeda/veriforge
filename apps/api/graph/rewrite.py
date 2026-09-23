"""Rewrite + summary node (TRD §7): small-LLM condensation of the question
with history, and the rolling chat summary refreshed every 10 turns.
"""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Message
from prompts.load import load_prompt

logger = logging.getLogger(__name__)

SUMMARY_INTERVAL_TURNS = 10
CompleteFn = Callable[..., Awaitable[str]]


async def rewrite_query(
    *,
    question: str,
    history: list[tuple[str, str]],
    summary: str | None,
    small_model: str,
    complete_fn: CompleteFn,
) -> str:
    """Standalone-ise a follow-up question. First turn returns unchanged —
    no LLM call without context to resolve."""
    if not history:
        return question
    recent = "\n".join(f"{role}: {content}" for role, content in history[-8:])
    response = await complete_fn(
        litellm_model=small_model,
        messages=[
            {
                "role": "system",
                "content": load_prompt("rewrite.md").format(
                    summary=summary or "(none)",
                    history=recent,
                    question=question,
                ),
            },
            {"role": "user", "content": question},
        ],
        metadata={},
    )
    rewritten = response.strip()
    if not rewritten:
        logger.warning("rewrite returned empty; using original question")
        return question
    return rewritten


async def maybe_refresh_summary(
    session: AsyncSession,
    *,
    chat_id: UUID,
    summary: str | None,
    small_model: str,
    complete_fn: CompleteFn,
) -> None:
    """Regenerate chats.summary when the turn count hits a multiple of 10."""
    count = (
        await session.execute(
            select(func.count(Message.id)).where(Message.chat_id == chat_id)
        )
    ).scalar_one()
    if count == 0 or count % SUMMARY_INTERVAL_TURNS != 0:
        return
    messages = (
        await session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(SUMMARY_INTERVAL_TURNS)
        )
    ).scalars().all()
    recent = "\n".join(f"{m.role}: {m.content[:500]}" for m in reversed(messages))
    response = await complete_fn(
        litellm_model=small_model,
        messages=[
            {
                "role": "system",
                "content": load_prompt("summary.md").format(
                    summary=summary or "(none)", messages=recent
                ),
            },
            {"role": "user", "content": recent[-2000:]},
        ],
        metadata={},
    )
    if response.strip():
        await session.execute(
            update(Chat).where(Chat.id == chat_id).values(summary=response.strip()[:4000])
        )
