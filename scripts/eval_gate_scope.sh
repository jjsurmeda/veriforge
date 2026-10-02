#!/usr/bin/env bash
# Decide whether the TRD §15 eval gate applies to this event, and say why.
#
# Prints two lines, in the form `ci.yml` writes straight into `$GITHUB_OUTPUT`:
#
#   applies=true|false
#   reason=<text>          (empty only when the gate will really run)
#
# `reason` is empty only when the gate will really run. A skip is reported
# with its cause instead of passing silently: a green eval-gate job that
# never called OpenRouter is not evidence that the gate passed, and reading
# it as one is how the baseline went unrecorded for three runs (KI-6).
#
# Usage:
#   scripts/eval_gate_scope.sh <event> <before> <sha> [base-ref]
#
#     event     github.event_name. `push` and everything else are two
#               different questions, and answering them with one command is
#               what skipped the gate on `main` (D8 item 1).
#     before    github.event.before: the commit a push moved from. Empty on a
#               workflow_dispatch; all zeros when a branch is created.
#     sha       github.sha: the commit being checked out.
#     base-ref  the ref a non-push event diffs against. Default origin/main.
#
# This is a script and not a shell one-liner inside ci.yml because the
# workflow is the one place a bug cannot report itself: a scope check that
# wrongly says "applies=false" produces a green job that measured nothing,
# and looks identical to a pass. D6 fixed this step twice and D7 changed it
# a third time with no test each time. `apps/api/tests/evals/test_gate_scope.py`
# runs it against a temporary git repository, so the decision is checked
# rather than re-argued.
#
# Exit status: 0 when a decision was reached (true *or* false), non-zero when
# it could not be. An undecidable scope is a failed job, never a skip — the
# difference between "nothing gated changed" and "I could not tell".
set -euo pipefail

event="${1:?usage: eval_gate_scope.sh <event> <before> <sha> [base-ref]}"
before="${2:-}"
sha="${3:-}"
base_ref="${4:-origin/main}"

# The gated paths (TRD §15). The four product packages whose behaviour the
# gate judges, plus the three that carry the gate's own parameters:
#   apps/api/evals/    the runner, the comparison and the thresholds
#   evals/seed/        the baseline file, the items and the corpus
#   apps/api/providers/  the models that carry the parameters those runs measure
#
# The last three are in scope because a change to the gate's own limits, or
# to the file it compares against, is invisible to every unit test and
# invisible to a skipped gate: a tolerance widened to 0.5, or a baseline
# written from a favourable run, would both have gone green here. That is the
# same failure D6 found twice — a green eval-gate job that never called
# OpenRouter read as a pass — one level up, on the branch whose whole subject
# is the gate.
gated_paths='^(apps/api/(graph|retrieval|decisions|prompts|evals|providers)/|evals/seed/)'

emit() {
  echo "applies=$1"
  echo "reason=$2"
}

all_zeros() {
  [ -z "$1" ] || printf '%s' "$1" | grep -Eq '^0+$'
}

resolvable() {
  git rev-parse --verify --quiet "$1^{commit}" >/dev/null
}

case "$event" in
  push)
    # The event carries the parent it moved from, so `before..sha` is the
    # diff that decides the scope. `before` is not always available: it is
    # empty on a workflow_dispatch and all zeros on a branch creation.
    # Neither is a reason to skip — a scope that cannot be decided must not
    # read as "nothing gated changed". That silent skip is precisely what a
    # merge-base gives on a push to `main`, where HEAD *is* the new
    # origin/main: the merge-base is HEAD, the diff is empty, and the push
    # TRD §15 gates on the merge reported `applies=false`. Run 36970934461
    # (the D1-D6 merge) skipped this way.
    if all_zeros "$before"; then
      emit true "the push reports no parent commit (before is missing or all zeros); the gate runs rather than skips on an unknown diff"
      exit 0
    fi
    if ! resolvable "$before"; then
      echo "::error::the push's parent $before is not in this clone (shallow fetch?); the gate's scope check cannot decide"
      exit 1
    fi
    base="$before"
    echo "comparing the push $sha against its parent $base" >&2
    ;;
  *)
    # The scope is the BRANCH, not the last commit. A workflow_dispatch checks
    # out one commit, so `HEAD~1..HEAD` sees only that commit and reports "no
    # gated paths" for a branch whose earlier commits changed them — the gate
    # would skip on exactly the pushes it exists for. So diff against the
    # merge-base with main, which is what the gate is actually protecting.
    if ! resolvable "$base_ref"; then
      echo "::error::$base_ref is not fetched; the gate's scope check cannot decide"
      exit 1
    fi
    base=$(git merge-base "$sha" "$base_ref" || true)
    if [ -z "$base" ]; then
      echo "::error::no merge-base between $sha and $base_ref; the gate's scope check cannot decide"
      exit 1
    fi
    echo "comparing against merge-base $base" >&2
    ;;
esac

changed=$(git diff --name-only "$base" "$sha" | grep -E "$gated_paths" || true)
if [ -n "$changed" ]; then
  echo "gated paths in this diff:" >&2
  echo "$changed" >&2
  emit true ""
else
  emit false "no graph/retrieval/decisions/prompts/evals/providers or evals/seed change in this diff"
fi