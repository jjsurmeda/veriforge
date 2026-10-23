#!/usr/bin/env bash
# R3 shadow measurement: start ONLY the instrumented api (apps/api/scripts/
# shadow_api.py) against an already-ingested database, or run a command with
# the env loaded. Never drops, migrates or seeds anything.
#
#   SHADOW_ENV_FILE=/path/to/.env ACCEPTANCE_DB=veriforge_accept_r3dec \
#     scripts/shadow_stack.sh up | down | exec <cmd...>
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api="$root/apps/api"
cd "$api"
envfile="${SHADOW_ENV_FILE:-$root/.env}"
if [ -f "$envfile" ]; then set -a; . "$envfile"; set +a; fi
PY="${SHADOW_PYTHON:-.venv/bin/python}"
DB_NAME="${ACCEPTANCE_DB:-veriforge_accept_r3dec}"
PORT="${SHADOW_PORT:-8123}"
export DATABASE_URL="postgresql+asyncpg://veriforge:veriforge@localhost:5432/${DB_NAME}"
export PROCRASTINATE_CONNINFO="postgresql://veriforge:veriforge@localhost:5432/${DB_NAME}"
export OBJECT_STORAGE_DIR="${OBJECT_STORAGE_DIR:-$root/.data/accept-objects}"
export SHADOW_CALL_LOG="${SHADOW_CALL_LOG:-$root/.data/shadow/calls.jsonl}"
pidf="$root/.data/shadow-api.pid"
case "${1:-}" in
up)
  mkdir -p "$root/.data/shadow"
  "$PY" -m scripts.shadow_api >"$root/.data/shadow-api.log" 2>&1 &
  echo $! >"$pidf"
  for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1 && break; sleep 1; done
  curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null || { echo "api did not come up" >&2; exit 1; }
  echo "up on :${PORT}, db ${DB_NAME}" ;;
down) [ -f "$pidf" ] && kill "$(cat "$pidf")" 2>/dev/null; rm -f "$pidf"; echo stopped ;;
exec) shift; exec "$@" ;;
*) echo "usage: $0 up|down|exec <cmd...>" >&2; exit 2 ;;
esac
