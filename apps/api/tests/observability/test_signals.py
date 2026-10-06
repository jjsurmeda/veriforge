"""Structured signal events (item 2).

Two things are asserted here, and the second is the one that matters: that
each event is *emitted*, and that it is emitted **exactly once at its
trigger**. A signal that fires twice is indistinguishable from one that
fires once until someone builds an alarm on the count, and a signal that
fires on every success is worse than no signal at all.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import pytest

from decisions.breaker import CircuitBreaker
from observability import signals


def emitted(capsys: pytest.CaptureFixture[str], **kwargs: Any) -> list[dict[str, Any]]:
    """Emit one signal and return the JSON lines it wrote to stdout."""
    capsys.readouterr()  # discard anything from setup
    signals.emit(kwargs.pop("event", signals.RUN_FAILED), **kwargs)
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]


def read(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]


def _breaker(**kwargs: Any) -> CircuitBreaker:
    defaults: dict[str, Any] = {
        "failure_threshold": 3,
        "window_seconds": 60,
        "cooldown_seconds": 60,
    }
    return CircuitBreaker(**{**defaults, **kwargs})


class TestLineFormat:
    def test_every_line_is_one_json_object_with_the_contract_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = emitted(
            capsys,
            run_id=uuid4(),
            user_id=uuid4(),
            error_code="boom",
            event=signals.RUN_FAILED,
        )
        assert len(payload) == 1, "one signal must be one line"
        assert set(payload[0]) >= {"ts", "level", "event"}
        assert payload[0]["event"] == signals.RUN_FAILED
        assert payload[0]["level"] == "ERROR"
        assert payload[0]["error_code"] == "boom"

    def test_ids_are_strings_not_uuids(self, capsys: pytest.CaptureFixture[str]) -> None:
        # A UUID is not JSON serialisable, so the conversion happens in
        # `emit`. If it moved to a call site, this is the test that fails.
        rid, uid = uuid4(), uuid4()
        payload = emitted(capsys, run_id=rid, user_id=uid)
        assert payload[0]["run_id"] == str(rid)
        assert payload[0]["user_id"] == str(uid)

    def test_optional_fields_are_absent_when_unknown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = emitted(capsys, run_id=uuid4(), event=signals.WORKER_STALLED)
        assert "user_id" not in payload[0]
        assert "error_code" not in payload[0]

    def test_extra_context_is_kept(self, capsys: pytest.CaptureFixture[str]) -> None:
        payload = emitted(
            capsys, event=signals.INGEST_FAILED, document_id="d-1", error="bad pdf"
        )
        assert payload[0]["document_id"] == "d-1"
        assert payload[0]["error"] == "bad pdf"

    def test_ts_is_iso_utc(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert emitted(capsys)[0]["ts"].endswith("+00:00")

    def test_every_documented_event_name_is_known(self) -> None:
        # A typo in an event name would log happily and build a metric filter
        # that matches nothing, so the contract is asserted, not trusted.
        assert {
            "run.failed",
            "breaker.opened",
            "breaker.closed",
            "quota.denied",
            "provider.credit_low",
            "worker.stalled",
            "ingest.failed",
        } == signals.EVENTS

    def test_emit_never_raises_on_an_unserialisable_extra(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `default=str` in json.dumps: a signal must never be the reason a
        # run fails, so an unserialisable extra degrades to its repr.
        payload = emitted(capsys, event=signals.INGEST_FAILED, weird=object())
        assert payload[0]["weird"].startswith("<object")


class TestBreakerSignals:
    def test_breaker_opened_emitted_once_at_the_threshold(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        breaker = _breaker()
        breaker.record_failure()
        breaker.record_failure()
        assert read(capsys) == [], "two failures must not open the breaker"
        breaker.record_failure()
        payload = read(capsys)
        assert [p["event"] for p in payload] == [signals.BREAKER_OPENED]
        assert payload[0]["state"] == "open"
        assert payload[0]["reason"] == "threshold_reached"

    def test_further_failures_while_open_do_not_re_emit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure()
        for _ in range(5):
            breaker.record_failure()
        assert len(read(capsys)) == 1

    def test_breaker_closed_emitted_only_on_recovery(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        breaker = _breaker()
        breaker.record_success()  # already closed: not a transition
        assert read(capsys) == []
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        read(capsys)
        breaker.record_success()
        payload = read(capsys)
        assert [p["event"] for p in payload] == [signals.BREAKER_CLOSED]
        assert payload[0]["state"] == "closed"

    def test_probe_failure_reopens_and_emits_again(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        breaker = _breaker(failure_threshold=1, cooldown_seconds=0.01)
        breaker.record_failure()
        time.sleep(0.02)
        assert breaker.allow_jev()  # -> PROBING
        read(capsys)
        breaker.record_failure()  # probe failed
        payload = read(capsys)
        assert [p["event"] for p in payload] == [signals.BREAKER_OPENED]
        assert payload[0]["reason"] == "probe_failed"

    def test_probe_success_closes_and_emits_closed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        breaker = _breaker(failure_threshold=1, cooldown_seconds=0.01)
        breaker.record_failure()
        time.sleep(0.02)
        assert breaker.allow_jev()
        read(capsys)
        breaker.record_success()
        assert [p["event"] for p in read(capsys)] == [signals.BREAKER_CLOSED]


class TestQuotaSignal:
    @pytest.mark.asyncio
    async def test_quota_denied_emitted_once_with_the_window(
        self, capsys: pytest.CaptureFixture[str], quota_denied_case: Any
    ) -> None:
        from quota.service import QuotaExceeded, gate_and_reserve

        user_id, run_id, session = quota_denied_case
        capsys.readouterr()
        with pytest.raises(QuotaExceeded):
            await gate_and_reserve(session, user_id=user_id, run_id=run_id, mode="auto")
        payload = read(capsys)
        assert [p["event"] for p in payload] == [signals.QUOTA_DENIED]
        assert payload[0]["error_code"] == "quota_exceeded"
        assert payload[0]["user_id"] == str(user_id)
        assert payload[0]["run_id"] == str(run_id)
        # `both` is a real value: `_blocked_detail` names it when the 5h and
        # the monthly window are both exhausted and the sooner reset wins.
        # My first version of this assertion assumed {"5h", "month"} and
        # failed, which is how the case got noticed.
        assert payload[0]["window"] in {"5h", "month", "both"}
        assert payload[0]["reset_at"]

    @pytest.mark.asyncio
    async def test_an_allowed_reservation_emits_nothing(
        self, capsys: pytest.CaptureFixture[str], quota_allowed_case: Any
    ) -> None:
        from quota.service import gate_and_reserve

        user_id, run_id, session = quota_allowed_case
        capsys.readouterr()
        await gate_and_reserve(session, user_id=user_id, run_id=run_id, mode="auto")
        assert read(capsys) == []


class TestIngestSignal:
    @pytest.mark.asyncio
    async def test_ingest_failed_emitted_with_the_document_id(
        self, capsys: pytest.CaptureFixture[str], failed_document: Any
    ) -> None:
        from ingest.pipeline import _mark_failed

        capsys.readouterr()
        await _mark_failed(failed_document, "pdf parse blew up")
        payload = read(capsys)
        assert [p["event"] for p in payload] == [signals.INGEST_FAILED]
        assert payload[0]["document_id"] == str(failed_document)
        assert payload[0]["error"] == "pdf parse blew up"

    @pytest.mark.asyncio
    async def test_unknown_document_emits_no_signal(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ingest.pipeline import _mark_failed

        capsys.readouterr()
        await _mark_failed(uuid4(), "never existed")
        assert read(capsys) == [], "a document that is not there cannot have failed"


class TestHealthz:
    @pytest.mark.asyncio
    async def test_old_shape_still_present_and_values_unchanged(self, breaker_closed: Any) -> None:
        body = await healthz_body()
        assert {key: body[key] for key in ("status", "db")} == {"status": "ok", "db": "ok"}

    @pytest.mark.asyncio
    async def test_new_fields_present(self, breaker_closed: Any) -> None:
        body = await healthz_body()
        assert set(body) >= {"status", "db", "breaker", "jev", "worker_heartbeat_age_s"}
        assert body["breaker"] == "closed"
        assert body["jev"] == "ok"

    @pytest.mark.asyncio
    async def test_jev_degraded_when_breaker_open(self, breaker_open: Any) -> None:
        body = await healthz_body()
        assert body["breaker"] == "open"
        # Degraded, not failed: a run still answers on the fallback, so this
        # must not become a 503 or the whole API leaves service for something
        # the pipeline absorbs by design.
        assert body["jev"] == "degraded"
        assert body["status"] == "ok"

    @pytest.mark.asyncio
    async def test_heartbeat_age_is_none_or_a_number(self, breaker_closed: Any) -> None:
        value = (await healthz_body())["worker_heartbeat_age_s"]
        assert value is None or isinstance(value, (int, float))

    @pytest.mark.asyncio
    async def test_a_body_without_the_new_fields_would_still_pass_the_old_check(
        self, breaker_closed: Any
    ) -> None:
        # The old check keyed on `{"status": "ok", "db": "ok"}`. Both keys
        # keep their values whatever else the body grows — this is that
        # assertion, kept as a statement about the contract.
        body = await healthz_body()
        assert body["status"] == "ok" and body["db"] == "ok"

    @pytest.mark.asyncio
    async def test_heartbeat_age_is_a_real_number_against_a_real_session(
        self, breaker_closed: Any, running_run_with_heartbeat: Any, db: Any
    ) -> None:
        """The mocked test cannot see a number, so this one uses the database.

        `worker_heartbeat_age_s` is the field an alarm reads, and a Mock
        makes every branch return None — which would pass a test that the
        production path never takes.
        """
        value = (await healthz_body(session=db))["worker_heartbeat_age_s"]
        assert value is not None
        assert 80 <= float(value) <= 120, f"a 90-second-old heartbeat read as {value}"

    @pytest.mark.asyncio
    async def test_heartbeat_age_is_none_when_no_run_has_heartbeated(
        self, breaker_closed: Any, db: Any
    ) -> None:
        from sqlalchemy import update

        from db.models import Run

        await db.execute(update(Run).values(heartbeat_at=None))
        await db.commit()
        # None, not 0: a heartbeat age of 0 reads as "healthy right now",
        # which is the opposite of the outage this field exists to show.
        assert (await healthz_body(session=db))["worker_heartbeat_age_s"] is None


async def healthz_body(session: Any = None) -> dict[str, Any]:
    """GET /healthz as a body dict.

    With no `session`, the dependency is mocked — enough for the shape of
    the body. With a real session, the fields that read the database
    (`worker_heartbeat_age_s`) actually return values.

    No lifespan: `TestClient(app)` as a context manager starts the RunBus,
    the ingest queue and the sweeper, none of which these tests are about.
    `ASGITransport` calls the app the way a request does and starts nothing.
    """
    from unittest.mock import AsyncMock

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.session import get_session
    from main import app

    async def _override() -> Any:
        yield AsyncMock(spec=AsyncSession) if session is None else session

    app.dependency_overrides[get_session] = _override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/healthz")
            return dict(response.json())
    finally:
        app.dependency_overrides.clear()