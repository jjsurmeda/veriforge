"""`make check-work` step 6 (the books acceptance set) is wired, not aspirational.

Two properties of the step are the whole point of the brief and neither is
visible in the Python: it runs the *pinned* script rather than `make acceptance`
(which scores the dev stack, i.e. the main checkout's code), and it fails when
the api it measured is not serving HEAD. Both are shell, so they are pinned here
rather than left to review — a step that quietly reverts to `make acceptance`
would score the wrong commit and still go green.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CHECK_WORK = ROOT / "scripts" / "check_work.sh"
ACCEPTANCE_LOCAL = ROOT / "scripts" / "acceptance_local.sh"


def test_check_work_runs_the_acceptance_step() -> None:
    script = CHECK_WORK.read_text()
    assert "acceptance_books" in script
    assert 'step "acceptance:' in script


def test_the_acceptance_step_is_after_entity_mismatch() -> None:
    """Order matters: entity-mismatch is the cheap abstention check, the
    57-item run is the expensive one, so the expensive step never runs on a tree
    that already failed."""
    script = CHECK_WORK.read_text()
    assert script.index('step "eval: entity-mismatch') < script.index('step "acceptance:')


def test_the_step_does_not_call_make_acceptance() -> None:
    """`make acceptance` talks to the running dev stack, which serves the main
    checkout's code. In a worktree that scores the wrong commit."""
    # Compared over non-comment lines only: the script names `make acceptance`
    # in the comment saying why it does not call it.
    commands = [
        line.strip()
        for line in CHECK_WORK.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not any("make acceptance" in line for line in commands), commands
    assert any("scripts/acceptance_local.sh" in line for line in commands)


def test_the_step_fails_when_the_served_commit_is_not_head() -> None:
    script = ACCEPTANCE_LOCAL.read_text()
    assert 'git -C "$root" rev-parse HEAD' in script
    # The comparison, and the failure it causes.
    assert '[ "$served" != "$head_sha" ]' in script
    assert "ACCEPTANCE FAIL: the api is serving" in script


def test_the_served_commit_is_read_from_the_api_not_assumed() -> None:
    """The whole check is worthless if the script supplies the number itself."""
    script = ACCEPTANCE_LOCAL.read_text()
    assert "${API_URL}/healthz" in script
    assert 'print(json.load(sys.stdin).get("served_commit"' in script


def test_the_summary_path_is_explicit_and_stdout_is_not_scraped() -> None:
    """As `--summary-out` was done for the runner: LiteLLM and Langfuse both
    write to stdout, so a verdict read out of the printed output is a verdict
    read out of a log."""
    script = ACCEPTANCE_LOCAL.read_text()
    assert "--summary-out" in script
    assert "evals.acceptance_gate" in script