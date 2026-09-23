"""Web retrieval (TRD §9.3): Tavily → cleaned content → chat-scoped temp
chunks (7-day TTL) that flow through the same hybrid search as documents.

Brave + fetch-and-clean is the fallback when Tavily fails. Results are
cached by normalised query for 24 h (cache.py). Pinning copies a page's
rows into a collection as a regular document.

TODO(slice-4): the sanitizer / chunk_injection decision doesn't exist yet —
web chunks flow through unfiltered and are treated as data only by the
generate prompt's source wrapping (TRD §11).
"""

import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import httpx
from markitdown import MarkItDown
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import Chat, Chunk, Document, Section, User, WebPage
from errors import AppError
from ingest.chunk import chunk_document
from ingest.repository import get_owned_collection
from providers.llm import embed_batch
from retrieval.cache import get_web_results, put_web_results

logger = logging.getLogger(__name__)

TAVILY_RESULTS = 5


@dataclass(frozen=True)
class WebResult:
    url: str
    title: str
    content: str


class WebSearchProvider(Protocol):
    async def search(self, query: str) -> list[WebResult]: ...


class TavilySearch:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, query: str) -> list[WebResult]:
        async def call(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": TAVILY_RESULTS,
                },
            )

        if self._client is not None:
            response = await call(self._client)
        else:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await call(client)
        response.raise_for_status()
        return [
            WebResult(url=r["url"], title=r.get("title") or r["url"], content=r["content"])
            for r in response.json().get("results", [])
            if r.get("content")
        ]


class BraveSearch:
    """Brave returns snippets only; each result is fetched and cleaned."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str) -> list[WebResult]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": self._api_key},
                params={"q": query, "count": TAVILY_RESULTS},
            )
            response.raise_for_status()
            hits = response.json().get("web", {}).get("results", [])
            results: list[WebResult] = []
            for hit in hits[:TAVILY_RESULTS]:
                content = await self._fetch_clean(client, hit["url"])
                if content:
                    results.append(
                        WebResult(
                            url=hit["url"],
                            title=hit.get("title") or hit["url"],
                            content=content,
                        )
                    )
            return results

    async def _fetch_clean(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            page = await client.get(url, follow_redirects=True)
            page.raise_for_status()
            converted = MarkItDown().convert_stream(io.BytesIO(page.content))
            return converted.text_content
        except Exception as exc:
            logger.warning("brave fetch failed", extra={"url": url, "error": str(exc)})
            return ""


def _providers() -> list[WebSearchProvider]:
    settings = get_settings()
    providers: list[WebSearchProvider] = []
    if settings.tavily_api_key:
        providers.append(TavilySearch(settings.tavily_api_key))
    if settings.brave_api_key:
        providers.append(BraveSearch(settings.brave_api_key))
    return providers


async def _search(query: str) -> list[WebResult]:
    last_error: Exception | None = None
    for provider in _providers():
        try:
            return await provider.search(query)
        except (httpx.HTTPError, KeyError) as exc:
            logger.warning(
                "web search provider failed",
                extra={"provider": type(provider).__name__, "error": str(exc)},
            )
            last_error = exc
    if last_error is not None:
        raise AppError("web_search_failed", "Web search failed") from last_error
    raise AppError("web_search_unconfigured", "No web search provider is configured")


async def ensure_web_chunks(session: AsyncSession, *, query: str, chat_id: UUID) -> int:
    """Fetch (or reuse cached) web results and index them as chat-scoped
    chunks. Returns the number of pages available for this chat+query."""
    results = await get_web_results(session, query)
    if results is None:
        fresh = await _search(query)
        results = [{"url": r.url, "title": r.title, "content": r.content} for r in fresh]
        await put_web_results(session, query, results)

    expires = datetime.now(UTC) + timedelta(days=get_settings().web_chunk_ttl_days)
    pages = 0
    for result in results:
        existing = (
            await session.execute(
                select(WebPage).where(
                    WebPage.chat_id == chat_id,
                    WebPage.url == str(result["url"]),
                    WebPage.expires_at > datetime.now(UTC),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            pages += 1
            continue
        page = WebPage(
            chat_id=chat_id, url=str(result["url"]), title=str(result["title"]),
            expires_at=expires,
        )
        session.add(page)
        await session.flush()
        sections = chunk_document(str(result["content"]), [])
        drafts = [child for section in sections for child in section.children]
        if not drafts:
            await session.delete(page)
            continue
        embeddings = await embed_batch(texts=[d.text for d in drafts])
        for draft, embedding in zip(drafts, embeddings, strict=True):
            session.add(
                Chunk(
                    document_id=None,
                    section_id=None,
                    ord=draft.ord,
                    page=None,
                    text=draft.text,
                    embedding=embedding,
                    source_type="web",
                    chat_id=chat_id,
                    expires_at=expires,
                    chunk_metadata={"web_page_id": str(page.id)},
                )
            )
        pages += 1
    return pages


async def pin_web_page(
    session: AsyncSession, *, user_id: UUID, web_page_id: UUID, collection_id: UUID
) -> Document:
    """Copy a web page's temp chunks into a collection as a real document."""
    user = await session.get(User, user_id)
    page = await session.get(WebPage, web_page_id)
    chat = await session.get(Chat, page.chat_id) if page is not None else None
    if user is None or page is None or chat is None or chat.user_id != user_id:
        raise AppError("web_source_not_found", "Web source not found", status_code=404)
    if await get_owned_collection(session, user, collection_id) is None:
        raise AppError("collection_not_found", "Collection not found", status_code=404)

    chunks = (
        await session.execute(
            select(Chunk)
            .where(
                Chunk.source_type == "web",
                Chunk.chat_id == page.chat_id,
                Chunk.chunk_metadata["web_page_id"].astext == str(page.id),
            )
            .order_by(Chunk.ord)
        )
    ).scalars().all()
    if not chunks:
        raise AppError("web_source_not_found", "Web source not found", status_code=404)

    text_all = "\n\n".join(c.text for c in chunks)
    document = Document(
        collection_id=collection_id,
        name=page.title or page.url,
        mime="text/markdown",
        sha256=hashlib.sha256(text_all.encode()).hexdigest(),
        s3_key=f"web/{page.id}",
        status="ready",
        tags=[],
        page_flags=None,
    )
    session.add(document)
    await session.flush()
    section = Section(
        document_id=document.id, heading_path="", ord=0, text=text_all,
        tokens=sum(len(c.text) // 4 for c in chunks),
    )
    session.add(section)
    await session.flush()
    for chunk in chunks:
        session.add(
            Chunk(
                document_id=document.id,
                section_id=section.id,
                ord=chunk.ord,
                page=chunk.page,
                text=chunk.text,
                embedding=chunk.embedding,
                source_type="document",
                chunk_metadata={"pinned_from": page.url},
            )
        )
    return document


async def sweep_expired_web_chunks(session: AsyncSession) -> int:
    """Delete expired temp chunks and their page rows (nightly job, TRD §13)."""
    now = datetime.now(UTC)
    pages = (
        await session.execute(select(WebPage).where(WebPage.expires_at <= now))
    ).scalars().all()
    for page in pages:
        await session.execute(
            delete(Chunk).where(
                Chunk.source_type == "web",
                Chunk.chunk_metadata["web_page_id"].astext == str(page.id),
            )
        )
        await session.delete(page)
    orphaned = await session.execute(
        delete(Chunk).where(Chunk.expires_at.isnot(None), Chunk.expires_at <= now)
    )
    return len(pages) + int(getattr(orphaned, "rowcount", 0) or 0)
