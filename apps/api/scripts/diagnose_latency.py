"""Attribute end-to-end LLM latency to us vs. the provider (known-issues KI-18).

Runs N live streaming calls through the app's own `providers.llm.stream_completion`
and, for each, compares our measured wall clock against the figure OpenRouter
reports for the same generation:

    GET /api/v1/generation?id=<x-generation-id>   ->  generation_time  (ms)

`our_overhead_ms` is the difference. Endpoint and field names were read off a
live response, not assumed: the generation id arrives in the `x-generation-id`
response header (litellm surfaces it on the streaming response as
`_response_headers`), and `generation_time` is OpenRouter's total generation
duration. `provider_responses[0].latency` is the upstream vendor's own latency,
recorded alongside because it splits "OpenRouter routing" from "the model".

OpenRouter stores these stats asynchronously — a lookup right after the call
returns 404 for roughly 10-30 s, so `_stats` retries before giving up. A call
whose stats never appear is reported as unattributed rather than estimated.

This is a diagnostic, not part of the app: nothing here is imported at runtime,
and `providers/llm.py` is deliberately left alone. Instrumenting the hot path
with a synchronous stats call would add a network round trip to every real
request, which is the opposite of the point.

Usage: `uv run python scripts/diagnose_latency.py [n_calls]`
"""

import asyncio
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.attribution import record_generation_ids
from providers.llm import stream_completion

MODEL = "openrouter/openai/gpt-4o-mini"
PROMPT = "Answer in one short sentence: what is a retrieval index?"
METADATA = {"role": "generator"}


@dataclass
class Sample:
    total_ms: float
    ttft_ms: float | None
    generation_ms: int | None
    upstream_ms: int | None
    provider_name: str | None

    @property
    def overhead_ms(self) -> int | None:
        if self.generation_ms is None:
            return None
        return round(self.total_ms - self.generation_ms)


async def _stats(generation_id: str) -> dict[str, Any] | None:
    from evals.attribution import _stats as fetch

    return await fetch(generation_id)


async def _once() -> Sample:
    started = time.perf_counter()
    first: float | None = None
    async with record_generation_ids() as generation_ids:
        async for _delta in stream_completion(
            litellm_model=MODEL, messages=[{"role": "user", "content": PROMPT}], metadata=METADATA
        ):
            if first is None:
                first = time.perf_counter()
    total_ms = (time.perf_counter() - started) * 1000
    ttft_ms = (first - started) * 1000 if first is not None else None

    data = await _stats(generation_ids[0]) if generation_ids else None
    if data is None:
        return Sample(total_ms, ttft_ms, None, None, None)
    responses = data.get("provider_responses") or [{}]
    return Sample(
        total_ms=total_ms,
        ttft_ms=ttft_ms,
        generation_ms=data.get("generation_time"),
        upstream_ms=responses[0].get("latency"),
        provider_name=data.get("provider_name"),
    )


async def main(count: int) -> None:
    if os.environ.get("OPENROUTER_API_KEY") is None:
        raise SystemExit("OPENROUTER_API_KEY is not set")

    samples: list[Sample] = []
    for index in range(1, count + 1):
        sample = await _once()
        samples.append(sample)
        attributed = f"{sample.overhead_ms:>7}" if sample.overhead_ms is not None else "  n/a"
        print(
            f"  call {index:>2}/{count}  total {sample.total_ms:>8.0f}ms  "
            f"ttft {sample.ttft_ms or 0:>7.0f}ms  provider {sample.generation_ms or 0:>6}ms  "
            f"upstream {sample.upstream_ms or 0:>6}ms  ours {attributed}ms  "
            f"[{sample.provider_name or 'unattributed'}]",
            flush=True,
        )

    _report(samples)


def _report(samples: list[Sample]) -> None:
    attributed = [s.overhead_ms for s in samples if s.overhead_ms is not None]
    print("\nsummary")
    print(f"  calls            {len(samples)}")
    print(f"  attributed       {len(attributed)}/{len(samples)}")
    print(f"  providers seen   {sorted({s.provider_name or 'n/a' for s in samples})}")
    for label, values in (
        ("total_ms", [s.total_ms for s in samples]),
        ("ttft_ms", [s.ttft_ms for s in samples if s.ttft_ms is not None]),
        ("provider_generation_ms", [float(s.generation_ms) for s in samples if s.generation_ms]),
        ("upstream_ms", [float(s.upstream_ms) for s in samples if s.upstream_ms]),
    ):
        if values:
            print(
                f"  {label:<22} p50 {statistics.median(values):>8.0f}  "
                f"min {min(values):>8.0f}  max {max(values):>8.0f}"
            )
    if attributed:
        stdev = statistics.stdev(attributed) if len(attributed) > 1 else 0.0
        print(
            f"  {'our_overhead_ms':<22} p50 {statistics.median(attributed):>8.0f}  "
            f"min {min(attributed):>8}  max {max(attributed):>8}  stdev {stdev:>7.0f}"
        )
    else:
        print("  our_overhead_ms       no call could be attributed")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
