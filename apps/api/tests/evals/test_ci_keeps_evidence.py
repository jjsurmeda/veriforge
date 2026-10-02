"""A CI eval-gate run has to leave the evidence behind, pass or fail.

KI-42 is what happens when it does not. CI scored 0.90833 against a
0.97556 local baseline and the run could say nothing more than that the
number differed: `scripts/eval_dump_stages.py` — the export carrying each
item's answer, its extracted claims with their verdicts, the retrieved
contexts and `stage_ms` — did not run in the eval-gate job at all. So the
claims and verdicts that would have said *which* items moved were discarded
with the runner, and the only remaining move was to re-argue whether 0.90833
was the tail of the distribution or a different one. KI-32, KI-37 and D6
each warn that guessing "just variance" is how that question has been got
wrong before.

The same export is what decomposed D3's and D4's faithfulness dips down to
named item ids, so it is not a nice-to-have for the red case: it is the only
instrument this repo has for the question the gate raises by failing.

These tests read `ci.yml`. A workflow cannot report a missing artifact — an
upload step that silently uploads nothing looks exactly like one that worked,
which is the KI-42 failure mode one level up. So the assertions are on the
configuration that produces the evidence.

What is pinned:

* the export runs **before** the database is gone, and on the failure path
  as well as the success path;
* the artifact is uploaded with `always()`, so a red gate still keeps its
  evidence;
* `if-no-files-found: error`, so an empty upload fails instead of reporting
  success with nothing in it.
"""

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "ci.yml"

# The `job` fixture's value, aliased so the test signatures fit.
Job = dict[str, object]


@pytest.fixture(scope="module")
def job() -> Job:
    """The eval-gate job's steps, by name.

    Parsed with indentation rather than a YAML library: PyYAML has no type
    stubs in this project's env, and `mypy --strict` runs over the tests.
    Reading the block is enough for the ordering and conditions asserted here.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^  eval-gate:\n(.*?)^  \w", text, re.M | re.S)
    assert match, "ci.yml no longer has an eval-gate job"
    return {"body": match.group(1)}


def _steps(body: str) -> list[tuple[str | None, str]]:
    """(name, the step's lines) for each `- ...` step in the job body."""
    steps: list[tuple[str | None, str]] = []
    current_name: str | None = None
    current: list[str] = []
    for line in body.splitlines():
        step = re.match(r"^      - (.*)$", line)
        if step:
            if current or current_name:
                steps.append((current_name, "\n".join(current)))
            head = step.group(1)
            named = re.match(r'^name: "(.*)"$', head)
            current_name = named.group(1) if named else None
            current = [line]
            continue
        if current:
            current.append(line)
    if current or current_name:
        steps.append((current_name, "\n".join(current)))
    return steps


def test_the_export_runs_in_the_eval_gate_job(job: Job) -> None:
    """`eval_dump_stages.py` reads `eval_results` back out of the database, so
    it has to be a step of the gate job — after the gate has run, and before
    the service container is torn down."""
    body = str(job["body"])
    assert "scripts/eval_dump_stages.py" in body, (
        "the per-item export no longer runs in CI: a failing gate would again "
        "report only that the number moved, not which items moved (KI-42)"
    )


def test_the_export_runs_after_the_gate_and_before_the_database_goes(job: Job) -> None:
    """Order is the whole mechanism. `eval_dump_stages.py` reads the rows the
    gate wrote, out of a database that exists only for the length of the job."""
    steps = _steps(str(job["body"]))
    gate_at = next(
        (i for i, (_, text) in enumerate(steps) if "-m evals.gate" in text),
        None,
    )
    export_at = next(
        (i for i, (_, text) in enumerate(steps) if "eval_dump_stages.py" in text),
        None,
    )

    assert gate_at is not None, "the gate step is gone"
    assert export_at is not None, "the export step is gone"
    assert export_at > gate_at, (
        "the export runs before the gate, so it exports nothing: the rows it "
        "reads are written by the gate"
    )


def test_the_export_is_not_conditional_on_the_gate_passing(job: Job) -> None:
    """A gate that fails is the case worth keeping evidence for.

    `success()` is the default for a step whose predecessor failed, so a step
    with no `if:` of its own does not run after a red gate — and the evidence
    that would explain the red gate is exactly what would be missing.
    """
    body = str(job["body"])
    export_step = next(
        text for _, text in _steps(body) if "eval_dump_stages.py" in text
    )

    condition = re.search(r"^\s+if: (.*)$", export_step, re.M)
    assert condition is not None, (
        "the export step has no `if:`, so it inherits success() and is skipped "
        "when the gate fails — which is the only run whose evidence is wanted"
    )
    assert "always()" not in condition.group(1), (
        "the export is behind always(), which would run it even when the gate "
        "never ran at all"
    )
    assert "steps.gate" not in condition.group(1), (
        "the export is conditional on the gate's outcome"
    )


def test_the_evidence_is_uploaded_on_the_failure_path(job: Job) -> None:
    """`always()` on the upload, which is what keeps a red run diagnosable."""
    body = str(job["body"])
    upload_step = next(
        (text for _, text in _steps(body) if "actions/upload-artifact" in text), None
    )

    assert upload_step is not None, "no artifact is uploaded: the evidence dies with the runner"
    condition = re.search(r"^\s+if: (.*)$", upload_step, re.M)
    assert condition is not None and "always()" in condition.group(1), (
        "the upload is not behind always(), so it is skipped when the gate fails"
    )


def test_an_empty_upload_is_an_error_not_a_success(job: Job) -> None:
    """An upload step that finds nothing reports success with nothing in it,
    which is KI-42's failure mode one level up: a green step that means there
    is no evidence."""
    body = str(job["body"])
    upload_step = next(text for _, text in _steps(body) if "actions/upload-artifact" in text)

    assert re.search(r"^\s+if-no-files-found: error$", upload_step, re.M), (
        "an empty artifact upload must fail the job, not pass it"
    )


def test_the_artifact_carries_both_the_export_and_the_gate_log(job: Job) -> None:
    """The export is the per-item evidence; the log is the comparison itself —
    the baseline, the current numbers and every `GATE FAIL` line. Without the
    log the artifact says what the items were but not what the gate decided."""
    body = str(job["body"])
    upload_step = next(text for _, text in _steps(body) if "actions/upload-artifact" in text)
    paths = re.findall(r"^\s+(\.data/evals/\S+)$", upload_step, re.M)

    assert any(path.endswith("*.json") for path in paths), "the run summaries are not uploaded"
    assert any(path.endswith("gate.log") for path in paths), "the gate's own log is not uploaded"


def test_the_gate_output_is_tee_d_to_the_log(job: Job) -> None:
    """A log file that is never written is an artifact path that silently
    matches nothing, and the `GATE FAIL:` lines are the run's verdict.

    `pipefail` is what keeps the tee from swallowing the gate's exit status:
    without it the pipeline succeeds whenever `tee` succeeds, and the gate
    would report green on a red comparison — the one failure this whole job
    exists to prevent.
    """
    body = str(job["body"])
    gate_step = next(text for _, text in _steps(body) if "-m evals.gate" in text)

    assert "pipefail" in gate_step, (
        "without pipefail the tee pipeline's exit status is tee's, and a failed "
        "gate reports success"
    )
    assert re.search(r"-m evals\.gate .*\| tee \.data/evals/gate\.log", gate_step, re.S), (
        "the gate's stdout and stderr are not captured to the log"
    )