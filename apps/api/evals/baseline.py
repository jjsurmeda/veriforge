"""Write `evals/seed/baseline_fast20.json` from the mean of N run summaries
(owner decision A8, 2026-10-02).

`evals.runner --baseline` writes the fast20 baseline from whichever single run
it has just taken, and D6 took that single run four times: three gave a
faithfulness spread of 0.0250 and the fourth broke it at 0.05625, so the
baseline written from the median of the first three — 0.98333, sitting 0.039
above the worst run — failed the gate on the very next run. A median of three
does not drift like that by accident: it *selects* the favourable subset. The
mean of N is the same statistic for every run in the set, so it cannot select,
and recording every run's faithfulness in the file makes the spread auditable
from the file rather than inferred from the report that wrote it.

So the baseline is written from summaries already on disk, never from a run in
flight:

    uv run python -m evals.gate                       # one run; records its summary
    uv run python -m evals.baseline .data/evals/summary-*.json

`evals.gate` records a summary on every run for exactly that reason. The
per-item evidence `scripts/eval_dump_stages.py` writes beside it is what says
*which* items moved; this file is what the gate compares against.
"""

import argparse
import json
import statistics
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.runner import BASELINE_FAST20_FILE

# Where `evals.gate` records each run's summary. Gitignored, like the
# per-item export next to it. `summary-` distinguishes these from
# `eval_dump_stages.py`'s `<timestamp>-<sha>.json` files.
SUMMARY_DIR = Path(__file__).resolve().parents[3] / ".data" / "evals"

# The metrics averaged, per metric, across the runs. Every numeric key
# `evals.runner.aggregate` emits except the four keys in INVARIANT_KEYS, which
# are recorded as they are: a mean over two different item sets is not a
# measurement of anything, so those runs are refused instead of averaged.
MEAN_METRICS: tuple[str, ...] = (
    "faithfulness",
    "context_recall",
    "abstention_accuracy",
    "answer_rate",
    "should_abstain_correct",
    "answerable_answered",
    "p50_latency_ms",
    "p50_our_overhead_ms",
    "overhead_items_attributed",
    "p50_total_ms_unattributed_items",
    "failed",
)

# Must be identical in every run, or the mean is a number over nothing. The two
# totals are the denominators the gate compares item counts against (P9), and
# `items`/`scored` say how much of the subset each run actually measured — a
# run that lost an item has nothing to contribute to a mean of five.
INVARIANT_KEYS: tuple[str, ...] = (
    "should_abstain_total",
    "answerable_total",
    "items",
    "scored",
)


def record(summary: Mapping[str, Any], *, now: datetime | None = None) -> Path:
    """Write one run's summary where `mean_baseline` can find it later.

    Returns the path. Read-only with respect to the run: the summary is
    already in memory, and the database it came from is dropped when
    `eval_gate_local.sh` exits.
    """
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    path = SUMMARY_DIR / f"summary-{stamp}.json"
    path.write_text(json.dumps(dict(summary), indent=2) + "\n", encoding="utf-8")
    return path


def mean_baseline(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The fast20 baseline as the per-metric mean of N run summaries.

    Refuses rather than guesses. Two things it will not average over: runs
    that used different models, and runs that graded different item sets. Both
    are the failure `evals.gate.compare_models` and `_totals_gate` already
    refuse to compare — a mean over them would be a number that reads like a
    measurement and is not one, and unlike a comparison failure it would then
    be *stored* and every later run compared against it.

    A metric no run recorded stays `None`, matching `aggregate`: a null is "not
    measured", never a zero. A metric only *some* runs recorded is a refusal,
    because the runs did not measure the same thing.
    """
    if len(summaries) < 2:
        raise ValueError(
            f"a baseline is the mean of at least 2 runs; got {len(summaries)}. One run is "
            "not a mean, it is that run — which is what D6 wrote (0.98333, the median of "
            "three) and what the fourth run then failed at 0.94375."
        )
    first = summaries[0]
    models = first.get("models")
    if models is None:
        raise ValueError(
            "run 1 records no `models`, so the gate would refuse to compare against the "
            "baseline this would write (evals.gate.compare_models)"
        )

    for index, summary in enumerate(summaries[1:], start=2):
        if summary.get("models") != models:
            raise ValueError(
                f"run {index} ran with different models ({summary.get('models')!r} against "
                f"{models!r} in run 1). A faithfulness or latency number from one model says "
                "nothing about the same number from another, so their mean is not a "
                "measurement of either. Re-measure every run on one set of models."
            )
    for key in INVARIANT_KEYS:
        expected = first.get(key)
        if expected is None:
            raise ValueError(
                f"run 1 records no `{key}`, so the runs cannot be shown to have graded the "
                "same items and averaging them would compare two different measurements"
            )
        for index, summary in enumerate(summaries[1:], start=2):
            if summary.get(key) != expected:
                raise ValueError(
                    f"`{key}` differs: run {index} graded {summary.get(key)!r} and run 1 "
                    f"graded {expected!r}. The item set changed between the runs, so the mean "
                    "is not a measurement of the subset. Re-measure them all on one subset."
                )
    # Written, not merely checked: the item counts the gate compares are bare
    # numbers, and these are their denominators. A baseline that refuses the
    # comparison but records no totals is the file D6 was stuck with — the gate
    # warns "baseline records no should_abstain_total" on every run and cannot
    # verify the metric at all.
    invariants = {key: float(first[key]) for key in INVARIANT_KEYS}

    means: dict[str, Any] = {}
    for key in MEAN_METRICS:
        values = [summary.get(key) for summary in summaries]
        present = [value for value in values if value is not None]
        if not present:
            means[key] = None
            continue
        if len(present) != len(values):
            missing = ", ".join(str(i) for i, value in enumerate(values, start=1) if value is None)
            raise ValueError(
                f"`{key}` is missing from run(s) {missing} and recorded by the rest, so the "
                "runs did not measure the same thing; the mean of the ones that did would not "
                "be a mean of the metric"
            )
        means[key] = float(statistics.mean(present))

    faithfulnesss: list[float | None] = [
        float(summary["faithfulness"]) if summary.get("faithfulness") is not None else None
        for summary in summaries
    ]
    measured = [value for value in faithfulnesss if value is not None]
    baseline: dict[str, Any] = {
        "models": models,
        **invariants,
        **means,
        # The audit record (A8): how many runs the file is a mean of, and every
        # one's faithfulness. The gate cannot see these — it reads the mean —
        # so without them the spread this baseline was written to accommodate is
        # a claim in a commit body and nowhere else.
        "runs": len(summaries),
        "faithfulness_runs": faithfulnesss,
    }
    if measured:
        baseline["faithfulness_spread"] = max(measured) - min(measured)
    return baseline


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the fast20 baseline from N run summaries")
    parser.add_argument(
        "summaries", nargs="+", type=Path, help="summary files, as recorded by `evals.gate`"
    )
    parser.add_argument("--out", type=Path, default=BASELINE_FAST20_FILE)
    args = parser.parse_args(argv)

    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in args.summaries]
    try:
        baseline = mean_baseline(summaries)
    except ValueError as exc:
        # Exit 1 with the reason and nothing written: a half-written or
        # guessed baseline is the outcome this whole module exists to prevent.
        print(f"baseline not written: {exc}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out} written as the mean of {baseline['runs']} runs:")
    print(json.dumps(baseline, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
