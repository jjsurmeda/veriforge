"""Rerank application, dedupe/expansion and context budget (TRD §9.2)."""

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chunk, Document, Section, User
from retrieval.context import count_tokens, trim_context
from retrieval.expand import ExpandedContext, dedupe_adjacent, expand_context
from retrieval.hybrid import ScoredChunk
from retrieval.rerank import CohereRerank, FusedOrderRerank, apply_rerank
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
