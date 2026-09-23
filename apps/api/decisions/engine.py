"""DecisionEngine facade (TRD §8).

The graph calls `engine.decide(state, questions)` and never knows which
engine answered. Per call: Jev first (unless the breaker is open or admin
mode says otherwise), retry once on the fallback on Jev error/timeout.
Shadow mode samples 2% of decisions and runs the fallback in the
background to detect drift.

Engine selection honours `settings.data.decision_engine_mode`:
`auto` (default) | `jev_only` | `fallback_only`.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from config import get_settings
from decisions.breaker import CircuitBreaker
from decisions.fallback import FallbackEngine, FallbackError
from decisions.jev import JevClient, JevError
from schemas.decisions import Answer, Choice, Noul, Question, Score

logger = logging.getLogger(__name__)

EngineMode = Literal["auto", "jev_only", "fallback_only"]


class EngineProtocol(Protocol):
    """Structural type for an engine — JevClient, FallbackEngine, and the
    fakes in tests/decisions/ all satisfy this."""

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]: ...


DecisionEventEmitter = Callable[[str, Answer], Awaitable[None]]
ShadowWriter = Callable[[str, str, Answer, Answer, bool], Awaitable[None]]


class DecisionEngine:
    """One DecisionEngine per process. Mode/breaker state are process-local —
    single-worker Stage 1 makes that safe (slice 9 multi-worker noted in
    breaker.py)."""

    def __init__(
        self,
        *,
        jev: EngineProtocol | None = None,
        fallback: EngineProtocol | None = None,
        breaker: CircuitBreaker | None = None,
        mode: EngineMode = "auto",
        shadow_sample_rate: float | None = None,
        shadow_writer: ShadowWriter | None = None,
        event_emitter: DecisionEventEmitter | None = None,
        rng: random.Random | None = None,
    ) -> None:
        settings = get_settings()
        self._jev = jev or JevClient()
        self._fallback = fallback or FallbackEngine()
        self._breaker = breaker or CircuitBreaker(
            failure_threshold=settings.breaker_failure_threshold,
            window_seconds=settings.breaker_window_seconds,
            cooldown_seconds=settings.breaker_cooldown_seconds,
        )
        self._mode: EngineMode = mode
        self._shadow_sample_rate = (
            shadow_sample_rate
            if shadow_sample_rate is not None
            else settings.shadow_sample_rate
        )
        self._shadow_writer = shadow_writer
        self._emitter = event_emitter
        # S311: shadow sampling is not a security boundary — the rng picks
        # which decisions to double-check, not tokens or secrets.
        self._rng = rng or random.Random()  # noqa: S311

    @property
    def mode(self) -> EngineMode:
        return self._mode

    def set_mode(self, mode: EngineMode) -> None:
        self._mode = mode

    def set_event_emitter(self, emitter: DecisionEventEmitter | None) -> None:
        """Rebind the per-run emitter. One DecisionEngine is process-local;
        the runner rebinds before each run so decision events route to the
        correct run's RunBus topic."""
        self._emitter = emitter

    async def _emit(self, name: str, answer: Answer) -> None:
        if self._emitter is not None:
            try:
                await self._emitter(name, answer)
            except Exception:
                logger.exception("decision event emitter failed for %s", name)

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        """Answer every question via Jev or fallback per switching rules."""
        if not questions:
            return {}

        if self._mode == "fallback_only":
            answers = await self._fallback.decide(state=state, questions=questions)
            for name, answer in answers.items():
                await self._emit(name, answer)
            return answers

        if self._mode == "jev_only":
            answers = await self._jev.decide(state=state, questions=questions)
            for name, answer in answers.items():
                await self._emit(name, answer)
            return answers

        # auto
        if self._breaker.allow_jev():
            try:
                answers = await self._jev.decide(state=state, questions=questions)
            except (JevError, TimeoutError) as exc:
                logger.warning("jev failed, retrying on fallback: %s", exc)
                self._breaker.record_failure()
                answers = await self._fallback.decide(state=state, questions=questions)
            else:
                self._breaker.record_success()
                self._maybe_shadow(state, questions, answers)
        else:
            answers = await self._fallback.decide(state=state, questions=questions)

        for name, answer in answers.items():
            await self._emit(name, answer)
        return answers

    def _maybe_shadow(
        self,
        state: dict[str, Any] | str,
        questions: dict[str, Question],
        jev_answers: dict[str, Answer],
    ) -> None:
        """2% sample: fire-and-forget the fallback and diff against Jev."""
        if self._shadow_writer is None:
            return
        if self._rng.random() >= self._shadow_sample_rate:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._shadow_compare(state, questions, jev_answers))
        # Fire-and-forget: keep a strong ref until done so GC can't reap mid-flight.
        task.add_done_callback(lambda _t: None)

    async def _shadow_compare(
        self,
        state: dict[str, Any] | str,
        questions: dict[str, Question],
        jev_answers: dict[str, Answer],
    ) -> None:
        try:
            fallback_answers = await self._fallback.decide(state=state, questions=questions)
        except FallbackError:
            logger.exception("shadow fallback call failed")
            return
        if self._shadow_writer is None:
            return
        run_id = _run_id_from_state(state)
        for name, question in questions.items():
            jev_answer = jev_answers.get(name)
            fallback_answer = fallback_answers.get(name)
            if jev_answer is None or fallback_answer is None:
                continue
            agree = _answers_agree(question, jev_answer, fallback_answer)
            try:
                await self._shadow_writer(run_id, name, jev_answer, fallback_answer, agree)
            except Exception:
                logger.exception("shadow write failed for %s", name)


def _run_id_from_state(state: dict[str, Any] | str) -> str:
    if isinstance(state, dict):
        value = state.get("run_id")
        if value is not None:
            return str(value)
    return ""


def _answers_agree(question: Question, jev: Answer, fallback: Answer) -> bool:
    """Loose agreement test per question type. Tolerances chosen so shadow
    data is useful, not noisy — admin can tighten in slice 7."""
    if isinstance(question, Noul):
        j = float(jev.value)
        f = float(fallback.value)
        return abs(j - f) <= 0.20
    if isinstance(question, Choice):
        return str(jev.value) == str(fallback.value)
    if isinstance(question, Score):
        return abs(float(jev.value) - float(fallback.value)) <= 0.20
    return False
