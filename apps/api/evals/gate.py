"""Eval gate (TRD §15): run the 20-item fast subset and compare with the
stored baseline. Fails (exit 1) when faithfulness drops by more than 0.03,
abstention accuracy or answer rate drops by more than 5 points, or p50
*our* latency rises by more than 20%.

Since KI-18 the gated latency is `p50_our_overhead_ms` — wall clock minus the
generation time OpenRouter reports for the same calls — because a slow
provider is not a regression in this repo. The total is still reported; see
TRD §15 for the full rule and the fallback when nothing could be attributed.

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
from collections.abc import Mapping

from evals.loader import STATE_FILE
from evals.runner import (
    BASELINE_FAST20_FILE,
    BASELINE_FILE,
    aggregate,
    models_on_record,
    run_eval,
)

FAITHFULNESS_DROP = 0.03
ABSTENTION_DROP_POINTS = 5.0
ANSWER_RATE_DROP_POINTS = 5.0
LATENCY_RISE_FACTOR = 1.20


def compare_models(
    baseline: Mapping[str, object], current: Mapping[str, object]
) -> list[str]:
    """Refuse to compare runs that did not use the same models.

    A faithfulness or latency number from gpt-4o-mini says nothing about the
    same number from Haiku. Comparing them would either invent a regression
    (the cheaper, noisier model scores worse) or hide a real one, and the
    difference is invisible in the output: the rows line up, only the models
    moved. So this is checked before the metrics, and a baseline with no
    `models` key at all is named too rather than quietly accepted.
    """
    base = baseline.get("models")
    curr = current.get("models")
    if base == curr:
        return []
    if base is None:
        return [
            "the baseline records no models, so this comparison cannot be trusted; "
            "rewrite it with `python -m evals.runner --subset fast20 --baseline`"
        ]
    if curr is None:
        return ["this run records no models, so it cannot be compared with the baseline"]
    # Both are the {role: model} mapping `models_on_record` writes; anything
    # else in the baseline file is not a role record.
    base_roles = base if isinstance(base, dict) else {}
    curr_roles = curr if isinstance(curr, dict) else {}
    differing = sorted(
        role
        for role in set(base_roles) | set(curr_roles)
        if base_roles.get(role) != curr_roles.get(role)
    )
    detail = ", ".join(
        f"{role}: {base_roles.get(role)!r} -> {curr_roles.get(role)!r}" for role in differing
    )
    return [
        f"the baseline was measured with different models ({detail}); a faithfulness "
        "or latency number is not comparable across models, so the gate does not "
        "compare them. Re-measure and rewrite the baseline on the current models."
    ]


def compare(baseline: dict[str, float | None], current: dict[str, float | None]) -> list[str]:
    failures: list[str] = []
    # An item that raised produced no measurement, so a run that lost items
    # says nothing about the three metrics below. Fail it rather than compare
    # a partial run against a full baseline.
    failed = current.get("failed") or 0.0
    scored = current.get("scored") or 0.0
    if failed:
        failures.append(
            f"{failed:.0f} of {failed + scored:.0f} items errored "
            "(an errored run is not a measurement)"
        )
    base_f, curr_f = baseline.get("faithfulness"), current.get("faithfulness")
    if base_f is not None and curr_f is not None and curr_f < base_f - FAITHFULNESS_DROP:
        failures.append(f"faithfulness {base_f:.3f} → {curr_f:.3f} (drop > {FAITHFULNESS_DROP})")
    base_a, curr_a = baseline.get("abstention_accuracy"), current.get("abstention_accuracy")
    if base_a is not None and curr_a is not None and curr_a < base_a - ABSTENTION_DROP_POINTS / 100:
        failures.append(
            f"abstention accuracy {base_a:.2%} → {curr_a:.2%} (drop > {ABSTENTION_DROP_POINTS} pts)"
        )
    # An abstention scores faithfulness 1.0, so a pipeline that abstained on
    # everything beats both metrics above. Answer rate is the counterweight:
    # it can only fall when answerable items stop being answered (TRD §15).
    base_r, curr_r = baseline.get("answer_rate"), current.get("answer_rate")
    if (
        base_r is not None
        and curr_r is not None
        and curr_r < base_r - ANSWER_RATE_DROP_POINTS / 100
    ):
        failures.append(
            f"answer rate {base_r:.2%} → {curr_r:.2%} (drop > {ANSWER_RATE_DROP_POINTS} pts)"
        )
    base_p50, curr_p50 = baseline.get("p50_latency_ms"), current.get("p50_latency_ms")
    # KI-18: gate on latency we introduced, not the provider's. OpenRouter's
    # share varies by seconds between runs and is not something this repo can
    # regress, so only the attributed remainder is strictly gated. The total is
    # still reported above; it only fails the gate when no run could be
    # attributed at all, which is the pre-KI-18 behaviour.
    gate_key = (
        "p50_our_overhead_ms"
        if baseline.get("p50_our_overhead_ms") is not None
        and current.get("p50_our_overhead_ms") is not None
        else "p50_latency_ms"
    )
    base_p50, curr_p50 = baseline.get(gate_key), current.get(gate_key)
    if base_p50 and curr_p50 and curr_p50 > base_p50 * LATENCY_RISE_FACTOR:
        failures.append(f"{gate_key} {base_p50:.0f} → {curr_p50:.0f} ms (rise > 20%)")
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
    # The metric rows and the model record are kept apart so `compare` keeps its
    # numeric signature; only `compare_models` sees the mixed shape.
    failures = compare_models(baseline, {"models": models_on_record(), **current}) + compare(
        baseline, current
    )
    print(
        json.dumps(
            {
                "baseline_file": baseline_path.name,
                "models": models_on_record(),
                "baseline": baseline,
                "current": current,
            },
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
