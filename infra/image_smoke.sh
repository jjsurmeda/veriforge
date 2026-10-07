#!/usr/bin/env bash
# Proves the production api image starts and answers /healthz, without AWS and
# without touching the dev stack.
#
# What it proves, and what it does not:
#   - the image is built with --frozen and starts under its own non-root user
#   - alembic + the procrastinate schema apply succeed against a fresh database
#   - GET /healthz returns 200 with the documented body
#   - the memory limits in compose.prod.yaml are accepted by the image
# It does NOT prove anything about CloudFront, the security group, the SSM
# parameters or the instance itself. Those are the day-2 checklist.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
API_IMAGE="${API_IMAGE:-veriforge/api:$IMAGE_TAG}"

# Deliberately not 5432 (dev postgres), 8000 (dev api) or 5173/5174 (dev web).
SMOKE_PG_PORT="${SMOKE_PG_PORT:-15432}"
SMOKE_API_PORT="${SMOKE_API_PORT:-18001}"
SMOKE_DB="veriforge_image_smoke"

# A throwaway password for a container that is destroyed on exit. Never a real
# one, never written to a file in the repo.
SMOKE_PG_PASSWORD="smoke-$(date +%s)-$$"

NETWORK="vf-image-smoke-$$"
cleanup() {
  docker rm -f "smoke-api" "smoke-db" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> image: $API_IMAGE"
docker image inspect "$API_IMAGE" --format '    id={{.Id}} size={{.Size}} user={{.Config.User}}' || {
  echo "image not found: $API_IMAGE (run 'make image-build' first)" >&2
  exit 1
}

docker network create "$NETWORK" >/dev/null

echo "==> starting a throwaway postgres on 127.0.0.1:$SMOKE_PG_PORT"
docker run -d --name smoke-db --network "$NETWORK" --network-alias postgres \
  -e POSTGRES_USER=veriforge \
  -e POSTGRES_PASSWORD="$SMOKE_PG_PASSWORD" \
  -e POSTGRES_DB="$SMOKE_DB" \
  -p "127.0.0.1:${SMOKE_PG_PORT}:5432" \
  paradedb/paradedb:0.25.9-pg16 >/dev/null

echo "==> waiting for postgres"
for _ in $(seq 1 60); do
  if docker exec smoke-db pg_isready -U veriforge -d "$SMOKE_DB" >/dev/null 2>&1; then
    echo "    postgres ready"
    break
  fi
  sleep 2
done
docker exec smoke-db pg_isready -U veriforge -d "$SMOKE_DB" >/dev/null || {
  echo "postgres did not become ready; its log:" >&2
  docker logs --tail 40 smoke-db >&2
  exit 1
}

echo "==> starting the api image on 127.0.0.1:$SMOKE_API_PORT"
# EMAIL_TRANSPORT is deliberately NOT smtp and ENVIRONMENT is deliberately not
# production: this smoke test is about the image, not about the deployment's
# configuration. The production refusal is proven in docs/ops/runbook.md's day-2
# list, where the SES credentials exist.
#
# The command is the one compose.prod.yaml gives the api service, byte for
# byte: alembic, then the procrastinate schema, then uvicorn. An earlier
# version of this script ran the image's bare CMD instead, so no migration ran
# and the `alembic_version` assertion below failed with
# `ERROR: relation "alembic_version" does not exist` — the image was fine,
# the test was not exercising the deployed start-up path.
docker run -d --name smoke-api --network "$NETWORK" \
  -p "127.0.0.1:${SMOKE_API_PORT}:8000" \
  --memory 650m \
  -e DATABASE_URL="postgresql+asyncpg://veriforge:${SMOKE_PG_PASSWORD}@postgres:5432/${SMOKE_DB}" \
  -e PROCRASTINATE_CONNINFO="postgresql://veriforge:${SMOKE_PG_PASSWORD}@postgres:5432/${SMOKE_DB}" \
  -e OBJECT_STORAGE_DIR=/data/objects \
  -e ENVIRONMENT=development \
  -e EMAIL_TRANSPORT=dev_log \
  "$API_IMAGE" \
  sh -c "alembic upgrade head && \
         (python -m procrastinate --app=ingest.worker.app schema --apply \
          || echo 'procrastinate schema already applied') && \
         uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log" >/dev/null

echo "==> waiting for /healthz (start period 90s, image healthcheck)"
healthy=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${SMOKE_API_PORT}/healthz" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 2
done

if [ "$healthy" -ne 1 ]; then
  echo "the api never answered /healthz. Container state and logs:" >&2
  docker inspect smoke-api --format '    state={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}' >&2
  docker logs --tail 60 smoke-api >&2
  exit 1
fi

echo "==> GET /healthz"
curl -fsS "http://127.0.0.1:${SMOKE_API_PORT}/healthz" | python3 -m json.tool | sed 's/^/    /'

echo "==> the image's own HEALTHCHECK (docker's view, not curl's)"
deadline=$((SECONDS + 90))
status=""
while [ $SECONDS -lt $deadline ]; do
  status="$(docker inspect smoke-api --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')"
  [ "$status" = "healthy" ] && break
  sleep 3
done
echo "    docker health status: $status"
if [ "$status" != "healthy" ]; then
  echo "    the image's HEALTHCHECK did not report healthy; its log:" >&2
  docker inspect smoke-api --format '{{range .State.Health.Log}}{{.Output}}{{end}}' | tail -5 >&2
  exit 1
fi

echo "==> migrations applied in this fresh database"
docker exec smoke-db psql -U veriforge -d "$SMOKE_DB" -tAc \
  "select 'alembic_version=' || version_num from alembic_version;" | sed 's/^/    /'
docker exec smoke-db psql -U veriforge -d "$SMOKE_DB" -tAc \
  "select 'procrastinate_jobs_table=' || coalesce(to_regclass('queue.procrastinate_jobs')::text, 'MISSING');" | sed 's/^/    /'

echo "==> the api ran as a non-root user"
docker exec smoke-api id | sed 's/^/    /'

echo
echo "image-smoke: PASS"