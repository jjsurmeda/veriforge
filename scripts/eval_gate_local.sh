#!/usr/bin/env bash
# Run the TRD §15 eval gate against a fresh, ephemeral database, so a local
# baseline and the CI gate measure the same thing.
#
# Why this exists (D3 item 2). `make acceptance` and a bare
# `python -m evals.gate` both ran against the long-lived development database,
# where the eval user can see the Shared library (11 Gutenberg books) as well
# as the 7 seed-corpus documents. CI loads only `evals/seed/corpus` into a
# fresh database. Two consequences, both of which made a local number
# incomparable with the gate: the D1 book twins were near-misses locally and
# declined trivially in CI, and the `not_in_sources` items only abstained
# because the out-of-scope answer was sitting right there (KI-24).
#
# So the database is created empty and destroyed afterwards, and the steps are
# the ones ci.yml's eval-gate job runs, in the same order, against the same
# image (the local `db` service *is* `paradedb/paradedb:0.25.9-pg16`, which is
# what the CI job's service runs):
#
#   migrations -> evals.loader -> evals.gate
#
# Usage:
#   make eval-gate-local                    # gate the fast20 subset
#   make eval-gate-local BASELINE=1         # also rewrite baseline_fast20.json
#   scripts/eval_gate_local.sh --items 47   # the full seed set instead of fast20
#
# Baselines are written only this way. `evals/seed/baseline_fast20.json` is the
# file ci.yml's gate compares against, and a number measured over a different
# corpus or a different set of models is not a comparison (evals.gate now
# refuses a model mismatch rather than reporting one).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api="$root/apps/api"
cd "$api"

# Same image and credentials as ci.yml's eval-gate service, but a database of
# its own. CI gets a fresh database from the service container; locally that
# is a fresh database inside the same ParadeDB container.
DB_NAME="${EVAL_GATE_DB:-veriforge_eval_gate}"
DB_PORT="${DB_PORT:-5432}"
DB_URL="postgresql+asyncpg://veriforge:veriforge@localhost:${DB_PORT}/${DB_NAME}"

if [ ! -x .venv/bin/python ]; then
  echo "apps/api/.venv is missing; run 'uv sync' in apps/api first" >&2
  exit 1
fi

psql_eval() {
  # The db service is the only thing in compose that has a psql client.
  docker compose -f "$root/compose.yaml" exec -T db \
    psql -U veriforge -d "${1:-postgres}" -v ON_ERROR_STOP=1 -qtAX -c "$2"
}

echo "==> fresh database ${DB_NAME}"
# DROP ... WITH (FORCE) also evicts connections left by an interrupted run;
# without it a killed run leaves the next one unable to create the database.
psql_eval postgres "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)"
psql_eval postgres "CREATE DATABASE ${DB_NAME}"

cleanup() {
  local code=$?
  echo "==> dropping ${DB_NAME}"
  psql_eval postgres "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)" || true
  return $code
}
trap cleanup EXIT

# CI's job runs alembic then the loader. Procrastinate's own schema is applied
# too, because the api service's command does it and the eval runner opens a
# session on the same database; if a future run needs it, it is already here.
echo "==> migrations"
DATABASE_URL="$DB_URL" .venv/bin/python -m alembic upgrade head
DATABASE_URL="$DB_URL" .venv/bin/python -m procrastinate --app=ingest.worker.app \
  schema --apply >/dev/null 2>&1 || echo "    (procrastinate schema already applied)"

echo "==> seed items + corpus (7 AW-2000 documents, eval user only)"
DATABASE_URL="$DB_URL" .venv/bin/python -m evals.loader

gate_status=0
if [ "${BASELINE:-0}" = "1" ]; then
  echo "==> writing baseline_fast20.json from this run"
  DATABASE_URL="$DB_URL" .venv/bin/python -m evals.runner --subset fast20 --baseline || gate_status=$?
else
  echo "==> gate: fast20 vs baseline_fast20.json"
  DATABASE_URL="$DB_URL" .venv/bin/python -m evals.gate || gate_status=$?
fi

# Read the per-stage latency breakdown back out of eval_results. The gate's own
# summary does not carry it, the database is about to be dropped, and P3's
# latency work needs the numbers. Read-only; it calls no provider. It runs even
# when the gate failed, because a failing run is exactly when the stage
# breakdown matters most.
echo "==> per-stage latency and per-item detail"
DATABASE_URL="$DB_URL" .venv/bin/python scripts/eval_dump_stages.py || true

exit "$gate_status"