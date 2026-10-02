#!/usr/bin/env python3
"""Dump the numbers an eval run produced, read back from `eval_results`.

`evals.gate` prints its own summary but not the per-stage latency
breakdown, and TRD §15's attribution work (P3/L2) needs the per-stage p50s to
start from data rather than from a guess. `make eval-gate-local` drops its
ephemeral database on exit, so this has to run while it still exists.

It also *exports* the per-item detail to `.data/evals/<timestamp>-<sha>.json`,
because printing it to a terminal is not keeping it: D3 traced a faithfulness
dip to two item ids and could not go further, since the claims and verdicts that
would say *why* were dropped with the database. The export carries the answer,
the extracted claims with their verdicts, the retrieved contexts and
`stage_ms` for every item — the four candidate sources of a run-to-run
faithfulness swing (D4 item 3).

Read-only; it never writes to the database and never calls a provider.

    DATABASE_URL=... uv run python scripts/eval_dump_stages.py [--run-id UUID]
"""

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Run as `python scripts/eval_dump_stages.py`, so sys.path[0] is scripts/ and
# the app packages are not importable without this (acceptance.py does the same).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from db.models import EvalItem, EvalResult, EvalRun
from db.session import get_session_factory

OUT_DIR = Path(__file__).resolve().parents[3] / ".data" / "evals"


def measured_sha() -> str:
    """The commit the run measured.

    Read from git rather than taken on trust, and `unknown` if git is
    unavailable — a file named after the wrong SHA is worse than one named
    after none.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            cwd=Path(__file__).resolve().parents[3],
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else "unknown"


def write_export(payload: str, *, now: datetime | None = None) -> Path:
    """Write the dump to `.data/evals/<timestamp>-<sha>.json`, return the path."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{stamp}-{measured_sha()}.json"
    path.write_text(payload + "\n")
    return path


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
        "p50_total_ms_unattributed_items": p50(
            [
                float(r.latency_ms)
                for r, _ in scored
                if (r.stage_ms or {}).get("generations_unattributed")
            ]
        ),
        "stage_p50_ms": {name: p50(values) for name, values in sorted(stages.items())},
        "unresolved_generation_ids": [
            line
            for r, _ in scored
            for line in ((r.stage_ms or {}).get("unresolved_generation_ids") or [])
        ],
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
                    "generations_attributed": (r.stage_ms or {}).get("generations_attributed"),
                    "generations_unattributed": (r.stage_ms or {}).get("generations_unattributed"),
                    # Item 3: the evidence a faithfulness swing has to be read
                    # against. `claims` are the reviewer's extracted claims and
                    # their verdicts; `contexts` are the retrieved chunks, by
                    # digest. Together with `answer` below they separate the
                    # four candidate sources — different answer, different
                    # extraction, same claim judged differently, different
                    # citation or context.
                    "answer": r.answer,
                    **(r.review_detail or {}),
                }
                for r, _ in scored
            ],
            key=lambda row: float(row["latency_ms"] or 0),
            reverse=True,
        ),
    }
    printed = json.dumps(out, indent=2)
    print(printed)
    # The gate's summary is not the per-item evidence, and the database is about
    # to be dropped, so the whole dump — answers, claims with verdicts,
    # citations, stage_ms — is written out as well as printed. Named for the
    # commit that produced it, because a faithfulness number without the SHA it
    # was measured at cannot be reproduced.
    written = write_export(printed)
    print(f"exported to {written}")


if __name__ == "__main__":
    asyncio.run(main())
