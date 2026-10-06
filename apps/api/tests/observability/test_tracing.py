"""Langfuse tracing (KI-21).

The claim under test is TRD §15's: "decision calls appear as spans with
their probabilities", and "the LangGraph callback traces every run with node
spans". Nothing here reaches a network — a fake client records what was
traced, and a second fake that raises on every call proves the failure
contract ("failures of tracing must never fail a run").
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from config import get_settings
from decisions.fallback import FallbackEngine, FallbackError
from decisions.jev import JevClient, JevError
from graph.timing import make_step_timer
from observability import tracing
from providers.llm import _request_kwargs, _trace_id
from quota.usage import reset_usage_context, set_usage_context
from schemas.decisions import Choice, Noul, Question
from tests.fakes.langfuse import FakeLangfuse


@pytest.fixture
def fake_langfuse(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLangfuse]:
    """Install a fake client as the process-wide one, keys enabled."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    get_settings.cache_clear()
    # `get_client` is `@cache`d, so the real function has to be captured
    # before it is replaced — monkeypatch restores the attribute, but this
    # fixture's teardown wants the cache cleared on the real one.
    real_get_client = tracing.get_client
    real_get_client.cache_clear()
    client = FakeLangfuse()
    monkeypatch.setattr(tracing, "get_client", lambda: client)
    yield client
    real_get_client.cache_clear()
    get_settings.cache_clear()


def _questions() -> dict[str, Question]:
    return {
        "guard_injection": Noul(prompt="injection?"),
        "intent": Choice(prompt="intent", options=["lookup", "chitchat"]),
    }


class _RunContext:
    """Just enough of a `UsageContext` for the run-scoped readers.

    `quota.usage.get_usage_context()` is a ContextVar, so a stand-in with a
    `run_id` is all `tracing.current_trace_id` reads. A real `UsageContext`
    would need a live session factory for `record_call`, which these tests
    are not about — the usage ledger has its own tests — so the three
    methods `decisions/jev.py` calls are here as no-ops that keep the id.
    """

    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id

    async def resolve_model(self, requested: str, role: str) -> str:
        return requested

    def api_key_for(self, model: str) -> str | None:
        return None

    async def record_call(
        self, *, model_id: str, role: str, tokens_in: int, tokens_out: int
    ) -> float:
        return 0.0


def _run_context(run_id: UUID) -> _RunContext:
    return _RunContext(run_id)


class TestLangfuseHost:
    def test_host_setting_reads_langfuse_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_HOST", "https://jp.cloud.langfuse.com")
        get_settings.cache_clear()
        assert get_settings().langfuse_host == "https://jp.cloud.langfuse.com"

    def test_langfuse_base_url_accepted_as_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `.env` has always carried LANGFUSE_BASE_URL; an existing deployment
        # must not need a rename to start sending traces (KI-21).
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
        monkeypatch.setenv("LANGFUSE_BASE_URL", "https://jp.cloud.langfuse.com")
        get_settings.cache_clear()
        assert get_settings().langfuse_host == "https://jp.cloud.langfuse.com"

    def test_host_exported_to_the_environment_the_sdk_reads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The SDK reads LANGFUSE_HOST and nothing else — this export is the
        # whole fix for "nothing arrives since 2026-09-20".
        monkeypatch.setenv("LANGFUSE_HOST", "https://jp.cloud.langfuse.com")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        get_settings.cache_clear()
        import os

        tracing.export_environment()
        assert os.environ["LANGFUSE_HOST"] == "https://jp.cloud.langfuse.com"
        assert os.environ["LANGFUSE_PUBLIC_KEY"] == "pk-lf-test"

    def test_client_is_built_with_the_configured_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        monkeypatch.setenv("LANGFUSE_HOST", "https://jp.cloud.langfuse.com")
        get_settings.cache_clear()
        tracing.get_client.cache_clear()
        seen: dict[str, Any] = {}

        class _Recording:
            def __init__(self, **kwargs: Any) -> None:
                seen.update(kwargs)

        import langfuse

        monkeypatch.setattr(langfuse, "Langfuse", _Recording)
        try:
            client = tracing.get_client()
            assert client is not None
            assert seen["host"] == "https://jp.cloud.langfuse.com"
            assert seen["public_key"] == "pk-lf-test"
        finally:
            tracing.get_client.cache_clear()

    def test_tracing_disabled_without_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
        get_settings.cache_clear()
        tracing.get_client.cache_clear()
        assert tracing.enabled() is False
        assert tracing.get_client() is None


class TestJevSpans:
    @pytest.mark.asyncio
    async def test_one_span_per_jev_call_with_names_and_probabilities(
        self, fake_langfuse: FakeLangfuse, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        get_settings.cache_clear()
        run_id = uuid4()
        token = set_usage_context(_run_context(run_id))  # type: ignore[arg-type]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "answers": {
                        "guard_injection": {"noul": 0.05},
                        "intent": {"probabilities": {"lookup": 0.8, "chitchat": 0.2}},
                    }
                },
            )

        try:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            answers = await JevClient(client=client).decide(
                state={"kind": "ingress", "run_id": str(run_id)}, questions=_questions()
            )
        finally:
            reset_usage_context(token)

        assert answers["guard_injection"].probability == pytest.approx(0.05)
        assert len(fake_langfuse.spans) == 1, fake_langfuse.names()
        span = fake_langfuse.spans[0]
        assert span.name == "decision.jev"
        assert span.metadata["engine"] == "jev"
        assert sorted(span.metadata["decision_names"]) == ["guard_injection", "intent"]
        assert span.metadata["probabilities"]["guard_injection"] == pytest.approx(0.05)
        assert span.metadata["latency_ms"] >= 0
        assert span.ended

    @pytest.mark.asyncio
    async def test_span_nests_under_the_runs_trace(
        self, fake_langfuse: FakeLangfuse, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The point of the whole item: the decision lands under the *same*
        # trace as the run's LLM generations, not in a trace of its own.
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        get_settings.cache_clear()
        run_id = uuid4()
        token = set_usage_context(_run_context(run_id))  # type: ignore[arg-type]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "answers": {
                        "guard_injection": {"noul": 0.1},
                        "intent": {"probabilities": {"lookup": 0.5, "chitchat": 0.5}},
                    }
                },
            )

        try:
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            await JevClient(client=client).decide(state={"kind": "ingress"}, questions=_questions())
            assert fake_langfuse.spans[0].trace_id == str(run_id)
            # And the trace id the LLM generations use is the same value, so
            # the decision nests under the run's generations rather than
            # sitting beside them in a trace of its own.
            assert _trace_id({"role": "generator"}) == str(run_id)
        finally:
            reset_usage_context(token)

    @pytest.mark.asyncio
    async def test_failed_jev_call_still_records_a_span(
        self, fake_langfuse: FakeLangfuse, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        get_settings.cache_clear()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(JevError):
            await JevClient(client=client).decide(state={"kind": "ingress"}, questions=_questions())

        assert len(fake_langfuse.spans) == 1
        assert fake_langfuse.spans[0].metadata["engine"] == "jev"
        assert "500" in fake_langfuse.spans[0].metadata["error"]

    @pytest.mark.asyncio
    async def test_fallback_call_records_a_span(
        self, fake_langfuse: FakeLangfuse
    ) -> None:
        async def fake_complete(*, litellm_model: str, messages: Any, metadata: Any) -> str:
            return (
                '{"guard_injection": {"probability": 0.2}, '
                '"intent": {"probabilities": {"lookup": 1.0, "chitchat": 0.0}}}'
            )

        engine = FallbackEngine(complete_fn=fake_complete)
        await engine.decide(state={"kind": "sanitize"}, questions=_questions())

        assert len(fake_langfuse.spans) == 1
        span = fake_langfuse.spans[0]
        assert span.name == "decision.fallback"
        assert span.metadata["engine"] == "fallback"
        assert span.metadata["stage"] == "sanitize"
        assert "guard_injection" in span.metadata["probabilities"]

    @pytest.mark.asyncio
    async def test_fallback_failure_records_a_span_and_still_raises(
        self, fake_langfuse: FakeLangfuse
    ) -> None:
        async def fake_complete(*, litellm_model: str, messages: Any, metadata: Any) -> str:
            return "not json at all"

        engine = FallbackEngine(complete_fn=fake_complete)
        with pytest.raises(FallbackError):
            await engine.decide(state={"kind": "sanitize"}, questions=_questions())

        assert len(fake_langfuse.spans) == 1
        assert fake_langfuse.spans[0].metadata["error"]


class TestTracingNeverFailsARun:
    @pytest.mark.asyncio
    async def test_jev_answers_succeed_when_the_client_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        get_settings.cache_clear()
        monkeypatch.setattr(tracing, "get_client", lambda: FakeLangfuse(raises=True))
        try:

            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200,
                    json={
                        "answers": {
                            "guard_injection": {"noul": 0.1},
                            "intent": {"probabilities": {"lookup": 1.0, "chitchat": 0.0}},
                        }
                    },
                )

            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            answers = await JevClient(client=client).decide(
                state={"kind": "ingress"}, questions=_questions()
            )
            assert answers["guard_injection"].probability == pytest.approx(0.1)
        finally:
            get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_step_returns_its_value_when_the_client_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tracing, "get_client", lambda: FakeLangfuse(raises=True))

        async def work() -> str:
            return "answer"

        step = make_step_timer(node="fast", run_id=uuid4(), latency_ms={}, publish=None)
        assert await step("retrieve", work) == "answer"

    @pytest.mark.asyncio
    async def test_failed_step_still_propagates_and_is_marked(
        self, fake_langfuse: FakeLangfuse
    ) -> None:
        async def work() -> str:
            raise RuntimeError("retrieval blew up")

        step = make_step_timer(node="fast", run_id=uuid4(), latency_ms={}, publish=None)
        with pytest.raises(RuntimeError):
            await step("retrieve", work)

        assert len(fake_langfuse.spans) == 1
        assert fake_langfuse.spans[0].level == "ERROR"
        assert "retrieval blew up" in (fake_langfuse.spans[0].status_message or "")
        assert fake_langfuse.spans[0].ended


class TestStageSpans:
    @pytest.mark.asyncio
    async def test_one_span_per_stage_under_the_run_trace(
        self, fake_langfuse: FakeLangfuse
    ) -> None:
        run_id = uuid4()

        async def work() -> str:
            return "ok"

        latency: dict[str, int] = {}
        step = make_step_timer(node="fast", run_id=run_id, latency_ms=latency, publish=None)
        await step("rewrite", work)
        await step("retrieve", work)

        assert fake_langfuse.names() == ["fast.rewrite", "fast.retrieve"]
        assert {span.trace_id for span in fake_langfuse.spans} == {str(run_id)}
        assert all(span.ended for span in fake_langfuse.spans)
        assert all("duration_ms" in span.metadata for span in fake_langfuse.spans)
        assert set(latency) == {"rewrite", "retrieve"}

    @pytest.mark.asyncio
    async def test_no_span_when_tracing_is_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tracing, "get_client", lambda: None)

        async def work() -> str:
            return "ok"

        step = make_step_timer(node="fast", run_id=uuid4(), latency_ms={}, publish=None)
        assert await step("retrieve", work) == "ok"


class TestEmptyTraceIds:
    """KI-21's second half: `Langfuse trace_id mismatch: set ,` (1374 times)."""

    def test_no_trace_id_is_invented_without_a_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Outside a run (a seeding script, an eval) there is no run id, and
        # "" is worse than absent: every such call claimed the same empty
        # trace, which is what produced the warning. None lets LiteLLM name
        # the trace after the call.
        monkeypatch.setattr(tracing, "current_trace_id", lambda: None)
        assert _trace_id({"role": "planner"}) is None
        assert _trace_id({"role": "rewriter"}) is None

    def test_job_label_is_not_used_as_a_trace_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The actual bug: `trace_id` was `metadata.get("job", ...)`, so
        # `job="decision_fallback"` made every fallback generation its own
        # trace named after the job.
        monkeypatch.setattr(tracing, "current_trace_id", lambda: "run-1")
        assert _trace_id({"job": "decision_fallback", "role": "decision_fallback"}) == "run-1"

    def test_explicit_run_id_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tracing, "current_trace_id", lambda: "from-context")
        assert _trace_id({"run_id": "explicit"}) == "explicit"

    def test_request_metadata_carries_the_trace_id_and_keeps_the_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tracing, "current_trace_id", lambda: "run-7")
        kwargs = _request_kwargs("openrouter/x", {"job": "claim_extraction", "role": "x"})
        metadata = kwargs["metadata"]
        assert metadata["trace_id"] == "run-7"
        assert metadata["job"] == "claim_extraction"

    def test_trace_id_key_absent_outside_a_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tracing, "current_trace_id", lambda: None)
        kwargs = _request_kwargs("openrouter/x", {"role": "planner"})
        assert "trace_id" not in kwargs["metadata"]


class TestScores:
    def test_score_push_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tracing, "get_client", lambda: FakeLangfuse(raises=True))
        tracing.score("run-1", {"faithfulness": 0.9})  # must not raise

    def test_scores_go_to_the_configured_client(self, fake_langfuse: FakeLangfuse) -> None:
        tracing.score("run-1", {"faithfulness": 0.9})
        assert fake_langfuse.scores == [
            {"trace_id": "run-1", "name": "faithfulness", "value": 0.9}
        ]