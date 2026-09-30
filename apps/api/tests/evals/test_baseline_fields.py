"""The baseline records `answer_rate` and `p50_our_overhead_ms`, and the gate
uses both when they are present (C3 item 4).

Both stored baselines predate those fields, which is what made two of C2's
gate conditions unverifiable. The fields are computed by `aggregate` and
honoured by `compare`; what was missing was proof, so these tests pin both
sides against a synthetic baseline — the shape the runner would write.
"""

import json
from typing import Any
from uuid import uuid4

from db.models import EvalItem, EvalResult
from evals.gate import ANSWER_RATE_DROP_POINTS, LATENCY_RISE_FACTOR, compare
from evals.runner import aggregate

# What `evals.runner --baseline` writes for a clean run: both fields present.
SYNTHETIC_BASELINE: dict[str, float | None] = {
    "faithfulness": 0.9875,
    "context_recall": 1.0,
    "abstention_accuracy": 0.25,
    "answer_rate": 0.9375,
    "p50_latency_ms": 14384.5,
    "p50_our_overhead_ms": 8457.0,
    "items": 20.0,
    "scored": 20.0,
    "failed": 0.0,
}


def _item(*, should_abstain: bool = False) -> EvalItem:
    return EvalItem(
        id=uuid4(),
        dataset_id=uuid4(),
        category="lookup",
        question="q",
        reference_answer="a",
        should_abstain=should_abstain,
    )


def _result(
    *,
    abstained: bool = False,
    latency_ms: int = 6000,
    overhead_ms: float | None = 300.0,
) -> EvalResult:
    stage = {} if overhead_ms is None else {"our_overhead_ms": overhead_ms}
    return EvalResult(
        eval_run_id=uuid4(),
        item_id=uuid4(),
        answer="a",
        faithfulness=0.98,
        abstained=abstained,
        latency_ms=latency_ms,
        stage_ms=stage,
    )


def _current(**over: Any) -> dict[str, float | None]:
    current = dict(SYNTHETIC_BASELINE)
    current.update(over)
    return current


def test_the_synthetic_baseline_carries_both_fields() -> None:
    """What a written baseline looks like — the two conditions C2 could not
    check are readable from it."""
    for key in ("answer_rate", "p50_our_overhead_ms"):
        assert SYNTHETIC_BASELINE[key] is not None, key
    assert json.loads(json.dumps(SYNTHETIC_BASELINE)) == SYNTHETIC_BASELINE


def test_a_baseline_run_records_both_fields() -> None:
    """`aggregate` is what --baseline writes, so this is the writer's contract."""
    summary = aggregate(
        [
            (_item(), _result(latency_ms=6000, overhead_ms=300.0)),
            (_item(), _result(latency_ms=7000, overhead_ms=500.0)),
        ]
    )
    assert summary["answer_rate"] == 1.0
    assert summary["p50_our_overhead_ms"] == 400.0
    assert set(SYNTHETIC_BASELINE) <= set(summary)


def test_the_gate_checks_answer_rate_when_the_baseline_has_it() -> None:
    failures = compare(SYNTHETIC_BASELINE, _current(answer_rate=0.50))
    assert len(failures) == 1 and "answer rate" in failures[0]
    assert f"{ANSWER_RATE_DROP_POINTS} pts" in failures[0]


def test_a_small_answer_rate_drop_is_inside_the_gate() -> None:
    drop = ANSWER_RATE_DROP_POINTS / 100
    assert compare(SYNTHETIC_BASELINE, _current(answer_rate=0.9375 - drop / 2)) == []


def test_the_gate_prefers_our_overhead_over_total_latency() -> None:
    """A 3x rise that is all provider time must not fail: only the attributed
    remainder is this repo's to regress (KI-18)."""
    assert (
        compare(
            SYNTHETIC_BASELINE,
            _current(p50_latency_ms=40000.0, p50_our_overhead_ms=8600.0),
        )
        == []
    )
    failures = compare(
        SYNTHETIC_BASELINE,
        _current(p50_latency_ms=40000.0, p50_our_overhead_ms=11000.0),
    )
    assert len(failures) == 1 and "our_overhead_ms" in failures[0]
    assert f"{LATENCY_RISE_FACTOR}" not in failures[0]


def test_a_stale_baseline_still_gates_on_what_it_does_have() -> None:
    """The stored baseline has no answer_rate and no overhead. Removing them
    must not remove the checks it *does* carry — this is the state the repo is
    in right now, and it is why two C2 conditions were unverifiable."""
    stale = {
        k: v
        for k, v in SYNTHETIC_BASELINE.items()
        if k not in ("answer_rate", "p50_our_overhead_ms")
    }
    failures = compare(
        stale, _current(answer_rate=0.1, p50_our_overhead_ms=99999.0, p50_latency_ms=14384.5)
    )
    assert failures == []
    # and it still fails the conditions it does carry
    assert compare(stale, _current(faithfulness=0.9, p50_latency_ms=14384.5)) != []


def test_a_baseline_with_the_fields_ignores_a_missing_current_field() -> None:
    """One side absent is no measurement, not a regression."""
    assert compare(SYNTHETIC_BASELINE, _current(answer_rate=None)) == []
    assert (
        compare(SYNTHETIC_BASELINE, _current(p50_our_overhead_ms=None, p50_latency_ms=14384.5))
        == []
    )
