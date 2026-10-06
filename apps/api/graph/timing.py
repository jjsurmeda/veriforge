"""Shared step-timing helper (TRD §12 step.started/step.completed) — every
mode's prepare_*_run wraps timed sub-steps with this so StepStarted/
StepCompleted events and latency_ms are recorded the same way everywhere.

Each step also opens a Langfuse span under the run's trace (KI-21). This is
the one place a stage passes through on every mode's path, so it is where
node-level spans belong: TRD §15 promises them, and until now only the LLM
generations and the post-hoc scores reached Langfuse, so a run's trace
showed what it said and nothing about how it got there.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

from observability import tracing
from schemas.events import RunStreamEvent, StepCompleted, StepStarted

logger = logging.getLogger(__name__)

T = TypeVar("T")
EventPublisher = Callable[[UUID, RunStreamEvent], Awaitable[None]]


def make_step_timer(
    *, node: str, run_id: UUID, latency_ms: dict[str, int], publish: EventPublisher | None
) -> Callable[[str, Callable[[], Awaitable[T]]], Awaitable[T]]:
    async def _step(label: str, work: Callable[[], Awaitable[T]]) -> T:
        if publish is not None:
            await publish(run_id, StepStarted(node=node, label=label))
        started = time.monotonic()
        # `trace_id=str(run_id)` rather than `tracing.current_trace_id()`:
        # the run id is right here, so the span lands under the run's trace
        # without depending on a contextvar being set. Falls back to the
        # caller's id when tracing is off (yields None, which is ignored).
        duration = 0
        async with tracing.async_span(
            f"{node}.{label}",
            trace_id=str(run_id),
            metadata={"node": node, "label": label, "run_id": str(run_id)},
        ) as handle:
            try:
                result = await work()
            except BaseException as exc:
                if handle is not None:
                    _mark_failed(handle, exc)
                raise
            duration = int((time.monotonic() - started) * 1000)
            # `+=`, not `=`: the Auto retry loop re-enters `retrieve`/`sanitize`,
            # and overwriting dropped every attempt but the last from the totals.
            latency_ms[label] = latency_ms.get(label, 0) + duration
            if handle is not None:
                try:
                    handle.update(metadata={"duration_ms": duration})
                except Exception:
                    logger.warning("langfuse step span %s/%s not updated", node, label)
        if publish is not None:
            await publish(run_id, StepCompleted(node=node, label=label, duration_ms=duration))
        return result

    return _step


def _mark_failed(handle: object, exc: BaseException) -> None:
    """Record a failed step as an ERROR span. Never raises."""
    try:
        handle.update(  # type: ignore[attr-defined]
            level="ERROR",
            status_message=f"{type(exc).__name__}: {exc}"[:500],
        )
    except Exception:
        logger.warning("langfuse step span not marked failed", exc_info=True)