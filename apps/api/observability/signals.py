"""Structured signal events (TRD §15, lane C).

**The contract lane A's CloudWatch metric filters are built from. Do not
rename the fields or the event names** — a filter matching on
`{ $.event = "run.failed" }` keeps working only while both stay put. The
full list, with an example line each, is `docs/ops/signals.md`.

Every line is one JSON object with `ts`, `level`, `event`, and — when they
are known — `run_id`, `user_id`, `error_code`. One object per line, on its
own line, because that is what CloudWatch Logs Insights can parse without
a schema; `json.dumps` with `separators` set produces exactly that and
nothing else (no trailing prose, no embedded newline).

`emit` never raises and never blocks. A signal that fails to write must not
be the reason a run fails, so every exception here is swallowed after a log
line of its own — the same rule `observability/tracing.py` follows.
"""

from __future__ import annotations

import json
import logging
import socket
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("veriforge.signals")

#: Emitted when a run ends failed. `error_code` carries the reason.
RUN_FAILED = "run.failed"
#: Emitted when the Jev circuit breaker changes state, either way.
BREAKER_OPENED = "breaker.opened"
BREAKER_CLOSED = "breaker.closed"
#: Emitted when a run is refused for quota.
QUOTA_DENIED = "quota.denied"
#: Emitted when the provider answers 402 or a quota error.
PROVIDER_CREDIT_LOW = "provider.credit_low"
#: Emitted when the sweeper fails a run for heartbeat timeout.
WORKER_STALLED = "worker.stalled"
#: Emitted when a document ingestion fails.
INGEST_FAILED = "ingest.failed"

#: Every event this module can emit. A typo in an event name would compile,
#: log happily and build a metric filter that matches nothing, so the set is
#: asserted in the tests rather than trusted.
EVENTS: frozenset[str] = frozenset(
    {
        RUN_FAILED,
        BREAKER_OPENED,
        BREAKER_CLOSED,
        QUOTA_DENIED,
        PROVIDER_CREDIT_LOW,
        WORKER_STALLED,
        INGEST_FAILED,
    }
)


def emit(
    event: str,
    *,
    level: str = "ERROR",
    run_id: object | None = None,
    user_id: object | None = None,
    error_code: str | None = None,
    **extra: Any,
) -> None:
    """Write one signal line.

    `run_id` and `user_id` are typed `object` because every caller holds a
    `UUID` and the field must serialise as a string — a UUID is not JSON
    serialisable, so they are converted here rather than at 8 call sites,
    each of which would get it wrong eventually.

    Any extra keyword lands in the line as-is. That is deliberate: the
    contract fixes the four named fields, and a caller's own context
    (breaker state, document id, window) is worth having without a new
    event name and a new filter to match on.
    """
    payload: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "level": level,
        "event": event,
    }
    if run_id is not None:
        payload["run_id"] = str(run_id)
    if user_id is not None:
        payload["user_id"] = str(user_id)
    if error_code is not None:
        payload["error_code"] = error_code
    payload.update({key: value for key, value in extra.items() if value is not None})
    try:
        # separators: no spaces, so the line is one compact object; and
        # `message`/`asctime` suppressed so basicConfig's formatter cannot
        # wrap the JSON in prose that Logs Insights would then have to strip.
        print(json.dumps(payload, separators=(",", ":"), default=str), flush=True)
    except Exception:
        logger.warning("signal %s could not be written", event, exc_info=True)


def host() -> str:
    """The hostname, for a line that must be attributable to one container.

    Not part of the contract — it is extra context, and the fields lane A
    filters on are unaffected by it.
    """
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"