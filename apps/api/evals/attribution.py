"""Attribute a measured wall clock to us vs. the provider (known-issues KI-18).

OpenRouter reports, per generation, the time it spent generating. Reading it
back lets the eval gate separate "the provider was slow" from "we added
latency", so only the latter is hard-gated (TRD §15).

Endpoint and field names were read off a live response rather than assumed:
the generation id arrives in the `x-generation-id` response header, which
litellm surfaces on the streaming response as `_response_headers`, and
`generation_time` is that generation's total generation duration in ms. Jev's
records are the exception — `api_type == "decisions"` reports the duration in
`latency` and leaves `generation_time` at 0 (A3; `_record_provider_ms`).

Two things this deliberately does not do:

- It does not touch `providers/llm.py`. A synchronous stats call there would
  add a network round trip to every real request.
- It does not fabricate. A generation whose stats never appear contributes no
  provider figure, and the caller decides how to report the remainder — but it
  is *named*, with its call site, the HTTP status of its last lookup and how
  long after the call it was abandoned (KI-31). An unattributed generation used
  to be a bare count, which is why the cause took three dispatches to find.

Partial attribution (KI-31): a generation that resolves contributes its
provider time even when a sibling on the same item does not. The gated
`our_overhead_ms` is still recorded only when every id resolved, because a
partial sum understates the item's provider time and would overstate our
overhead — the wrong direction to guess at. `generations_unattributed` and the
per-id detail ride along so the gap is visible instead of silent.
"""

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class GenerationRef:
    """One LLM call, and where it came from.

    The id alone cannot be diagnosed: KI-31 spent three dispatches on "2-4 ids
    per fast20 run never resolve" with nothing but a count to go on. The call
    site is what separates the candidate classes — a Jev call, a stream that
    died and restarted, the reviewer's revision — so it is recorded at the same
    moment the id is, not reconstructed afterwards.
    """

    generation_id: str
    source: str  # "litellm" | "jev"
    model: str = ""
    role: str = ""  # the LLM role, from litellm metadata
    job: str = ""  # the pipeline stage, from litellm metadata
    called_at: float = field(default_factory=time.monotonic)

    def as_id(self) -> str:
        return self.generation_id


@dataclass(frozen=True)
class Unresolved:
    """A generation id whose stats record never arrived, and what we know."""

    ref: GenerationRef
    last_status: int | None  # HTTP status of the final lookup, None on transport error
    attempts: int
    api_type: str | None  # if a record did come back but carried no duration

    @property
    def generation_id(self) -> str:
        return self.ref.generation_id

    @property
    def age_ms(self) -> int:
        """How long after the call the lookups gave up.

        The ~20 s landing delay is the thing to compare this against: an id
        abandoned well past that was never going to resolve, which rules the
        delay out as the cause for that id.
        """
        return int((time.monotonic() - self.ref.called_at) * 1000)

    def describe(self) -> str:
        site = f"{self.ref.source}/{self.ref.model or '?'}"
        if self.ref.role or self.ref.job:
            site += f" role={self.ref.role or '?'} job={self.ref.job or '?'}"
        status = self.last_status if self.last_status is not None else "transport-error"
        return (
            f"id={self.generation_id} site={site} last_status={status} "
            f"attempts={self.attempts} age_ms={self.age_ms} api_type={self.api_type or '-'}"
        )


@dataclass
class Attribution:
    """`total_ms` is ours plus the provider's; `provider_ms` is the part we can
    prove was upstream, so `overhead_ms` is the remainder."""

    total_ms: float
    provider_ms: int
    attributed: int
    unattributed: int
    unresolved: list[Unresolved] = field(default_factory=list)

    @property
    def overhead_ms(self) -> int:
        return round(self.total_ms - self.provider_ms)

    @property
    def complete(self) -> bool:
        return self.unattributed == 0 and self.attributed > 0

    @property
    def partial(self) -> bool:
        """Some provider time resolved and some did not. The item is measured
        (it has a `provider_ms`) but its overhead is not trustworthy, so the
        gated figure is withheld and the gap reported instead."""
        return self.attributed > 0 and self.unattributed > 0


@asynccontextmanager
async def record_generation_ids() -> AsyncIterator[list[GenerationRef]]:
    """Collect every LLM call made in this block, with the id and its call site.

    Two seams: `litellm.acompletion` (patching at the litellm boundary is
    the only place the id is visible — `providers/llm.stream_completion`
    yields content deltas and nothing else), and the Jev client's
    `generation_id_sink` (Jev uses raw httpx; its OpenRouter response
    carries the same `x-generation-id` header, verified live 2026-10-01).

    The call site comes from the request's own metadata — `providers/llm.py`
    sends `role` and a `trace_id` built from the pipeline job for every call,
    so nothing new has to be threaded through the graph (KI-31).
    """
    from decisions import jev

    refs: list[GenerationRef] = []
    original = litellm.acompletion

    async def recording(**kwargs: Any) -> Any:
        response = await original(**kwargs)
        headers = getattr(response, "_response_headers", None) or {}
        generation_id = headers.get("x-generation-id")
        if generation_id:
            metadata = kwargs.get("metadata") or {}
            refs.append(
                GenerationRef(
                    generation_id=str(generation_id),
                    source="litellm",
                    model=str(kwargs.get("model", "")),
                    role=str(metadata.get("role", "")),
                    job=str(metadata.get("trace_id", "")),
                )
            )
        return response

    def jev_sink(generation_id: str) -> None:
        # Jev's own sink signature carries only the id; the model is the
        # configured one, which is enough to tell this class apart from a
        # chat completion's.
        from config import get_settings

        refs.append(
            GenerationRef(
                generation_id=generation_id,
                source="jev",
                model=get_settings().jev_model,
                role="decision_engine",
            )
        )

    litellm.acompletion = recording
    original_sink = jev.generation_id_sink
    jev.generation_id_sink = jev_sink
    try:
        yield refs
    finally:
        litellm.acompletion = original
        jev.generation_id_sink = original_sink


def _get(generation_id: str) -> tuple[dict[str, Any] | None, int | None]:
    """The stats record, and the HTTP status of the lookup that produced it.

    The status is returned rather than swallowed because "404 forever" and
    "404 then 200" and "500" are different failures, and KI-31 could not tell
    them apart. `None` status means the request never got an answer.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if key is None:
        return None, None
    request = urllib.request.Request(  # noqa: S310
        STATS_URL.format(generation_id=generation_id),
        headers={"Authorization": f"Bearer {key}", "User-Agent": "veriforge-eval"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return dict(json.load(response)["data"]), response.status
    except urllib.error.HTTPError as exc:
        # OpenRouter stores these asynchronously; a lookup right after the
        # call 404s for a while before the record lands.
        if exc.code != 404:
            raise
        return None, exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        # A transport failure is not evidence the record is missing, so it is
        # reported as its own class rather than as a 404.
        return None, None


async def _stats(generation_id: str) -> tuple[dict[str, Any] | None, int | None, int]:
    """Poll until the record lands. Returns (record, last_status, attempts)."""
    last_status: int | None = None
    for attempt in range(STATS_ATTEMPTS):
        data, last_status = await asyncio.to_thread(_get, generation_id)
        if data is not None:
            return data, last_status, attempt + 1
        if attempt + 1 < STATS_ATTEMPTS:
            await asyncio.sleep(STATS_BACKOFF_SECONDS)
    return None, last_status, STATS_ATTEMPTS


def _record_provider_ms(record: dict[str, Any]) -> int | None:
    """The provider time this one generation record accounts for, in ms.

    Two shapes, both read off live responses rather than assumed:

    - An ordinary chat completion reports `generation_time`.
    - A Jev call reports `api_type == "decisions"` and its `generation_time`
      is **0** on every probe (D2 2c: two calls, 22 and 1590 native tokens,
      both `generation_time` 0 with `latency` 241-242 ms). The duration sits
      in `latency` instead. Reading `generation_time` for these counted Jev's
      time as 0, so every Jev millisecond — rerank batches, sufficient,
      sanitize, conflict, ingress, review verification — was charged to *our*
      overhead in the figure the gate hard-limits. Owner decision A3 records
      Jev's time from `latency`; TRD §15's latency paragraph says so.
    """
    if record.get("api_type") == "decisions":
        latency = record.get("latency")
        return int(latency) if latency is not None else None
    generation_time = record.get("generation_time")
    return int(generation_time) if generation_time is not None else None


async def provider_time_ms(
    generation_ids: Sequence[str | GenerationRef],
) -> tuple[int, int]:
    """Total provider generation time across these generations, and how many
    were actually attributed. Lookups run concurrently, so a whole item costs
    about one backoff, not one per call."""
    provider_ms, attributed, _ = await _attribute_ids(generation_ids)
    return provider_ms, attributed


async def _attribute_ids(
    generation_ids: Sequence[str | GenerationRef],
) -> tuple[int, int, list[Unresolved]]:
    """Provider time, how many generations it accounts for, and every id that
    did not resolve — each with the call site that made it.

    A bare string is accepted so a caller (and a test) can pass ids it has no
    call site for; it becomes a ref with no model, which shows up in the
    unresolved report as `litellm/?`.
    """
    if not generation_ids:
        return 0, 0, []
    refs = [
        gen_id
        if isinstance(gen_id, GenerationRef)
        else GenerationRef(generation_id=gen_id, source="litellm")
        for gen_id in generation_ids
    ]
    results = await asyncio.gather(*(_stats(ref.generation_id) for ref in refs))
    found: list[int] = []
    unresolved: list[Unresolved] = []
    for ref, (record, status, attempts) in zip(refs, results, strict=True):
        ms = _record_provider_ms(record) if record is not None else None
        if ms is None:
            # Two different failures land here, and the report separates them:
            # no record at all (status 404 after the budget), or a record that
            # came back carrying no duration field.
            api_type = record.get("api_type") if record is not None else None
            unresolved.append(
                Unresolved(ref=ref, last_status=status, attempts=attempts, api_type=api_type)
            )
            if record is not None:
                logger.warning(
                    "generation record has no duration field: id=%s api_type=%s keys=%s",
                    ref.generation_id,
                    api_type,
                    sorted(record),
                )
        else:
            found.append(ms)
    return sum(found), len(found), unresolved


async def attribute(total_ms: float, generation_ids: Sequence[str | GenerationRef]) -> Attribution:
    provider_ms, attributed, unresolved = await _attribute_ids(generation_ids)
    for entry in unresolved:
        logger.warning("unresolved generation id: %s", entry.describe())
    result = Attribution(
        total_ms=total_ms,
        provider_ms=provider_ms,
        attributed=attributed,
        unattributed=len(generation_ids) - attributed,
        unresolved=unresolved,
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
