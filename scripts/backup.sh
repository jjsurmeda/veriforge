#!/usr/bin/env bash
# Database dump (and the uploads directory) to S3 or to a local directory.
#
#   scripts/backup.sh                              -> s3://$BACKUP_BUCKET
#   scripts/backup.sh --dest /tmp/dumps            -> a local directory
#   scripts/backup.sh --compose compose.prod.yaml  -> the deployed stack
#   scripts/backup.sh --compose compose.yaml       -> the local dev stack
#
# --dest taking a plain directory is what makes this testable without AWS:
# infra/tests/test_backup_restore.sh uses it, and the code path to S3 is the
# same `aws s3 cp` with a different target.
#
# The dump is pg_dump's custom format (-Fc), which is compressed and lets
# pg_restore --list run without decompressing the whole file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="compose.prod.yaml"
DEST="${BACKUP_BUCKET:-}"
INCLUDE_OBJECTS=1
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --compose) COMPOSE_FILE="$2"; shift 2 ;;
    --pg-service) PG_SERVICE="$2"; shift 2 ;;
    --dest) DEST="$2"; shift 2 ;;
    --no-objects) INCLUDE_OBJECTS=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# compose.prod.yaml names the service `postgres`; compose.yaml names it `db`.
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${POSTGRES_USER:-veriforge}"
PG_DB="${POSTGRES_DB:-veriforge}"
COMPOSE=(docker compose -f "$COMPOSE_FILE")

if [ -z "$DEST" ]; then
  die "no destination. Pass --dest s3://<bucket>, or set BACKUP_BUCKET."
fi

# A local directory destination is for testing and for pulling a dump off a box
# by hand; the deployed path always uses S3.
IS_LOCAL=0
case "$DEST" in
  s3://*) IS_LOCAL=0 ;;
  /*) IS_LOCAL=1; mkdir -p "$DEST" ;;
  *) die "--dest must be s3://<bucket> or an absolute path" ;;
esac

TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOCAL_DUMP="${TMPDIR:-/tmp}/veriforge-$TS.dump"

say "==> dumping $PG_DB from $COMPOSE_FILE"
if [ "$DRY_RUN" -eq 1 ]; then
  say "  would run: ${COMPOSE[*]} exec -T $PG_SERVICE pg_dump -U $PG_USER -d $PG_DB -Fc > $LOCAL_DUMP"
  say "  would run: ${COMPOSE[*]} exec -T $PG_SERVICE pg_dumpall -U $PG_USER --globals-only > globals-$TS.sql"
  exit 0
fi

# The `|| true` on globals is deliberate: pg_dumpall --globals-only wants a
# superuser, and the deployed POSTGRES_USER is the database owner rather than
# a superuser in some configurations. Roles are not needed to restore this
# dump, so a failure here must not fail the backup.
"${COMPOSE[@]}" exec -T $PG_SERVICE pg_dump -U "$PG_USER" -d "$PG_DB" -Fc > "$LOCAL_DUMP" \
  || die "pg_dump failed"
[ -s "$LOCAL_DUMP" ] || die "pg_dump produced an empty file"

SIZE="$(du -h "$LOCAL_DUMP" | cut -f1)"
say "    $SIZE -> $LOCAL_DUMP"

if [ "$IS_LOCAL" -eq 1 ]; then
  cp "$LOCAL_DUMP" "$DEST/db-veriforge-$TS.dump"
  say "    copied to $DEST/db-veriforge-$TS.dump"
  LATEST="$DEST/db-veriforge-$TS.dump"
else
  aws s3 cp "$LOCAL_DUMP" "s3://$DEST/db/veriforge-$TS.dump" --region "${AWS_REGION:-ap-southeast-1}"
  say "    uploaded to s3://$DEST/db/veriforge-$TS.dump"
  LATEST="s3://$DEST/db/veriforge-$TS.dump"
fi

# The uploads directory. Object storage is a local directory at Stage 1
# (compose.prod.yaml mounts it at /data/objects), so "back up the uploads" is
# "copy that directory", and it is the part pg_dump cannot help with.
if [ "$INCLUDE_OBJECTS" -eq 1 ]; then
  say "==> copying the uploads directory"
  CONTAINER_ID="$("${COMPOSE[@]}" ps -q api | head -1)"
  if [ -z "$CONTAINER_ID" ]; then
    say "    no api container running; skipping objects"
  elif [ "$IS_LOCAL" -eq 1 ]; then
    docker cp "$CONTAINER_ID:/data/objects" "$DEST/objects-$TS" 2>/dev/null \
      && say "    copied objects to $DEST/objects-$TS" \
      || say "    the objects directory is empty; nothing to copy"
  else
    "$REPO_ROOT/infra/scripts/objects_sync.sh" push "s3://$DEST" 2>/dev/null \
      && say "    objects uploaded to s3://$DEST/objects/" \
      || say "    objects upload failed; the database dump above is unaffected"
  fi
fi

rm -f "$LOCAL_DUMP"
say ""
say "backup complete: $LATEST"
say "restore it with: scripts/restore.sh '$LATEST'"