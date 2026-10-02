"""The baseline records `answer_rate` and `p50_our_overhead_ms`, and the gate
uses both when they are present (C3 item 4).

Both stored baselines predate those fields, which is what made two of C2's
gate conditions unverifiable. The fields are computed by `aggregate` and
honoured by `compare`; what was missing was proof, so these tests pin both
sides against a synthetic baseline — the shape the runner would write.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from db.models import EvalItem, EvalResult
from evals import runner
from evals.gate import (
    ITEM_FLIP_LIMIT,
    LATENCY_RISE_FACTOR,
    OVERHEAD_RISE_FACTOR,
    compare,
    compare_models,
    notes,
)
from evals.runner import aggregate, models_on_record

# What `evals.runner --baseline` writes for a clean run: both fields present,
# and the two item counts A7 gates on.
SYNTHETIC_BASELINE: dict[str, float | None] = {
    "faithfulness": 0.9875,
    "context_recall": 1.0,
    "abstention_accuracy": 0.25,
    "answer_rate": 0.9375,
    "should_abstain_correct": 2.0,
    "answerable_answered": 15.0,
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
    failures = compare(SYNTHETIC_BASELINE, _current(answerable_answered=13.0))
    assert len(failures) == 1 and "answer rate" in failures[0]
    assert f"{ITEM_FLIP_LIMIT} items flipped" in failures[0]


def test_a_one_item_answer_rate_drop_is_inside_the_gate() -> None:
    one_down = _current(answerable_answered=14.0)
    assert compare(SYNTHETIC_BASELINE, one_down) == []
    assert any("1 item flipped" in warning for warning in notes(SYNTHETIC_BASELINE, one_down))


def test_the_gate_prefers_our_overhead_over_total_latency() -> None:
    """A 3x rise that is all provider time must not fail: only the attributed
    remainder is this repo's to regress (KI-18). The rising figure is +42%
    because A6 moved the factor from 1.20 to 1.35 — 11000 was +30%, which the
    gate now passes on purpose."""
    assert (
        compare(
            SYNTHETIC_BASELINE,
            _current(p50_latency_ms=40000.0, p50_our_overhead_ms=8600.0),
        )
        == []
    )
    failures = compare(
        SYNTHETIC_BASELINE,
        _current(p50_latency_ms=40000.0, p50_our_overhead_ms=12000.0),
    )
    assert len(failures) == 1 and "our_overhead_ms" in failures[0]
    # The message names the factor that actually applied (A6), not the
    # fallback's 1.20 — the two are different limits on different figures.
    assert f"{OVERHEAD_RISE_FACTOR:.2f}" in failures[0]
    assert f"{LATENCY_RISE_FACTOR:.2f}" not in failures[0]


def test_a_stale_baseline_still_gates_on_what_it_does_have() -> None:
    """The stored baseline has no answer_rate and no overhead. Removing them
    must not remove the checks it *does* carry — this is the state the repo is
    in right now, and it is why two C2 conditions were unverifiable."""
    stale = {
        k: v
        for k, v in SYNTHETIC_BASELINE.items()
        if k
        not in (
            "answer_rate",
            "answerable_answered",
            "should_abstain_correct",
            "p50_our_overhead_ms",
        )
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


# --- the models on record (D3 item 2) -------------------------------------
#
# The writer is `evals.runner.main`, which prints the run summary and writes
# both baseline files. It is exercised here through the real entry point with
# `run_eval` stubbed, because the contract that matters is "the file ci.yml
# reads names the models it was measured with" -- reading the source for the
# string would not prove the key reaches the file.


def test_the_run_summary_carries_the_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = [(_item(), _result())]

    async def fake_run_eval(**_: Any) -> tuple[Any, list[tuple[EvalItem, EvalResult]]]:
        return SimpleNamespace(id=uuid4()), results

    monkeypatch.setattr(runner, "run_eval", fake_run_eval)
    monkeypatch.setattr(sys, "argv", ["evals.runner"])
    asyncio.run(runner.main())
    summary = json.loads(capsys.readouterr().out)
    assert summary["models"] == models_on_record()
    assert set(summary["models"]) == {"generator", "small"}


def test_the_written_baseline_carries_the_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate reads baseline_fast20.json; if the models are not in it,
    `compare_models` has nothing to check the next run against."""
    results = [(_item(), _result())]
    (tmp_path / "items.json").write_text(
        json.dumps(
            {"dataset": "seed", "fast20_ids": [], "items": [{"id": "lookup-01", "question": "q"}]}
        ),
        encoding="utf-8",
    )

    async def fake_run_eval(**_: Any) -> tuple[Any, list[tuple[EvalItem, EvalResult]]]:
        return SimpleNamespace(id=uuid4()), results

    monkeypatch.setattr(runner, "run_eval", fake_run_eval)
    # The baseline paths are module constants derived from SEED_DIR at import
    # time, so pointing SEED_DIR at tmp_path is not enough on its own — and
    # letting them resolve for real would overwrite the committed baseline.
    monkeypatch.setattr(runner, "SEED_DIR", tmp_path)
    monkeypatch.setattr(runner, "BASELINE_FILE", tmp_path / "baseline.json")
    monkeypatch.setattr(runner, "BASELINE_FAST20_FILE", tmp_path / "baseline_fast20.json")
    monkeypatch.setattr(sys, "argv", ["evals.runner", "--baseline"])
    asyncio.run(runner.main())
    capsys.readouterr()
    # The writer targets the module constants, not SEED_DIR. Assert they are
    # redirected before reading anything, so a future edit that drops the
    # monkeypatch fails here instead of overwriting the committed baselines --
    # which is exactly what it did the first time this test ran.
    assert runner.BASELINE_FILE.parent == tmp_path
    assert runner.BASELINE_FAST20_FILE.parent == tmp_path
    for name in ("baseline.json", "baseline_fast20.json"):
        written = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert written["models"] == models_on_record(), name
        # And the stored baseline is one the gate accepts as comparable.
        assert compare_models(written, {"models": models_on_record()}) == []
