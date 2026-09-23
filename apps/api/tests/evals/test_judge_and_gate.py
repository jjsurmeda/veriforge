"""Judge parsing and gate comparison (pure functions; no LLM calls)."""

import pytest

from evals.gate import compare
from evals.judge import parse_judge_response

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
        "faithfulness": 0.80, "abstention_accuracy": 0.90, "p50_latency_ms": 2000.0,
    }
    current: dict[str, float | None] = {
        "faithfulness": 0.78, "abstention_accuracy": 0.87, "p50_latency_ms": 2100.0,
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
