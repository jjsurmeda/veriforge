"""Cohere / NVIDIA rerank behind a provider interface (TRD §9.2: top 40 → top 8).

No SDK — httpx is already a dependency. Without COHERE_API_KEY or
NVIDIA_API_KEY the fused order passes through unchanged (local dev), which
the fused_score doubles as the rerank score. Rerank results are never
cached (TRD §9.4).
"""

import asyncio
import logging
from typing import Protocol

import httpx

from config import get_settings
from retrieval.hybrid import ScoredChunk
from runtime import runtime_value

logger = logging.getLogger(__name__)

RERANK_TOP_N = 8

RerankResult = list[tuple[int, float]]


class RerankProvider(Protocol):
    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        """Return (document index, relevance score) pairs, best first."""
        ...


class CohereRerank:
    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client

    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        async def call(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                "https://api.cohere.com/v2/rerank",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_n,
                },
            )

        if self._client is not None:
            response = await call(self._client)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await call(client)
        # One short retry for a per-minute 429. A trial key's monthly cap also
        # answers 429, and waiting on it only delays apply_rerank's fused-order
        # fallback, so the wait is capped rather than honouring retry-after.
        if response.status_code == 429:
            await asyncio.sleep(min(float(response.headers.get("retry-after", 2)), 2.0))
            if self._client is not None:
                response = await call(self._client)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await call(client)
        response.raise_for_status()
        results = response.json()["results"]
        return [(int(r["index"]), float(r["relevance_score"])) for r in results]


class NvidiaRerank:
    """NVIDIA NIM reranking (ai.api.nvidia.com, model-in-path URL).

    The endpoint has no top_n parameter and does not guarantee ordering, so
    results are sorted by logit and sliced here.
    """

    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client

    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        async def call(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                f"https://ai.api.nvidia.com/v1/retrieval/{self._model}/reranking",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "query": {"text": query},
                    "passages": [{"text": d} for d in documents],
                    "truncate": "END",
                },
            )

        if self._client is not None:
            response = await call(self._client)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await call(client)
        # Same capped single retry as CohereRerank for per-minute 429s; the
        # fused-order fallback in apply_rerank covers persistent failures.
        if response.status_code == 429:
            await asyncio.sleep(2.0)
            if self._client is not None:
                response = await call(self._client)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await call(client)
        response.raise_for_status()
        rankings = response.json()["rankings"]
        pairs = sorted(
            ((int(r["index"]), float(r["logit"])) for r in rankings),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return pairs[:top_n]


class FusedOrderRerank:
    """Local fallback: identity ranking over the fused order (score = fused)."""

    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        return [(i, 1.0 / (1 + i)) for i in range(min(top_n, len(documents)))]


def get_reranker() -> RerankProvider:
    if not bool(runtime_value("retrieval.rerank", True)):
        return FusedOrderRerank()
    settings = get_settings()
    if settings.cohere_api_key:
        return CohereRerank(settings.cohere_api_key, settings.cohere_rerank_model)
    if settings.nvidia_api_key:
        return NvidiaRerank(settings.nvidia_api_key, settings.nvidia_rerank_model)
    return FusedOrderRerank()


async def apply_rerank(
    provider: RerankProvider,
    *,
    query: str,
    chunks: list[ScoredChunk],
    top_n: int = RERANK_TOP_N,
) -> list[ScoredChunk]:
    """top 40 fused → provider rerank → top n, rerank_score attached (§9.2)."""
    if not chunks:
        return []
    if not bool(runtime_value("retrieval.rerank", True)):
        return chunks[: int(runtime_value("retrieval.top_k", top_n))]
    if top_n == RERANK_TOP_N:
        top_n = int(runtime_value("retrieval.top_k", top_n))
    try:
        ranked = await provider.rerank(query=query, documents=[c.text for c in chunks], top_n=top_n)
    except httpx.HTTPError as exc:
        # A rerank outage degrades retrieval to fused order; it never fails the run.
        logger.warning("rerank failed (%s); using fused order", exc)
        ranked = await FusedOrderRerank().rerank(
            query=query, documents=[c.text for c in chunks], top_n=top_n
        )
    return [chunks[index].with_rerank(score) for index, score in ranked]
