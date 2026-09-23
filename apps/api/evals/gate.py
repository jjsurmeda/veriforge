"""Eval gate (TRD §15): run the 20-item fast subset and compare with the
stored baseline. Fails (exit 1) when faithfulness drops by more than 0.03,
abstention accuracy drops by more than 5 points, or p50 latency rises by
more than 20%.

Slice 6: the comparison is like-for-like — `baseline_fast20.json`
(written by `evals.runner --baseline` alongside the full-50
`baseline.json`) baselines the same subset the gate runs. The previous
full-50-vs-fast20 comparison failed on sampling noise: with ~6 abstain
items in the subset, abstention accuracy swings ±25 points between runs.

Usage: uv run python -m evals.gate
"""

import asyncio
import json
import sys

from evals.loader import STATE_FILE
from evals.runner import BASELINE_FAST20_FILE, BASELINE_FILE, aggregate, run_eval

FAITHFULNESS_DROP = 0.03
ABSTENTION_DROP_POINTS = 5.0
LATENCY_RISE_FACTOR = 1.20


def compare(baseline: dict[str, float | None], current: dict[str, float | None]) -> list[str]:
    failures: list[str] = []
    base_f, curr_f = baseline.get("faithfulness"), current.get("faithfulness")
    if base_f is not None and curr_f is not None and curr_f < base_f - FAITHFULNESS_DROP:
        failures.append(f"faithfulness {base_f:.3f} → {curr_f:.3f} (drop > {FAITHFULNESS_DROP})")
    base_a, curr_a = baseline.get("abstention_accuracy"), current.get("abstention_accuracy")
    if (
        base_a is not None
        and curr_a is not None
        and curr_a < base_a - ABSTENTION_DROP_POINTS / 100
    ):
        failures.append(
            f"abstention accuracy {base_a:.2%} → {curr_a:.2%} (drop > {ABSTENTION_DROP_POINTS} pts)"
        )
    base_p50, curr_p50 = baseline.get("p50_latency_ms"), current.get("p50_latency_ms")
    if base_p50 and curr_p50 and curr_p50 > base_p50 * LATENCY_RISE_FACTOR:
        failures.append(f"p50 latency {base_p50:.0f} → {curr_p50:.0f} ms (rise > 20%)")
    return failures


async def main() -> None:
    if not STATE_FILE.exists():
        print("eval gate skipped: seed corpus not loaded (run evals.loader first)")
        return
    baseline_path = BASELINE_FAST20_FILE
    if not baseline_path.exists():
        baseline_path = BASELINE_FILE
    if not baseline_path.exists():
        print("eval gate skipped: no baseline (run evals.runner --baseline first)")
        return
    baseline = json.loads(baseline_path.read_text())
    _, results = await run_eval(subset="fast20", baseline=False)
    current = aggregate(results)
    failures = compare(baseline, current)
    print(
        json.dumps(
            {"baseline_file": baseline_path.name, "baseline": baseline, "current": current},
            indent=2,
        )
    )
    if failures:
        for failure in failures:
            print(f"GATE FAIL: {failure}", file=sys.stderr)
        sys.exit(1)
    print("eval gate passed")


if __name__ == "__main__":
    asyncio.run(main())
