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


def query_hash(query: str) -> str:
    return hashlib.sha256(normalise_query(query).encode()).hexdigest()


async def get_query_embedding(session: AsyncSession, query: str) -> list[float]:
    key = query_hash(query)
    cached = await session.get(QueryCache, key)
    ttl = timedelta(days=get_settings().query_cache_ttl_days)
    if cached is not None and cached.created_at > datetime.now(UTC) - ttl:
        return list(cached.embedding)
    embedding = (await embed_batch(texts=[normalise_query(query)]))[0]
    await session.merge(QueryCache(query_hash=key, embedding=embedding))
    return embedding


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
