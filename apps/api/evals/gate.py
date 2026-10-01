"""Eval gate (TRD §15): run the 20-item fast subset and compare with the
stored baseline. Fails (exit 1) when faithfulness drops by more than 0.03,
the count of items classified correctly drops by 2 or more, or the gated
latency rises by more than its factor.

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
# Owner decision A6 (2026-10-02, KI-6/A6): the gated overhead key gets its
# own, wider factor than the total-latency fallback. Evidence: three
# consecutive fast20 runs measured p50_our_overhead_ms 2317 / 2533 / 2848 ms
# on an unchanged commit, so run-to-run spread is already +22.9% — wider
# than the 20% this gate used to allow, which means the gate flapped on
# measurement noise and a confirmation run at +22.9% FAILED on nothing but
# variance. 1.35 puts the bar outside that spread without touching the
# fallback below.
#
# RESET AT P3 EXIT (owner decision, 2026-10-02): re-measure >= 5 fast20 runs
# after P3's latency work and set this factor to max(1.20, 1 + 2 * spread),
# where `spread` is the observed run-to-run spread of p50_our_overhead_ms.
# The point of P3 is to move the number down; the widening is buying the gate
# back its authority, not lowering the bar permanently.
OVERHEAD_RISE_FACTOR = 1.35
# The fallback keeps 1.20: it is the pre-KI-18 behaviour, reached only when
# neither run attributed a call at all, so it is a floor that stops the check
# being silently disabled rather than a measured tolerance.
LATENCY_RISE_FACTOR = 1.20
# Owner decision A7 (2026-10-02, KI-6/A7): abstention accuracy and answer
# rate are compared as item counts, not percentage points. Evidence: fast20
# holds 8 should-abstain items and 12 answerable items, so ONE item flipping
# moves the two rates by 12.5 and 8.3 points respectively — each more than
# twice the 5-point tolerance the gate used to apply. A single item flip was
# failing the gate on noise. One flip is now a warning and passes; two flips
# are a regression worth stopping a merge for.
#
# RESET AT P1b (owner decision, 2026-10-02): these item-based limits are
# replaced once P1b adds per-corpus resolution, because more items per corpus
# makes percentage points meaningful again (the failure below re-appears once
# a rate moves by less than one item).
ITEM_FLIP_LIMIT = 2


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
    """The gate's failures. `notes` reports the same run's warnings; both walk
    the same checks, so the two can never disagree about what was measured."""
    failures, _warnings = check(baseline, current)
    return failures


def notes(baseline: dict[str, float | None], current: dict[str, float | None]) -> list[str]:
    """What the gate saw that is worth saying out loud but must not fail a
    merge: a single item flip (A7) and any metric it could not verify."""
    _failures, warnings = check(baseline, current)
    return warnings


def _item_gate(
    baseline: Mapping[str, float | None],
    current: Mapping[str, float | None],
    *,
    count_key: str,
    label: str,
    failures: list[str],
    warnings: list[str],
) -> None:
    """Compare one classification metric by *item count*, not by percentage
    points (A7).

    What a flip means here: `count_key` is the number of items the run put in
    the correct bucket — should-abstain items that abstained, or answerable
    items that answered. It is a count over a fixed set of items, so it moves
    in whole items and one item is the smallest change the metric can express.
    Comparing the counts means the gate fires on "two more items landed in the
    wrong bucket than before", which is a property of the run; comparing the
    rates instead means the same fact reads as "12.5 points", which on 8 items
    is one coin toss.

    Direction matters: only a drop is a regression. A run that classifies *more*
    items correctly than the baseline improves the metric and must never fail,
    so the test is a drop of `ITEM_FLIP_LIMIT` or more and an improvement is
    below it.

    A baseline written before these counts existed records the rate and not the
    count. That is unverifiable rather than passing: the rate's denominator is
    not in the file, so the number of flipped items cannot be recovered from it
    by any honest arithmetic. It is reported as a warning, never as a failure,
    because an old baseline is not a regression.
    """
    base_count, curr_count = baseline.get(count_key), current.get(count_key)
    if base_count is None or curr_count is None:
        warnings.append(
            f"{label}: the baseline records no `{count_key}`, so an item flip cannot be "
            "counted and this metric is UNVERIFIED rather than passing. Rewrite the "
            "baseline with `python -m evals.runner --subset fast20 --baseline`."
        )
        return
    drop = int(base_count) - int(curr_count)
    detail = f"{label} {base_count:.0f} → {curr_count:.0f} items correct"
    if drop >= ITEM_FLIP_LIMIT:
        failures.append(f"{detail} ({drop} items flipped, limit {ITEM_FLIP_LIMIT})")
    elif drop == 1:
        warnings.append(
            f"{detail}: 1 item flipped. On a 20-item subset one flip is measurement "
            f"noise, so this passes and is reported (limit is {ITEM_FLIP_LIMIT})."
        )


def check(
    baseline: dict[str, float | None], current: dict[str, float | None]
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
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
    # A should-abstain item that stopped abstaining is a flip; so is an
    # answerable item that started abstaining, and that one shows up here as a
    # rise in `answered`. Both are counted as the same failure — the gate does
    # not care which direction the item moved, only that the number of items
    # classified correctly fell.
    _item_gate(
        baseline,
        current,
        count_key="should_abstain_correct",
        label="abstention accuracy",
        failures=failures,
        warnings=warnings,
    )
    # An abstention scores faithfulness 1.0, so a pipeline that abstained on
    # everything beats both metrics above. Answer rate is the counterweight:
    # it can only fall when answerable items stop being answered (TRD §15).
    # Gate it on its own count, independently of abstention: a run cannot pay
    # for a fall in one by gaining in the other.
    _item_gate(
        baseline,
        current,
        count_key="answerable_answered",
        label="answer rate",
        failures=failures,
        warnings=warnings,
    )
    # KI-18: gate on latency we introduced, not the provider's. OpenRouter's
    # share varies by seconds between runs and is not something this repo can
    # regress, so only the attributed remainder is strictly gated. The total is
    # still reported above; it only fails the gate when no run could be
    # attributed at all, which is the pre-KI-18 behaviour.
    # The key and its factor are chosen together, so the factor always belongs
    # to the figure it is applied to and the failure can name which.
    if (
        baseline.get("p50_our_overhead_ms") is not None
        and current.get("p50_our_overhead_ms") is not None
    ):
        gate_key, factor = "p50_our_overhead_ms", OVERHEAD_RISE_FACTOR
    else:
        gate_key, factor = "p50_latency_ms", LATENCY_RISE_FACTOR
    base_p50, curr_p50 = baseline.get(gate_key), current.get(gate_key)
    if base_p50 and curr_p50 and curr_p50 > base_p50 * factor:
        failures.append(
            f"{gate_key} {base_p50:.0f} → {curr_p50:.0f} ms "
            f"(rise > {factor:.2f}x = {factor - 1:.0%})"
        )
    return failures, warnings


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
    for warning in notes(baseline, current):
        print(f"GATE WARN: {warning}", file=sys.stderr)
    if failures:
        for failure in failures:
            print(f"GATE FAIL: {failure}", file=sys.stderr)
        sys.exit(1)
    print("eval gate passed")


if __name__ == "__main__":
    asyncio.run(main())
