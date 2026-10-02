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

* the export runs **after** the gate and **before** the database is gone, and on
  the failure path as well as the success path;
* the artifact is uploaded with `always()`, so a red gate still keeps its
  evidence;
* `if-no-files-found: error`, so an empty upload fails instead of reporting
  success with nothing in it;
* `.data/evals` exists before `tee` opens the log, or `pipefail` turns a passing
  gate into a failed step.

The first and the last of those two were both wrong in the first version of this
work, and a CI run is what caught them — see the two tests that name the run.
"""

import posixpath
import re
from pathlib import Path, PurePosixPath

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


def test_the_export_runs_even_when_the_gate_fails(job: Job) -> None:
    """A gate that fails is the case worth keeping evidence for.

    `always()` is load-bearing, and the subtlety is that an `if:` which looks
    unconditional is not. GitHub gives a step with no status check function an
    implicit `success()`, so

        if: steps.scope.outputs.applies == 'true'

    means "the gate passed AND the scope check said yes" — the exact opposite of
    what it reads like. The export is then skipped on every red gate, which is
    precisely the run whose evidence is wanted.

    This was written the other way round first, and CI run 36982769288 proved
    it: the gate failed, the export never ran, and the artifact went up with a
    single 621-byte summary and no per-item evidence in it.
    """
    body = str(job["body"])
    export_step = next(text for _, text in _steps(body) if "eval_dump_stages.py" in text)

    condition = re.search(r"^\s+if: (.*)$", export_step, re.M)
    assert condition is not None, "the export step has no `if:` at all"
    assert "always()" in condition.group(1), (
        "without always() this step inherits success() and is skipped when the "
        "gate fails — the run whose evidence is wanted (CI run 36982769288)"
    )
    assert "steps.gate" not in condition.group(1), (
        "the export must not be conditional on the gate's outcome"
    )


def test_the_gate_log_directory_exists_before_tee_opens_it(job: Job) -> None:
    """`tee` opens its output file when the pipeline *starts*.

    The directory is otherwise created by `evals.baseline.record` inside the
    gate, six minutes into a run — so without an explicit `mkdir` first, tee
    exits non-zero on the missing directory, and `pipefail` (which item 3 put
    there to stop a failed gate reporting green) turns a *passing* gate into a
    failed step. Also CI run 36982769288: the gate passed at 0.96042 and the job
    went red on this line.
    """
    body = str(job["body"])
    gate_step = next(text for _, text in _steps(body) if "-m evals.gate" in text)

    mkdir_at = gate_step.find("mkdir -p ")
    tee_at = gate_step.find("| tee ")

    assert mkdir_at != -1, (
        "the gate step never creates the evidence directory, so tee cannot open its log"
    )
    assert tee_at != -1, "the gate output is not tee'd"
    assert mkdir_at < tee_at, (
        "the mkdir must come before the tee; tee opens the file as the pipeline starts, "
        "not when the gate finishes"
    )


def test_the_gate_log_is_written_where_the_upload_looks_for_it(job: Job) -> None:
    """The tee and the upload have to name the same file, and they resolve
    relative paths differently.

    `run` steps inherit `defaults.run.working-directory` (`apps/api` here);
    a `uses:` step — `actions/upload-artifact` — does **not**, and resolves its
    paths against the workspace root. So the same string means two different
    files in the same job.

    CI run 36983971448 is the proof: the job went green, the artifact contained
    the two run summaries (written by `evals.baseline` at the repo root) and the
    45 KB per-item export, and no `gate.log` at all — the tee had written it to
    `apps/api/.data/evals/`. Green, with evidence missing, which is the failure
    this whole item exists to prevent.

    So the two paths are compared as *resolved files*, not as strings.
    """
    body = str(job["body"])
    gate_step = next(text for _, text in _steps(body) if "-m evals.gate" in text)
    upload_step = next(text for _, text in _steps(body) if "actions/upload-artifact" in text)

    written = re.search(r"\|\s*tee\s+(\S+)", gate_step)
    assert written is not None, "the gate output is not tee'd to a file"
    # `run` steps resolve against the job's working-directory, so the path is
    # normalised to get the file it actually names.
    written_path = PurePosixPath(posixpath.normpath(f"apps/api/{written.group(1)}"))

    uploaded = [
        PurePosixPath(posixpath.normpath(path))
        for path in re.findall(r"^\s+(\S+\.(?:log|json))$", upload_step, re.M)
    ]
    assert uploaded, "the upload step lists no files"
    # `uses:` steps resolve against the workspace root.
    assert written_path in uploaded, (
        f"the gate writes its log to {written_path} but the upload only collects "
        f"{uploaded}: a `uses:` step does not inherit the job's working-directory, "
        "so the artifact ships without the log and the run looks green anyway"
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

    `set -o pipefail` is what keeps the tee from swallowing the gate's exit
    status: without it the pipeline succeeds whenever `tee` succeeds, and the
    gate would report green on a red comparison — the one failure this whole job
    exists to prevent.

    Both are matched as whole lines rather than as substrings. A substring match
    is satisfied by the comment above them explaining why they are there, which
    is exactly what happened when this test was first written: deleting
    `set -o pipefail` left it green, because the comment naming it survived.
    """
    body = str(job["body"])
    gate_step = next(text for _, text in _steps(body) if "-m evals.gate" in text)

    assert re.search(r"^\s*set -o pipefail\s*$", gate_step, re.M), (
        "without `set -o pipefail` the tee pipeline's exit status is tee's, and a "
        "failed gate reports success"
    )
    tee = r"^\s*uv run python -m evals\.gate 2>&1 \| tee (\S+)\s*$"
    assert re.search(tee, gate_step, re.M), (
        "the gate's stdout and stderr are not captured to the log"
    )