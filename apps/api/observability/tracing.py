"""Langfuse tracing seam (TRD §15, KI-21).

Everything here is best-effort. A trace that cannot be pushed is a missing
line in a dashboard; a run that cannot answer because a tracing client threw
is a lost user. So every function in this module swallows its own failures,
logs them at `warning`, and returns None — the one rule that keeps
observability from becoming an outage cause.

Why a module of its own (KI-21's host half): the pinned SDK (`langfuse<3`)
reads `LANGFUSE_HOST` from the environment, not from `config.py`, and the
three places that used to talk to Langfuse each built a client differently
— `_configure_langfuse` exported only the two keys onto `os.environ`, so
the SDK fell back to its EU default, the JP keys failed to authenticate,
and 301 traces were the last thing that ever arrived. One client, one place
that reads the host, one rule that tracing never fails a run.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from functools import cache
from typing import Any

from config import get_settings

logger = logging.getLogger("veriforge.tracing")


def enabled() -> bool:
    """Whether Langfuse is configured at all. Empty keys disable tracing."""
    settings = get_settings()
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def export_environment() -> None:
    """Publish the Langfuse settings as the env vars the SDK reads.

    The SDK is configured entirely from `LANGFUSE_PUBLIC_KEY`,
    `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST`: there is no way to pass a
    host through LiteLLM's langfuse callback, which is how the host was
    lost in the first place. `setdefault`, so a value already in the
    process environment (compose forwarding, a test) still wins.
    """
    settings = get_settings()
    if settings.langfuse_public_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    if settings.langfuse_secret_key:
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    if settings.langfuse_host:
        os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)


@cache
def get_client() -> Any | None:
    """The process-wide Langfuse client, or None when tracing is off.

    Cached because constructing one starts a background flush thread; a
    client per traced call would leak a thread per call. Tests that need a
    fake call `get_client.cache_clear()` after patching.
    """
    if not enabled():
        return None
    export_environment()
    try:
        from langfuse import Langfuse

        settings = get_settings()
        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host or None,
        )
    except Exception:
        logger.warning("langfuse client construction failed; tracing disabled", exc_info=True)
        return None


def current_trace_id() -> str | None:
    """The run id of the run in flight, which is the trace id.

    `providers/llm.py` groups LiteLLM generations under `trace_id=run_id`,
    so using the same id here is what nests Jev calls and stage spans
    *under* the run's trace instead of beside it. The usage context is the
    run-scoped contextvar the runner sets, so this resolves for every node
    without threading a run id through each call site.
    """
    from quota.usage import get_usage_context

    context = get_usage_context()
    return str(context.run_id) if context is not None else None


@contextmanager
def span(
    name: str,
    *,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    input: Any = None,
) -> Iterator[Any | None]:
    """A Langfuse span around a block, or None when tracing is off.

    Yields the stateful span so the caller can `.update(metadata=...)`
    with whatever the block learned. An exception from the *body* is not
    swallowed — it is the caller's business, and `finally` still closes the
    span so a failed stage is recorded as a span that ended. What is
    swallowed is any failure of the tracing client itself, which ends as a
    logged warning and a yielded None.
    """
    client = get_client()
    if client is None:
        yield None
        return
    handle: Any
    try:
        handle = client.span(
            name=name,
            trace_id=trace_id,
            metadata=metadata,
            input=input,
            start_time=datetime.now(UTC),
        )
    except Exception:
        logger.warning("langfuse span %s could not be opened", name, exc_info=True)
        yield None
        return
    try:
        yield handle
    finally:
        try:
            handle.end()
        except Exception:
            logger.warning("langfuse span %s could not be closed", name, exc_info=True)


@asynccontextmanager
async def async_span(
    name: str,
    *,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    input: Any = None,
) -> AsyncIterator[Any | None]:
    """`span` for an async block. Same contract, same never-raise rule.

    The SDK's client is synchronous and buffers events to a background
    thread, so opening and closing a span does not block the loop
    meaningfully. What matters is that the body's own exception is not
    swallowed here either, or a broken stage would look like a clean one.
    """
    with span(name, trace_id=trace_id, metadata=metadata, input=input) as handle:
        yield handle


def record_decision_call(
    *,
    engine: str,
    decision_names: list[str],
    stage: str | None,
    trace_id: str | None,
    answers: dict[str, Any] | None = None,
    latency_ms: int = 0,
    error: str | None = None,
) -> None:
    """Record one decision-engine call as a span under the run's trace.

    Jev uses raw `httpx`, not LiteLLM, so before this nothing about a
    decision reached Langfuse: the trace showed the LLM generations and
    nothing that decided anything (KI-21). A span rather than a generation
    because there is no completion to bill — `engine`, `latency_ms`, the
    decision names and their probabilities are the payload.
    """
    client = get_client()
    if client is None:
        return
    metadata: dict[str, Any] = {
        "engine": engine,
        "decision_names": decision_names,
        "latency_ms": latency_ms,
    }
    if stage is not None:
        metadata["stage"] = stage
    probabilities: dict[str, float] = {}
    for name, answer in (answers or {}).items():
        probability = getattr(answer, "probability", None)
        if probability is not None:
            probabilities[name] = float(probability)
    if probabilities:
        metadata["probabilities"] = probabilities
    if error is not None:
        metadata["error"] = error
    try:
        handle = client.span(
            name=f"decision.{engine}",
            trace_id=trace_id,
            metadata=metadata,
            start_time=datetime.now(UTC),
        )
        handle.end(end_time=datetime.now(UTC))
    except Exception:
        logger.warning("langfuse decision span failed", exc_info=True)


def score(trace_id: str, scores: dict[str, float]) -> None:
    """Push trace-level scores, one failure per score never failing the rest.

    Called from `graph/async_scoring.py` in a worker thread, so the
    synchronous client is fine here.
    """
    client = get_client()
    if client is None:
        return
    for name, value in scores.items():
        try:
            client.score(trace_id=trace_id, name=name, value=value)
        except Exception:
            logger.warning("langfuse score %s could not be pushed", name, exc_info=True)


def flush() -> None:
    """Push whatever is buffered. For one-shot scripts, never for a run."""
    client = get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.warning("langfuse flush failed", exc_info=True)