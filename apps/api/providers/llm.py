"""LiteLLM wrapper (python.md: providers owns the model catalogue and calls).

Langfuse tracing is env-gated: when LANGFUSE_PUBLIC_KEY/SECRET_KEY are set,
every completion is forwarded as a Langfuse generation (TRD §15).
"""

import os
from collections.abc import AsyncIterator

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
) -> AsyncIterator[str]:
    """Yield content deltas from one streamed chat completion.

    litellm_model is the fully-qualified id ("openrouter/<model_id>").
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
            delta = chunk["choices"][0]["delta"].get("content")
        except (KeyError, IndexError, TypeError):
            continue
        if delta:
            yield str(delta)
