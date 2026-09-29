"""Judge parsing and gate comparison (pure functions; no LLM calls)."""

from uuid import uuid4

import pytest

from db.models import EvalItem, EvalResult
from evals.gate import compare
from evals.judge import parse_judge_response
from evals.runner import aggregate

GOOD = """```json
{"context_precision": 0.6, "context_recall": 0.75, "answer_relevance": 0.9}
```"""


def test_parse_judge_response_valid_json() -> None:
    scores = parse_judge_response(
        '{"context_precision": 0.7, "context_recall": 0.8, "answer_relevance": 0.9}'
    )
    assert scores is not None
    assert scores.answer_relevance == pytest.approx(0.9)
    assert scores.context_recall == pytest.approx(0.8)


def test_parse_judge_response_strips_fence() -> None:
    scores = parse_judge_response(GOOD)
    assert scores is not None and scores.context_precision == pytest.approx(0.6)


def test_parse_judge_response_rejects_garbage() -> None:
    assert parse_judge_response("not json") is None
    assert parse_judge_response('{"context_precision": "high"}') is None
    assert parse_judge_response('{"context_precision": 1}') is None


def test_gate_passes_within_thresholds() -> None:
    baseline: dict[str, float | None] = {
        "faithfulness": 0.80,
        "abstention_accuracy": 0.90,
        "p50_latency_ms": 2000.0,
    }
    current: dict[str, float | None] = {
        "faithfulness": 0.78,
        "abstention_accuracy": 0.87,
        "p50_latency_ms": 2100.0,
    }
    assert compare(baseline, current) == []


def test_gate_fails_on_faithfulness_drop() -> None:
    baseline = {"faithfulness": 0.80, "abstention_accuracy": None, "p50_latency_ms": 2000.0}
    current = {"faithfulness": 0.76, "abstention_accuracy": None, "p50_latency_ms": 2000.0}
    failures = compare(baseline, current)
    assert len(failures) == 1 and "faithfulness" in failures[0]


def test_gate_fails_on_latency_rise() -> None:
    baseline = {"faithfulness": 0.8, "abstention_accuracy": None, "p50_latency_ms": 2000.0}
    current = {"faithfulness": 0.8, "abstention_accuracy": None, "p50_latency_ms": 3000.0}
    failures = compare(baseline, current)
    assert len(failures) == 1 and "latency" in failures[0]


def test_gate_abstention_check_is_passive_without_decision() -> None:
    # TODO(slice-4): abstention accuracy must not fail the gate when the
    # decision layer does not exist yet — recorded but pass-through.
    baseline = {"faithfulness": 0.8, "abstention_accuracy": None, "p50_latency_ms": None}
    current = {"faithfulness": 0.8, "abstention_accuracy": 0.0, "p50_latency_ms": None}
    assert compare(baseline, current) == []


def test_gate_missing_metrics_do_not_fail() -> None:
    assert compare({}, {}) == []
    assert compare({"faithfulness": None}, {"faithfulness": 0.0}) == []


def test_gate_gates_our_overhead_not_the_providers_time() -> None:
    """KI-18: a 3x rise in wall clock that is all upstream must not fail the
    gate, because nothing in this repo regressed."""
    baseline = {
        "faithfulness": 0.8,
        "abstention_accuracy": None,
        "p50_latency_ms": 6000.0,
        "p50_our_overhead_ms": 300.0,
    }
    current = {
        "faithfulness": 0.8,
        "abstention_accuracy": None,
        "p50_latency_ms": 18000.0,
        "p50_our_overhead_ms": 320.0,
    }
    assert compare(baseline, current) == []


def test_gate_fails_when_our_own_overhead_rises() -> None:
    baseline = {
        "faithfulness": 0.8,
        "abstention_accuracy": None,
        "p50_latency_ms": 6000.0,
        "p50_our_overhead_ms": 300.0,
    }
    current = {
        "faithfulness": 0.8,
        "abstention_accuracy": None,
        "p50_latency_ms": 6000.0,
        "p50_our_overhead_ms": 900.0,
    }
    failures = compare(baseline, current)
    assert len(failures) == 1 and "our_overhead_ms" in failures[0]


def test_gate_falls_back_to_total_when_no_run_was_attributed() -> None:
    """No overhead on either side must not silently disable the check."""
    baseline = {"faithfulness": 0.8, "abstention_accuracy": None, "p50_latency_ms": 2000.0}
    current = {"faithfulness": 0.8, "abstention_accuracy": None, "p50_latency_ms": 3000.0}
    failures = compare(baseline, current)
    assert len(failures) == 1 and "p50_latency_ms" in failures[0]


def _item() -> EvalItem:
    return EvalItem(
        id=uuid4(),
        dataset_id=uuid4(),
        category="lookup",
        question="q",
        reference_answer="a",
        should_abstain=False,
    )


def _result(latency_ms: int, stage_ms: dict[str, object] | None) -> EvalResult:
    return EvalResult(
        eval_run_id=uuid4(),
        item_id=uuid4(),
        answer="ok",
        faithfulness=0.9,
        abstained=False,
        latency_ms=latency_ms,
        stage_ms=stage_ms or {},
    )


def test_aggregate_reports_total_and_our_overhead_p50() -> None:
    summary = aggregate(
        [
            (_item(), _result(6000, {"provider_ms": 5700, "our_overhead_ms": 300})),
            (_item(), _result(7000, {"provider_ms": 6800, "our_overhead_ms": 200})),
        ]
    )
    assert summary["p50_latency_ms"] == 6500.0
    assert summary["p50_our_overhead_ms"] == 250.0


def test_aggregate_never_fabricates_overhead_when_nothing_was_attributed() -> None:
    summary = aggregate([(_item(), _result(6000, {"provider_ms": 0, "generations_attributed": 0}))])
    assert summary["p50_our_overhead_ms"] is None
    assert summary["p50_latency_ms"] == 6000.0


def test_aggregate_drops_overhead_when_only_some_items_were_attributed() -> None:
    """A median over a subset would silently compare different populations."""
    summary = aggregate(
        [
            (_item(), _result(6000, {"our_overhead_ms": 300})),
            (_item(), _result(7000, {})),
        ]
    )
    assert summary["p50_our_overhead_ms"] is None
