"""A cancelled or crashed half-open probe must not disable Jev for good (S6).

`CircuitBreaker.allow_jev` moves the breaker from OPEN to PROBING and
returns True. PROBING rejects every later Jev attempt, so whatever resolves
the probe is the only thing standing between one cancelled probe and a
process that routes every decision to the fallback forever — a decision
engine that never makes a decision again, with no log line to say so.

Each test drives the real `DecisionEngine.decide` with a fake Jev that
blocks until the test releases it, so the cancellation lands inside the
probe rather than around it.
"""

import asyncio
from typing import Any

import pytest

from decisions.breaker import BreakerState, CircuitBreaker
from decisions.engine import DecisionEngine
from schemas.decisions import Answer, Question
from tests.decisions.test_engine import _FakeFallback, _questions

_JevAnswers = dict[str, Answer]


class _BlockingJev:
    """Signals when the probe has started, then waits to be released."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> _JevAnswers:
        del state, questions
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return {}


class _ExplodingJev:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> _JevAnswers:
        del state, questions
        self.calls += 1
        raise ValueError("something we did not anticipate")


class _OkJev:
    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> _JevAnswers:
        del state, questions
        return {}


class _FailingJev:
    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> _JevAnswers:
        del state, questions
        raise TimeoutError


def _breaker_in_probing(cooldown: float = 0.0) -> CircuitBreaker:
    breaker = CircuitBreaker(failure_threshold=1, window_seconds=60, cooldown_seconds=cooldown)
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    return breaker


async def test_a_cancelled_probe_leaves_the_breaker_retryable() -> None:
    jev = _BlockingJev()
    breaker = _breaker_in_probing()
    engine = DecisionEngine(jev=jev, fallback=_FakeFallback(), breaker=breaker, mode="auto")

    task = asyncio.create_task(engine.decide(state="q", questions=_questions()))
    await jev.started.wait()
    assert breaker.state is BreakerState.PROBING
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert breaker.state is not BreakerState.PROBING, (
        "the breaker is stuck PROBING: every later decision now uses the fallback"
    )
    # A failed probe re-opens with the cooldown already elapsed (0.0 here), so
    # the breaker is retryable rather than latched.
    assert breaker.allow_jev(), "the breaker did not become retryable after a cancelled probe"


async def test_the_decision_after_a_cancelled_probe_attempts_jev_again() -> None:
    jev = _BlockingJev()
    breaker = _breaker_in_probing()
    engine = DecisionEngine(jev=jev, fallback=_FakeFallback(), breaker=breaker, mode="auto")

    task = asyncio.create_task(engine.decide(state="q", questions=_questions()))
    await jev.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The very next decision reaches Jev, without waiting out a fresh cooldown.
    fresh = _BlockingJev()
    fresh.release.set()
    engine2 = DecisionEngine(jev=fresh, fallback=_FakeFallback(), breaker=breaker, mode="auto")
    await engine2.decide(state="q", questions=_questions())
    assert fresh.calls == 1, "Jev was not attempted after a cancelled probe"


async def test_an_unexpected_exception_during_a_probe_resolves_it() -> None:
    breaker = _breaker_in_probing()
    engine = DecisionEngine(
        jev=_ExplodingJev(), fallback=_FakeFallback(), breaker=breaker, mode="auto"
    )

    with pytest.raises(ValueError, match="did not anticipate"):
        await engine.decide(state="q", questions=_questions())

    assert breaker.state is not BreakerState.PROBING
    assert breaker.allow_jev()


async def test_a_successful_probe_still_closes_the_breaker() -> None:
    breaker = _breaker_in_probing()
    engine = DecisionEngine(jev=_OkJev(), fallback=_FakeFallback(), breaker=breaker, mode="auto")

    await engine.decide(state="q", questions=_questions())

    assert breaker.state is BreakerState.CLOSED


async def test_a_closed_breaker_still_accumulates_failures_towards_open() -> None:
    """The context manager must not turn one failure into an immediate open."""
    breaker = CircuitBreaker(failure_threshold=3, window_seconds=60, cooldown_seconds=60)
    engine = DecisionEngine(
        jev=_FailingJev(), fallback=_FakeFallback(), breaker=breaker, mode="auto"
    )

    for expected in (BreakerState.CLOSED, BreakerState.CLOSED, BreakerState.OPEN):
        await engine.decide(state="q", questions=_questions())
        assert breaker.state is expected
