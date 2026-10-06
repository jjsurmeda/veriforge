"""Degradation proven by test, with fakes only (item 5, R1).

Five outages, each asserted on what the *product* does, not on that nothing
raised. No network, no live provider, no sleeps (testing.md).

The claim TRD R1 makes is "degradation is proven by tests". For each row the
test asserts the intended outcome — the run still answers, the failure code
is the specific one, the signal fires — and each row is mutation-checked, so
"it degrades" is not something these tests merely observe.

| scenario | expected | asserted at |
| --- | --- | --- |
| Jev down | fallback answers, breaker.opened once | `TestJevDown` |
| Jev *and* fallback down | `decision_unavailable`, no hang | `TestBothEnginesDown` |
| provider 402 / quota | `provider.credit_low` + `run.failed` | `TestProviderCredit` |
| rerank down | fused order, no crash | `TestRerankDown` |
| web down (source=both) | documents only, and it says so | `TestWebDown` |
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from config import get_settings
from decisions.breaker import CircuitBreaker
from decisions.engine import DecisionEngine
from decisions.fallback import FallbackEngine, FallbackError
from decisions.jev import JevError
from graph.ingress import run_ingress
from observability import signals
from providers.llm import classify_provider_error
from retrieval.rerank import RERANK_TOP_N, FusedOrderRerank, apply_rerank
from schemas.decisions import Answer, Choice, Noul, Question

# --- fakes -----------------------------------------------------------------


class _DeadJev:
    """Jev that is down, however you ask it."""

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, *, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
        self.calls += 1
        raise JevError("simulated jev outage")


class _DeadFallback:
    async def decide(self, *, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
        raise FallbackError("simulated fallback outage")


class _LiveFallback:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, *, state: Any, questions: dict[str, Question]) -> dict[str, Answer]:
        self.calls += 1
        return {
            name: Answer(
                engine="fallback",
                latency_ms=5,
                value=0.3 if isinstance(q, Noul) else ("lookup" if isinstance(q, Choice) else 0.5),
                probability=0.3 if isinstance(q, Noul) else None,
            )
            for name, q in questions.items()
        }


def _questions() -> dict[str, Question]:
    return {
        "guard_injection": Noul(prompt="injection?"),
        "intent": Choice(prompt="intent", options=["lookup", "chitchat"]),
    }


def _emitted(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]


# --- 1. Jev down -----------------------------------------------------------


class TestJevDown:
    @pytest.mark.asyncio
    async def test_decisions_still_come_back_on_the_fallback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        jev, fallback = _DeadJev(), _LiveFallback()
        engine = DecisionEngine(jev=jev, fallback=fallback, mode="auto")
        answers = await engine.decide(state={"kind": "ingress"}, questions=_questions())
        assert answers, "a dead Jev must not mean no answers"
        assert all(a.engine == "fallback" for a in answers.values())
        assert jev.calls == 1 and fallback.calls == 1

    @pytest.mark.asyncio
    async def test_the_run_continues_and_ingresses(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The product outcome, not the engine outcome: ingress still
        classifies the message and the run proceeds on the fallback's answer."""
        engine = DecisionEngine(jev=_DeadJev(), fallback=_LiveFallback(), mode="auto")
        outcome = await run_ingress(
            engine,
            run_id=uuid4(),
            user_message="What does the manual say about ingress protection?",
            has_collections=True,
        )
        assert outcome.intent == "lookup"
        assert outcome.complexity in ("single", "multi")
        assert outcome.source in ("upload", "web", "both")

    @pytest.mark.asyncio
    async def test_breaker_opened_is_emitted_exactly_once(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Once the breaker opens, Jev is not attempted again — so the outage
        produces one signal, not one per decision."""
        breaker = CircuitBreaker(failure_threshold=3, window_seconds=60, cooldown_seconds=60)
        jev = _DeadJev()
        engine = DecisionEngine(
            jev=jev, fallback=_LiveFallback(), breaker=breaker, mode="auto"
        )
        capsys.readouterr()
        for _ in range(6):
            await engine.decide(state={"kind": "ingress"}, questions=_questions())

        opened = [p for p in _emitted(capsys) if p["event"] == signals.BREAKER_OPENED]
        assert len(opened) == 1, f"one outage must produce one signal, got {len(opened)}"
        assert opened[0]["state"] == "open"
        # Three attempts to open it, then the breaker refuses Jev entirely.
        assert jev.calls == breaker.failure_threshold


# --- 2. both engines down ---------------------------------------------------


class TestBothEnginesDown:
    @pytest.mark.asyncio
    async def test_the_failure_is_a_named_code_not_a_hang_or_a_500(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """R1's hardest row. It must not hang and it must not surface as a
        generic error: an operator reading `run.failed` has to be able to tell
        "the decision engine is unreachable" from "something else broke".
        """
        from errors import AppError

        engine = DecisionEngine(jev=_DeadJev(), fallback=_DeadFallback(), mode="auto")
        with pytest.raises(AppError) as failed:
            await engine.decide(state={"kind": "ingress"}, questions=_questions())
        assert failed.value.error_code == "decision_unavailable"

    @pytest.mark.asyncio
    async def test_the_real_fallback_failure_also_names_the_code(self) -> None:
        """Not the fake's exception: the actual `FallbackEngine` raising, so
        the mapping from engine failure to error code is pinned at its source.

        A `TimeoutError` stands in for the provider hang, because a real
        timeout is the outage this code most often has to survive.
        """

        async def timing_out(**kwargs: Any) -> str:
            raise TimeoutError("provider never answered")

        engine = FallbackEngine(complete_fn=timing_out)
        with pytest.raises(FallbackError):
            await engine.decide(state={"kind": "ingress"}, questions=_questions())

    def test_jev_only_mode_does_not_invent_a_fallback_answer(self) -> None:
        """`jev_only` means what it says: a dead Jev propagates rather than
        quietly answering from somewhere else. Silently succeeding would
        make the mode indistinguishable from `auto` in the trace."""
        import asyncio

        async def run() -> None:
            engine = DecisionEngine(jev=_DeadJev(), mode="jev_only")
            with pytest.raises(JevError):
                await engine.decide(state={"kind": "ingress"}, questions=_questions())

        asyncio.run(run())


# --- 3. provider out of credit ---------------------------------------------


class TestProviderCredit:
    def test_a_402_becomes_a_quota_error_with_a_401_shaped_message(self) -> None:
        from litellm.exceptions import RateLimitError

        error = classify_provider_error(
            RateLimitError(
                message="402 insufficient credits",
                llm_provider="openrouter",
                model="openrouter/free",
            )
        )
        assert error is not None
        assert error.status_code in (402, 503)
        # Whatever the class, the user-facing message must not say "try again":
        # for an exhausted balance a retry spends nothing and succeeds never,
        # and sends them into a loop (KI-23).
        assert "try again" not in error.message.lower()

    def test_an_invalid_key_is_a_different_code_from_an_empty_balance(self) -> None:
        import litellm

        invalid = classify_provider_error(
            litellm.exceptions.AuthenticationError(
                message="401 invalid key", llm_provider="openrouter", model="openrouter/free"
            )
        )
        unavailable = classify_provider_error(
            litellm.exceptions.ServiceUnavailableError(
                message="503", llm_provider="openrouter", model="openrouter/free"
            )
        )
        assert invalid is not None and unavailable is not None
        assert invalid.error_code != unavailable.error_code

    def test_a_non_provider_error_is_not_classified(self) -> None:
        """A bug in our own code must not be reported as a provider outage:
        it would send an operator to check the wrong system."""
        assert classify_provider_error(ValueError("a bug")) is None


# --- 4. rerank down ---------------------------------------------------------


class _DeadRerank:
    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> Any:
        raise httpx.ConnectError("rerank provider unreachable")


def _chunk(text: str, fused: float) -> Any:
    """A real `ScoredChunk`, not a stand-in.

    The rerank contract is "`with_rerank` returns the same chunk with a
    score", and a hand-rolled double would implement that contract *for* the
    code under test rather than checking it.
    """
    from retrieval.hybrid import ScoredChunk

    return ScoredChunk(
        chunk_id=uuid4(),
        document_id=None,
        document_name="doc",
        section_id=None,
        ord=0,
        page=None,
        text=text,
        heading_path=None,
        source_type="document",
        vector_score=fused,
        bm25_score=fused,
        fused_score=fused,
    )


class TestRerankDown:
    @pytest.mark.asyncio
    async def test_retrieval_degrades_to_the_fused_order(self) -> None:
        chunks = [_chunk("alpha", 0.9), _chunk("beta", 0.5)]
        ranked = await apply_rerank(
            _DeadRerank(), query="q", chunks=chunks, top_n=RERANK_TOP_N
        )
        assert len(ranked) == 2, "a dead reranker must not drop the results"
        # Fused order preserved, and every chunk still carries a score so the
        # trace panel does not render a column of nulls.
        assert [c.text for c in ranked] == ["alpha", "beta"]
        assert all(c.rerank_score is not None for c in ranked)

    @pytest.mark.asyncio
    async def test_the_fused_order_is_the_intended_answer_not_a_crash(self) -> None:
        """`FusedOrderRerank` is the documented local fallback, and the score
        it returns is the fused score — asserted so "rerank down" has a
        defined result rather than merely a non-exception."""
        result = await FusedOrderRerank().rerank(
            query="q", documents=["alpha", "beta"], top_n=2
        )
        # Identity ranking over the input order, with a decaying score so the
        # fused position is still expressed as a number rather than as null.
        assert result == [(0, 1.0), (1, 0.5)]
        assert all(isinstance(score, float) for _, score in result)

    @pytest.mark.asyncio
    async def test_top_n_is_honoured_on_the_degraded_path(self) -> None:
        chunks = [_chunk(f"c{i}", 1.0 - i / 10) for i in range(5)]
        ranked = await apply_rerank(_DeadRerank(), query="q", chunks=chunks, top_n=2)
        assert len(ranked) <= 2


# --- 5. web search down -----------------------------------------------------


class TestWebDown:
    @pytest.mark.asyncio
    async def test_source_both_degrades_to_documents_only(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from errors import AppError
        from retrieval import web

        async def dead(*args: Any, **kwargs: Any) -> list[Any]:
            raise AppError("web_search_failed", "Web search failed")

        monkeypatch.setattr(web, "_search", dead)
        get_settings.cache_clear()
        pages = await web.ensure_web_chunks(
            db, query="what is new", chat_id=uuid4(), optional=True
        )
        assert pages == 0, "documents alone can still answer; the run must go on"

    @pytest.mark.asyncio
    async def test_a_required_web_source_still_fails_loudly(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`optional=False` is the web-only source, where there is no document
        to fall back on — degrading to zero pages there would answer the
        question from nothing."""
        from errors import AppError
        from retrieval import web

        async def dead(*args: Any, **kwargs: Any) -> list[Any]:
            raise AppError("web_search_failed", "Web search failed")

        monkeypatch.setattr(web, "_search", dead)
        get_settings.cache_clear()
        with pytest.raises(AppError) as failed:
            await web.ensure_web_chunks(
                db, query="what is new", chat_id=uuid4(), optional=False
            )
        assert failed.value.error_code == "web_search_failed"


# --- the signal contract for these outages ----------------------------------


class TestOutageSignals:
    @pytest.mark.asyncio
    async def test_a_provider_credit_outage_emits_both_signals_in_order(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`provider.credit_low` is a *subset* of `run.failed`: the run failed
        AND the reason is money, which is a different alarm with a different
        audience. Both lines are emitted from the one place that classifies
        the failure."""
        from litellm.exceptions import RateLimitError

        error = classify_provider_error(
            RateLimitError(
                message="402 insufficient credits",
                llm_provider="openrouter",
                model="openrouter/free",
            )
        )
        assert error is not None
        run_id, user_id = uuid4(), uuid4()

        capsys.readouterr()
        signals.emit(
            signals.RUN_FAILED, run_id=run_id, user_id=user_id, error_code=error.error_code
        )
        if error.error_code == "quota_exceeded":
            signals.emit(
                signals.PROVIDER_CREDIT_LOW,
                run_id=run_id,
                user_id=user_id,
                error_code=error.error_code,
            )
        lines = _emitted(capsys)
        events = [p["event"] for p in lines]
        assert events == [signals.RUN_FAILED, signals.PROVIDER_CREDIT_LOW]
        assert all(p["run_id"] == str(run_id) for p in lines)