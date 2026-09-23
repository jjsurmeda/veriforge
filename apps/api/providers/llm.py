"""LiteLLM wrapper (python.md: providers owns the model catalogue and calls).

Langfuse tracing is env-gated: when LANGFUSE_PUBLIC_KEY/SECRET_KEY are set,
every completion is forwarded as a Langfuse generation (TRD §15).
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import litellm

from config import get_settings
from quota.usage import get_usage_context

_callbacks_configured = False


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _usage(response: Any) -> tuple[int, int] | None:
    usage = _field(response, "usage")
    if usage is None:
        return None
    tokens_in = _field(usage, "prompt_tokens")
    tokens_out = _field(usage, "completion_tokens")
    if tokens_in is None or tokens_out is None:
        return None
    return int(tokens_in), int(tokens_out)


async def _resolved_model(litellm_model: str, metadata: dict[str, str]) -> str:
    context = get_usage_context()
    if context is None:
        return litellm_model
    return await context.resolve_model(litellm_model, metadata.get("role", "unknown"))


async def _record_usage(
    model: str, metadata: dict[str, str], tokens_in: int, tokens_out: int
) -> None:
    context = get_usage_context()
    if context is not None:
        await context.record_call(
            model_id=model,
            role=metadata.get("role", "unknown"),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


def _api_key(model: str) -> str | None:
    context = get_usage_context()
    return context.api_key_for(model) if context is not None else None


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
    model = await _resolved_model(litellm_model, metadata)
    request_kwargs: dict[str, Any] = {}
    api_key = _api_key(model)
    if api_key is not None:
        request_kwargs["api_key"] = api_key
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        metadata={
            "trace_id": metadata.get("run_id", ""),
            "run_id": metadata.get("run_id", ""),
            "user_id": metadata.get("user_id", ""),
            "role": metadata.get("role", "unknown"),
        },
        **request_kwargs,
    )
    usage: tuple[int, int] | None = None
    async for chunk in response:
        chunk_usage = _usage(chunk)
        if chunk_usage is not None:
            usage = chunk_usage
        try:
            delta = chunk["choices"][0]["delta"]
        except (KeyError, IndexError, TypeError):
            continue
        if on_reasoning is not None:
            reasoning = getattr(delta, "reasoning_content", None) or delta.get("reasoning_content")
            if reasoning:
                await on_reasoning(str(reasoning))
        content = delta.get("content")
        if content:
            yield str(content)
    if usage is not None:
        await _record_usage(model, metadata, *usage)


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
    model = await _resolved_model(litellm_model, metadata)
    request_kwargs: dict[str, Any] = {}
    api_key = _api_key(model)
    if api_key is not None:
        request_kwargs["api_key"] = api_key
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        metadata={
            "trace_id": metadata.get("job", metadata.get("run_id", "")),
            "run_id": metadata.get("run_id", ""),
            "user_id": metadata.get("user_id", ""),
            "role": metadata.get("role", "unknown"),
        },
        **request_kwargs,
    )
    usage = _usage(response)
    if usage is not None:
        await _record_usage(model, metadata, *usage)
    content = _field(_field(response, "choices")[0], "message")
    content = _field(content, "content")
    return str(content) if content else ""


async def embed_batch(*, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts with the configured embedding model (TRD §9.1)."""
    _configure_langfuse()
    response = await litellm.aembedding(model=get_settings().embedding_model, input=texts)
    return [list(map(float, item["embedding"])) for item in response.data]
