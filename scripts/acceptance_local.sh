#!/usr/bin/env bash
# Phase 1b step 9: the books acceptance set, against an api pinned to this
# checkout (`make check-work`).
#
# Why a script of its own rather than a `make acceptance` call: **`make
# acceptance` talks to the running dev stack, which serves the main checkout's
# code.** In a worktree that means the run scores a different commit from the
# one under test and reports it as if it were this branch — the false report
# agents.md exists to prevent. So this script brings its own api up from this
# checkout, against its own database, and *proves* which commit that api serves:
# it reads the served commit off the api's `/healthz` and fails when it is not
# `git rev-parse HEAD`. The comparison is a step condition, not advice, because
# "the api might be stale" is exactly what has to be caught.
#
# The database is per-lane (`ACCEPTANCE_DB`), so two worktrees never share a
# library or an eval account's quota ledger. Books are ingested over the real
# HTTP upload path with the workers this stack starts, because an acceptance run
# against a library nothing ingested measures an empty one.
#
# Spends provider credit: a full run is 57 items. Check the OpenRouter balance
# first (docs/conventions/agents.md, "Credit pre-flight").
#
# Usage:
#   scripts/acceptance_local.sh                 # the whole set
#   scripts/acceptance_local.sh id1,id2         # only these items (fixing)
#   ACCEPTANCE_FRESH=1 scripts/acceptance_local.sh   # rebuild the library
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api="$root/apps/api"
cd "$api"

# The api reads `env_file=".env"` relative to the working directory, and the
# provider keys live in the *root* `.env`. Same trap eval_gate_local.sh
# documents: without this every Jev call raises "not set", the breaker opens,
# and 57 items come back as fallback errors — a harness fault dressed as a
# product failure. Explicitly-exported variables still win.
if [ -f "$root/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$root/.env"
  set +a
fi

if [ ! -x .venv/bin/python ]; then
  echo "apps/api/.venv is missing; run 'uv sync' in apps/api first" >&2
  exit 1
fi

# A lane exports its own so a parallel worktree gets its own library and its own
# quota ledger (agents.md, "Parallel work").
DB_NAME="${ACCEPTANCE_DB:-veriforge_accept}"
PORT="${ACCEPTANCE_PORT:-8123}"
API_URL="http://127.0.0.1:${PORT}"
SUMMARY_OUT="${ACCEPTANCE_SUMMARY_OUT:-$root/.data/evals/summary-acceptance.json}"
ITEMS="${1:-}"
# ACCEPTANCE_SET picks another set file (evals/heldout/items.json). The stack
# must have been built with the matching GUTENBERG_SET so its library holds the
# books that set asks about.
SET_ARGS=()
if [ -n "${ACCEPTANCE_SET:-}" ]; then
  SET_ARGS=(--set "$ACCEPTANCE_SET")
fi
# OpenRouter's free tier caps free-model requests at 20/min account-wide.
# A full 57-item acceptance run needs ~114 calls; without pacing the cap is hit
# around item 10 and every subsequent chat creation returns a 429. 6 s between
# non-smalltalk items keeps the pace under the cap (10 items/min, 20 calls/min).
PACE="${ACCEPTANCE_PACE:-0}"
STACK_LOG="$root/.data/acceptance-stack.log"

export ACCEPTANCE_DB="$DB_NAME"
export ACCEPTANCE_PORT="$PORT"

head_sha="$(git -C "$root" rev-parse HEAD)"
echo "==> acceptance: HEAD ${head_sha:0:12}, database ${DB_NAME}, port ${PORT}"

reusing=0
if [ -z "${ACCEPTANCE_FRESH:-}" ] && curl -sf "${API_URL}/healthz" >/dev/null 2>&1; then
  # An api from this checkout is already up on this port. Reused deliberately:
  # re-ingesting eleven books costs minutes and no credit, and a reused stack is
  # the same code either way — the served-commit check below is what makes the
  # reuse safe, and it runs on this path too.
  reusing=1
  echo "==> reusing the api already serving ${API_URL}"
fi

cleanup() {
  local code=$?
  if [ "$reusing" -eq 0 ]; then
    echo "==> stopping the acceptance stack"
    "$root/scripts/acceptance_stack.sh" down || true
  fi
  return $code
}
trap cleanup EXIT

if [ "$reusing" -eq 0 ]; then
  # `up` creates the database, migrates it, seeds the eval user and the eval
  # corpus, starts the api and the ingest workers from THIS checkout, and then
  # uploads the books over HTTP (a few minutes; the texts are cached).
  "$root/scripts/acceptance_stack.sh" up
fi

if ! curl -sf "${API_URL}/healthz" >/dev/null 2>&1; then
  echo "the acceptance api is not answering on ${API_URL}; see $STACK_LOG" >&2
  exit 1
fi

# The proof, read from the api itself rather than from this script's assumption
# about which checkout it started. `unknown` (no git in the image, or an api
# predating the field) fails here rather than passing silently.
served="$(curl -sf "${API_URL}/healthz" | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin).get("served_commit","unknown"))')"
echo "==> api serving commit ${served}"
if [ "$served" != "$head_sha" ]; then
  echo "ACCEPTANCE FAIL: the api is serving ${served}, but HEAD is ${head_sha}." >&2
  echo "  A run against the wrong checkout scores the wrong code. Stop the stale" >&2
  echo "  api (scripts/acceptance_stack.sh down) or use another ACCEPTANCE_PORT." >&2
  exit 1
fi

mkdir -p "$(dirname "$SUMMARY_OUT")"
rm -f "$SUMMARY_OUT"

# `--summary-out` rather than parsing the printed table: LiteLLM and Langfuse
# both write to stdout during a run, and stdout is the operator's log. The runner
# writes the counts itself, from the per-item fields it recorded.
echo "==> running the acceptance set${ITEMS:+ (items: $ITEMS)}"
runner_status=0
if [ -n "$ITEMS" ]; then
  VERIFORGE_API_URL="$API_URL" EVAL_USER_EMAIL="$EVAL_USER_EMAIL" \
    EVAL_USER_PASSWORD="$EVAL_USER_PASSWORD" \
    .venv/bin/python scripts/acceptance.py "$ITEMS" ${SET_ARGS[@]+"${SET_ARGS[@]}"} --summary-out "$SUMMARY_OUT" --pace "$PACE" \
    || runner_status=$?
else
  VERIFORGE_API_URL="$API_URL" EVAL_USER_EMAIL="$EVAL_USER_EMAIL" \
    EVAL_USER_PASSWORD="$EVAL_USER_PASSWORD" \
    .venv/bin/python scripts/acceptance.py ${SET_ARGS[@]+"${SET_ARGS[@]}"} --summary-out "$SUMMARY_OUT" --pace "$PACE" \
    || runner_status=$?
fi
if [ "$runner_status" -ne 0 ]; then
  # The runner exits 0 whatever the items did, so a non-zero here is a harness
  # failure (it could not sign in, or the stack went away mid-run). The gate
  # still runs: it reports why the step failed in PRD §5 terms as well.
  echo "==> the runner itself failed (exit $runner_status)" >&2
fi

# The verdict, classified from the summary's own fields. `|| gate_status=$?`
# rather than reading `$?` after the call: under `set -e` a non-zero exit ends
# the script before the status is ever captured, which would report a gate
# failure as a bare non-zero with no verdict printed.
gate_status=0
.venv/bin/python -m evals.acceptance_gate "$SUMMARY_OUT" || gate_status=$?

if [ "$runner_status" -ne 0 ]; then
  exit "$runner_status"
fi
exit "$gate_status"