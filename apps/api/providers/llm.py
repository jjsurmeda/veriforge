"""LiteLLM wrapper (python.md: providers owns the model catalogue and calls).

Langfuse tracing is env-gated: when LANGFUSE_PUBLIC_KEY/SECRET_KEY are set,
every completion is forwarded as a Langfuse generation (TRD §15).
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable

import litellm

from config import get_settings

_callbacks_configured = False


def _configure_langfuse() -> None:
    global _callbacks_configured
    if _callbacks_configured:
        return
    settings = get_settings()
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
        if "langfuse" not in litellm.success_callback:
            litellm.success_callback.append("langfuse")
        if "langfuse" not in litellm.failure_callback:
            litellm.failure_callback.append("langfuse")
    _callbacks_configured = True


async def stream_completion(
    *,
    litellm_model: str,
    messages: list[dict[str, str]],
    metadata: dict[str, str],
    on_reasoning: Callable[[str], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    """Yield content deltas from one streamed chat completion.

    litellm_model is the fully-qualified id ("openrouter/<model_id>").
    `on_reasoning`, when given, is called with each native reasoning delta
    (litellm normalises provider-specific chain-of-thought fields to
    `delta.reasoning_content`) — existing callers that don't pass it see
    no behaviour change.
    """
    _configure_langfuse()
    response = await litellm.acompletion(
        model=litellm_model,
        messages=messages,
        stream=True,
        metadata={
            "trace_id": metadata.get("run_id", ""),
            "run_id": metadata.get("run_id", ""),
            "user_id": metadata.get("user_id", ""),
        },
    )
    async for chunk in response:
        try:
            delta = chunk["choices"][0]["delta"]
        except (KeyError, IndexError, TypeError):
            continue
        if on_reasoning is not None:
            reasoning = getattr(delta, "reasoning_content", None) or delta.get(
                "reasoning_content"
            )
            if reasoning:
                await on_reasoning(str(reasoning))
        content = delta.get("content")
        if content:
            yield str(content)


async def complete(
    *,
    litellm_model: str,
    messages: list[dict[str, str]],
    metadata: dict[str, str],
) -> str:
    """One non-streamed completion; returns the assistant message content.

    For simple background LLM calls (e.g. starter-question regeneration,
    TRD §9.1 step 6) — routing/scoring/verification decisions go through
    DecisionEngine instead (CLAUDE.md non-negotiable, slice 4+).
    """
    _configure_langfuse()
    response = await litellm.acompletion(
        model=litellm_model,
        messages=messages,
        metadata={
            "trace_id": metadata.get("job", ""),
            "user_id": metadata.get("user_id", ""),
        },
    )
    content = response["choices"][0]["message"].get("content")
    return str(content) if content else ""


async def embed_batch(*, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with the configured embedding model (TRD §9.1)."""
    _configure_langfuse()
    response = await litellm.aembedding(model=get_settings().embedding_model, input=texts)
    return [list(map(float, item["embedding"])) for item in response.data]
