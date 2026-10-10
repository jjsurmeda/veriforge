"""Retrieval caches (TRD §9.4).

Query embeddings cached in Postgres by hash of the normalised query
(30-day TTL); Tavily results cached the same way (24 h). TTLs are enforced
at read time; the nightly expiry sweep is a later worker job. Rerank is
deliberately not cached.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import QueryCache, WebCache
from providers.llm import embed_batch


def normalise_query(query: str) -> str:
    return " ".join(query.lower().split())


def query_hash(query: str, namespace: str = "") -> str:
    return hashlib.sha256(f"{namespace}{normalise_query(query)}".encode()).hexdigest()


async def get_query_embedding(session: AsyncSession, query: str) -> list[float]:
    # Keyed by embedding model: vectors from different models are
    # incompatible, so a model switch invalidates the cache without a wipe.
    key = query_hash(query, namespace=f"{get_settings().embedding_model}\n")
    cached = await session.get(QueryCache, key)
    ttl = timedelta(days=get_settings().query_cache_ttl_days)
    if cached is not None and cached.created_at > datetime.now(UTC) - ttl:
        return list(cached.embedding)
    embedding = (await embed_batch(texts=[normalise_query(query)]))[0]
    await session.merge(QueryCache(query_hash=key, embedding=embedding))
    return embedding


async def get_query_embeddings(session: AsyncSession, queries: list[str]) -> list[list[float]]:
    """Embed every query in ONE `embed_batch` call (TRD §7.1, "one embedding
    call for every variant").

    `retrieve_queries` used to call `get_query_embedding` once per query
    variant, and each of those was a cache read plus an `embed_batch` of one
    text — four variants, four provider round trips, each paying its own
    queueing latency, inside the stage that dominates the run.

    Same keys, same TTL and same normalisation as the single-query path, so an
    entry written by either is an entry the other reads: the duplicates inside
    one call are embedded once and the answer keeps the caller's order.
    Failures are not caught here either — the single-query path lets the
    provider error propagate, and a batch that swallowed it would answer a
    retrieval with a silent zero vector.
    """
    if not queries:
        return []
    settings = get_settings()
    namespace = f"{settings.embedding_model}\n"
    ttl = timedelta(days=settings.query_cache_ttl_days)
    cutoff = datetime.now(UTC) - ttl

    embeddings: list[list[float] | None] = [None] * len(queries)
    # One lookup per distinct key, in one pass; `session.get` consults the
    # identity map first, so a repeated query costs no statement.
    for index, query in enumerate(queries):
        key = query_hash(query, namespace=namespace)
        cached = await session.get(QueryCache, key)
        if cached is not None and cached.created_at > cutoff:
            embeddings[index] = list(cached.embedding)

    missing = [index for index, embedding in enumerate(embeddings) if embedding is None]
    if missing:
        # Deduplicate the misses: two identical variants are one text to embed.
        unique: dict[str, list[int]] = {}
        for index in missing:
            unique.setdefault(normalise_query(queries[index]), []).append(index)
        texts = list(unique)
        fresh = await embed_batch(texts=texts)
        if len(fresh) != len(texts):
            raise ValueError(
                f"embed_batch returned {len(fresh)} vectors for {len(texts)} queries"
            )
        by_text = dict(zip(texts, fresh, strict=True))
        for text, indexes in unique.items():
            for index in indexes:
                embeddings[index] = by_text[text]
        for index in missing:
            await session.merge(
                QueryCache(
                    query_hash=query_hash(queries[index], namespace=namespace),
                    embedding=embeddings[index],
                )
            )
    filled: list[list[float]] = []
    for embedding in embeddings:
        # Unreachable by construction (every miss was filled by the batch);
        # raised rather than skipped, because a shifted list here would pair a
        # retrieval with another query's vector.
        if embedding is None:
            raise ValueError("query embedding missing after a batched embed")
        filled.append(embedding)
    return filled


async def get_web_results(session: AsyncSession, query: str) -> list[dict[str, object]] | None:
    key = query_hash(query)
    cached = await session.get(WebCache, key)
    ttl = timedelta(hours=get_settings().web_cache_ttl_hours)
    if cached is not None and cached.created_at > datetime.now(UTC) - ttl:
        return list(cached.results)
    return None


async def put_web_results(
    session: AsyncSession, query: str, results: list[dict[str, object]]
) -> None:
    await session.merge(WebCache(query_hash=query_hash(query), results=results))
