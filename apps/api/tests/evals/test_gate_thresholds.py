"""The gate's two widened limits (owner decisions A6 and A7, 2026-10-02).

Both changes came from the same measurement: the fast20 gate was failing on
run-to-run noise rather than on anything the product did. A6 widens the
overhead factor from 1.20 to 1.35 because measured run-to-run spread of
`p50_our_overhead_ms` is +22.9%; A7 compares abstention accuracy and answer
rate as item counts because fast20 holds 8 should-abstain and 12 answerable
items, so one flip is 12.5 and 8.3 percentage points against a 5-point
tolerance. See `evals.gate`, TRD §15 and KI-6.

The comments in `evals.gate` claim two things that a reader should be able to
check directly, and most of this file is that check: the factor applied to the
gated figure is the one named in the message, and *one* item flip passes while
*two* fail. A gate that cannot be shown to hold that line is a gate nobody
should trust to have been widened honestly.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from db.models import EvalItem, EvalResult
from evals import gate
from evals.gate import (
    ITEM_FLIP_LIMIT,
    LATENCY_RISE_FACTOR,
    OVERHEAD_RISE_FACTOR,
    compare,
    compare_models,
    notes,
)
from evals.runner import aggregate, models_on_record

# The D4 fast20 baseline's faithfulness, as a float so the arithmetic in the
# faithfulness tests below is typed.
FAITHFULNESS = 0.9683333333333334

# What `--baseline` writes for a 20-item fast20 run: 8 should-abstain items
# with 7 correctly abstaining, 12 answerable items with 11 answered.
# Those are the D4 baseline's rates (0.875 and 0.9167) over the item counts
# the subset actually contains.
FAST20_BASELINE: dict[str, float | None] = {
    "faithfulness": FAITHFULNESS,
    "abstention_accuracy": 0.875,
    "answer_rate": 0.9166666666666666,
    "should_abstain_correct": 7.0,
    "answerable_answered": 11.0,
    "p50_latency_ms": 8548.5,
    "p50_our_overhead_ms": 2317.5,
    "items": 20.0,
    "scored": 20.0,
    "failed": 0.0,
}


def _run(**over: Any) -> dict[str, float | None]:
    current = dict(FAST20_BASELINE)
    current.update(over)
    return current


# The baseline file also carries `models`, which `compare_models` reads and the
# numeric comparison does not.
def _file() -> dict[str, Any]:
    return {"models": models_on_record(), **FAST20_BASELINE}


def _item(*, should_abstain: bool) -> EvalItem:
    return EvalItem(
        id=uuid4(),
        dataset_id=uuid4(),
        category="lookup",
        question="q",
        reference_answer="a",
        should_abstain=should_abstain,
    )


def _scored_result(*, abstained: bool, overhead_ms: float = 2317.5) -> EvalResult:
    return EvalResult(
        eval_run_id=uuid4(),
        item_id=uuid4(),
        answer="a",
        faithfulness=1.0,
        abstained=abstained,
        latency_ms=8548,
        stage_ms={"our_overhead_ms": overhead_ms},
    )


# --- A6: the overhead factor is 1.35, and the total fallback is still 1.20 ---


def test_the_overhead_factor_is_1_35() -> None:
    """Named here as well as in the message so a reader can see the constant
    and not only its formatting."""
    assert OVERHEAD_RISE_FACTOR == 1.35
    assert LATENCY_RISE_FACTOR == 1.20


def test_a_thirty_percent_overhead_rise_passes() -> None:
    """Inside the widened factor, and inside nothing else it needs to be."""
    assert compare(FAST20_BASELINE, _run(p50_our_overhead_ms=2317.5 * 1.30)) == []


def test_a_forty_percent_overhead_rise_fails() -> None:
    failures = compare(FAST20_BASELINE, _run(p50_our_overhead_ms=2317.5 * 1.40))
    assert len(failures) == 1 and "p50_our_overhead_ms" in failures[0]


def test_the_overhead_failure_names_the_factor_it_applied() -> None:
    """The old message hardcoded "20%", which was wrong twice over once the
    factors diverged: it named a limit the gate does not apply, and it did not
    say which figure it was talking about."""
    failures = compare(FAST20_BASELINE, _run(p50_our_overhead_ms=2317.5 * 1.40))
    assert "1.35" in failures[0]
    assert "35%" in failures[0]
    assert "20%" not in failures[0]
    assert "1.20" not in failures[0]


def test_the_total_fallback_keeps_the_tighter_factor() -> None:
    """+25% on total latency fails: 1.25 is past 1.20 and well inside 1.35, so
    this is the assertion that the wider factor did not leak onto the key it
    was not written for."""
    baseline = {k: v for k, v in FAST20_BASELINE.items() if k != "p50_our_overhead_ms"}
    current = _run(p50_our_overhead_ms=None, p50_latency_ms=8548.5 * 1.25)
    failures = compare(baseline, current)
    assert len(failures) == 1 and "p50_latency_ms" in failures[0]
    assert "1.20" in failures[0]


def test_the_total_fallback_passes_a_twenty_percent_total_rise() -> None:
    baseline = {k: v for k, v in FAST20_BASELINE.items() if k != "p50_our_overhead_ms"}
    assert compare(baseline, _run(p50_our_overhead_ms=None, p50_latency_ms=8548.5 * 1.19)) == []


# --- A7: item counts, one flip warns, two flips fail -----------------------


def test_one_abstained_item_flipping_passes_with_a_warning() -> None:
    """7 of 8 correct down to 6 is 12.5 percentage points — twice the old
    5-point tolerance — and it is one item."""
    current = _run(should_abstain_correct=6.0, abstention_accuracy=0.75)
    assert compare(FAST20_BASELINE, current) == []
    warnings = notes(FAST20_BASELINE, current)
    assert any("abstention accuracy" in w and "1 item flipped" in w for w in warnings)


def test_two_abstained_items_flipping_fails() -> None:
    current = _run(should_abstain_correct=5.0, abstention_accuracy=0.625)
    failures = compare(FAST20_BASELINE, current)
    assert len(failures) == 1 and "abstention accuracy" in failures[0]
    assert f"{ITEM_FLIP_LIMIT} items flipped" in failures[0]


def test_one_answered_item_disappearing_passes_with_a_warning() -> None:
    """11 of 12 answered down to 10 is 8.3 points — past the old 5-point
    tolerance, from a single item."""
    current = _run(answerable_answered=10.0, answer_rate=10 / 12)
    assert compare(FAST20_BASELINE, current) == []
    warnings = notes(FAST20_BASELINE, current)
    assert any("answer rate" in w and "1 item flipped" in w for w in warnings)


def test_two_answered_items_disappearing_fails() -> None:
    current = _run(answerable_answered=9.0, answer_rate=9 / 12)
    failures = compare(FAST20_BASELINE, current)
    assert len(failures) == 1 and "answer rate" in failures[0]
    assert f"{ITEM_FLIP_LIMIT} items flipped" in failures[0]


def test_a_gain_never_fails_the_gate() -> None:
    """Two items the *good* way round is two flips too, and it must not be
    reported as a regression — the limit is on a drop, not on a change."""
    current = _run(should_abstain_correct=9.0, answerable_answered=12.0)
    assert compare(FAST20_BASELINE, current) == []
    assert notes(FAST20_BASELINE, current) == []


def test_a_gain_in_one_metric_cannot_pay_for_a_loss_in_the_other() -> None:
    """Answer rate is the counterweight to abstention, but it is not a budget:
    a run that answers one more item does not get to abstain one more."""
    current = _run(answerable_answered=12.0, should_abstain_correct=5.0)
    failures = compare(FAST20_BASELINE, current)
    assert [f for f in failures if "abstention accuracy" in f]


def test_a_one_item_drop_in_both_metrics_is_still_two_warnings_not_a_failure() -> None:
    """They are separate gates. The same pipeline change moves both, and the
    question each answers is a different one."""
    current = _run(should_abstain_correct=6.0, answerable_answered=10.0)
    assert compare(FAST20_BASELINE, current) == []
    assert len([w for w in notes(FAST20_BASELINE, current) if "1 item flipped" in w]) == 2


def test_the_warning_is_printed_and_the_gate_still_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The warning has to reach CI's log, and reaching it must not change the
    exit code. Driven through `gate.main` with `run_eval` stubbed, because the
    claim under test is about what the process prints and returns, not about
    what `notes` returns."""
    baseline_path = tmp_path / "baseline_fast20.json"
    baseline_path.write_text(json.dumps(_file()), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")

    # One should-abstain item answers instead of abstaining, one answerable
    # item abstains: one flip on each metric, i.e. two warnings, no failure.
    results: list[tuple[EvalItem, EvalResult]] = []
    for should_abstain, abstained in (
        *((True, True),) * 6,
        (True, False),
        (True, False),
        *((False, False),) * 10,
        (False, True),
        (False, True),
    ):
        results.append((_item(should_abstain=should_abstain), _scored_result(abstained=abstained)))

    async def fake_run_eval(**_: Any) -> tuple[Any, list[tuple[EvalItem, EvalResult]]]:
        return SimpleNamespace(id=uuid4()), results

    monkeypatch.setattr(gate, "run_eval", fake_run_eval)
    monkeypatch.setattr(gate, "BASELINE_FAST20_FILE", baseline_path)
    monkeypatch.setattr(gate, "STATE_FILE", state)
    asyncio.run(gate.main())
    captured = capsys.readouterr()
    assert "eval gate passed" in captured.out
    assert captured.err.count("GATE WARN:") == 2
    assert "GATE FAIL" not in captured.err


def test_a_baseline_without_the_counts_is_unverifiable_not_passing() -> None:
    """The shipped `baseline_fast20.json` predates the counts: it records the
    rates and nothing to divide them by. That is reported, and it is not a
    failure — an old baseline is not a regression, but it is not a pass
    either, so the warning has to name the key and the way out."""
    baseline = dict(FAST20_BASELINE)
    del baseline["should_abstain_correct"]
    del baseline["answerable_answered"]
    current = _run(should_abstain_correct=0.0, answerable_answered=0.0)
    assert compare(baseline, current) == []
    warnings = notes(baseline, current)
    assert len(warnings) == 2
    assert "should_abstain_correct" in warnings[0] and "UNVERIFIED" in warnings[0]
    assert "answerable_answered" in warnings[1] and "UNVERIFIED" in warnings[1]


# --- unchanged behaviour ---------------------------------------------------


def test_the_faithfulness_limit_is_untouched_at_0_03() -> None:
    """A6 and A7 relaxed two limits. They did not touch this one: a drop just
    past 0.03 still fails, and one just inside it still passes."""
    assert compare(FAST20_BASELINE, _run(faithfulness=FAITHFULNESS - 0.031)) != []
    assert compare(FAST20_BASELINE, _run(faithfulness=FAITHFULNESS - 0.02)) == []


def test_an_errored_run_is_still_refused() -> None:
    failures = compare(FAST20_BASELINE, _run(failed=1.0, scored=19.0))
    assert any("errored" in failure for failure in failures)


def test_compare_models_is_unchanged() -> None:
    assert compare_models(_file(), {"models": models_on_record()}) == []
    assert compare_models(_file(), {"models": {"generator": "x", "small": "y"}}) != []


# --- the counts the gate reads are the counts aggregate computes ----------


def test_aggregate_reports_the_two_item_counts_the_gate_gates_on() -> None:
    # 3 should-abstain items, 2 of which abstained; 2 answerable, 1 answered.
    summary = aggregate(
        [
            (_item(should_abstain=True), _scored_result(abstained=True)),
            (_item(should_abstain=True), _scored_result(abstained=True)),
            (_item(should_abstain=True), _scored_result(abstained=False)),
            (_item(should_abstain=False), _scored_result(abstained=False)),
            (_item(should_abstain=False), _scored_result(abstained=True)),
        ]
    )
    assert summary["should_abstain_correct"] == 2.0
    assert summary["answerable_answered"] == 1.0
    # The counts and the rates are two views of the same run and must agree.
    assert summary["abstention_accuracy"] == pytest.approx(2 / 3)
    assert summary["answer_rate"] == pytest.approx(0.5)


def test_an_errored_item_is_left_out_of_the_counts() -> None:
    """An errored item was never measured, so it cannot be counted as a
    misclassification — that would turn a dropped item into a fake flip."""
    failed = EvalResult(
        eval_run_id=uuid4(),
        item_id=uuid4(),
        answer="",
        latency_ms=0,
        error="TimeoutError: boom",
        stage_ms={},
    )
    summary = aggregate([(_item(should_abstain=True), failed)])
    assert summary["should_abstain_correct"] == 0.0
    assert summary["abstention_accuracy"] is None