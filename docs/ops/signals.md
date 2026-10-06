# Operational signals

The structured events the api and the workers emit, for CloudWatch Logs
Insights metric filters and alarms (TRD §15).

**The contract. Do not rename a field or an event name.** A filter written
against `{ $.event = "run.failed" }` keeps matching only while both the name
and the fields stay as below. Adding an event or an extra field is safe;
renaming is a coordinated change with every alarm built on it.

## The line format

One JSON object per line, nothing else on the line. That is what CloudWatch
Logs Insights parses without a schema.

| field | always | meaning |
| --- | --- | --- |
| `ts` | yes | ISO 8601, UTC, e.g. `2026-10-06T03:14:07.881234+00:00` |
| `level` | yes | `ERROR` or `INFO` (mirrors the log level of the trigger) |
| `event` | yes | one of the names in the table below |
| `run_id` | when known | the run, as a string |
| `user_id` | when known | the user, as a string |
| `error_code` | when known | the machine-readable reason |

Anything else a caller knows (breaker state, document id, quota window) is
added as an extra top-level field. Extra fields do not break a filter that
does not mention them.

Emitted by `apps/api/observability/signals.py`. `emit()` never raises: a
signal that cannot be written is logged and dropped, because a broken signal
must not be the reason a run fails.

## The events

| event | level | emitted when | where |
| --- | --- | --- | --- |
| `run.failed` | ERROR | a run ends failed; `error_code` carries the reason | `graph/runner.py` (all three terminal paths) |
| `breaker.opened` | ERROR | the Jev circuit breaker changes state to open | `decisions/breaker.py` |
| `breaker.closed` | INFO | the breaker recovers (a successful probe) | `decisions/breaker.py` |
| `quota.denied` | WARNING | a run is refused for quota | `quota/service.py` |
| `provider.credit_low` | ERROR | the provider returns 402 or a quota error | `graph/runner.py` |
| `worker.stalled` | ERROR | the sweeper fails a run for heartbeat timeout | `graph/runner.py` |
| `ingest.failed` | ERROR | a document ingestion fails | `ingest/pipeline.py` |

### Exactly-once, and why it matters

Each event fires **once per occurrence**. Two of these needed a gate to get
there, and both are worth knowing about before someone "simplifies" the
condition away:

- `breaker.opened` is gated on the *state transition*, not on "the failure
  threshold is met". The threshold stays met while the breaker is open, so
  gating on that re-emitted once per further failure — an alarm counting
  occurrences reported one outage as N. A probe failure re-opening is a
  genuine new opening and does emit again, with
  `reason: "probe_failed"`.
- `breaker.closed` is emitted only on recovery, never on an ordinary
  successful decision. The closed state is the normal state; a line per
  successful decision would bury the event entirely.

### One example line each

```json
{"ts":"2026-10-06T03:14:07.881234+00:00","level":"ERROR","event":"run.failed","run_id":"01a10d98-23cb-72dd-aba2-02af265072cc","user_id":"5f0c...","error_code":"provider_unavailable"}
{"ts":"2026-10-06T03:14:12.104901+00:00","level":"ERROR","event":"breaker.opened","state":"open","reason":"threshold_reached","failures":3,"window_seconds":60.0}
{"ts":"2026-10-06T03:15:44.771230+00:00","level":"INFO","event":"breaker.closed","state":"closed","cooldown_seconds":60.0}
{"ts":"2026-10-06T03:16:02.559310+00:00","level":"WARNING","event":"quota.denied","run_id":"01a10d99-2a26-75a4-a6d3-c3d3f674a332","user_id":"5f0c...","error_code":"quota_exceeded","window":"5h","reset_at":"2026-10-06T05:41:00+00:00"}
{"ts":"2026-10-06T03:17:20.331245+00:00","level":"ERROR","event":"provider.credit_low","run_id":"01a10d99-2a26-75a4-a6d3-c3d3f674a332","user_id":"5f0c...","error_code":"quota_exceeded"}
{"ts":"2026-10-06T03:18:40.902114+00:00","level":"ERROR","event":"worker.stalled","run_id":"01a10d9a-1c33-7b40-9d21-0f2b8a7c5511","error_code":"heartbeat_timeout","sweep_seconds":60.0}
{"ts":"2026-10-06T03:19:05.447781+00:00","level":"ERROR","event":"ingest.failed","document_id":"9c1d0e2a-6f3b-4a51-8d77-2b6e4f0c19aa","error":"pdf parse blew up"}
```

(`user_id` is elided above; the real line carries the full string.)

## `GET /healthz`

```json
{
  "status": "ok",
  "db": "ok",
  "breaker": "closed",
  "jev": "ok",
  "worker_heartbeat_age_s": 12.4
}
```

- `breaker` — `closed`, `open` or `probing`.
- `jev` — `ok` when the breaker is closed, `degraded` otherwise.
- `worker_heartbeat_age_s` — seconds since the newest run heartbeat, or
  **`null`** when there is none.

Backward compatible: `status` and `db` keep their exact values, and the
503-on-unreachable-database behaviour is unchanged. The new fields are
additive.

Two deliberate choices:

- **It never 503s for degradation.** A run still answers while the breaker
  is open — the fallback engine exists for exactly that — so reporting 503
  would take the whole API out of service for something the pipeline is
  designed to absorb. The fields are there to be read by an alarm.
- **`worker_heartbeat_age_s` is `null`, not `0`, for "no heartbeat".** A 0
  reads as "a heartbeat just arrived", which is the healthy case, so an
  alarm keyed on the age would never fire in the worst outage: every run
  dead and no heartbeat at all.

Suggested alarm inputs:

| alarm | filter |
| --- | --- |
| Jev degraded | `breaker = "open"` on `/healthz`, or `event = "breaker.opened"` |
| Provider out of credit | `event = "provider.credit_low"` |
| Users hitting quota | `count(event = "quota.denied") > 0` grouped by `user_id` |
| Worker stalls | `event = "worker.stalled"` |
| Run failures | `event = "run.failed"` grouped by `error_code` |
| Ingestion failures | `event = "ingest.failed"` grouped by `document_id` |