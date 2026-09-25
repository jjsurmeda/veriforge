import json
import logging
import re
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat
from prompts.load import load_prompt
from providers.llm import complete


class CompleteFn(Protocol):

    def __call__(
        self,
        *,
        litellm_model: str,
        messages: list[dict[str, str]],
        metadata: dict[str, str],
    ) -> Awaitable[str]: ...


logger = logging.getLogger(__name__)

DEFAULT_CHAT_TITLE = "New chat"
MAX_INSTANT_TITLE_CHARS = 60
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def collapse_instant_title(question: str) -> str:
    collapsed = " ".join(question.split()) or DEFAULT_CHAT_TITLE
    if len(collapsed) <= MAX_INSTANT_TITLE_CHARS:
        return collapsed
    limit = MAX_INSTANT_TITLE_CHARS - 1
    prefix = collapsed[:limit]
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return f"{prefix.rstrip()}…"


def parse_chat_title(response: str) -> str | None:
    match = _FENCE_RE.match(response.strip())
    text = match.group(1).strip() if match is not None else response.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    title = data.get("title")
    if not isinstance(title, str):
        return None
    title = title.strip().strip('"“”').rstrip(".!? ")
    return title or None


async def generate_chat_title(
    *,
    question: str,
    answer: str,
    small_model: str,
    complete_fn: CompleteFn | None = None,
) -> str | None:
    complete_call = complete if complete_fn is None else complete_fn
    prompt = (
        load_prompt("chat_title.md")
        .replace("{question}", question)
        .replace("{answer}", answer[:4000])
    )
    try:
        response = await complete_call(
            litellm_model=small_model,
            messages=[{"role": "system", "content": prompt}],
            metadata={"job": "chat_title", "role": "titler"},
        )
    except Exception:
        logger.exception("chat title generation failed")
        return None
    return parse_chat_title(response)


async def refine_chat_title(
    *,
    session: AsyncSession,
    chat_id: UUID,
    instant_title: str | None,
    question: str,
    answer: str,
    small_model: str,
) -> str | None:
    if instant_title is None:
        return None
    title = await generate_chat_title(question=question, answer=answer, small_model=small_model)
    if title is None:
        return None
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.title != instant_title:
        return None
    chat.title = title
    return title
