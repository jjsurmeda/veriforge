"""Phase 1d item 1: a single provider timeout must not fail a whole item.

Run 1 of phase 1c lost one item to a raw Jev `httpx.ReadTimeout`, which made
`make check-work` fail at random. `decisions/jev.py` wraps `httpx.HTTPError`
in `JevError` and `DecisionEngine` falls back on it, so a *raw* timeout
reaching an item means some path bypasses that. These tests are the proof:
each injects a real `httpx.ReadTimeout` at a named point and asserts where it
ends up.
"""

from uuid import UUID

import httpx
import pytest

from decisions.engine import DecisionEngine, DecisionUnavailable
from decisions.jev import JevClient, JevError
from retrieval.hybrid import ScoredChunk
from retrieval.rerank import FusedOrderRerank, JevRerank, apply_rerank
from schemas.decisions import Answer, Noul, Question


def _questions() -> dict[str, Question]:
    return {"is_answerable": Noul(prompt="is it answerable?")}


def _ok(engine_name: str = "fallback") -> dict[str, Answer]:
    return {"is_answerable": Answer(engine=engine_name, latency_ms=1, value=0.9, probability=0.9)}


def _chunk(text: str, index: int = 0) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=UUID(int=index),
        document_id=None,
        document_name="doc",
        section_id=None,
        ord=index,
        page=None,
        text=text,
        heading_path=None,
        source_type="document",
        vector_score=1.0,
        bm25_score=None,
        fused_score=1.0,
    )


def _read_timeout_client() -> httpx.AsyncClient:
    """A transport that raises the exception httpx actually raises."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestJevClientWrapsTransportErrors:
    """`decisions/jev.py:194` is the first line of defence and it holds:
    `httpx.ReadTimeout` is an `httpx.HTTPError`, so it becomes a `JevError`."""

    @pytest.mark.asyncio
    async def test_read_timeout_becomes_a_jev_error(self) -> None:
        with pytest.raises(JevError):
            await JevClient(client=_read_timeout_client()).decide(
                state="s", questions=_questions()
            )


class TestDecisionEngineFallsBackOnAJevTimeout:
    @pytest.mark.asyncio
    async def test_a_real_jev_timeout_falls_back_to_the_fallback_engine(self) -> None:
        class _Fallback:
            calls = 0

            async def decide(self, *, state, questions):  # type: ignore[no-untyped-def]
                self.calls += 1
                return _ok()

        fallback = _Fallback()
        # The real JevClient, wired to a transport that times out — so the
        # whole real path runs, wrapper included.
        engine = DecisionEngine(
            jev=JevClient(client=_read_timeout_client()), fallback=fallback, mode="auto"
        )
        answers = await engine.decide(state="q", questions=_questions())
        assert fallback.calls == 1
        assert answers["is_answerable"].engine == "fallback"


class TestRerankDegradationHolds:
    """`apply_rerank`'s contract (rerank.py:253) is that a rerank outage
    degrades retrieval to fused order and never fails the run. It catches
    `httpx.HTTPError` — but the Jev reranker's provider is the DecisionEngine,
    whose total failure is `DecisionUnavailable`, an `AppError`. That is not
    an `httpx.HTTPError`, so it escapes the handler the contract is written
    against and kills the run — the exact failure item 1 is about.
    """

    @pytest.mark.asyncio
    async def test_decision_unavailable_from_the_jev_reranker_degrades(self) -> None:
        class _BothEnginesDown:
            def __init__(self) -> None:
                self.calls = 0

            async def decide(self, *, state, questions):  # type: ignore[no-untyped-def]
                self.calls += 1
                raise DecisionUnavailable(
                    "decision_unavailable",
                    "The decision engine could not be reached. Please try again.",
                    {"stage": "rerank", "batch_size": 1},
                )

        reranker = JevRerank(
            engine=DecisionEngine(jev=_BothEnginesDown(), fallback=_BothEnginesDown()),
            run_id="run-1",
        )
        chunks = [_chunk("alpha", 0), _chunk("beta", 1)]
        # The run must degrade, not die.
        ranked = await apply_rerank(reranker, query="q", chunks=chunks, top_n=2)
        assert len(ranked) == 2


class TestTheFusedOrderFallbackItselfIsIntact:
    """Guard the degradation the test above relies on."""

    @pytest.mark.asyncio
    async def test_fused_order_ranks_in_input_order(self) -> None:
        result = await FusedOrderRerank().rerank(
            query="q", documents=["a", "b", "c"], top_n=3
        )
        assert [i for i, _ in result] == [0, 1, 2]