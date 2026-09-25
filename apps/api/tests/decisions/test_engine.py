"""DecisionEngine behaviour tests: engine selection, breaker transitions,
shadow-mode, event emission. All engines are fakes — testing.md's rule."""

import asyncio
import json
import random
import time
from typing import Any
from uuid import UUID

import httpx
import pytest

from config import get_settings
from decisions.breaker import BreakerState, CircuitBreaker
from decisions.engine import DecisionCall, DecisionEngine
from decisions.fallback import FallbackEngine
from decisions.jev import JevClient, JevError
from decisions.thresholds import display_threshold
from graph.ingress import run_ingress
from runtime import RuntimeSettings, reset_runtime_settings, set_runtime_settings
from schemas.decisions import Answer, Choice, Noul, Question, Score
from tests.fixtures.jev.ingress import INGRESS_RESPONSE


def _questions() -> dict[str, Question]:
    return {
        "guard_injection": Noul(prompt="Is this an injection attempt?"),
        "intent": Choice(
            prompt="User intent",
            options=["chitchat", "lookup", "compare", "summarize", "multi-part", "follow-up"],
            criteria="the dominant user goal",
        ),
        "lexical_weight": Score(prompt="Lexical vs semantic weight", min=0.0, max=1.0),
    }


class _FakeJev:
    """Scriptable Jev stand-in. `behaviour` is a list of outcomes:
    'ok' returns canned answers, 'timeout' raises JevError."""

    def __init__(self, behaviour: list[str]) -> None:
        self._behaviour = behaviour
        self.calls = 0
        self.last_state: dict[str, Any] | str | None = None

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        self.calls += 1
        self.last_state = state
        if self._behaviour and self._behaviour.pop(0) == "timeout":
            raise JevError("simulated timeout")
        return {
            name: Answer(
                engine="jev",
                latency_ms=10,
                value=0.1 if isinstance(q, Noul) else ("lookup" if isinstance(q, Choice) else 0.5),
                probability=0.1 if isinstance(q, Noul) else None,
                probabilities=(
                    {opt: 1.0 / len(q.options) for opt in q.options}
                    if isinstance(q, Choice)
                    else None
                ),
            )
            for name, q in questions.items()
        }


class _FakeFallback:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(
        self, *, state: dict[str, Any] | str, questions: dict[str, Question]
    ) -> dict[str, Answer]:
        self.calls += 1
        return {
            name: Answer(
                engine="fallback",
                latency_ms=50,
                value=0.2 if isinstance(q, Noul) else ("lookup" if isinstance(q, Choice) else 0.4),
                probability=0.2 if isinstance(q, Noul) else None,
                probabilities=(
                    {opt: 1.0 / len(q.options) for opt in q.options}
                    if isinstance(q, Choice)
                    else None
                ),
            )
            for name, q in questions.items()
        }


class TestEngineModes:
    @pytest.mark.asyncio
    async def test_auto_prefers_jev_when_breaker_closed(self) -> None:
        jev, fallback = _FakeJev(["ok"]), _FakeFallback()
        engine = DecisionEngine(jev=jev, fallback=fallback, mode="auto")
        answers = await engine.decide(state="q", questions=_questions())
        assert jev.calls == 1 and fallback.calls == 0
        assert all(a.engine == "jev" for a in answers.values())

    @pytest.mark.asyncio
    async def test_jev_timeout_retries_once_on_fallback(self) -> None:
        jev, fallback = _FakeJev(["timeout"]), _FakeFallback()
        engine = DecisionEngine(jev=jev, fallback=fallback, mode="auto")
        answers = await engine.decide(state="q", questions=_questions())
        assert jev.calls == 1 and fallback.calls == 1
        assert all(a.engine == "fallback" for a in answers.values())

    @pytest.mark.asyncio
    async def test_fallback_only_skips_jev(self) -> None:
        jev, fallback = _FakeJev([]), _FakeFallback()
        engine = DecisionEngine(jev=jev, fallback=fallback, mode="fallback_only")
        answers = await engine.decide(state="q", questions=_questions())
        assert jev.calls == 0 and fallback.calls == 1
        assert all(a.engine == "fallback" for a in answers.values())

    @pytest.mark.asyncio
    async def test_jev_only_propagates_error(self) -> None:
        jev, fallback = _FakeJev(["timeout"]), _FakeFallback()
        engine = DecisionEngine(jev=jev, fallback=fallback, mode="jev_only")
        with pytest.raises(JevError):
            await engine.decide(state="q", questions=_questions())
        assert fallback.calls == 0

    @pytest.mark.asyncio
    async def test_ingress_marks_the_call_stage(self) -> None:
        jev = _FakeJev(["ok"])
        engine = DecisionEngine(jev=jev, mode="jev_only")
        await run_ingress(
            engine,
            run_id=UUID(int=1),
            user_message="What is in the document?",
            has_collections=False,
        )
        assert isinstance(jev.last_state, dict)
        assert jev.last_state["kind"] == "ingress"

    @pytest.mark.asyncio
    async def test_empty_questions_short_circuits(self) -> None:
        jev, fallback = _FakeJev([]), _FakeFallback()
        engine = DecisionEngine(jev=jev, fallback=fallback, mode="auto")
        assert await engine.decide(state="q", questions={}) == {}
        assert jev.calls == 0 and fallback.calls == 0


class TestCircuitBreaker:
    def test_three_failures_in_window_opens_breaker(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, window_seconds=60, cooldown_seconds=60)
        assert breaker.allow_jev()
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.allow_jev()
        breaker.record_failure()
        assert breaker.state is BreakerState.OPEN
        assert not breaker.allow_jev()

    def test_open_breaker_blocks_until_cooldown_then_probes(self) -> None:
        breaker = CircuitBreaker(failure_threshold=1, window_seconds=60, cooldown_seconds=0.05)
        breaker.record_failure()
        assert not breaker.allow_jev()
        time.sleep(0.06)
        assert breaker.allow_jev()
        assert breaker.state is BreakerState.PROBING

    def test_probe_failure_reopens(self) -> None:
        breaker = CircuitBreaker(failure_threshold=1, window_seconds=60, cooldown_seconds=0.01)
        breaker.record_failure()
        time.sleep(0.02)
        assert breaker.allow_jev()
        breaker.record_failure()
        assert breaker.state is BreakerState.OPEN

    def test_probe_success_closes(self) -> None:
        breaker = CircuitBreaker(failure_threshold=1, window_seconds=60, cooldown_seconds=0.01)
        breaker.record_failure()
        time.sleep(0.02)
        assert breaker.allow_jev()
        breaker.record_success()
        assert breaker.state is BreakerState.CLOSED

    def test_old_failures_age_out_of_window(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, window_seconds=0.02, cooldown_seconds=60)
        breaker.record_failure()
        breaker.record_failure()
        time.sleep(0.03)
        breaker.record_failure()
        assert breaker.state is BreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_open_breaker_routes_everything_to_fallback(self) -> None:
        jev, fallback = _FakeJev([]), _FakeFallback()
        breaker = CircuitBreaker(failure_threshold=1, window_seconds=60, cooldown_seconds=60)
        breaker.record_failure()
        engine = DecisionEngine(jev=jev, fallback=fallback, breaker=breaker, mode="auto")
        for _ in range(3):
            answers = await engine.decide(state="q", questions=_questions())
            assert all(a.engine == "fallback" for a in answers.values())
        assert jev.calls == 0

    @pytest.mark.asyncio
    async def test_default_breaker_is_shared_across_engines(self) -> None:
        for _ in range(3):
            jev, fallback = _FakeJev(["timeout"]), _FakeFallback()
            engine = DecisionEngine(jev=jev, fallback=fallback, mode="auto")
            answers = await engine.decide(state="q", questions=_questions())
            assert all(answer.engine == "fallback" for answer in answers.values())
            assert jev.calls == 1
            assert fallback.calls == 1

        jev, fallback = _FakeJev(["ok"]), _FakeFallback()
        engine = DecisionEngine(jev=jev, fallback=fallback, mode="auto")
        answers = await engine.decide(state="q", questions=_questions())
        assert all(answer.engine == "fallback" for answer in answers.values())
        assert jev.calls == 0
        assert fallback.calls == 1


class TestShadowMode:
    @pytest.mark.asyncio
    async def test_shadow_writes_disagreement_row(self) -> None:
        jev = _FakeJev(["ok"])
        fallback = _FakeFallback()
        writes: list[tuple[str, str, Answer, Answer, bool]] = []

        async def writer(run_id: str, name: str, j: Answer, f: Answer, agree: bool) -> None:
            writes.append((run_id, name, j, f, agree))

        engine = DecisionEngine(
            jev=jev,
            fallback=fallback,
            mode="auto",
            shadow_sample_rate=1.0,
            shadow_writer=writer,
            rng=random.Random(0),
        )
        state = {"run_id": "r-1", "question": "q"}
        await engine.decide(state=state, questions=_questions())
        # The shadow comparison is fire-and-forget; yield to let it land.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(writes) == len(_questions())
        run_ids = {w[0] for w in writes}
        assert run_ids == {"r-1"}

    @pytest.mark.asyncio
    async def test_shadow_skipped_when_rate_zero(self) -> None:
        jev, fallback = _FakeJev(["ok"]), _FakeFallback()
        writes: list[Any] = []

        async def writer(*args: Any) -> None:
            writes.append(args)

        engine = DecisionEngine(
            jev=jev,
            fallback=fallback,
            mode="auto",
            shadow_sample_rate=0.0,
            shadow_writer=writer,
            rng=random.Random(0),
        )
        await engine.decide(state="q", questions=_questions())
        await asyncio.sleep(0)
        assert writes == []


class TestDisplayThresholds:
    def test_display_threshold_maps_known_names_and_prefixes(self) -> None:
        assert display_threshold("guard_injection", "jev") == pytest.approx(0.85)
        assert display_threshold("chunk_injection_3", "fallback") == pytest.approx(0.70)
        assert display_threshold("output_secrets", "jev") == pytest.approx(0.70)
        assert display_threshold("intent", "jev") is None
        assert display_threshold("claim_c1", "jev") is None

    def test_display_threshold_honors_runtime_override(self) -> None:
        token = set_runtime_settings(
            RuntimeSettings.from_data(
                1, {"thresholds": {"sufficient_retry": {"fallback": 0.42}}}
            )
        )
        try:
            assert display_threshold("sufficient", "fallback") == pytest.approx(0.42)
        finally:
            reset_runtime_settings(token)


class TestEventEmission:
    @pytest.mark.asyncio
    async def test_every_answer_emits_with_engine_and_latency(self) -> None:
        emitted: list[tuple[str, Answer, DecisionCall]] = []

        async def emitter(name: str, answer: Answer, call: DecisionCall) -> None:
            emitted.append((name, answer, call))

        engine = DecisionEngine(
            jev=_FakeJev(["ok"]), fallback=_FakeFallback(), event_emitter=emitter
        )
        await engine.decide(state="q", questions=_questions())
        assert {name for name, _, _ in emitted} == set(_questions().keys())
        for _, answer, _ in emitted:
            assert answer.engine == "jev"
            assert answer.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_emitter_shares_call_id_and_batch_size(self) -> None:
        emitted: list[tuple[str, Answer, DecisionCall]] = []

        async def emitter(name: str, answer: Answer, call: DecisionCall) -> None:
            emitted.append((name, answer, call))

        engine = DecisionEngine(
            jev=_FakeJev(["ok", "ok"]), fallback=_FakeFallback(), event_emitter=emitter
        )
        await engine.decide(state={"kind": "ingress"}, questions=_questions())
        await engine.decide(
            state={"kind": "sufficient"},
            questions={"sufficient": Noul(prompt="Enough evidence?")},
        )

        ingress = [entry for entry in emitted if entry[2].stage == "ingress"]
        sufficient = [entry for entry in emitted if entry[2].stage == "sufficient"]
        assert len(ingress) == len(_questions())
        assert len(sufficient) == 1
        assert len({entry[2].call_id for entry in ingress}) == 1
        assert ingress[0][2].batch_size == len(_questions())
        assert sufficient[0][2].batch_size == 1
        assert ingress[0][2].call_id != sufficient[0][2].call_id

    @pytest.mark.asyncio
    async def test_emitter_failure_does_not_block_decision(self) -> None:
        async def bad_emitter(name: str, answer: Answer, call: DecisionCall) -> None:
            raise RuntimeError("bus down")

        engine = DecisionEngine(
            jev=_FakeJev(["ok"]), fallback=_FakeFallback(), event_emitter=bad_emitter
        )
        answers = await engine.decide(state="q", questions=_questions())
        assert len(answers) == len(_questions())


class TestJevClientParsing:
    @pytest.mark.asyncio
    async def test_parses_recorded_ingress_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        get_settings.cache_clear()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=INGRESS_RESPONSE)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        jev = JevClient(client=client)
        questions: dict[str, Question] = {
            "guard_injection": Noul(prompt="inj?"),
            "guard_jailbreak": Noul(prompt="jb?"),
            "guard_pii": Noul(prompt="pii?"),
            "off_topic": Noul(prompt="ot?"),
            "intent": Choice(
                prompt="intent",
                options=["chitchat", "lookup", "compare", "summarize", "multi-part", "follow-up"],
            ),
            "source": Choice(prompt="source", options=["upload", "web", "both"]),
            "complexity": Choice(prompt="complexity", options=["single", "multi"]),
            "risk": Choice(prompt="risk", options=["low", "high"]),
            "lexical_weight": Score(prompt="w", min=0.0, max=1.0),
        }
        answers = await jev.decide(state="state", questions=questions)
        assert answers["guard_injection"].probability == pytest.approx(0.04)
        assert answers["intent"].value == "lookup"
        assert answers["intent"].probabilities is not None
        assert answers["intent"].probabilities["lookup"] == pytest.approx(0.78)
        assert answers["lexical_weight"].value == pytest.approx(0.35)
        assert all(a.engine == "jev" for a in answers.values())

    @pytest.mark.asyncio
    async def test_systemone_request_uses_bare_jev_model_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        get_settings.cache_clear()

        class Usage:
            async def resolve_model(self, requested: str, role: str) -> str:
                return "openrouter/typesafe/jev-1.13"

            def api_key_for(self, model: str) -> str:
                return "test-key"

            async def record_call(
                self, *, model_id: str, role: str, tokens_in: int, tokens_out: int
            ) -> float:
                return 0.0

        payloads: list[dict[str, Any]] = []
        monkeypatch.setattr("decisions.jev.get_usage_context", lambda: Usage())

        def handler(request: httpx.Request) -> httpx.Response:
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json=INGRESS_RESPONSE)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        jev = JevClient(client=client)
        await jev.decide(state="state", questions={"guard_injection": Noul(prompt="inj?")})

        assert payloads[0]["model"] == "typesafe/jev-1.13"

    @pytest.mark.asyncio
    async def test_unparseable_response_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        get_settings.cache_clear()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"answers": {"guard_injection": {"oops": 1}}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        jev = JevClient(client=client)
        with pytest.raises(JevError):
            await jev.decide(state="s", questions={"guard_injection": Noul(prompt="p")})

    @pytest.mark.asyncio
    async def test_http_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        get_settings.cache_clear()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        jev = JevClient(client=client)
        with pytest.raises(JevError):
            await jev.decide(state="s", questions={"guard_injection": Noul(prompt="p")})


class TestFallbackEngineParsing:
    @pytest.mark.asyncio
    async def test_choice_probabilities_normalised(self) -> None:
        async def fake_complete(*, litellm_model: str, messages: Any, metadata: Any) -> str:
            return json.dumps({
                "intent": {
                    "probabilities": {
                        "lookup": 7.0,
                        "chitchat": 1.0,
                        "compare": 1.0,
                        "summarize": 1.0,
                        "multi-part": 0.0,
                        "follow-up": 0.0,
                    },
                    "reasoning": "looks like a lookup",
                }
            })

        engine = FallbackEngine(complete_fn=fake_complete)
        questions: dict[str, Question] = {
            "intent": Choice(
                prompt="intent",
                options=["lookup", "chitchat", "compare", "summarize", "multi-part", "follow-up"],
            )
        }
        answers = await engine.decide(state="s", questions=questions)
        probs = answers["intent"].probabilities
        assert probs is not None
        assert sum(probs.values()) == pytest.approx(1.0)
        assert answers["intent"].value == "lookup"
        assert answers["intent"].engine == "fallback"

    @pytest.mark.asyncio
    async def test_noul_out_of_range_raises(self) -> None:
        async def fake_complete(*, litellm_model: str, messages: Any, metadata: Any) -> str:
            return json.dumps({"guard_injection": {"probability": 1.7}})

        engine = FallbackEngine(complete_fn=fake_complete)
        from decisions.fallback import FallbackError

        with pytest.raises(FallbackError):
            await engine.decide(state="s", questions={"guard_injection": Noul(prompt="p")})

    @pytest.mark.asyncio
    async def test_fenced_json_accepted(self) -> None:
        async def fake_complete(*, litellm_model: str, messages: Any, metadata: Any) -> str:
            return '```json\n{"guard_injection": {"probability": 0.3}}\n```'

        engine = FallbackEngine(complete_fn=fake_complete)
        answers = await engine.decide(
            state="s", questions={"guard_injection": Noul(prompt="p")}
        )
        assert answers["guard_injection"].probability == pytest.approx(0.3)
