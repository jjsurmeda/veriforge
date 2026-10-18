"""Rewrite + summary node (TRD §7): small-LLM condensation of the question
with history, and the rolling chat summary refreshed every 10 turns.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Message
from prompts.load import load_prompt

logger = logging.getLogger(__name__)

SUMMARY_INTERVAL_TURNS = 10
CompleteFn = Callable[..., Awaitable[str]]

# The rewriter's output contract (KI-73). A rewrite is a *query*: a standalone
# question to search on. Asked to rewrite a message that contains no question,
# a chat model can answer the instruction instead of following it — and the
# recorded run's reply was:
#
#   "I understand. You're correct—there is no question to rewrite in your
#    message. I'm ready to help when you provide:"
#
# That prose became retrieval query #1 and, through the variant fan-out, every
# other query in the run. Nothing validated it, the nonsense retrieval cleared
# sufficiency, and a message with no question answered with eight citations.
#
# The test is the SHAPE of the reply, not a list of phrasings — a phrase list
# here would be the greeting-allowlist mistake CLAUDE.md fixes in the opposite
# direction. A search query is one clause. So: a reply that asks a question is
# a query however long it is ("What is Rocinante? And who rides him?" is a
# two-sentence multi-part query, and the follow-up path depends on long
# rewrites being kept), and a reply that never asks is a query only while it
# stays inside one sentence. Two sentence terminators without a "?" means the
# model opened a reply rather than a query, and the safe direction is to drop
# it: the run falls back to the user's own message, which is a real query even
# when it is a pronoun-laden follow-up, and never a paragraph about the
# conversation that contains no question at all.
_SENTENCE_END = re.compile(r"[.!?…]")


def is_query_shape(rewritten: str) -> bool:
    """Whether `rewritten` has the shape of a search query rather than prose."""
    text = rewritten.strip()
    if not text:
        return False
    if "?" in text:
        return True
    return len(_SENTENCE_END.findall(text)) < 2


async def rewrite_query(
    *,
    question: str,
    history: list[tuple[str, str]],
    summary: str | None,
    small_model: str,
    complete_fn: CompleteFn,
) -> str:
    """Standalone-ise a follow-up question. First turn returns unchanged —
    no LLM call without context to resolve.

    A reply that fails the output contract above is discarded and the original
    question is used instead, so a message with no question cannot be
    answered from the rewriter's prose about having no question.
    """
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
        metadata={"role": "rewriter"},
    )
    rewritten = response.strip()
    if not rewritten:
        logger.warning("rewrite returned empty; using original question")
        return question
    if not is_query_shape(rewritten):
        logger.warning(
            "rewrite answered the instruction instead of following it (%r); "
            "using the original question",
            rewritten[:160],
        )
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
        await session.execute(select(func.count(Message.id)).where(Message.chat_id == chat_id))
    ).scalar_one()
    if count == 0 or count % SUMMARY_INTERVAL_TURNS != 0:
        return
    messages = (
        (
            await session.execute(
                select(Message)
                .where(Message.chat_id == chat_id)
                .order_by(Message.created_at.desc())
                .limit(SUMMARY_INTERVAL_TURNS)
            )
        )
        .scalars()
        .all()
    )
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
        metadata={"role": "rewriter"},
    )
    if response.strip():
        await session.execute(
            update(Chat).where(Chat.id == chat_id).values(summary=response.strip()[:4000])
        )
