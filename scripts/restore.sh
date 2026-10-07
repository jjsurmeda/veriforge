#!/usr/bin/env bash
# Restore a database dump from S3 or a local directory.
#
#   scripts/restore.sh latest                      -> the newest dump in BACKUP_BUCKET
#   scripts/restore.sh s3://<bucket>/db/x.dump
#   scripts/restore.sh /tmp/dumps/x.dump --compose compose.yaml
#
# `--restore` on up.sh calls this with `latest`.
#
# IMPORTANT: restoring REPLACES the database. Every row of `users` disappears
# and comes back from the dump, which means every refresh token issued after
# the dump is dead and everyone is logged out. That is why up.sh --restore is a
# deliberate flag and not part of a plain up.sh.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="compose.prod.yaml"
# The service name differs between the two compose files: compose.prod.yaml
# calls it `postgres`, compose.yaml calls it `db`.
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${POSTGRES_USER:-veriforge}"
PG_DB="${PG_RESTORE_DB:-${POSTGRES_DB:-veriforge}}"
REGION="${AWS_REGION:-ap-southeast-1}"
SOURCE="${1:-latest}"
# Shift the source off BEFORE the option loop. Without this, `$1` is still the
# dump path when the loop starts, hits the `*) break` arm and every option after
# it is silently ignored — so `--compose compose.yaml --pg-db <scratch>` was
# dropped and the restore went to compose.prod.yaml's database instead.
[ $# -gt 0 ] && shift

while [ $# -gt 0 ]; do
  case "$1" in
    --compose) COMPOSE_FILE="$2"; shift 2 ;;
    # Restoring into a database other than the compose default. The test uses
    # this so it can restore into a scratch database on the same server instead
    # of overwriting the developer's dev data.
    --pg-db) PG_DB="$2"; shift 2 ;;
    --pg-service) PG_SERVICE="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) break ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
COMPOSE=(docker compose -f "$COMPOSE_FILE")

BUCKET="${BACKUP_BUCKET:-}"
if [ "$SOURCE" = "latest" ]; then
  [ -n "$BUCKET" ] || die "no BACKUP_BUCKET set, so 'latest' cannot be resolved. Pass a path instead."
  say "==> finding the newest dump in s3://$BUCKET/db/"
  SOURCE="$(aws s3 ls "s3://$BUCKET/db/" --region "$REGION" \
    | awk '{print $4}' | grep '\.dump$' | sort | tail -1 \
    | sed "s|^|s3://$BUCKET/db/|")"
  [ -n "$SOURCE" ] || die "no .dump files under s3://$BUCKET/db/"
  say "    $SOURCE"
fi

LOCAL_DUMP="${TMPDIR:-/tmp}/veriforge-restore-$$.dump"
trap 'rm -f "$LOCAL_DUMP"' EXIT

say "==> fetching $SOURCE"
case "$SOURCE" in
  s3://*) aws s3 cp "$SOURCE" "$LOCAL_DUMP" --region "$REGION" ;;
  /*) cp "$SOURCE" "$LOCAL_DUMP" ;;
  *) die "the dump must be s3://... or an absolute path" ;;
esac
[ -s "$LOCAL_DUMP" ] || die "the downloaded dump is empty"

# Read the archive's table of contents before touching anything. If the file is
# truncated or not a pg_dump custom archive, this fails here rather than
# half-way through a restore.
say "==> reading the archive's contents (--list)"
"${COMPOSE[@]}" exec -T $PG_SERVICE pg_restore --list < "$LOCAL_DUMP" > /dev/null \
  || die "pg_restore --list failed: the dump is not a readable custom archive"
TABLES="$("${COMPOSE[@]}" exec -T $PG_SERVICE pg_restore --list < "$LOCAL_DUMP" \
  | grep -c 'TABLE DATA' || true)"
say "    $TABLES tables of data in the archive"

say "==> restoring into $PG_DB"
say "    this REPLACES the current database; every session is dropped"

# --clean --if-exists so a restore into a database that already has rows
# replaces rather than collides. Without --clean a restore fails on the first
# duplicate key instead of replacing.
"${COMPOSE[@]}" exec -T $PG_SERVICE \
  pg_restore --clean --if-exists --no-owner --no-privileges --jobs=1 -U "$PG_USER" -d "$PG_DB" \
  < "$LOCAL_DUMP" \
  || die "pg_restore failed"

say "==> verifying the restore answered"
"${COMPOSE[@]}" exec -T $PG_SERVICE pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null \
  || die "postgres is not accepting connections after the restore"

say ""
say "restored from $SOURCE"
say "NOTE: this does NOT re-embed anything. The corpus comes back with its"
say "embeddings, which is the whole point of the backups bucket — re-embedding"
say "costs provider credit and about an hour."
say "row counts, as a sanity check:"
"${COMPOSE[@]}" exec -T $PG_SERVICE psql -U "$PG_USER" -d "$PG_DB" -tAc \
  "select '  users=' || (select count(*) from users)
        || ' documents=' || (select count(*) from documents)
        || ' chunks=' || (select count(*) from chunks);"