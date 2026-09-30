"""Rerank application, dedupe/expansion and context budget (TRD §9.2)."""

import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from db.models import Chunk, Document, Section, User
from retrieval.context import count_tokens, trim_context
from retrieval.expand import ExpandedContext, dedupe_adjacent, expand_context
from retrieval.hybrid import ScoredChunk
from retrieval.rerank import (
    CohereRerank,
    FusedOrderRerank,
    JevRerank,
    NvidiaRerank,
    apply_rerank,
    get_reranker,
)
from schemas.decisions import Answer
from tests.retrieval.conftest import make_collection


def _chunk(
    ord: int,
    document_id: UUID | None = None,
    section_id: UUID | None = None,
    score: float = 0.5,
    text: str = "t",
) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        document_name="d",
        section_id=section_id,
        ord=ord,
        page=1,
        text=text,
        heading_path="",
        source_type="document",
        vector_score=None,
        bm25_score=None,
        fused_score=score,
    )


async def test_apply_rerank_orders_by_provider_and_caps_top_n() -> None:
    chunks = [_chunk(i, score=1.0 - i / 10) for i in range(12)]
    ranked = await apply_rerank(FusedOrderRerank(), query="q", chunks=chunks, top_n=8)
    assert len(ranked) == 8
    assert [c.ord for c in ranked] == list(range(8))
    scores = [c.rerank_score for c in ranked]
    assert all(s is not None for s in scores)
    assert scores[0] is not None and scores[-1] is not None and scores[0] > scores[-1]


async def test_apply_rerank_empty_input() -> None:
    assert await apply_rerank(FusedOrderRerank(), query="q", chunks=[]) == []


async def test_cohere_rerank_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.cohere.com"
        return httpx.Response(200, json={"results": [{"index": 2, "relevance_score": 0.9},
                                                     {"index": 0, "relevance_score": 0.4}]})

    provider = CohereRerank("k", "rerank-v3.5", client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ))
    chunks = [_chunk(0, text="a"), _chunk(1, text="b"), _chunk(2, text="c")]
    ranked = await apply_rerank(provider, query="q", chunks=chunks, top_n=2)
    assert [c.text for c in ranked] == ["c", "a"]
    assert ranked[0].rerank_score == pytest.approx(0.9)


async def test_nvidia_rerank_sorts_by_logit_and_caps_top_n() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ai.api.nvidia.com"
        assert request.url.path == "/v1/retrieval/nvidia/llama-nemotron-rerank-vl-1b-v2/reranking"
        body = json.loads(request.content)
        assert body["model"] == "nvidia/llama-nemotron-rerank-vl-1b-v2"
        assert body["query"] == {"text": "q"}
        assert body["passages"] == [{"text": "a"}, {"text": "b"}, {"text": "c"}]
        assert body["truncate"] == "END"
        # deliberately unsorted: c > a > b
        return httpx.Response(200, json={"rankings": [{"index": 1, "logit": 0.1},
                                                       {"index": 2, "logit": 4.2},
                                                       {"index": 0, "logit": 1.3}]})

    provider = NvidiaRerank("k", "nvidia/llama-nemotron-rerank-vl-1b-v2", client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ))
    chunks = [_chunk(0, text="a"), _chunk(1, text="b"), _chunk(2, text="c")]
    ranked = await apply_rerank(provider, query="q", chunks=chunks, top_n=2)
    assert [c.text for c in ranked] == ["c", "a"]
    assert ranked[0].rerank_score == pytest.approx(4.2)


def test_get_reranker_precedence_cohere_then_nvidia_then_fused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def settings(cohere: str, nvidia: str) -> Settings:
        return Settings(cohere_api_key=cohere, nvidia_api_key=nvidia)

    monkeypatch.setattr("retrieval.rerank.get_settings", lambda: settings("k", "k"))
    assert isinstance(get_reranker(), CohereRerank)

    monkeypatch.setattr("retrieval.rerank.get_settings", lambda: settings("", "k"))
    assert isinstance(get_reranker(), NvidiaRerank)

    monkeypatch.setattr("retrieval.rerank.get_settings", lambda: settings("", ""))
    assert isinstance(get_reranker(), FusedOrderRerank)


def test_dedupe_adjacent_keeps_first_winner_per_document() -> None:
    doc_a, doc_b = uuid4(), uuid4()
    section = uuid4()
    winners = [
        _chunk(0, doc_a, section, score=0.9),
        _chunk(1, doc_a, section, score=0.8),   # adjacent in same doc → dropped
        _chunk(5, doc_a, section, score=0.7),   # ord gap > 1 → kept
        _chunk(0, doc_b, section, score=0.6),
        _chunk(0, None, None, score=0.5),       # web chunk: document_id None → kept
    ]
    kept = dedupe_adjacent(winners)
    assert [c.fused_score for c in kept] == [0.9, 0.7, 0.6, 0.5]


def test_dedupe_adjacent_keeps_same_ordinal_from_different_sections() -> None:
    document = uuid4()
    winners = [
        _chunk(0, document, uuid4(), score=0.9),
        _chunk(0, document, uuid4(), score=0.8),
    ]

    assert dedupe_adjacent(winners) == winners


async def test_expand_uses_small_parent_whole(
    db: AsyncSession, user_a: User
) -> None:
    collection = await make_collection(db, user_a, "c")
    document = Document(collection_id=collection.id, name="d", mime="text/plain",
                        sha256="x" * 64, s3_key="k", status="ready", tags=[])
    db.add(document)
    await db.flush()
    section = Section(document_id=document.id, heading_path="H", ord=0,
                      text="whole parent text", tokens=100)
    db.add(section)
    await db.flush()
    child = Chunk(document_id=document.id, section_id=section.id, ord=0, page=2,
                  text="child text", chunk_metadata={})
    db.add(child)
    await db.commit()

    winner = ScoredChunk(
        chunk_id=child.id, document_id=document.id, document_name="d",
        section_id=section.id, ord=0, page=2, text="child text", heading_path="H",
        source_type="document", vector_score=None, bm25_score=None, fused_score=1.0,
    )
    contexts = await expand_context(db, [winner])
    assert contexts[0].context_text == "whole parent text"
    assert contexts[0].chunk.chunk_id == child.id  # citation still points at child


async def test_expand_uses_neighbours_when_parent_large(
    db: AsyncSession, user_a: User
) -> None:
    collection = await make_collection(db, user_a, "c")
    document = Document(collection_id=collection.id, name="d", mime="text/plain",
                        sha256="x" * 64, s3_key="k", status="ready", tags=[])
    db.add(document)
    await db.flush()
    section = Section(document_id=document.id, heading_path="H", ord=0,
                      text="huge", tokens=10_000)
    db.add(section)
    await db.flush()
    chunks = [
        Chunk(document_id=document.id, section_id=section.id, ord=i, page=i,
              text=f"chunk {i}", chunk_metadata={})
        for i in range(3)
    ]
    db.add_all(chunks)
    await db.commit()

    winner = ScoredChunk(
        chunk_id=chunks[1].id, document_id=document.id, document_name="d",
        section_id=section.id, ord=1, page=1, text="chunk 1", heading_path="H",
        source_type="document", vector_score=None, bm25_score=None, fused_score=1.0,
    )
    contexts = await expand_context(db, [winner])
    assert contexts[0].context_text == "chunk 0\n\nchunk 1\n\nchunk 2"


async def test_expand_web_chunk_is_itself() -> None:
    web = _chunk(0, None, None)
    contexts = await expand_context(_NoopSession(), [web])  # type: ignore[arg-type]
    assert contexts[0].context_text == "t"


class _NoopSession:
    async def get(self, *_args: object, **_kwargs: object) -> None:
        return None


def test_trim_context_respects_budget() -> None:
    long_text = "word " * 400  # ~400 tokens
    contexts = [
        ExpandedContext(_chunk(0), long_text),
        ExpandedContext(_chunk(1), long_text),
        ExpandedContext(_chunk(2), long_text),
    ]
    kept, used = trim_context(contexts, window_tokens=2_000, history_tokens=0)
    # budget = 0.6 * 2000 = 1200 → two ~400-token contexts fit, third cut
    assert len(kept) == 2
    assert used <= 1_200


def test_trim_context_subtracts_history() -> None:
    contexts = [ExpandedContext(_chunk(0), "word " * 400)]
    kept, _ = trim_context(contexts, window_tokens=1_000, history_tokens=700)
    # budget = 600 - 700 < 0 → only truncated first context survives
    assert len(kept) == 0 or count_tokens(kept[0].context_text) <= 1


def test_trim_context_truncates_first_when_oversize() -> None:
    contexts = [ExpandedContext(_chunk(0), "word " * 10_000)]
    kept, used = trim_context(contexts, window_tokens=1_000, history_tokens=0)
    assert len(kept) == 1
    assert used <= 600


async def test_apply_rerank_falls_back_to_fused_order_when_the_provider_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "trial key monthly limit"})

    provider = CohereRerank("k", "rerank-v3.5", client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ))
    chunks = [_chunk(i) for i in range(5)]
    ranked = await apply_rerank(provider, query="q", chunks=chunks, top_n=3)
    assert [c.chunk_id for c in ranked] == [c.chunk_id for c in chunks[:3]]


class _ScoreJev:
    """Fake DecisionEngine: scores a passage by whether its text contains
    'good', so the expected order is obvious by inspection."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def decide(self, *, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(len(questions))
        return {
            name: Answer(
                engine="jev",
                latency_ms=1,
                value=0.9 if "good" in q.prompt else 0.1,
                probability=None,
            )
            for name, q in questions.items()
        }


async def test_jev_rerank_orders_by_score_and_caps_top_n() -> None:
    jev = _ScoreJev()
    provider = JevRerank(jev, "run")  # type: ignore[arg-type]
    documents = ["bad one", "good two", "bad three", "good four"]

    ranked = await provider.rerank(query="q", documents=documents, top_n=2)

    assert [i for i, _ in ranked] == [1, 3]
    assert {s for _, s in ranked} == {0.9}
    assert len(ranked) == 2
    # one batched call, not one call per passage
    assert jev.calls == [4]


async def test_jev_rerank_scores_an_unanswered_passage_zero() -> None:
    class _Silent(_ScoreJev):
        async def decide(self, *, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
            return {}

    provider = JevRerank(_Silent(), "run")  # type: ignore[arg-type]

    ranked = await provider.rerank(query="q", documents=["good", "bad"], top_n=2)

    assert [s for _, s in ranked] == [0.0, 0.0]


async def test_jev_rerank_clamps_and_survives_a_non_numeric_answer() -> None:
    class _Weird(_ScoreJev):
        async def decide(self, *, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
            return {
                name: Answer(engine="jev", latency_ms=1, value=v, probability=None)
                for name, v in (("passage_0", 42.0), ("passage_1", "not a number"))
            }

    ranked = await JevRerank(_Weird(), "run").rerank(  # type: ignore[arg-type]
        query="q", documents=["a", "b"], top_n=2
    )

    assert dict(ranked) == {0: 1.0, 1: 0.0}


async def test_a_breaker_open_jev_falls_back_to_fused_order() -> None:
    """Jev is unreachable: reranking must degrade to the fused order, never
    fail the run (same contract apply_rerank gives the HTTP providers)."""

    class _Down(_ScoreJev):
        async def decide(self, *, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
            raise httpx.ConnectError("jev down")

    chunks = [_chunk(0, text="good"), _chunk(1, text="bad")]

    ranked = await apply_rerank(
        JevRerank(_Down(), "run"),  # type: ignore[arg-type]
        query="q",
        chunks=chunks,
        top_n=2,
    )

    assert [c.text for c in ranked] == ["good", "bad"]


def test_the_setting_selects_the_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = object()

    monkeypatch.setattr(
        "retrieval.rerank.runtime_value",
        lambda name, default: "jev" if name == "retrieval.reranker" else default,
    )
    assert isinstance(get_reranker(engine, "run"), JevRerank)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "retrieval.rerank.runtime_value",
        lambda name, default: "nvidia" if name == "retrieval.reranker" else default,
    )
    monkeypatch.setattr(
        "retrieval.rerank.get_settings", lambda: Settings(cohere_api_key="", nvidia_api_key="k")
    )
    assert isinstance(get_reranker(engine, "run"), NvidiaRerank)  # type: ignore[arg-type]


def test_jev_selected_without_an_engine_falls_back_to_fused_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "retrieval.rerank.runtime_value",
        lambda name, default: "jev" if name == "retrieval.reranker" else default,
    )

    assert isinstance(get_reranker(), FusedOrderRerank)



def test_jev_without_an_engine_falls_back_to_the_provider_reranker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fast mode has no DecisionEngine; with Jev selected it still reranks
    through the provider chain instead of dropping to fused order."""
    monkeypatch.setattr(
        "retrieval.rerank.runtime_value",
        lambda name, default: "jev" if name == "retrieval.reranker" else default,
    )
    monkeypatch.setattr(
        "retrieval.rerank.get_settings", lambda: Settings(cohere_api_key="", nvidia_api_key="k")
    )
    assert isinstance(get_reranker(), NvidiaRerank)
