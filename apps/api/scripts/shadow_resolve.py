"""Resolve the generation ids in a `shadow_api` call log to tokens and real USD.

Uses the repo's own `evals.attribution._stats` (OpenRouter generation record;
the key comes from the environment, nothing here reads or prints it). Writes
`<log>.gens.json`: id -> the fields of the record that matter. Ids that never
resolve are listed, not guessed.

    python -m scripts.shadow_resolve .data/shadow-calls.jsonl [--attempts N]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals import attribution

KEEP = (
    "total_cost",
    "usage",
    "cache_discount",
    "tokens_prompt",
    "tokens_completion",
    "native_tokens_prompt",
    "native_tokens_completion",
    "native_tokens_reasoning",
    "latency",
    "generation_time",
    "api_type",
    "model",
    "provider_name",
    "created_at",
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--attempts", type=int, default=10)
    args = parser.parse_args()
    attribution.STATS_ATTEMPTS = args.attempts
    ids = sorted(
        {
            rec["id"]
            for rec in map(json.loads, args.log.read_text().splitlines())
            if rec.get("type") == "gen" and rec.get("id")
        }
    )
    out_path = args.log.with_suffix(".gens.json")
    known: dict[str, dict] = json.loads(out_path.read_text()) if out_path.exists() else {}
    known = {k: v for k, v in known.items() if "unresolved" not in v}  # retry the misses
    todo = [i for i in ids if i not in known]
    sem = asyncio.Semaphore(8)

    async def one(gid: str) -> None:
        async with sem:
            data, status, _ = await attribution._stats(gid)
        known[gid] = {k: data.get(k) for k in KEEP} if data else {"unresolved": status}

    await asyncio.gather(*(one(g) for g in todo))
    out_path.write_text(json.dumps(known, indent=1))
    bad = [g for g, v in known.items() if "unresolved" in v]
    cost = sum(v.get("total_cost") or 0 for v in known.values())
    print(
        f"{len(ids)} ids, {len(ids) - len(bad)} resolved, {len(bad)} unresolved, total ${cost:.4f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
