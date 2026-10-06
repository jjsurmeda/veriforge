"""In-process rate limiting (item 4), per ADR-001's "no Redis at Stage 1".

An invited beta is a handful of people on one instance with one api process,
so an in-process counter is the right size of answer and the wrong size of
claim. What it buys is real: signup and login are the endpoints worth
brute-forcing, and 10 attempts a minute per IP is the difference between a
costless guessing loop and an unusable account list.

What it does not buy, stated here so nobody builds an alarm on it:

- **It is per process.** A second api worker doubles every limit. Stage 1
  runs one (TRD §16), so this is currently exact, and it stops being exact
  the moment that changes — which is the documented Redis seam.
- **It is per instance.** An attacker who can reach several instances gets
  several times the limit. Behind one Caddy on one t4g, that is not a
  meaningful weakening.
- **It forgets on restart.** Limits reset when the process does. A restart
  loop is therefore a way to get fresh attempts, which is a reason to alert
  on restarts and not to treat this as a security boundary.

A sliding window rather than a fixed one: a fixed window lets an attacker
spend the whole quota at 59s and the whole quota again at 61s, doubling the
rate at the boundary. The deque keeps the timestamps of recent attempts and
drops the ones that have aged out, so the limit holds at every instant
rather than averaging over the window.

Not an authentication control. The real defences against credential
guessing are argon2's cost, the lockout policy in `auth/`, and the fact that
a wrong password and a wrong email are answered identically.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Literal

from config import get_settings
from errors import AppError

BucketKey = tuple[str, str]


@dataclass
class RateLimiter:
    """Sliding-window counter, in-process."""

    limit: int
    window_seconds: float
    _hits: dict[BucketKey, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _now: object = time.monotonic

    def _prune(self, bucket: BucketKey, now: float) -> deque[float]:
        hits = self._hits[bucket]
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def check(self, bucket: BucketKey) -> int | None:
        """Record an attempt; return the seconds to wait, or None if allowed.

        The attempt is recorded whether or not it is allowed, so a client
        that keeps hammering stays throttled instead of getting a fresh
        budget each time its window rolls over.
        """
        now = float(self._now())  # type: ignore[operator]
        hits = self._prune(bucket, now)
        if len(hits) >= self.limit:
            return max(1, round(self.window_seconds - (now - hits[0])))
        hits.append(now)
        return None

    def reset(self, bucket: BucketKey) -> None:
        self._hits.pop(bucket, None)

    def clear(self) -> None:
        self._hits.clear()


class RateLimited(AppError):
    """429, with `Retry-After` set by the route from `detail.retry_after`."""

    status_code = 429

    def __init__(self, scope: str, retry_after: int) -> None:
        super().__init__(
            "rate_limited",
            f"Too many attempts. Try again in {retry_after} seconds.",
            {"scope": scope, "retry_after": retry_after},
        )
        self.retry_after = retry_after


# Named scopes so the limits can be read in one place, and so the numbers
# are settings rather than constants buried in a route.
SCOPES: dict[str, tuple[str, str]] = {
    # (setting holding the limit, setting holding the window)
    "signup": ("rate_limit_signup", "rate_limit_signup_window_seconds"),
    "login": ("rate_limit_login", "rate_limit_login_window_seconds"),
    "run": ("rate_limit_run", "rate_limit_run_window_seconds"),
}

_auth_limiter: RateLimiter | None = None
_run_limiter: RateLimiter | None = None


def _settings_for(scope: str) -> tuple[int, float]:
    limit_setting, window_setting = SCOPES[scope]
    settings = get_settings()
    return int(getattr(settings, limit_setting)), float(getattr(settings, window_setting))


def limiter_for(scope: Literal["signup", "login", "run"]) -> RateLimiter:
    """The process-wide limiter for a scope, built from current settings.

    Rebuilt whenever the settings change under it (tests do this constantly,
    and an admin changing a limit should take effect without a restart), by
    comparing the built limit/window to what the cached one was built from.
    """
    global _auth_limiter, _run_limiter
    limit, window = _settings_for(scope)
    existing = _run_limiter if scope == "run" else _auth_limiter
    if existing is None or existing.limit != limit or existing.window_seconds != window:
        fresh = RateLimiter(limit=limit, window_seconds=window)
        if scope == "run":
            _run_limiter = fresh
        else:
            _auth_limiter = fresh
        return fresh
    return existing


def reset_all() -> None:
    """Drop every bucket. Test-support only; never called in a request."""
    global _auth_limiter, _run_limiter
    _auth_limiter = None
    _run_limiter = None


def enforce(
    scope: Literal["signup", "login", "run"],
    *,
    ip: str | None,
    user_id: str | None = None,
) -> None:
    """Count this attempt against the scope's IP and (when known) user buckets.

    Both buckets are checked, and both are consumed on success: a client
    that rotates IPs is still bounded per account, and one that rotates
    accounts is still bounded per IP. Checking only one is the obvious gap;
    checking one and *recording* the other is worse than useless, because the
    second bucket would then be consulted against attempts it never saw.
    """
    limiter = limiter_for(scope)
    waits: list[int] = []
    if ip:
        ip_wait = limiter.check((scope, f"ip:{ip}"))
        if ip_wait is not None:
            waits.append(ip_wait)
    if user_id:
        user_wait = limiter.check((scope, f"user:{user_id}"))
        if user_wait is not None:
            waits.append(user_wait)
    # The longer of the two waits, so a client told "retry in N" is not let
    # back in before the bucket it is actually hitting has drained.
    retry = max(waits) if waits else None
    if retry is not None:
        raise RateLimited(scope, retry)