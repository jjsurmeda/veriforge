"""The gate may judge a retry's mean of 3 runs; it must never judge a lucky run
(owner decision, 2026-10-02, D8 item 4).

One fast20 run is a single draw from a distribution wider than the gate's own
limits: four serial runs on the unchanged D6 tree (`ed1ea59`) spread 0.05625 of
faithfulness against a 0.06 tolerance, and D7's local-plus-CI set spread 0.09167
across two machines. So a single draw fails the gate about as often as its
tolerance says it should, and for no other reason. What a merge gate has to
distinguish is "this run was unlucky" from "this change made the product worse".

The retry separates them by taking the mean of three runs. The mean is the same
statistic for all three, which is exactly what a median of three is not — a
median *selects*, and selects the favourable subset, which is how D6 wrote a
baseline (0.98333) that its own fourth run then failed at 0.94375.

The properties worth pinning:

* **a first-run pass costs one run.** The retry is not a standing cost on a
  healthy tree; if it were, every merge would pay three live runs forever.
* **the judged number is the mean, and every run is reported.** A retry that
  rescued a merge has to be *visible* as a retry. A gate that silently accepted
  the first passing draw would be indistinguishable from a gate with no retry at
  all, and would hide exactly the flapping that motivated it.
* **the floor is applied to the mean**, not to each run and not to the best run.
  That is the whole defence of the decision: the 0.06 tolerance is for
  run-to-run variance, and the absolute 0.90 floor (PRD v3 §5) is the product
  bar. A retry that could rescue a mean of 0.89 would have turned a variance
  allowance into permission for quality to fall.
* **the per-metric limits do not move.** 0.06, 0.90, 2 items and 1.35x are the
  same numbers as before the retry.
"""

import asyncio
import io
import json
import math
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals import gate as gate_module
from evals.baseline import AGGREGATE_METRICS
from evals.gate import (
    FAITHFULNESS_DROP,
    FAITHFULNESS_FLOOR,
    GATE_ATTEMPTS,
    ITEM_FLIP_LIMIT,
    OVERHEAD_RISE_FACTOR,
    _mean_of,
)

MODELS = {"generator": "gpt-4o-mini", "small": "claude-haiku"}


def run(
    *,
    faithfulness: float = 0.97556,
    p50_our_overhead_ms: float = 2565.3,
    should_abstain_correct: float = 7.0,
    answerable_answered: float = 11.0,
    failed: float = 0.0,
    unattributed: float | None = None,
) -> dict[str, float | None]:
    """One run's `aggregate` output, shaped as the fast20 subset produces it.

    20 items, 8 of which should abstain and 12 of which are answerable, every
    latency attributed — the committed baseline's own shape. `unattributed` is
    left null because that is what `aggregate` reports when no call could be
    attributed, and the mean must preserve the null rather than zero it.
    """
    return {
        "faithfulness": faithfulness,
        "context_recall": 0.9,
        "abstention_accuracy": 0.875,
        "answer_rate": 0.9166666666666666,
        "should_abstain_correct": should_abstain_correct,
        "answerable_answered": answerable_answered,
        "should_abstain_total": 8.0,
        "answerable_total": 12.0,
        "min_support_share": 0.95,
        "answers_with_min_support": 12.0,
        "answers_total": 12.0,
        "false_abstention_rate": 0.0,
        "confident_wrong_answers": 0.0,
        "clean_declines": 7.0,
        "unclean_declines": 1.0,
        "should_abstain_item_runs": 8.0,
        "p50_latency_ms": 8856.8,
        "p50_our_overhead_ms": p50_our_overhead_ms,
        "overhead_items_attributed": 20.0,
        "p50_total_ms_unattributed_items": unattributed,
        "items": 20.0,
        "scored": 20.0,
        "failed": failed,
    }


BASELINE: dict[str, Any] = {**run(), "models": MODELS}  # the committed baseline's shape
# The same baseline without `models`, for the tests that call `check`/`compare`
# directly: those take the numeric mapping, and `models` is a nested dict.
NUMERIC: dict[str, float | None] = {k: v for k, v in run().items()}


@dataclass
class GateResult:
    """What one scripted `evals.gate.main()` did."""

    exit_code: int
    out: str
    err: str
    recorded: list[dict[str, Any]] = field(default_factory=list)

    @property
    def everything(self) -> str:
        return self.out + self.err


# The `gate` fixture's value. Aliased so the test signatures stay under the
# 100-column limit instead of wrapping every one of them.
GateHarness = Callable[..., GateResult]


@pytest.fixture
def gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> GateHarness:
    """Drive `evals.gate.main()` over a scripted sequence of runs.

    Two seams are stubbed, and both are the boundary rather than the decision:
    `run_eval` is the only thing that calls OpenRouter, and `aggregate` is the
    roll-up that reads ORM rows (covered by its own tests, and not what this
    decision is about). Everything that decides — the retry loop, `_mean_of`,
    `compare`, the recording and the exit status — is the real code, so a test
    that says "the gate did this" is saying it about the gate.

    Asking for a run the test did not script is an error, not a stop: that is
    what makes "a first-run pass costs exactly one run" a real assertion rather
    than a comment. And every scripted run's keys are checked against
    `aggregate`'s real key set, so the fixtures here cannot quietly drift away
    from what a real run produces.
    """

    def script(
        runs: list[dict[str, float | None]], baseline: dict[str, Any] | None = None
    ) -> GateResult:
        for index, scripted in enumerate(runs, start=1):
            assert set(scripted) == set(AGGREGATE_METRICS), (
                f"scripted run {index} does not match what `evals.runner.aggregate` "
                f"emits: missing {set(AGGREGATE_METRICS) - set(scripted)}, "
                f"unexpected {set(scripted) - set(AGGREGATE_METRICS)}"
            )
        # The baseline is scriptable because two of the gate's rules only bind on
        # some baselines: with the committed 0.97556 the 0.06 drop threshold sits
        # at 0.91556, *above* the 0.90 floor, so the drop always fires first and a
        # test of the floor against it proves nothing. A10's own words: the floor
        # is what stops a low baseline being validated against itself.
        # Written to a real file rather than patched into `gate_module.json`:
        # monkeypatching a stdlib module through another module's namespace is
        # not something mypy can see, and a test harness should not need that.
        stored = dict(BASELINE if baseline is None else baseline)
        baseline_file = tmp_path / "baseline_fast20.json"
        baseline_file.write_text(json.dumps(stored), encoding="utf-8")

        queue = list(runs)
        calls = {"n": 0}
        recorded: list[dict[str, Any]] = []

        async def fake_run_eval(**_kwargs: Any) -> tuple[Any, list[Any]]:
            index = calls["n"]
            if index >= len(queue):
                raise AssertionError(
                    f"the gate asked for run {index + 1} but the test scripted only "
                    f"{len(queue)}: the retry ran more times than it should"
                )
            calls["n"] += 1
            return SimpleNamespace(id=f"run-{index + 1}"), []

        def fake_aggregate(_results: list[Any]) -> dict[str, float | None]:
            return dict(queue[calls["n"] - 1])

        def fake_record(summary: dict[str, Any]) -> Path:
            recorded.append(summary)
            return Path(f"/tmp/summary-{len(recorded)}.json")

        monkeypatch.setattr(gate_module, "run_eval", fake_run_eval)
        monkeypatch.setattr(gate_module, "aggregate", fake_aggregate)
        monkeypatch.setattr(gate_module, "record_summary", fake_record)
        monkeypatch.setattr(gate_module, "models_on_record", lambda: MODELS)
        # `main` returns early unless the seed corpus is loaded, and reads the
        # baseline off disk; neither exists on a test machine.
        monkeypatch.setattr(gate_module, "STATE_FILE", Path(__file__))
        monkeypatch.setattr(gate_module, "BASELINE_FAST20_FILE", baseline_file)
        # Only the fast20 gate runs against the scripted queue: with no cf
        # baseline in the tree, `main()` skips the counterfactual gate rather
        # than drawing from the same scripted budget of runs.
        monkeypatch.setattr(gate_module, "BASELINE_CF_GATE_FILE", tmp_path / "no_cf_baseline.json")

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                asyncio.run(gate_module.main())
                exit_code = 0
            except SystemExit as exc:
                exit_code = int(exc.code or 0)

        return GateResult(exit_code, out.getvalue(), err.getvalue(), recorded)

    return script


# --- a first-run pass costs one run ---------------------------------------------


def test_a_first_run_pass_uses_exactly_one_run(gate: GateHarness) -> None:
    """The retry must not become a standing cost on a healthy tree.

    If it were, every merge would pay three live runs forever to guard against a
    failure that fires occasionally. The scripted `fake_run_eval` raises if asked
    for a second run, so a retry that does not short-circuit fails here rather
    than quietly costing money.
    """
    assert gate([run()]).exit_code == 0


def test_a_first_run_pass_is_judged_on_that_run_not_on_a_mean(gate: GateHarness) -> None:
    """Judged on the passing run itself. A mean would change the number a
    healthy merge is recorded against, which is the opposite of stability."""
    result = gate([run()])

    assert "the run that passed" in result.out
    assert "mean of" not in result.out


# --- the mean of three, and every run reported ---------------------------------


def test_the_mean_of_three_rescues_a_merge_that_every_run_failed(gate: GateHarness) -> None:
    """The case only averaging can rescue, and it is the item counts.

    Run 1 misses the faithfulness tolerance (0.90 against a threshold of
    0.91556 — the same 0.06723 drop D7 measured in CI). Runs 2 and 3 clear
    faithfulness comfortably but each lose two should-abstain items, which is
    the limit. No single run passes. The mean does: faithfulness 0.94 (inside
    0.06) and should_abstain_correct 5.67, a drop of 1.33 items, inside the
    two-item limit. Every number is in the output, because a rescued merge that
    looks like a clean pass is the failure mode of the whole mechanism.

    The item counts are the metric this works on, and only on them: averaging
    cannot cross a threshold that every run is already on the same side of. See
    `test_the_retry_cannot_rescue_a_faithfulness_failure` for the case where it
    provably cannot.
    """
    result = gate(
        [
            run(faithfulness=0.90, should_abstain_correct=7.0),
            run(faithfulness=0.96, should_abstain_correct=5.0),
            run(faithfulness=0.96, should_abstain_correct=5.0),
        ]
    )

    assert result.exit_code == 0, (
        "the mean is faithfulness 0.94 (inside 0.06) and 6.33 of 8 abstained "
        "(1.33 items below baseline, inside the 2-item limit)"
    )
    for number in ("0.90", "0.96"):
        assert number in result.everything, f"a run at {number} is not reported anywhere"
    assert "mean of 3" in result.out


def test_the_retry_cannot_rescue_a_faithfulness_failure(gate: GateHarness) -> None:
    """Averaging crosses a threshold only when the runs sit either side of it,
    so the mean is *not* a way under the faithfulness drop.

    If all three runs are below `baseline - 0.06`, their mean is below it too.
    This is a limit of the mechanism, pinned deliberately rather than left for
    someone to assume otherwise: it means the retry's faithfulness benefit comes
    from the two extra *draws*, not from the mean. A gate that averaged
    faithfulness and expected it to rescue failures would be wrong, and the code
    comment next to GATE_ATTEMPTS says so for the same reason.
    """
    result = gate(
        [run(faithfulness=0.905), run(faithfulness=0.905), run(faithfulness=0.905)]
    )

    assert result.exit_code == 1
    assert "faithfulness" in result.err


def test_the_mean_of_three_fails_when_the_mean_fails(gate: GateHarness) -> None:
    """A retry is not an escape hatch. Three bad runs still fail."""
    result = gate([run(faithfulness=0.80), run(faithfulness=0.82), run(faithfulness=0.84)])

    assert result.exit_code == 1


def test_a_first_run_that_passes_is_not_re_run_for_a_better_number(gate: GateHarness) -> None:
    """0.93 is a 0.0456 drop from the 0.97556 baseline — inside the 0.06
    tolerance — so the gate accepts it and stops.

    Asserted because the alternative is spending two more live runs looking for
    a better number than the one already in hand, which is both a standing cost
    on every merge and a way to make the gate flakier in the other direction:
    the more draws it takes, the more often *some* draw passes.
    """
    result = gate([run(faithfulness=0.93)])

    assert result.exit_code == 0
    assert "mean of" not in result.out


def test_every_retry_records_its_own_summary(gate: GateHarness) -> None:
    """A8's mechanism, extended to retries.

    A baseline is the mean of recorded run summaries, so a run has to record
    whether or not anyone is writing a baseline *and* whether or not it passed.
    A retried run that recorded nothing would be invisible to the next baseline
    writer — and retries are exactly the runs worth baselining from.
    """
    result = gate([run(faithfulness=0.90833)] * GATE_ATTEMPTS)

    assert len(result.recorded) == GATE_ATTEMPTS
    for summary in result.recorded:
        assert summary["models"] == MODELS, "a summary without models is one mean_baseline refuses"
        assert "eval_run" in summary
        assert summary["faithfulness"] == 0.90833


def test_a_single_pass_records_exactly_one_summary(gate: GateHarness) -> None:
    """The mirror: a healthy tree records one summary, not GATE_ATTEMPTS of them.
    Otherwise every merge would look like a three-run measurement to the next
    baseline writer."""
    result = gate([run()])

    assert len(result.recorded) == 1


# --- the floor applies to the mean ----------------------------------------------


def test_the_floor_applies_to_the_mean_not_to_each_run(gate: GateHarness) -> None:
    """The whole defence of the decision, in one test.

    Two of the three runs are above the 0.90 floor, so a gate checking the floor
    per run on a majority rule would pass this merge and report 0.895 as
    healthy. The mean is 0.895 — below the bar. PRD v3 §5 ("Faithfulness >= 0.90
    mean per corpus") is about the mean, so that is what the floor is applied to.
    Averaging must not become a way *under* the product bar: the tolerance is for
    variance, the floor is the bar.

    Scripted against a 0.93 baseline deliberately. With the committed 0.97556 the
    drop threshold is 0.91556 — above the floor — so the drop would fire first and
    this test would pass even with the floor deleted. The floor only binds on a
    baseline low enough for it to, which is A10's reason for adding it: "a
    baseline written at 0.93 with a 0.06 tolerance would pass 0.88 forever".
    """
    low_baseline: dict[str, Any] = {**BASELINE, "faithfulness": 0.93}
    result = gate([run(faithfulness=0.895)] * GATE_ATTEMPTS, baseline=low_baseline)

    assert result.exit_code == 1
    assert f"{FAITHFULNESS_FLOOR:.2f}" in result.err, (
        "the failure must name the floor, or a reader cannot tell a quality bar "
        "from a noise allowance"
    )
    assert "mean of 3" in result.err
    # The drop did NOT fire — the floor is the only reason this failed. 0.895 is
    # 0.035 below the 0.93 baseline, well inside 0.06.
    assert "drop >" not in result.err, (
        "this case must isolate the floor; if the drop also fired, the test "
        "cannot tell the two rules apart"
    )


def test_the_floor_is_evaluated_on_the_mean_not_on_each_run() -> None:
    """The rule itself, isolated from the retry loop.

    A mean of 0.89833 from runs at 0.895, 0.895 and 0.905 is below the 0.90 bar,
    even though two of the three runs are above it. Checked directly on `check`
    so the assertion is about the comparison rule and not about how many runs
    happened to be scripted.
    """
    mean = _mean_of(
        [run(faithfulness=0.895), run(faithfulness=0.895), run(faithfulness=0.905)]
    )
    assert mean["faithfulness"] == pytest.approx(0.898333, abs=1e-5)

    failures, _warnings = gate_module.check({**NUMERIC, "faithfulness": 0.93}, mean)

    assert any("below the floor" in failure for failure in failures), (
        f"the floor must be applied to the mean; got {failures}"
    )


def test_a_mean_above_the_floor_passes_even_though_one_run_was_below_it(gate: GateHarness) -> None:
    """The other side of the same boundary: the floor judges the mean.

    0.895 alone is below 0.90 and fails a single-run gate. At 0.93167 the mean is
    above the bar, and the bar is what the mean is measured against. This is the
    difference between "one draw was unlucky" and "the product is below the bar",
    which is the distinction the retry exists to draw.
    """
    result = gate([run(faithfulness=0.895), run(faithfulness=0.95), run(faithfulness=0.95)])

    assert result.exit_code == 0


def test_the_floor_is_not_applied_to_the_best_run(gate: GateHarness) -> None:
    """A gate judging on the *best* of three would pass any regression the other
    two caught. Here the best run is 0.96 and the mean is 0.91; the mean is above
    the floor, so this asserts the fact that matters — the mean decides — and
    `test_the_floor_applies_to_the_mean_not_to_each_run` is the case where
    best-run judging and mean judging disagree the other way."""
    result = gate([run(faithfulness=0.87), run(faithfulness=0.90), run(faithfulness=0.96)])

    assert result.exit_code == 0, "the mean is 0.91, above the floor"


# --- a failure a re-run cannot fix is not retried --------------------------------


def test_a_model_mismatch_is_not_retried(gate: GateHarness) -> None:
    """The retry is for a noisy measurement, not for a configuration decision.

    A baseline recorded with different models is refused outright, and re-running
    fast20 with the same models produces the same refusal — so spending two more
    live runs on it buys nothing and spends money. Only one run is scripted: if the
    gate retried, `fake_run_eval` raises rather than silently costing a run.
    """
    other_models: dict[str, Any] = {
        **BASELINE,
        "models": {"generator": "llama-3.3-70b", "small": "haiku"},
    }
    result = gate([run()], baseline=other_models)

    assert result.exit_code == 1
    assert "different models" in result.err
    assert "no retry" in result.err, (
        "the gate must say it declined to retry, or the single run looks like a "
        "silent short-circuit rather than a decision"
    )


def test_an_item_set_mismatch_is_not_retried(gate: GateHarness) -> None:
    """Same reasoning for the other configuration failure: a run that graded a
    different item set cannot be fixed by running the same subset again."""
    mismatched: dict[str, Any] = {**BASELINE, "answerable_total": 11.0}
    result = gate([run()], baseline=mismatched)

    assert result.exit_code == 1
    assert "no retry" in result.err


def test_a_measurement_failure_is_still_retried(gate: GateHarness) -> None:
    """The mirror, so the previous two tests are not passing because the retry was
    removed: a faithfulness drop *is* retried. Three runs are scripted and the
    first genuinely fails, so the loop has to run."""
    result = gate([run(faithfulness=0.80)] * GATE_ATTEMPTS)

    assert len(result.recorded) == GATE_ATTEMPTS
    assert "no retry" not in result.err


# --- _mean_of, on its own -------------------------------------------------------


def test_the_mean_is_computed_per_metric() -> None:
    """One mean applied to every metric would hide a regression in whichever
    metric the runs happened to agree on. Two runs, so the arithmetic is
    checkable by hand: faithfulness 0.94, answerable_answered 10."""
    mean = _mean_of(
        [
            run(faithfulness=0.90, answerable_answered=11.0),
            run(faithfulness=0.98, answerable_answered=9.0),
        ]
    )

    assert math.isclose(mean["faithfulness"] or 0.0, 0.94, abs_tol=1e-9)
    assert mean["answerable_answered"] == 10.0


def test_a_metric_no_run_recorded_stays_null_not_zero() -> None:
    """`aggregate` uses null for "not measured" and the mean must not turn it
    into a zero. A zeroed unattributed-latency figure would report an instant
    run, and the latency gate would compare against it happily."""
    both_null = _mean_of([run(), run()])
    assert both_null["p50_total_ms_unattributed_items"] is None

    one_null = _mean_of([run(), run(unattributed=4200.0)])
    assert one_null["p50_total_ms_unattributed_items"] == 4200.0, (
        "the runs that did measure it are averaged over, not diluted by the one that did not"
    )


def test_a_fractional_item_count_is_not_truncated_before_comparison() -> None:
    """A mean's item count is not an integer, and truncating it fails a gate the
    mean had cleared.

    `int(5.67)` is 5, so a mean of (7, 5, 5) — 5.67 of 8 items, a drop of 1.33
    — read as `7 - 5 = 2 items flipped` and failed. The error went in the
    direction that fails, and by up to a whole item. This is asserted on `check`
    directly because it is a comparison rule, not a retry rule.
    """
    mean = _mean_of(
        [
            run(should_abstain_correct=7.0),
            run(should_abstain_correct=5.0),
            run(should_abstain_correct=5.0),
        ]
    )
    assert mean["should_abstain_correct"] == pytest.approx(5.6667, abs=1e-3)

    failures, warnings = gate_module.check(NUMERIC, mean)

    assert not failures, f"a 1.33-item drop is inside the 2-item limit, got {failures}"
    assert any("1.33 items flipped" in warning for warning in warnings), (
        "the warning must report the fractional flip, or a reader sees a whole "
        "number for a decision taken on a mean"
    )


def test_a_whole_item_count_still_reads_as_one_item() -> None:
    """The message keeps saying "1 item flipped" for a single run, so the
    existing wording — and the tests that pin it — do not change."""
    _, warnings = gate_module.check(NUMERIC, run(should_abstain_correct=6.0))

    assert any("1 item flipped" in warning for warning in warnings)


def test_an_errored_run_does_not_hide_itself_in_the_mean() -> None:
    """An errored run is not a measurement, and averaging must not let two clean
    runs erase one.

    This is also the case where "the mean of the numbers" and "the mean of the
    verdicts" disagree, which is why it is the per-metric test with teeth: two of
    three runs pass, so a gate that averaged verdicts would report a pass, while
    the mean of `failed` is 1.0 and the gate fails.
    """
    mean = _mean_of([run(failed=0.0), run(failed=0.0), run(failed=3.0)])

    assert mean["failed"] == 1.0
    failures, _warnings = gate_module.check(NUMERIC, mean)
    assert failures, "a mean carrying an errored run must fail the gate"
    assert any("errored" in failure for failure in failures)


# --- the limits do not move -----------------------------------------------------


def test_the_retry_leaves_every_limit_where_it_was() -> None:
    """The decision is "retry, don't widen".

    Asserted so a later edit cannot widen a limit alongside the retry and leave
    the retry looking like the cause. 0.06 from A9, 0.90 from A10, 2 items from
    A7, 1.35x from A6, and three attempts from D8 item 4.
    """
    assert FAITHFULNESS_DROP == 0.06
    assert FAITHFULNESS_FLOOR == 0.90
    assert ITEM_FLIP_LIMIT == 2
    assert OVERHEAD_RISE_FACTOR == 1.35
    assert GATE_ATTEMPTS == 3


def test_the_retry_applies_locally_as_well_as_in_ci(gate: GateHarness) -> None:
    """`make eval-gate-local` calls `evals.gate` exactly as ci.yml does, so the
    retry is in both without a second implementation.

    Asserted on the call site rather than the workflow, because that is the fact
    that matters: the local script runs this module, so a local gate run gets the
    same three-run verdict as CI rather than a stricter single-run one.
    """
    script = (Path(__file__).resolve().parents[4] / "scripts" / "eval_gate_local.sh").read_text()

    assert "evals.gate" in script
    assert "GATE_ATTEMPTS" not in script, (
        "eval_gate_local.sh reimplements the retry; it should call evals.gate and "
        "inherit the same rule"
    )