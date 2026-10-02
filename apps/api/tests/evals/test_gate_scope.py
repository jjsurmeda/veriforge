"""The gate's scope decision is a script, and this tests it against real git.

`scripts/eval_gate_scope.sh` decides whether the TRD §15 eval gate runs. It
existed as a shell one-liner inside `.github/workflows/ci.yml` until D8 item 2,
and a bug in it cannot report itself: a scope check that wrongly answers
`applies=false` produces a green eval-gate job that measured nothing, which is
indistinguishable from a pass. It has now been wrong three times — D6 fixed it
twice, D7 changed it a third time — each time with no test, each time found by a
CI run or a live gate run rather than by a unit test.

So the tests run the actual script, against a temporary git repository with
actual commits, rather than against a description of it. A test that mocks git
would pass while the command line is wrong, which is how all three of the
previous bugs looked from the inside: each one was a *correct* piece of git
being asked the wrong question.

The properties worth pinning, each of which is a bug that has shipped:

* a **push** is scoped by `before..sha` — the commit it moved from. A
  merge-base answers a different question, and on a push to `main` it answers
  it with HEAD: the pushed commit *is* the new `origin/main`, the diff is empty,
  and the gate skips on exactly the merge TRD §15 gates on. Run 36970934461,
  the D1-D6 merge, skipped that way.
* a **push with no usable `before`** (empty, or all zeros from a branch
  creation) is `true`, not `false`. A scope that cannot be decided must never
  read as "nothing gated changed".
* a **workflow_dispatch** on a branch is scoped by the whole branch, via its
  merge-base with `origin/main` — a dispatch checks out one commit, so a
  last-commit diff misses the branch's earlier gated changes.
* the **gated paths** include the gate's own parameters (`apps/api/evals/`,
  `evals/seed/`, `apps/api/providers/`). A change to the tolerance or to the
  baseline file is invisible to every unit test and invisible to a skipped gate.
"""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "eval_gate_scope.sh"
ZERO_SHA = "0" * 40


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _commit(repo: Path, name: str, content: str = "x") -> str:
    """One commit adding `name`, with content, on whatever branch is checked out."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{content}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Path]:
    """A git repo shaped like the real one: `main`, then a feature branch off it.

    `origin/main` is a *local ref* rather than a real remote, which is what the
    merge-base path needs and is all the script asks of it.
    """
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "test@example.invalid")
    _git(work, "config", "user.name", "test")
    # main needs a root commit so the branch has something to fork from.
    _commit(work, "README.md")
    _git(work, "update-ref", "refs/remotes/origin/main", "HEAD")
    yield work


def scope(repo: Path, event: str, before: str, sha: str) -> dict[str, str]:
    """Run the script and parse its `key=value` output."""
    out = subprocess.run(
        [str(SCRIPT), event, before, sha],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    parsed: dict[str, str] = {}
    for line in out.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            parsed[key] = value
    return parsed


def applies(repo: Path, event: str, before: str, sha: str) -> str:
    return scope(repo, event, before, sha)["applies"]


# --- a push is scoped by its own parent ---------------------------------------


def test_a_push_touching_graph_applies(repo: Path) -> None:
    """The gate's reason for existing: a product change on a push."""
    base = _git(repo, "rev-parse", "HEAD")
    sha = _commit(repo, "apps/api/graph/auto.py")

    assert applies(repo, "push", base, sha) == "true"


def test_a_push_touching_only_docs_does_not_apply(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    sha = _commit(repo, "docs/notes.md")

    result = scope(repo, "push", base, sha)

    assert result["applies"] == "false"
    # A skip always says why, so a green job can be read as "did not run"
    # rather than "passed".
    assert result["reason"]


# --- the push's own parameters are in scope -----------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/evals/gate.py",  # the comparison and its thresholds
        "evals/seed/baseline_fast20.json",  # the file it compares against
        "evals/seed/items.json",  # the items and the corpus
        "apps/api/providers/catalogue.py",  # the models that carry the parameters
        "apps/api/prompts/answer.md",
    ],
)
def test_the_gates_own_parameters_are_gated_paths(repo: Path, path: str) -> None:
    """A tolerance widened to 0.5, or a baseline from a favourable run, would
    otherwise go green here — invisible to every unit test and to a skipped gate.
    That is D6's failure one level up."""
    base = _git(repo, "rev-parse", "HEAD")
    sha = _commit(repo, path)

    assert applies(repo, "push", base, sha) == "true"


@pytest.mark.parametrize("path", ["apps/web/src/App.tsx", "infra/cdk/app.py", "docs/TRD.md"])
def test_an_ungated_path_does_not_apply(repo: Path, path: str) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    sha = _commit(repo, path)

    assert applies(repo, "push", base, sha) == "false"


# --- an undecidable scope is never a skip --------------------------------------


@pytest.mark.parametrize("before", ["", ZERO_SHA])
def test_a_push_with_no_usable_parent_applies(repo: Path, before: str) -> None:
    """Empty `before` and the all-zeros `before` of a branch creation are the
    same fact: the diff cannot be computed.

    The failure mode this guards is a skip that reads as a pass. GitHub sends
    an all-zeros `before` when a branch is created, and an empty one when the
    event carries none — both arrive here as "I do not know what changed", and
    the answer must be "run the gate", not "nothing gated changed".
    """
    sha = _commit(repo, "apps/api/retrieval/hybrid.py")

    assert applies(repo, "push", before, sha) == "true"


def test_a_push_whose_parent_is_absent_fails_loudly(repo: Path) -> None:
    """Not decidable is not the same as false, and it must not be silent.

    A shallow clone cannot resolve `before`. The old one-liner read that
    failure as "no gated paths changed" and went green (KI-6); here it exits
    non-zero, which fails the job loudly instead of skipping quietly.
    """
    sha = _commit(repo, "apps/api/retrieval/hybrid.py")
    absent = "1" * 40

    result = subprocess.run(
        [str(SCRIPT), "push", absent, sha],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    # `::error::` goes to stdout on purpose: that is where GitHub reads
    # workflow annotations from, so a human sees it on the run page.
    assert result.returncode != 0
    assert "cannot decide" in result.stdout


# --- a branch is scoped as a branch --------------------------------------------


def test_a_dispatch_differs_the_whole_branch_through_the_merge_base(repo: Path) -> None:
    """A workflow_dispatch checks out ONE commit.

    So `HEAD~1..HEAD` sees only that commit and reports "no gated paths" for a
    branch whose *earlier* commit changed them — the gate skips on exactly the
    pushes it exists for. The scope is the branch, via its merge-base with
    origin/main.
    """
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "apps/api/decisions/engine.py")  # the gated change
    doc_only = _commit(repo, "docs/readme-2.md")  # the dispatched commit
    _git(repo, "update-ref", "refs/remotes/origin/feature", "HEAD")

    assert applies(repo, "workflow_dispatch", "", doc_only) == "true"
    # The last commit alone sees only docs/ — which is the bug, pinned.
    assert applies(repo, "push", _git(repo, "rev-parse", "HEAD~1"), doc_only) == "false"


def test_a_dispatch_on_an_unchanged_branch_does_not_apply(repo: Path) -> None:
    """The skip has to still be reachable, or the check is vacuous."""
    _git(repo, "checkout", "-q", "-b", "docs-only")
    sha = _commit(repo, "docs/design-refs/note.md")

    assert applies(repo, "workflow_dispatch", "", sha) == "false"


def test_a_dispatch_without_origin_main_fails_loudly(repo: Path) -> None:
    """An absent base ref is the shallow-clone case again, on the other path."""
    sha = _git(repo, "rev-parse", "HEAD")

    result = subprocess.run(
        [str(SCRIPT), "workflow_dispatch", "", sha, "origin/does-not-exist"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    # `::error::` goes to stdout on purpose: that is where GitHub reads
    # workflow annotations from, so a human sees it on the run page. The message
    # names the *fault*, not just the fact: an absent base ref and a base ref
    # unrelated to this history are different faults with different fixes, and
    # one loud failure is not evidence the other was diagnosed.
    assert result.returncode != 0
    assert "origin/does-not-exist is not fetched" in result.stdout
    assert "cannot decide" in result.stdout


def test_a_dispatch_with_no_merge_base_fails_loudly(repo: Path) -> None:
    """An unrelated history has no merge-base, and an empty answer must not be
    read as "diff against nothing", which diffs everything or nothing depending
    on the command."""
    _git(repo, "checkout", "-q", "--orphan", "unrelated")
    _git(repo, "rm", "-q", "-rf", ".")
    sha = _commit(repo, "apps/api/graph/auto.py")

    result = subprocess.run(
        [str(SCRIPT), "workflow_dispatch", "", sha],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    # `::error::` goes to stdout on purpose: that is where GitHub reads
    # workflow annotations from, so a human sees it on the run page. The message
    # names the *fault*, not just the fact: an absent base ref and a base ref
    # unrelated to this history are different faults with different fixes, and
    # one loud failure is not evidence the other was diagnosed.
    assert result.returncode != 0
    assert "no merge-base between" in result.stdout
    assert "cannot decide" in result.stdout


# --- the script the workflow runs is the script under test ----------------------


def test_ci_yml_calls_this_script_and_carries_no_scope_logic_of_its_own() -> None:
    """The test is worthless if the workflow grew its own copy of the decision.

    `ci.yml` used to hold the whole check, which is why none of it could be
    tested. So the workflow must call the script, and must not contain a second
    answer to the same question. The strings below are the scope decision
    specifically: the `api` job's codegen check is `git diff --exit-code
    ../web/openapi.json`, which is a different command and is left alone.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "eval_gate_scope.sh" in workflow, "ci.yml no longer calls the script"
    assert "git diff --name-only" not in workflow, "ci.yml diffs to decide scope again"
    assert "git merge-base" not in workflow, "ci.yml decides scope itself again"
    assert "^(apps/api/" not in workflow, "ci.yml carries its own gated-path pattern"


def test_the_script_is_executable_and_needs_nothing_installed(tmp_path: Path) -> None:
    """CI calls it before `uv sync`, and the scope check is the one step that
    cannot be skipped: a crash there is a failed merge, not a green job.

    So the script has to run on the bare runner image. Asserted by running it
    with `PATH` reduced to the base image's own toolchain, rather than by
    reading the script for forbidden words — which breaks on any edit while
    proving nothing about what actually executes.

    Its own throwaway repo, deliberately: the decision must not depend on how
    this branch compares with `main`, or the test breaks on the day it merges.
    """
    assert SCRIPT.stat().st_mode & 0o111, f"{SCRIPT} is not executable"

    repo = tmp_path / "bare"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _commit(repo, "README.md")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    sha = _commit(repo, "apps/api/prompts/answer.md")

    out = subprocess.run(
        [str(SCRIPT), "workflow_dispatch", "", sha],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo)},
    )

    assert "applies=true" in out.stdout