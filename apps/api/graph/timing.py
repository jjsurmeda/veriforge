"""Shared step-timing helper (TRD §12 step.started/step.completed) — every
mode's prepare_*_run wraps timed sub-steps with this so StepStarted/
StepCompleted events and latency_ms are recorded the same way everywhere."""

import time
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

from schemas.events import RunStreamEvent, StepCompleted, StepStarted

T = TypeVar("T")
EventPublisher = Callable[[UUID, RunStreamEvent], Awaitable[None]]


def make_step_timer(
    *, node: str, run_id: UUID, latency_ms: dict[str, int], publish: EventPublisher | None
) -> Callable[[str, Callable[[], Awaitable[T]]], Awaitable[T]]:
    async def _step(label: str, work: Callable[[], Awaitable[T]]) -> T:
        if publish is not None:
            await publish(run_id, StepStarted(node=node, label=label))
        started = time.monotonic()
        result = await work()
        duration = int((time.monotonic() - started) * 1000)
        latency_ms[label] = duration
        if publish is not None:
            await publish(run_id, StepCompleted(node=node, label=label, duration_ms=duration))
        return result

    return _step
