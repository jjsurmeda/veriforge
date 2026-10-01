#!/usr/bin/env python3
"""Dump the numbers an eval run produced, read back from `eval_results`.

`evals.gate` prints its own summary but not the per-stage latency
breakdown, and TRD §15's attribution work (P3/L2) needs the per-stage p50s to
start from data rather than from a guess. `make eval-gate-local` drops its
ephemeral database on exit, so this has to run while it still exists.

Read-only; it never writes to the database and never calls a provider.

    DATABASE_URL=... uv run python scripts/eval_dump_stages.py [--run-id UUID]
"""

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from db.models import EvalItem, EvalResult, EvalRun
from db.session import get_session_factory


def p50(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None, help="default: the most recent eval run")
    args = parser.parse_args()

    factory = get_session_factory()
    async with factory() as session:
        run: EvalRun | None
        if args.run_id:
            run = (
                await session.execute(select(EvalRun).where(EvalRun.id == args.run_id))
            ).scalar_one()
        else:
            run = (
                await session.execute(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(1))
            ).scalar_one()
        results = (
            (
                await session.execute(
                    select(EvalResult, EvalItem)
                    .join(EvalItem, EvalItem.id == EvalResult.item_id)
                    .where(EvalResult.eval_run_id == run.id)
                )
            )
            .tuples()
            .all()
        )

    if not results:
        print(json.dumps({"error": "no results for that run"}))
        return

    questions = {item.id: item.question for _, item in results}
    scored = [(r, i) for r, i in results if not r.error]
    errored = [
        {"question": questions.get(r.item_id, "")[:70], "error": (r.error or "")[:300]}
        for r, _ in results
        if r.error
    ]

    stages: dict[str, list[float]] = defaultdict(list)
    for result, _ in scored:
        for name, value in (result.stage_ms or {}).items():
            if isinstance(value, (int, float)):
                stages[name].append(float(value))

    # judge coverage: the post-hoc judge's context_precision/recall on the
    # items it was actually asked about (TRD §15).
    judge_scored = [
        r for r, _ in scored if r.context_recall is not None or r.context_precision is not None
    ]
    faithfulness = [float(r.faithfulness) for r, _ in scored if r.faithfulness is not None]
    latencies = sorted(float(r.latency_ms) for r, _ in scored)
    overheads = [
        float(r.stage_ms["our_overhead_ms"])
        for r, _ in scored
        if r.stage_ms and r.stage_ms.get("our_overhead_ms") is not None
    ]

    out: dict[str, Any] = {
        "eval_run": str(run.id),
        "items": len(results),
        "scored": len(scored),
        "errored": len(errored),
        "errored_items": errored,
        "faithfulness_mean": statistics.mean(faithfulness) if faithfulness else None,
        "faithfulness_p50": p50(faithfulness),
        "judge_coverage": f"{len(judge_scored)}/{len(scored)}",
        "judge_coverage_pct": round(100 * len(judge_scored) / len(scored), 1) if scored else None,
        "p50_latency_ms": p50(latencies),
        "p50_our_overhead_ms": p50(overheads),
        "overhead_items_attributed": len(overheads),
        "stage_p50_ms": {name: p50(values) for name, values in sorted(stages.items())},
        "per_item": sorted(
            [
                {
                    "question": questions.get(r.item_id, "")[:70],
                    "abstained": r.abstained,
                    "faithfulness": r.faithfulness,
                    "context_recall": r.context_recall,
                    "latency_ms": r.latency_ms,
                    "provider_ms": (r.stage_ms or {}).get("provider_ms"),
                    "our_overhead_ms": (r.stage_ms or {}).get("our_overhead_ms"),
                }
                for r, _ in scored
            ],
            key=lambda row: float(row["latency_ms"] or 0),
            reverse=True,
        ),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())