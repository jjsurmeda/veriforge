"""Plain-LLM streaming node — slice 1's single graph node (TRD §17 row 1).

LangGraph orchestration arrives in slices 3-4; this node takes the
message, calls the chat's model via LiteLLM and yields tokens, which the
runner coalesces into answer.delta events on the RunBus.
"""

from collections.abc import AsyncIterator
from pathlib import Path

from providers.llm import stream_completion

_PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompts" / "plain_chat.md"
_SYSTEM_PROMPT = _PROMPT_FILE.read_text()


def build_messages(history: list[tuple[str, str]], user_message: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for role, content in history:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


async def stream_plain_answer(
    *,
    litellm_model: str,
    history: list[tuple[str, str]],
    user_message: str,
    metadata: dict[str, str],
) -> AsyncIterator[str]:
    async for token in stream_completion(
        litellm_model=litellm_model,
        messages=build_messages(history, user_message),
        metadata=metadata,
    ):
        yield token
