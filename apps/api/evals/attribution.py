"""Attribute a measured wall clock to us vs. the provider (known-issues KI-18).

OpenRouter reports, per generation, the time it spent generating. Reading it
back lets the eval gate separate "the provider was slow" from "we added
latency", so only the latter is hard-gated (TRD §15).

Endpoint and field names were read off a live response rather than assumed:
the generation id arrives in the `x-generation-id` response header, which
litellm surfaces on the streaming response as `_response_headers`, and
`generation_time` is that generation's total generation duration in ms.

Two things this deliberately does not do:

- It does not touch `providers/llm.py`. A synchronous stats call there would
  add a network round trip to every real request.
- It does not fabricate. A generation whose stats never appear is simply not
  counted, and callers decide how to report the unattributed remainder.
"""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import litellm

logger = logging.getLogger(__name__)

STATS_URL = "https://openrouter.ai/api/v1/generation?id={generation_id}"
# Measured live 2026-09-29: the record for a generation lands roughly 20 s
# after the call, so a lookup needs a budget longer than that or it reports
# nothing. That is ~20 s of wall clock per eval item, and the lookups for one
# item run concurrently, so a fast20 run pays it once per item.
STATS_ATTEMPTS = 8
STATS_BACKOFF_SECONDS = 3.0


@dataclass
class Attribution:
    """`total_ms` is ours plus the provider's; `provider_ms` is the part we can
    prove was upstream, so `overhead_ms` is the remainder."""

    total_ms: float
    provider_ms: int
    attributed: int
    unattributed: int

    @property
    def overhead_ms(self) -> int:
        return round(self.total_ms - self.provider_ms)

    @property
    def complete(self) -> bool:
        return self.unattributed == 0 and self.attributed > 0


@asynccontextmanager
async def record_generation_ids() -> AsyncIterator[list[str]]:
    """Collect the generation id of every LLM call made in this block.

    Two seams: `litellm.acompletion` (patching at the litellm boundary is
    the only place the id is visible — `providers/llm.stream_completion`
    yields content deltas and nothing else), and the Jev client's
    `generation_id_sink` (Jev uses raw httpx; its OpenRouter response
    carries the same `x-generation-id` header, verified live 2026-10-01).
    """
    from decisions import jev

    ids: list[str] = []
    original = litellm.acompletion

    async def recording(**kwargs: Any) -> Any:
        response = await original(**kwargs)
        headers = getattr(response, "_response_headers", None) or {}
        generation_id = headers.get("x-generation-id")
        if generation_id:
            ids.append(str(generation_id))
        return response

    litellm.acompletion = recording
    original_sink = jev.generation_id_sink
    jev.generation_id_sink = ids.append
    try:
        yield ids
    finally:
        litellm.acompletion = original
        jev.generation_id_sink = original_sink


def _get(generation_id: str) -> dict[str, Any] | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key is None:
        return None
    request = urllib.request.Request(  # noqa: S310
        STATS_URL.format(generation_id=generation_id),
        headers={"Authorization": f"Bearer {key}", "User-Agent": "veriforge-eval"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return dict(json.load(response)["data"])
    except urllib.error.HTTPError as exc:
        # OpenRouter stores these asynchronously; a lookup right after the
        # call 404s for a while before the record lands.
        if exc.code != 404:
            raise
        return None


async def _stats(generation_id: str) -> dict[str, Any] | None:
    for attempt in range(STATS_ATTEMPTS):
        data = await asyncio.to_thread(_get, generation_id)
        if data is not None:
            return data
        if attempt + 1 < STATS_ATTEMPTS:
            await asyncio.sleep(STATS_BACKOFF_SECONDS)
    return None


async def provider_time_ms(generation_ids: list[str]) -> tuple[int, int]:
    """Total provider generation time across these generations, and how many
    were actually attributed. Lookups run concurrently, so a whole item costs
    about one backoff, not one per call."""
    if not generation_ids:
        return 0, 0
    results = await asyncio.gather(*(_stats(gid) for gid in generation_ids))
    found = [r for r in results if r is not None and r.get("generation_time") is not None]
    return sum(int(r["generation_time"]) for r in found), len(found)


async def attribute(total_ms: float, generation_ids: list[str]) -> Attribution:
    provider_ms, attributed = await provider_time_ms(generation_ids)
    result = Attribution(
        total_ms=total_ms,
        provider_ms=provider_ms,
        attributed=attributed,
        unattributed=len(generation_ids) - attributed,
    )
    if result.overhead_ms < 0:
        # Concurrent calls sum to more provider time than the wall clock.
        # Reported, never clamped (D2 2c).
        logger.warning(
            "negative per-item overhead: total_ms=%.0f provider_ms=%d over %d calls",
            total_ms,
            provider_ms,
            attributed,
        )
    return result
