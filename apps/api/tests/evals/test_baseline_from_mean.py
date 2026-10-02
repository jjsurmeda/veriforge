"""The fast20 baseline is the mean of N runs, not one of them (A8, 2026-10-02).

`evals.runner --baseline` wrote the baseline from whichever run it had just
taken, and D6 took that run four times: three runs spread 0.0250 of
faithfulness, the median of those three became the baseline, and the fourth
(0.94375) failed the gate against it — a 0.039 drop on an unchanged commit.
So the writer under test is the one that takes N recorded run summaries and
means them, and the properties that matter are:

* the mean is per metric, not one statistic applied to everything;
* the runs and their individual faithfulness values are recorded in the file,
  so the spread the baseline was written to accommodate is auditable from the
  file rather than from the report that wrote it;
* it refuses to average runs that used different models or graded different
  item sets, because a mean over those is not a measurement — and unlike a
  failed comparison, it would then be *stored* for every later run to be
  measured against.
"""

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from evals import baseline as baseline_module
from evals.baseline import MEAN_METRICS, mean_baseline, record
from evals.gate import compare, compare_models, notes
from evals.runner import models_on_record

# One recorded run summary, as `evals.gate` writes it. These are D6's runs 1-3
# on the unchanged tree (`ed1ea59`), which is the data the decision was made
# on; run 4 (0.94375) is the one that broke the median, and it is run 4 of the
# five here.
RUNS: tuple[dict[str, Any], ...] = (
    {
        "eval_run": "run-1",
        "faithfulness": 1.0,
        "context_recall": 0.8875,
        "abstention_accuracy": 0.875,
        "answer_rate": 0.9166666666666666,
        "should_abstain_correct": 7.0,
        "answerable_answered": 11.0,
        "should_abstain_total": 8.0,
        "answerable_total": 12.0,
        "p50_latency_ms": 8700.0,
        "p50_our_overhead_ms": 2742.5,
        "overhead_items_attributed": 20.0,
        "p50_total_ms_unattributed_items": None,
        "items": 20.0,
        "scored": 20.0,
        "failed": 0.0,
    },
    {
        "eval_run": "run-2",
        "faithfulness": 0.975,
        "context_recall": 0.8875,
        "abstention_accuracy": 0.875,
        "answer_rate": 0.9166666666666666,
        "should_abstain_correct": 7.0,
        "answerable_answered": 11.0,
        "should_abstain_total": 8.0,
        "answerable_total": 12.0,
        "p50_latency_ms": 8429.5,
        "p50_our_overhead_ms": 3004.0,
        "overhead_items_attributed": 20.0,
        "p50_total_ms_unattributed_items": None,
        "items": 20.0,
        "scored": 20.0,
        "failed": 0.0,
    },
    {
        "eval_run": "run-3",
        "faithfulness": 0.9833333333333334,
        "context_recall": 0.8875,
        "abstention_accuracy": 0.875,
        "answer_rate": 0.9166666666666666,
        "should_abstain_correct": 7.0,
        "answerable_answered": 11.0,
        "should_abstain_total": 8.0,
        "answerable_total": 12.0,
        "p50_latency_ms": 9378.0,
        "p50_our_overhead_ms": 3066.0,
        "overhead_items_attributed": 20.0,
        "p50_total_ms_unattributed_items": None,
        "items": 20.0,
        "scored": 20.0,
        "failed": 0.0,
    },
    {
        "eval_run": "run-4",
        "faithfulness": 0.94375,
        "context_recall": 0.8875,
        "abstention_accuracy": 0.875,
        "answer_rate": 0.9166666666666666,
        "should_abstain_correct": 7.0,
        "answerable_answered": 11.0,
        "should_abstain_total": 8.0,
        "answerable_total": 12.0,
        "p50_latency_ms": 9010.0,
        "p50_our_overhead_ms": 2900.0,
        "overhead_items_attributed": 20.0,
        "p50_total_ms_unattributed_items": None,
        "items": 20.0,
        "scored": 20.0,
        "failed": 0.0,
    },
    {
        "eval_run": "run-5",
        "faithfulness": 0.9683333333333334,
        "context_recall": 0.9,
        "abstention_accuracy": 0.875,
        "answer_rate": 0.9166666666666666,
        "should_abstain_correct": 7.0,
        "answerable_answered": 11.0,
        "should_abstain_total": 8.0,
        "answerable_total": 12.0,
        "p50_latency_ms": 8500.0,
        "p50_our_overhead_ms": 3050.0,
        "overhead_items_attributed": 20.0,
        "p50_total_ms_unattributed_items": None,
        "items": 20.0,
        "scored": 20.0,
        "failed": 0.0,
    },
)


def _with_models(**over: Any) -> dict[str, Any]:
    return {"models": models_on_record(), **over}


def _runs(*, models_on: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    return [
        {**_run, "models": models_on[index] if models_on else models_on_record()}
        for index, _run in enumerate(RUNS)
    ]


# --- the mean --------------------------------------------------------------


def test_the_mean_is_computed_per_metric() -> None:
    """The failure this prevents is a mean of the wrong thing, or one statistic
    applied to every metric. Each of these five runs moves a different metric
    away from the others, so one mean taken across all of them would be
    visibly wrong for at least one key."""
    mean = mean_baseline(_runs())

    assert mean["faithfulness"] == pytest.approx(
        sum(run["faithfulness"] for run in RUNS) / 5, abs=1e-12
    )
    # context_recall: four runs at 0.8875, one at 0.9.
    assert mean["context_recall"] == pytest.approx((4 * 0.8875 + 0.9) / 5)
    # p50 latency: 8700 / 8429.5 / 9378 / 9010 / 8500. The mean is 8803.5, and
    # the *median* is 8700 — so this is the number a median would get wrong.
    assert mean["p50_latency_ms"] == pytest.approx(8803.5)
    assert mean["p50_our_overhead_ms"] == pytest.approx((2742.5 + 3004 + 3066 + 2900 + 3050) / 5)
    # The counts every run agreed on mean back to themselves.
    assert mean["should_abstain_correct"] == 7.0
    assert mean["answerable_answered"] == 11.0
    assert mean["items"] == 20.0
    assert mean["scored"] == 20.0
    assert mean["failed"] == 0.0


def test_every_mean_metric_is_written() -> None:
    """A metric left out of the file is a metric the gate cannot see, which is
    the whole reason the baseline was unwritable: `baseline_fast20.json`
    predated the item counts, so the gate warned it could not verify them."""
    mean = mean_baseline(_runs())
    for key in MEAN_METRICS:
        assert key in mean, key
    # The denominators too, not only the means. This is the assertion the
    # first version of the writer failed: it *checked* the totals were equal
    # and then left them out of the file, which is the same "baseline records
    # no should_abstain_total" warning the old baseline produced.
    for key in baseline_module.INVARIANT_KEYS:
        assert key in mean, key
    assert mean["should_abstain_total"] == 8.0
    assert mean["answerable_total"] == 12.0
    assert compare_models(mean, {"models": models_on_record()}) == []


def test_the_runs_and_their_faithfulness_are_recorded() -> None:
    """The audit record. The gate reads the mean and cannot see the spread it
    was widened to accommodate (A9) — so if the file does not carry the runs,
    that fact survives only in a commit body."""
    mean = mean_baseline(_runs())

    assert mean["runs"] == 5
    assert mean["faithfulness_runs"] == [run["faithfulness"] for run in RUNS]
    # D6's four-run spread, plus run 5: 1.0 down to 0.94375.
    assert mean["faithfulness_spread"] == pytest.approx(0.05625)
    # The spread is derivable from the file, which is the point of recording it.
    recorded = mean["faithfulness_runs"]
    assert max(recorded) - min(recorded) == mean["faithfulness_spread"]


def test_the_written_baseline_is_one_the_gate_accepts_and_honours() -> None:
    """The end of the chain. A baseline the gate refuses, or one that trips its
    own item-count gates against a run with the same numbers, is not a
    baseline."""
    mean = mean_baseline(_runs())
    same_run = _runs()[0]

    assert compare_models(mean, {"models": models_on_record()}) == []
    assert compare(mean, same_run) == []
    assert notes(mean, same_run) == []


def test_a_metric_no_run_recorded_stays_null_and_is_never_zero() -> None:
    """`p50_total_ms_unattributed_items` is null when every item attributed
    (KI-31's withheld median). A fabricated 0.0 would read as "the excluded
    items were instant" and would then be averaged into the baseline."""
    mean = mean_baseline(_runs())
    assert mean["p50_total_ms_unattributed_items"] is None


def test_a_metric_only_some_runs_recorded_is_refused() -> None:
    runs = _runs()
    runs[2] = {**runs[2], "p50_our_overhead_ms": None}
    with pytest.raises(ValueError, match="p50_our_overhead_ms"):
        mean_baseline(runs)


# --- the refusals ----------------------------------------------------------


def test_runs_with_different_models_are_refused() -> None:
    """The comparison `compare_models` already refuses, caught at write time
    instead. Averaging a gpt-4o-mini faithfulness with a Haiku one produces a
    number that is not either, and unlike a failed comparison it would be
    *stored* and every later run compared against it."""
    models = [models_on_record()] * 5
    models[3] = {
        "generator": "openrouter/anthropic/claude-haiku-4.5",
        "small": "openrouter/anthropic/claude-haiku-4.5",
    }

    with pytest.raises(ValueError) as refused:
        mean_baseline(_runs(models_on=models))

    assert "different models" in str(refused.value)
    assert "run 4" in str(refused.value)


def test_runs_that_graded_different_item_sets_are_refused() -> None:
    """Same argument for the denominators (P9): a mean of 7-of-8 over one
    subset and 7-of-9 over another is a count over nothing, and it would be
    stored as the number every later run is measured against."""
    runs = _runs()
    runs[1] = {**runs[1], "should_abstain_total": 9.0, "answerable_total": 11.0}

    with pytest.raises(ValueError) as refused:
        mean_baseline(runs)

    assert "should_abstain_total" in str(refused.value)
    assert "item set" in str(refused.value)


def test_runs_that_scored_a_different_number_of_items_are_refused() -> None:
    """A run that lost an item to an error contributes nothing to a mean of
    five, and silently shrinking the set is how a baseline comes to describe
    an item set the gate never ran."""
    runs = _runs()
    runs[4] = {**runs[4], "scored": 19.0}

    with pytest.raises(ValueError, match="scored"):
        mean_baseline(runs)


def test_a_summary_with_no_models_is_refused() -> None:
    runs = _runs()
    runs[0] = {key: value for key, value in runs[0].items() if key != "models"}
    with pytest.raises(ValueError, match="models"):
        mean_baseline(runs)


def test_a_summary_missing_an_invariant_is_refused() -> None:
    """Not averaged as `None` and not assumed equal: without the denominator
    the file cannot show the runs graded the same items, which is the one thing
    the item-count gates depend on."""
    runs = _runs()
    runs[0] = {key: value for key, value in runs[0].items() if key != "answerable_total"}
    with pytest.raises(ValueError, match="answerable_total"):
        mean_baseline(runs)


def test_one_run_is_refused() -> None:
    """A baseline from a single run is not a mean, it is that run — which is
    what D6 wrote, and what the fourth run then failed against. The writer
    refuses rather than letting `evals.baseline summary.json` stand in for a
    five-run measurement."""
    with pytest.raises(ValueError, match="at least 2 runs"):
        mean_baseline(_runs()[:1])


# --- the recording, and the CLI that reads it ------------------------------


def test_record_writes_a_summary_json_the_cli_can_read_back(
    recorded_summaries_go_to_tmp: Path,
) -> None:
    """The two halves have to meet: the gate records, and the writer reads
    what the gate recorded. A summary file that `mean_baseline` could not load
    would make the mean unwritable while every run still reported success."""
    path = record(_runs()[0])

    assert path.parent == recorded_summaries_go_to_tmp
    loaded: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["faithfulness"] == 1.0
    assert loaded["models"] == models_on_record()
    assert mean_baseline([loaded, loaded])["faithfulness"] == 1.0


def test_the_gate_records_its_own_summary(tmp_path: Path) -> None:
    """Why the recording lives in `evals.gate` and not in a script the operator
    has to remember to run: the run has to be recorded whether or not anyone is
    thinking about baselines at the time.

    The one-item run below fails the gate against a 20-item baseline, and that
    is the point of driving it here — a failing run is exactly the one whose
    summary is needed afterwards, so the recording happens before the
    comparison rather than after a pass."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch
    from uuid import uuid4

    from db.models import EvalItem, EvalResult
    from evals import gate

    item = EvalItem(
        id=uuid4(),
        dataset_id=uuid4(),
        category="lookup",
        question="q",
        reference_answer="a",
        should_abstain=False,
    )
    result = EvalResult(
        eval_run_id=uuid4(),
        item_id=item.id,
        answer="a",
        faithfulness=1.0,
        abstained=False,
        latency_ms=6000,
        stage_ms={"our_overhead_ms": 100.0},
    )
    baseline_path = tmp_path / "baseline_fast20.json"
    baseline_path.write_text(json.dumps(_with_models(**RUNS[0])), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")

    async def fake_run_eval(**_: Any) -> tuple[Any, list[tuple[EvalItem, EvalResult]]]:
        return SimpleNamespace(id=uuid4()), [(item, result)]

    with (
        patch.object(gate, "run_eval", fake_run_eval),
        patch.object(gate, "BASELINE_FAST20_FILE", baseline_path),
        patch.object(gate, "STATE_FILE", state),
        pytest.raises(SystemExit) as exited,
    ):
        asyncio.run(gate.main())

    assert exited.value.code == 1  # the stub's 1 item is not the 20-item subset
    recorded = sorted(baseline_module.SUMMARY_DIR.glob("summary-*.json"))
    assert len(recorded) == 1
    assert json.loads(recorded[0].read_text(encoding="utf-8"))["faithfulness"] == 1.0


def test_the_cli_writes_the_file_and_says_where_from(tmp_path: Path) -> None:
    paths = []
    for index, run in enumerate(_runs()):
        path = tmp_path / f"summary-{index}.json"
        path.write_text(json.dumps(run), encoding="utf-8")
        paths.append(path)
    out = tmp_path / "baseline_fast20.json"

    assert baseline_module.main([*(str(p) for p in paths), "--out", str(out)]) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["runs"] == 5
    assert written["faithfulness"] == pytest.approx(
        sum(run["faithfulness"] for run in RUNS) / 5, abs=1e-12
    )


def test_the_cli_writes_nothing_when_it_refuses(tmp_path: Path) -> None:
    """The half that matters. A refusal that still leaves a file behind is the
    failure D6's revert was cleaning up, and it would be committed."""
    runs = _runs()
    runs[3] = {**runs[3], "should_abstain_total": 9.0}
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(runs[0]), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(runs[3]), encoding="utf-8")
    out = tmp_path / "baseline_fast20.json"

    assert baseline_module.main([str(path), str(bad), "--out", str(out)]) == 1
    assert not out.exists()


def test_a_refusal_exits_non_zero_from_the_shell_too(tmp_path: Path) -> None:
    """Through the module entry point, because a non-zero return is only a
    refusal if the process exits non-zero — which is what stops a `set -e`
    script writing the file on the next line."""
    python = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.skip("apps/api/.venv is missing; run `uv sync` first")
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_runs()[0]), encoding="utf-8")
    out = tmp_path / "baseline_fast20.json"

    completed = subprocess.run(
        [str(python), "-m", "evals.baseline", str(path), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        timeout=120,
    )

    assert completed.returncode == 1
    assert "baseline not written" in completed.stderr
    assert not out.exists()
