#!/usr/bin/env bash
# Phase 1 finish line: does the product *work*? (`make check-work`)
#
# Five steps, in order, stopping at the first failure, each reporting one
# PASS/FAIL line with the number that decided it:
#
#   1. api unit gate   ruff, mypy --strict, pytest (apps/api)
#   2. web unit gate   vitest, OpenAPI export + drift check
#   3. model defaults  no `:free` reachable from a config or seed default
#   4. eval gate       fast20 AND the counterfactual subset, against the
#                      stored baselines, each on a fresh ephemeral database
#   5. entity-mismatch 12/12 clean declines, 0 confident wrong, 0 errored,
#                      on a fresh ephemeral database
#
# Steps 4 and 5 SPEND PROVIDER CREDIT. They are the reason this is not a
# three-minute command: a fast20 gate run with its retry-to-mean-of-3 is a few
# live runs against OpenRouter, and entity-mismatch is 12 more. Check the
# balance (`GET https://openrouter.ai/api/v1/credits`) before starting; the
# floor for a lane is in docs/conventions/agents.md.
#
# Steps 4-5 are classified from each run's own recorded fields — the gate's
# verdict, and `evals.entity_gate` reading the runner's summary JSON. Nothing
# here infers an outcome from a stream: a decline streams a delta too, and
# lane B2's probe nearly reported a false failure rate for exactly that reason.
#
# Everything is re-runnable; no step depends on another's leftovers, and the
# eval steps drop their databases on exit.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api="$root/apps/api"
web="$root/apps/web"
cd "$root"

# `TEST_DATABASE_URL` defaults to the main checkout's test database. A lane in
# its own worktree exports its own (agents.md, "Parallel work").
: "${TEST_DATABASE_URL:=postgresql+asyncpg://veriforge:veriforge@localhost:5432/veriforge_test}"
export TEST_DATABASE_URL
# The dev stack's compose project, so `eval_gate_local.sh`'s `docker compose
# exec db` finds the running db container from any worktree.
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-veriforge}"
# The ephemeral gate database; a lane running in parallel exports its own name
# so two lanes cannot collide on it.
: "${EVAL_GATE_DB:=veriforge_eval_gate}"
export EVAL_GATE_DB

failed_step=""
start_of_step=0

step() {
  # One step: name it, run it, report PASS or FAIL with whatever the step
  # printed already visible above the line.
  local name="$1"
  shift
  echo
  echo "──────────────────────────────────────────────────────────────"
  echo "▶ $name"
  echo "──────────────────────────────────────────────────────────────"
  start_of_step=$SECONDS
  if "$@"; then
    printf 'PASS  %s  (%ds)\n' "$name" "$((SECONDS - start_of_step))"
  else
    printf 'FAIL  %s  (%ds)\n' "$name" "$((SECONDS - start_of_step))"
    failed_step="$name"
    report
    exit 1
  fi
}

report() {
  echo
  if [ -z "$failed_step" ]; then
    echo "check-work: PASS — the product works on $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
  else
    echo "check-work: FAIL at '$failed_step' on $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
    echo "Steps after a failure do not run: a later PASS on a tree that failed an"
    echo "earlier step is not evidence that the tree works."
  fi
}

# ── 1. api unit gate ──────────────────────────────────────────────────────────
api_ruff() { (cd "$api" && .venv/bin/python -m ruff check .); }
api_mypy() { (cd "$api" && .venv/bin/python -m mypy .); }
api_pytest() { (cd "$api" && .venv/bin/python -m pytest -q); }

# ── 2. web unit gate ──────────────────────────────────────────────────────────
web_vitest() {
  # `codegen:ci` first, and this is not optional: `src/generated/` is
  # gitignored (git.md — "What doesn't get committed") and every feature
  # imports the SDK from it, so vitest cannot even transform a test file
  # without it. ci.yml's web job does the same in the same order.
  if [ ! -d "$web/node_modules" ]; then
    echo "apps/web/node_modules is missing; run 'npm ci' in apps/web first" >&2
    return 1
  fi
  (cd "$web" && npm run codegen:ci && npm run test)
}
web_openapi_drift() {
  # CI's api job (`.github/workflows/ci.yml`): export the served schema and
  # fail if the committed file differs. Same two commands, same meaning — a
  # schema change that forgot to regenerate is a web client built against a
  # model the server no longer serves.
  (cd "$api" && .venv/bin/python scripts/export_openapi.py) || return 1
  git diff --exit-code "$web/openapi.json"
}

# ── 3. model defaults ─────────────────────────────────────────────────────────
# No provider call, no database: `tests/settings/test_free_models.py` asserts
# the config defaults name no free id, that the seed's default path binds
# gpt-4o-mini with the catalogue fetch stubbed to fail if it is called, and
# that the production boot check refuses a free binding and accepts the paid
# one. Step 1 already ran the whole suite, so re-running those three tests
# here would print a second number for a verdict already reached; this reads
# the defaults directly instead, so a flipped default is named at the line
# where it is flipped. Duplicating the *rule* would be the failure — the
# assertions stay the single definition of what a free default is.
no_free_defaults() {
  local failures=0
  local defaults
  defaults="$(
    cd "$api" && .venv/bin/python - <<'PY'
from config import Settings, is_free_model
s = Settings(_env_file=None)
for name in ("fallback_model", "llm_fallback_model"):
    value = getattr(s, name)
    if is_free_model(value):
        print(f"{name}={value}")
PY
  )"
  if [ -n "$defaults" ]; then
    echo "config defaults resolve to a free model:"
    echo "$defaults" | sed 's/^/  /'
    failures=1
  fi
  # The seed's default path, read from the seed's own resolver rather than
  # re-stating the rule here.
  local seeded
  seeded="$(cd "$api" && .venv/bin/python - <<'PY'
from scripts.seed_models import resolve_model_id
print(resolve_model_id() or "FREE_POOL")
PY
)"
  case "$seeded" in
    FREE_POOL)
      echo "seed_models' default path is the free pool; it must be behind --free"
      failures=1
      ;;
    *:free|*/free)
      echo "seed_models' default path resolves to the free model $seeded"
      failures=1
      ;;
  esac
  [ "$failures" -eq 0 ] && echo "config fallbacks and the seed default are openai/gpt-4o-mini"
  return "$failures"
}

# ── 4 + 5. eval steps (these spend credit) ────────────────────────────────────
eval_gate_both_subsets() {
  # `evals.gate` runs the fast20 subset and the counterfactual gate subset in
  # one process with the same writer, retry and tolerances, and exits non-zero
  # if either fails — that is exactly what ci.yml's eval-gate job runs, so the
  # verdict here is the CI verdict. A fresh ephemeral database, per D3 item 2.
  "$root/scripts/eval_gate_local.sh"
}

entity_mismatch_clean() {
  local summary="$root/.data/evals/summary-entity_mismatch.json"
  rm -f "$summary"
  "$root/scripts/eval_gate_local.sh" --dataset entity_mismatch || return 1
  # Verdict from the run's own fields — `failed`, `clean_declines`,
  # `confident_wrong_answers` — never inferred from the stream.
  (cd "$api" && .venv/bin/python -m evals.entity_gate "$summary")
}

echo "check-work on $(git rev-parse --short HEAD 2>/dev/null || echo '?') (test db: ${TEST_DATABASE_URL##*/})"
echo "Steps 4-5 spend OpenRouter credit."

step "api: ruff check" api_ruff
step "api: mypy --strict" api_mypy
step "api: pytest" api_pytest
step "web: openapi export + drift" web_openapi_drift
step "web: codegen + vitest" web_vitest
step "models: no :free default" no_free_defaults
step "eval gate: fast20 + counterfactual" eval_gate_both_subsets
step "eval: entity-mismatch 12/12" entity_mismatch_clean

report