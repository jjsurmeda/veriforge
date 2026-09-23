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
from dataclasses import dataclass, field
from enum import Enum


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
        self._failures.clear()
        self._opened_at = None
        self._state = BreakerState.CLOSED

    def record_failure(self) -> None:
        now = self._now()
        self._prune(now)
        if self._state is BreakerState.PROBING:
            # Probe failed — re-open for another cooldown.
            self._opened_at = now
            self._state = BreakerState.OPEN
            return
        self._failures.append(now)
        if len(self._failures) >= self.failure_threshold:
            self._opened_at = now
            self._state = BreakerState.OPEN

    @property
    def state(self) -> BreakerState:
        return self._state
