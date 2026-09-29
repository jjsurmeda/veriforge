"""LiteLLM wrapper (python.md: providers owns the model catalogue and calls).

Langfuse tracing is env-gated: when LANGFUSE_PUBLIC_KEY/SECRET_KEY are set,
every completion is forwarded as a Langfuse generation (TRD §15).
"""

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import litellm
from litellm.exceptions import (
    APIConnectionError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from config import get_settings
from quota.usage import get_usage_context

logger = logging.getLogger(__name__)

_callbacks_configured = False

# Transient provider failures worth one hop to llm_fallback_model (KI-7).
_FAILOVER_ERRORS = (
    RateLimitError,
    ServiceUnavailableError,
    InternalServerError,
    Timeout,
    APIConnectionError,
)

# ponytail: per-process cap keyed by (event loop, model); move to a
# Postgres-backed limiter if several workers together exceed provider limits.
_slots: dict[tuple[int, str], asyncio.Semaphore] = {}

_SENTENCE_END = re.compile(r"[.!?\n]")


def _slot(model: str) -> asyncio.Semaphore:
    key = (id(asyncio.get_running_loop()), model)
    slot = _slots.get(key)
    if slot is None:
        slot = _slots[key] = asyncio.Semaphore(get_settings().llm_max_concurrency)
    return slot


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


def _request_kwargs(
    model: str,
    metadata: dict[str, str],
    inherited_key: str | None = None,
    *,
    reasoning: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    role = metadata.get("role", "unknown")
    kwargs: dict[str, Any] = {
        "max_tokens": settings.llm_max_tokens.get(role, settings.llm_default_max_tokens),
        "num_retries": settings.llm_max_retries,
        "timeout": settings.llm_timeout_seconds,
        "metadata": {
            "trace_id": metadata.get("job", metadata.get("run_id", "")),
            "run_id": metadata.get("run_id", ""),
            "user_id": metadata.get("user_id", ""),
            "role": role,
        },
    }
    api_key = _api_key(model) or inherited_key
    if api_key is not None:
        kwargs["api_key"] = api_key
    reasoning = reasoning or role in settings.llm_reasoning_roles
    if model.startswith("openrouter/") and not reasoning:
        kwargs["extra_body"] = {"reasoning": {"enabled": False}}
    return kwargs


async def _acomplete(
    model: str, messages: list[dict[str, str]], kwargs: dict[str, Any], extra: dict[str, Any]
) -> Any:
    """One completion. Some free endpoints (openrouter/free resolving to
    nemotron-3.5-lightning:free) reject reasoning-disabled calls outright
    ("Reasoning is mandatory"); retry once letting the provider default
    (reasoning on) apply rather than failing the run."""
    try:
        return await litellm.acompletion(model=model, messages=messages, **kwargs, **extra)
    except BadRequestError as exc:
        if "reasoning is mandatory" not in str(exc).lower() or not kwargs.get("extra_body"):
            raise
        kwargs = {k: v for k, v in kwargs.items() if k != "extra_body"}
        return await litellm.acompletion(model=model, messages=messages, **kwargs, **extra)


async def _open(
    model: str,
    messages: list[dict[str, str]],
    metadata: dict[str, str],
    *,
    reasoning: bool = False,
    **extra: Any,
) -> tuple[str, Any]:
    """Start one completion, capped per model; on a transient failure hop once
    to llm_fallback_model. Returns the model that answered and its response.

    The cap covers opening the call, not reading a stream: provider limits
    count requests started. A stream never fails over after its first token.
    """
    kwargs = _request_kwargs(model, metadata, reasoning=reasoning)
    try:
        async with _slot(model):
            return model, await _acomplete(model, messages, kwargs, extra)
    except _FAILOVER_ERRORS as exc:
        fallback = get_settings().llm_fallback_model
        if not fallback or fallback == model:
            raise
        logger.warning(
            "llm %s failed (%s); failing over to %s", model, type(exc).__name__, fallback
        )
        same_provider = model.split("/", 1)[0] == fallback.split("/", 1)[0]
        inherited = kwargs.get("api_key") if same_provider else None
        fallback_kwargs = _request_kwargs(fallback, metadata, inherited, reasoning=reasoning)
        async with _slot(fallback):
            return fallback, await _acomplete(fallback, messages, fallback_kwargs, extra)


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


async def _stream_once(
    model: str,
    messages: list[dict[str, str]],
    metadata: dict[str, str],
    *,
    on_reasoning: Callable[[str], Awaitable[None]] | None,
) -> AsyncIterator[tuple[str, str]]:
    """One streamed attempt. Yields (model that answered, content delta). A
    provider error raised while iterating surfaces to the caller, which is what
    lets `stream_completion` restart the request (KI-17)."""
    answered, response = await _open(
        model,
        messages,
        metadata,
        # A caller that renders the thinking stream (Deep mode) needs it on.
        reasoning=on_reasoning is not None,
        stream=True,
        stream_options={"include_usage": True},
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
            yield answered, str(content)
    if usage is not None:
        await _record_usage(answered, metadata, *usage)


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

    A provider that dies after its first chunk restarts the whole request on
    llm_fallback_model rather than killing the run (KI-17). Partial output is
    never spliced: the first sentence is withheld until it completes so the
    common early-death case costs the user nothing, and a death after that
    restarts silently and accepts a visible hiccup. Reasoning deltas are sent
    as they arrive and so can repeat across a restart.
    """
    _configure_langfuse()
    model = await _resolved_model(litellm_model, metadata)
    # None once the first sentence has been released; otherwise the deltas held
    # back so far, so an early restart has nothing user-visible to retract.
    held: list[str] | None = []
    while True:
        current = model
        try:
            async for answered, delta in _stream_once(
                current, messages, metadata, on_reasoning=on_reasoning
            ):
                current = answered
                if held is None:
                    yield delta
                    continue
                held.append(delta)
                if _SENTENCE_END.search(delta):
                    for part in held:
                        yield part
                    held = None
            for part in held or ():
                yield part
            return
        except _FAILOVER_ERRORS as exc:
            fallback = get_settings().llm_fallback_model
            if not fallback or fallback == current:
                raise
            logger.warning(
                "llm %s died mid-stream (%s); restarting the request on %s",
                current,
                type(exc).__name__,
                fallback,
            )
            model, held = fallback, []


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
    model, response = await _open(model, messages, metadata)
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
