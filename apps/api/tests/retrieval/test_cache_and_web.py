"""Query-embedding and web-result caches (TRD §9.4) + web retrieval flow
(TRD §9.3): temp chunk lifecycle, chat scoping, pinning."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import retrieval.cache as cache_module
import retrieval.web as web_module
from config import get_settings
from db.models import Chunk, Document, QueryCache, User, WebPage
from errors import AppError
from retrieval.cache import (
    get_query_embedding,
    get_query_embeddings,
    get_web_results,
    normalise_query,
    put_web_results,
    query_hash,
)
from retrieval.web import TavilySearch, WebResult, ensure_web_chunks, pin_web_page
from tests.retrieval.conftest import make_chat, make_collection


@pytest.fixture
def embed_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    async def fake_embed_batch(*, texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(cache_module, "embed_batch", fake_embed_batch)
    monkeypatch.setattr(web_module, "embed_batch", fake_embed_batch)
    return calls


async def test_query_embedding_cache_hits_within_ttl(
    db: AsyncSession, embed_calls: list[list[str]]
) -> None:
    first = await get_query_embedding(db, "  What   is Zebra? ")
    second = await get_query_embedding(db, "what is zebra?")
    assert first == second
    assert len(embed_calls) == 1  # given, when queried twice, then embedded once


async def test_query_embedding_cache_expires(
    db: AsyncSession, embed_calls: list[list[str]]
) -> None:
    await get_query_embedding(db, "old query")
    key = query_hash("old query", namespace=f"{get_settings().embedding_model}\n")
    row = await db.get(QueryCache, key)
    assert row is not None
    row.created_at = datetime.now(UTC) - timedelta(days=get_settings().query_cache_ttl_days + 1)
    await db.commit()

    await get_query_embedding(db, "old query")
    assert len(embed_calls) == 2


def test_query_embedding_cache_key_includes_the_model() -> None:
    # vectors from different models are incompatible; the web cache shares
    # query_hash and stays un-namespaced
    assert query_hash("q") != query_hash("q", namespace="model-a\n")
    assert query_hash("q", namespace="model-a\n") != query_hash("q", namespace="model-b\n")


def test_normalise_query_collapses_case_and_whitespace() -> None:
    assert normalise_query("  Foo   BAR ") == "foo bar"


# Batched query embeddings (TRD §7.1): one `embed_batch` for the whole variant
# set instead of one per variant. Real Postgres (the cache is a table).


async def test_all_variants_cached_means_no_embedding_call_at_all(
    db: AsyncSession, embed_calls: list[list[str]]
) -> None:
    await get_query_embeddings(db, ["zebra stripes", "zebra habitat", "zebra diet"])

    calls_before = len(embed_calls)
    got = await get_query_embeddings(db, ["zebra stripes", "zebra habitat", "zebra diet"])

    assert calls_before == 1, "given, everything is embedded in one call"
    assert len(embed_calls) == calls_before, "when, then no provider call at all"
    assert len(got) == 3


async def test_mixed_hits_and_misses_make_exactly_one_call_for_the_misses(
    db: AsyncSession, embed_calls: list[list[str]]
) -> None:
    await get_query_embedding(db, "zebra stripes")
    assert len(embed_calls) == 1

    got = await get_query_embeddings(db, ["zebra stripes", "zebra habitat", "zebra diet"])

    assert len(embed_calls) == 2, "one more call, not two"
    assert embed_calls[1] == ["zebra habitat", "zebra diet"], "only the misses are embedded"
    assert len(got) == 3


async def test_batched_answers_are_in_the_caller_s_order_and_each_matches_its_query(
    db: AsyncSession, embed_calls: list[list[str]]
) -> None:
    got = await get_query_embeddings(db, ["zebra habitat", "zebra stripes"])

    assert embed_calls[0] == ["zebra habitat", "zebra stripes"]
    # every vector is identical in the fixture, so order is checked through the
    # cache the batch filled, not through the values themselves
    assert await get_query_embeddings(db, ["zebra stripes", "zebra habitat"]) == got


async def test_batched_and_single_paths_share_cache_entries(
    db: AsyncSession, embed_calls: list[list[str]]
) -> None:
    """The keys and TTL are unchanged, so an entry either path writes is an
    entry the other reads — otherwise the batch would re-embed what the
    single-query path already cached."""
    await get_query_embeddings(db, ["zebra stripes"])
    assert len(embed_calls) == 1

    single = await get_query_embedding(db, "zebra stripes")

    assert len(embed_calls) == 1, "the single-query path read what the batch wrote"
    assert single == [0.01] * 1536


async def test_a_duplicate_miss_is_embedded_once(
    db: AsyncSession, embed_calls: list[list[str]]
) -> None:
    await get_query_embeddings(db, ["zebra stripes", "ZEBRA   stripes"])

    assert embed_calls[0] == ["zebra stripes"], "normalised to one text"


async def test_an_embedding_failure_propagates_as_before(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-query path lets the provider error out; a batch that caught
    it would answer a retrieval with a silent zero vector."""

    async def failing(*, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding provider down")

    monkeypatch.setattr(cache_module, "embed_batch", failing)

    with pytest.raises(RuntimeError, match="embedding provider down"):
        await get_query_embeddings(db, ["zebra stripes"])


async def test_a_short_batch_raises_instead_of_pairing_the_wrong_vectors(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def short(*, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1536] * max(0, len(texts) - 1)

    monkeypatch.setattr(cache_module, "embed_batch", short)

    with pytest.raises(ValueError, match="returned 1 vectors for 2 queries"):
        await get_query_embeddings(db, ["zebra stripes", "zebra habitat"])


async def test_no_queries_means_no_call(db: AsyncSession, embed_calls: list[list[str]]) -> None:
    assert await get_query_embeddings(db, []) == []
    assert embed_calls == []


async def test_web_results_cache_roundtrip(db: AsyncSession) -> None:
    assert await get_web_results(db, "weather") is None
    await put_web_results(db, "weather", [{"url": "https://x", "title": "X", "content": "c"}])
    cached = await get_web_results(db, "weather")
    assert cached is not None and cached[0]["url"] == "https://x"


async def test_tavily_parses_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert json.loads(request.read())["search_depth"] == "advanced"
        return httpx.Response(200, json={"results": [
            {"url": "https://a", "title": "A", "content": "alpha"},
            {"url": "https://b", "title": "B", "content": ""},
        ]})

    provider = TavilySearch("k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    results = await provider.search("q")
    assert results == [WebResult(url="https://a", title="A", content="alpha")]


@pytest.fixture
def fake_search(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    queries: list[str] = []

    async def search(query: str) -> list[WebResult]:
        queries.append(query)
        return [WebResult(url="https://docs.example/warranty", title="Warranty",
                          content="# Warranty\n\nThe gadget is covered for 2 years.")]

    monkeypatch.setattr(web_module, "_search", search)
    return queries


async def test_ensure_web_chunks_creates_chat_scoped_temp_rows(
    db: AsyncSession, user_a: User, embed_calls: list[list[str]], fake_search: list[str]
) -> None:
    chat = await make_chat(db, user_a)
    pages = await ensure_web_chunks(db, query="gadget warranty", chat_id=chat.id)
    assert pages == 1
    chunks = (await db.execute(select(Chunk).where(Chunk.chat_id == chat.id))).scalars().all()
    assert chunks and all(c.source_type == "web" for c in chunks)
    assert all(c.expires_at is not None for c in chunks)
    assert all(c.document_id is None for c in chunks)

    # second call with same query: web cache hit, page rows reused, no dupes
    await ensure_web_chunks(db, query="gadget warranty", chat_id=chat.id)
    chunks_after = (await db.execute(select(Chunk).where(Chunk.chat_id == chat.id))).scalars().all()
    assert len(chunks_after) == len(chunks)
    assert len(fake_search) == 1


async def test_pin_copies_web_rows_into_owned_collection(
    db: AsyncSession,
    user_a: User,
    user_b: User,
    embed_calls: list[list[str]],
    fake_search: list[str],
) -> None:
    chat = await make_chat(db, user_a)
    await ensure_web_chunks(db, query="gadget warranty", chat_id=chat.id)
    page = (await db.execute(select(WebPage))).scalar_one()

    collection_b = await make_collection(db, user_b, "not yours")
    with pytest.raises(AppError) as other_chat:
        await pin_web_page(db, user_id=user_a.id, web_page_id=page.id,
                           collection_id=collection_b.id)
    assert other_chat.value.status_code == 404

    collection_a = await make_collection(db, user_a, "mine")
    document = await pin_web_page(db, user_id=user_a.id, web_page_id=page.id,
                                  collection_id=collection_a.id)
    pinned = (
        await db.execute(select(Chunk).where(Chunk.document_id == document.id))
    ).scalars().all()
    assert pinned and all(c.source_type == "document" for c in pinned)
    assert all(c.chat_id is None for c in pinned)
    assert document.mime == "text/markdown"
    stored = await db.get(Document, document.id)
    assert stored is not None and stored.status == "ready"


async def test_optional_web_search_degrades_when_unconfigured(
    db: AsyncSession, user_a: User
) -> None:
    """source=both with no web provider answers from documents (0 pages);
    source=web still fails loudly. conftest blanks every web key."""
    chat_id = (await make_chat(db, user_a)).id
    assert await ensure_web_chunks(db, query="q-optional", chat_id=chat_id, optional=True) == 0
    with pytest.raises(AppError):
        await ensure_web_chunks(db, query="q-required", chat_id=chat_id)
