#!/usr/bin/env bash
# One-off helper for P1b item 6: a fresh database, the eval user, the seed
# corpus, and the Gutenberg books ingested through the real HTTP path, so
# `scripts/acceptance.py` has an isolated stack to run against.
#
# Isolated on purpose (docs/conventions/agents.md): a separate database and a
# separate api process, never the hot-reloading dev api.
#
#   ACCEPTANCE_DB=veriforge_accept scripts/acceptance_stack.sh up
#   ACCEPTANCE_DB=veriforge_accept scripts/acceptance_stack.sh down
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api="$root/apps/api"
cd "$api"

DB_NAME="${ACCEPTANCE_DB:-veriforge_accept}"
PORT="${ACCEPTANCE_PORT:-8123}"
# The db container belongs to the compose project the stack was started from,
# which is named after the checkout that started it. A worktree has to point at
# the running project explicitly or `docker compose exec` looks for a project
# of its own name and finds nothing.
COMPOSE_PROJECT="${ACCEPTANCE_COMPOSE_PROJECT:-veriforge}"
DB_URL="postgresql+asyncpg://veriforge:veriforge@localhost:5432/${DB_NAME}"
PSYCOPG_URL="postgresql://veriforge:veriforge@localhost:5432/${DB_NAME}"
PID_FILE="$root/.data/acceptance-stack.pid"
LOG_FILE="$root/.data/acceptance-stack.log"

if [ -f "$root/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$root/.env"
  set +a
fi

psql_eval() {
  docker compose -p "$COMPOSE_PROJECT" -f "$root/compose.yaml" exec -T db \
    psql -U veriforge -d "${1:-postgres}" -v ON_ERROR_STOP=1 -qtAX -c "$2"
}

case "${1:-up}" in
up)
  mkdir -p "$root/.data"
  psql_eval postgres "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)"
  psql_eval postgres "CREATE DATABASE ${DB_NAME}"

  echo "==> migrations"
  DATABASE_URL="$DB_URL" .venv/bin/python -m alembic upgrade head >/dev/null
  # Both variables, deliberately. procrastinate reads PROCRASTINATE_CONNINFO,
  # not DATABASE_URL, so setting only the latter silently applies the schema to
  # whatever database that string names — here the dev one, where the enum
  # already existed, so the step "succeeded" as already-applied and every
  # upload then 500'd on a deferred job with no queue to run it. Not `|| true`
  # either: a real failure must stop the stack, not surface four steps later.
  DATABASE_URL="$DB_URL" PROCRASTINATE_CONNINFO="$PSYCOPG_URL" \
    .venv/bin/python -m procrastinate --app=ingest.worker.app schema --apply

  echo "==> eval user + internal-eval plan + seed corpus"
  DATABASE_URL="$DB_URL" .venv/bin/python scripts/seed_eval_user.py
  DATABASE_URL="$DB_URL" .venv/bin/python -m evals.loader

  # The eval corpus is private to the eval user now (KI-24); the books have to
  # be ingested separately because seed_gutenberg goes through the product's
  # admin-only upload route, which always lands in Shared.
  echo "==> admin for the Gutenberg upload"
  DATABASE_URL="$DB_URL" .venv/bin/python scripts/seed_admin.py

  echo "==> api on :${PORT}"
  # The ingest workers this api defers to, pinned to this worktree's code and
  # this stack's database. Without them the books upload and then sit in
  # `parsing` forever, which is what an isolated api with no workers looks like.
  for role in ingest light; do
    DATABASE_URL="$DB_URL" PROCRASTINATE_CONNINFO="$PSYCOPG_URL" \
    OBJECT_STORAGE_DIR="$root/.data/accept-objects" \
      .venv/bin/python -m procrastinate --app=ingest.worker.app worker \
      --queues="${role}" --concurrency=1 \
      >"$root/.data/acceptance-${role}.log" 2>&1 &
    echo $! >>"$PID_FILE"
  done

  DATABASE_URL="$DB_URL" PROCRASTINATE_CONNINFO="$PSYCOPG_URL" \
  OBJECT_STORAGE_DIR="$root/.data/accept-objects" \
    .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port "$PORT" \
    >"$LOG_FILE" 2>&1 &
  echo $! >>"$PID_FILE"

  for _ in $(seq 1 40); do
    curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1 && break
    sleep 1
  done
  if ! curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    echo "api did not come up; see $LOG_FILE" >&2
    exit 1
  fi

  # After the api, not before: the upload goes over HTTP, so something has to
  # be listening. Ingestion then needs the workers above, or every book sits in
  # `parsing` and the run measures an empty library.
  # GUTENBERG_CACHE_DIR is relative to the working directory and the script
  # runs from apps/api, so its default lands in apps/api/.data/gutenberg —
  # a different cache from the one `make seed-books` populates. Pointed at the
  # repo-root one so a re-run does not re-download eleven books.
  echo "==> books into Shared (cached texts; a few minutes)"
  VERIFORGE_API_URL="http://127.0.0.1:${PORT}" \
    GUTENBERG_CACHE_DIR="$root/.data/gutenberg" \
    GUTENBERG_ADMIN_EMAIL="$ADMIN_EMAIL" GUTENBERG_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    DATABASE_URL="$DB_URL" .venv/bin/python scripts/seed_gutenberg.py

  echo "==> up: VERIFORGE_API_URL=http://127.0.0.1:${PORT}"
  ;;
down)
  if [ -f "$PID_FILE" ]; then
    while read -r pid; do
      kill "$pid" 2>/dev/null || true
    done <"$PID_FILE"
    rm -f "$PID_FILE"
  fi
  echo "==> stopped"
  ;;
*)
  echo "usage: $0 {up|down}" >&2
  exit 2
  ;;
esac