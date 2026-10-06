"""Circuit breaker for the Jev engine (TRD §8).

Three failures within `breaker_window_seconds` open the breaker; while
open, all decisions route to the fallback. After `breaker_cooldown_seconds`
one probe call to Jev is allowed; success closes the breaker, failure
re-opens it for another cooldown.

State is in-process. Single-API-worker Stage 1 makes this safe; slice 9
will need a shared store if the API scales past one worker (noted in
ADR-001's "scale-out" section).
"""

import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import cache

from config import get_settings
from observability import signals


class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    PROBING = "probing"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    window_seconds: float = 60.0
    cooldown_seconds: float = 60.0
    _failures: deque[float] = field(default_factory=deque)
    _opened_at: float | None = None
    _state: BreakerState = BreakerState.CLOSED

    def _now(self) -> float:
        return time.monotonic()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def allow_jev(self) -> bool:
        """Whether the next call should attempt Jev (True) or go straight
        to the fallback (False)."""
        now = self._now()
        self._prune(now)
        if self._state is BreakerState.CLOSED:
            return True
        if self._state is BreakerState.OPEN:
            opened_at = self._opened_at if self._opened_at is not None else now
            if now - opened_at >= self.cooldown_seconds:
                self._state = BreakerState.PROBING
                return True
            return False
        # PROBING: allow exactly one probe. Subsequent allow_jev calls
        # while PROBING go to fallback until the probe resolves.
        return False

    def record_success(self) -> None:
        previous = self._state
        self._failures.clear()
        self._opened_at = None
        self._state = BreakerState.CLOSED
        # A closed breaker is the normal state, so this line is emitted only
        # on a state *change* — a breaker that was open and got a successful
        # probe back. Emitting on every success would bury `breaker.closed`
        # under a line per successful decision and the alarm would be
        # unreadable.
        if previous is not BreakerState.CLOSED:
            signals.emit(
                signals.BREAKER_CLOSED,
                level="INFO",
                state=self._state.value,
                cooldown_seconds=self.cooldown_seconds,
            )

    def record_failure(self) -> None:
        now = self._now()
        self._prune(now)
        previous = self._state
        if self._state is BreakerState.PROBING:
            # Probe failed — re-open for another cooldown.
            self._opened_at = now
            self._state = BreakerState.OPEN
            signals.emit(
                signals.BREAKER_OPENED,
                level="ERROR",
                state=self._state.value,
                reason="probe_failed",
            )
            return
        self._failures.append(now)
        if len(self._failures) >= self.failure_threshold:
            self._opened_at = now
            self._state = BreakerState.OPEN
            # Gated on the transition, not on "the threshold is met". The
            # threshold stays met while the breaker is open, so gating on
            # that re-emitted `breaker.opened` on every further failure —
            # an alarm counting occurrences would have reported one outage
            # as N. My own test caught this; see
            # test_further_failures_while_open_do_not_re_emit.
            #
            # The state machine above is unchanged: `_opened_at` is still
            # pushed forward on every failure while open, which is the
            # pre-existing cooldown behaviour and not this item's to change.
            if previous is not BreakerState.OPEN:
                signals.emit(
                    signals.BREAKER_OPENED,
                    level="ERROR",
                    state=self._state.value,
                    reason="threshold_reached",
                    failures=len(self._failures),
                    window_seconds=self.window_seconds,
                )

    @asynccontextmanager
    async def probe(self) -> AsyncIterator[None]:
        """Resolve the state `allow_jev` just moved to, on every exit path.

        `allow_jev` returning True from OPEN means the breaker is now PROBING
        and will reject every later Jev attempt until something resolves it.
        Resolving it in the caller's success/failure branches left it
        unresolved when the probe was cancelled or raised anything else, and
        an unresolved PROBING state is permanent for the process: every later
        decision uses the fallback (review S6). So the outcome is recorded
        here, next to the state it resolves, rather than at each call site.

        A non-probe attempt is unaffected — `record_success` and
        `record_failure` on a CLOSED breaker behave as they always did.
        """
        try:
            yield
        except BaseException:
            self.record_failure()
            raise
        self.record_success()

    @property
    def state(self) -> BreakerState:
        return self._state

    @property
    def open_until(self) -> datetime | None:
        if self._state is not BreakerState.OPEN or self._opened_at is None:
            return None
        remaining = max(0.0, self._opened_at + self.cooldown_seconds - self._now())
        return datetime.now(UTC) + timedelta(seconds=remaining)


@cache
def get_breaker() -> CircuitBreaker:
    settings = get_settings()
    return CircuitBreaker(
        failure_threshold=settings.breaker_failure_threshold,
        window_seconds=settings.breaker_window_seconds,
        cooldown_seconds=settings.breaker_cooldown_seconds,
    )
