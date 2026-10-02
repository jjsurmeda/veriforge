"""Isolation for the eval-gate tests.

`evals.gate` records every run's summary to `.data/evals/summary-*.json` so a
baseline can later be written from the mean of N runs (A8). A test that drives
`gate.main` with a stubbed `run_eval` therefore has a synthetic summary, not a
measured one, and the real directory is exactly where the next operator globs
for the summaries to average — a stray file there would be averaged into the
committed baseline without anyone noticing. So the recording directory is
redirected for every test in this package, whether or not the test asks for it.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from evals import baseline


@pytest.fixture(autouse=True)
def recorded_summaries_go_to_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    """Point `evals.baseline.record` at this test's tmp_path.

    `record` reads the module global at call time, so patching the constant is
    enough to redirect it — the alternative, patching `gate.record_summary`,
    would leave a gate-driven write reaching the repo for any test that forgets.
    """
    out = tmp_path / "summaries"
    monkeypatch.setattr(baseline, "SUMMARY_DIR", out)
    yield out
