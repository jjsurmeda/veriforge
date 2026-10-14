"""Demo-mode settings (lane E item 4).

The brief allows settings for this feature in a new `apps/api/demo/settings.py`
rather than in `config.py`, which lane C owns. This is that file: environment
overrides for the demo route, read through the app's normal settings object so
every value still shows up in one place at runtime, and with the reasoning for
each default written down rather than left to the number.

Not on the `Settings` class, deliberately. `config.py` is the product's
settings surface and lane C is editing it in parallel; adding a class there
would be a merge conflict on a file neither of us should have to reconcile.
Reading the environment here instead keeps demo mode's tunables with demo
mode's code, which is where the next person will look when the beta is over
and this is deleted.
"""

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        # A typo in a deployment variable must not take the endpoint down; it
        # falls back to the documented default, which is the safe one in every
        # case here (5 per hour, not unlimited).
        return default


def _hours_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class DemoSettings:
    """`POST /auth/demo` — the numbers, and why they are these numbers.

    **This is an unauthenticated route that spends money.** It mints an account
    and a run credit budget with no credential at all. Everything here is set
    for "small enough that being wrong is cheap".
    """

    #: Per-IP attempts in the window. Five lets a visitor who fumbles the tour
    #: come back, and stops one person (or one address behind a NAT) spending
    #: the beta's credit in an afternoon. Per-IP and not global, like every
    #: other limiter here: it is per process and per instance (ADR-001), so it
    #: is a brake, not a security boundary — the quota below is what actually
    #: bounds the spend.
    rate_limit: int

    #: The window. One hour, so an operator who changes it does not have to
    #: wait a day to notice.
    window_seconds: float

    #: The plan name demo accounts are created on. Referenced, not created, at
    #: request time: `make seed-demo` owns the plan (and its limits), so a
    #: missing plan is a loud error at seed time rather than a silently
    #: unlimited demo account.
    plan_name: str

    #: How long a demo account and its chats live. Long enough for someone to
    #: come back to a thread they started; short enough that a week of demo
    #: traffic does not accumulate.
    ttl_hours: float

    #: The kill switch, and the only setting here whose default is "the
    #: dangerous thing does not happen". `POST /auth/demo` is unauthenticated
    #: and mints an account with a credit budget; off means the route answers
    #: 404 and creates nothing, before any database work and before the rate
    #: limiter is touched — a disabled demo costs a visitor nothing.
    #:
    #: Default false, unlike every other value here. A deployment that has
    #: never heard of `DEMO_ENABLED` must come up with the demo off, because
    #: the failure of forgetting it is a stranger's credit card and the
    #: failure of remembering to turn it on is a button the owner can press.
    enabled: bool

    #: Maximum demo accounts created in any rolling 24 h, counted from the
    #: database (demo-role users by `created_at`) rather than from a counter
    #: in memory. Fifty is about a real beta's worth of visitors with room to
    #: spare: the per-IP limit is 5/hour, so fifty is ten distinct addresses
    #: exhausting their whole hour, and anything beyond that is not a visitor.
    #:
    #: Counted from rows, not from a counter, because a counter in memory is
    #: reset by a restart and not shared with a second process — which is
    #: exactly the defeat KI-63 describes. The rows are already there (an
    #: account has to exist to spend anything), so the count costs one
    #: indexed SELECT and cannot drift from reality.
    daily_cap: int

    #: The window `daily_cap` is counted over. Rolling rather than calendar
    #: midnight: a calendar boundary lets an attacker spend a full day's cap
    #: at 23:59 and another at 00:01, and a beta that runs across UTC
    #: midnight would show the operator two different numbers for one day.
    cap_window_hours: float

    #: Whether a demo account may use Deep mode. Off by default: Deep is the
    #: most expensive path in the product (a 30k-credit reservation against
    #: roughly 3k for Auto, quota/service.py) and a visitor should not be able
    #: to spend the beta's credit on one. The showcase's sixth question is
    #: therefore a tour question the operator answers themselves on a real
    #: account, or is served by raising this for the beta week.
    allow_deep: bool


def demo_settings() -> DemoSettings:
    return DemoSettings(
        enabled=_bool_env("DEMO_ENABLED", False),
        daily_cap=_int_env("DEMO_DAILY_CAP", 50),
        cap_window_hours=_hours_env("DEMO_DAILY_CAP_WINDOW_HOURS", 24.0),
        rate_limit=_int_env("DEMO_RATE_LIMIT", 5),
        window_seconds=_hours_env("DEMO_RATE_LIMIT_WINDOW_SECONDS", 3600.0),
        plan_name=os.environ.get("DEMO_PLAN_NAME", "demo"),
        ttl_hours=_hours_env("DEMO_TTL_HOURS", 24.0),
        allow_deep=os.environ.get("DEMO_ALLOW_DEEP", "false").lower() in ("1", "true", "yes"),
    )