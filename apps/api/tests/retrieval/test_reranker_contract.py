"""Contract every registered reranker must meet (R2c item 5, ADR-005).

Parametrised over `RERANKERS`: a new registry entry is covered by adding one
builder here, and the registry-completeness test fails until it is. Fake
transports only: no network, no keys.
"""

import json
import math
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from decisions.engine import DecisionUnavailable
from retrieval.rerank import (
    ANSWER_LEVELS,
    RERANKERS,
    CohereRerank,
    FusedOrderRerank,
    JevRerank,
    NvidiaRerank,
    RerankProvider,
    apply_rerank,
)
from schemas.decisions import Answer
from tests.retrieval.test_rerank_expand_context import _chunk, graded

SECRET = "OWNER-SECRET-NAME"


class _Wire:
    """Records what a fake transport / engine was actually sent."""

    def __init__(self) -> None:
        self.sent: list[str] = []


def _score(text: str) -> float:
    return 0.9 if "good" in text else 0.1


def _cohere(wire: _Wire, mode: str, tie: bool) -> RerankProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "down":
            raise httpx.ConnectError("down")
        body = json.loads(request.content)
        wire.sent.extend(body["documents"])
        rows = [
            {"index": i, "relevance_score": 0.5 if tie else _score(d)}
            for i, d in enumerate(body["documents"])
        ]
        rows.sort(key=lambda r: r["relevance_score"], reverse=True)
        return httpx.Response(200, json={"results": rows[: body["top_n"]]})

    return CohereRerank("k", "m", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _nvidia(wire: _Wire, mode: str, tie: bool) -> RerankProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "down":
            raise httpx.ConnectError("down")
        body = json.loads(request.content)
        docs = [p["text"] for p in body["passages"]]
        wire.sent.extend(docs)
        # Unsorted on purpose: the real endpoint does not guarantee order.
        rows = [{"index": i, "logit": 0.5 if tie else _score(d)} for i, d in enumerate(docs)]
        return httpx.Response(200, json={"rankings": list(reversed(rows))})

    return NvidiaRerank("k", "m", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


class _Engine:
    def __init__(self, wire: _Wire, mode: str, tie: bool) -> None:
        self._wire, self._mode, self._tie = wire, mode, tie

    async def decide(self, *, state: Any, questions: dict[str, Any]) -> dict[str, Answer]:
        if self._mode == "down":
            raise DecisionUnavailable("decision_unavailable", "down")
        out: dict[str, Answer] = {}
        for name, q in questions.items():
            self._wire.sent.append(q.prompt)
            good = self._tie or "good" in q.prompt
            out[name] = graded(ANSWER_LEVELS[2] if good else ANSWER_LEVELS[0])
        return out


def _jev(wire: _Wire, mode: str, tie: bool) -> RerankProvider:
    return JevRerank(_Engine(wire, mode, tie), "run")  # type: ignore[arg-type]


def _fused(wire: _Wire, mode: str, tie: bool) -> RerankProvider:
    return FusedOrderRerank()


BUILDERS: dict[str, Callable[[_Wire, str, bool], RerankProvider]] = {
    "jev": _jev,
    "cohere": _cohere,
    "nvidia": _nvidia,
    "fused": _fused,
}
# Fused order is the fallback itself: it has no transport to fail.
OUTAGE_IDS = [i for i in BUILDERS if i != "fused"]
DOCS = ["bad 0", "good 1", "bad 2", "good 3", "bad 4"]


def test_every_registered_reranker_has_a_contract_builder() -> None:
    assert set(BUILDERS) == set(RERANKERS)


@pytest.mark.parametrize("rid", BUILDERS)
async def test_top_n_is_respected_and_sorted_by_score(rid: str) -> None:
    ranked = await BUILDERS[rid](_Wire(), "ok", False).rerank(query="q", documents=DOCS, top_n=3)
    assert len(ranked) == 3
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)
    assert len({i for i, _ in ranked}) == 3 and all(0 <= i < len(DOCS) for i, _ in ranked)


@pytest.mark.parametrize("rid", BUILDERS)
async def test_scores_are_finite_floats(rid: str) -> None:
    ranked = await BUILDERS[rid](_Wire(), "ok", False).rerank(query="q", documents=DOCS, top_n=5)
    assert all(isinstance(s, float) and math.isfinite(s) for _, s in ranked)


@pytest.mark.parametrize("rid", BUILDERS)
async def test_empty_input_returns_empty(rid: str) -> None:
    assert await apply_rerank(BUILDERS[rid](_Wire(), "ok", False), query="q", chunks=[]) == []


@pytest.mark.parametrize("rid", [i for i in BUILDERS if i != "fused"])
async def test_ties_keep_input_order(rid: str) -> None:
    ranked = await BUILDERS[rid](_Wire(), "ok", True).rerank(query="q", documents=DOCS, top_n=5)
    assert [i for i, _ in ranked] == [0, 1, 2, 3, 4]


@pytest.mark.parametrize("rid", OUTAGE_IDS)
async def test_an_outage_degrades_to_fused_order_and_the_run_completes(rid: str) -> None:
    chunks = [_chunk(i, text=t) for i, t in enumerate(DOCS)]
    ranked = await apply_rerank(
        BUILDERS[rid](_Wire(), "down", False), query="q", chunks=chunks, top_n=3
    )
    assert [c.text for c in ranked] == DOCS[:3]


@pytest.mark.parametrize("rid", [i for i in BUILDERS if i != "fused"])
async def test_a_reranker_only_sees_passage_text_and_cannot_widen_scope(rid: str) -> None:
    wire = _Wire()
    chunks = [_chunk(i, text=t) for i, t in enumerate(DOCS)]
    for c in chunks:  # owner / collection data lives on the chunk, never in the text
        object.__setattr__(c, "document_name", SECRET)
    ranked = await apply_rerank(BUILDERS[rid](wire, "ok", False), query="q", chunks=chunks, top_n=5)
    assert wire.sent and not any(SECRET in s or str(chunks[0].chunk_id) in s for s in wire.sent)
    # Output is a reordering of exactly the input set, whatever the provider says.
    assert {c.chunk_id for c in ranked} <= {c.chunk_id for c in chunks}
