"""The eval-gate export keeps the per-item detail before the database is dropped.

`make eval-gate-local` drops its ephemeral database on exit, so `eval-gate-local`
has to read the per-stage breakdown out while it still exists — and printing it
to a terminal is not keeping it. D3 traced a faithfulness dip to two item ids
and could not go further: the claims and verdicts that would say *why* went with
the database. These pin that the dump is written to
`.data/evals/<timestamp>-<run-id>-<sha>.json` and that it carries the four
things a run-to-run comparison needs.

No provider calls: `write_export` and `measured_sha` are pure, and the file
system is a tmp_path.
"""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import eval_dump_stages

PAYLOAD = json.dumps({"per_item": [{"question": "q", "faithfulness": 1.0}]})


def test_the_export_is_written_named_for_its_run_timestamp_and_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(eval_dump_stages, "OUT_DIR", tmp_path / "evals")
    monkeypatch.setattr(eval_dump_stages, "measured_sha", lambda: "abc1234")

    path = eval_dump_stages.write_export(
        PAYLOAD,
        run_id="01a145b5-bf1c-75a1-a2ca-7cd7b64613cd",
        now=datetime(2026, 10, 2, 1, 2, 3, tzinfo=UTC),
    )

    assert path.name == "20261002-010203-01a145b5-bf1c-75a1-a2ca-7cd7b64613cd-abc1234.json"
    assert path.parent == tmp_path / "evals"
    assert path.read_text() == PAYLOAD + "\n"
    # Round-trips: an export nobody can load is not an export.
    assert json.loads(path.read_text())["per_item"][0]["faithfulness"] == 1.0


def test_a_dump_without_a_run_id_admits_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`unknown-run`, never a plausible-looking id: the gap in the name must
    say the run was lost, not hide it."""
    monkeypatch.setattr(eval_dump_stages, "OUT_DIR", tmp_path / "evals")
    monkeypatch.setattr(eval_dump_stages, "measured_sha", lambda: "abc1234")
    path = eval_dump_stages.write_export(
        PAYLOAD, run_id=None, now=datetime(2026, 10, 2, 1, 2, 3, tzinfo=UTC)
    )
    assert "unknown-run" in path.name


def test_the_export_directory_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eval_dump_stages, "OUT_DIR", tmp_path / "nested" / "evals")
    monkeypatch.setattr(eval_dump_stages, "measured_sha", lambda: "abc1234")
    path = eval_dump_stages.write_export(PAYLOAD, run_id="01a145b5")
    assert path.exists()


def test_the_measured_sha_is_the_committed_one() -> None:
    """Read from git, not taken on trust: a file named after the wrong SHA is
    worse than one named after none."""
    sha = eval_dump_stages.measured_sha()
    assert sha and sha != "unknown"
    assert all(c in "0123456789abcdef" for c in sha.lower())


def test_the_measured_sha_falls_back_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No git, or a git that fails: `unknown`, never a plausible-looking SHA."""

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no git here")

    monkeypatch.setattr(subprocess, "run", boom)
    assert eval_dump_stages.measured_sha() == "unknown"


def test_the_local_gate_dumps_every_run_it_judged() -> None:
    """R2a-4 lost fast20's per-item rows: the gate judged four runs (two per
    subset) and dumped only the latest. Every judged run has to be exported
    before the database is dropped."""
    script = Path(__file__).resolve().parents[4] / "scripts" / "eval_gate_local.sh"
    dump_lines = [line for line in script.read_text().splitlines() if "eval_dump_stages.py" in line]
    assert dump_lines and all(
        "--all" in line for line in dump_lines if not line.lstrip().startswith("#")
    )
