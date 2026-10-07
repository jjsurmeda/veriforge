#!/usr/bin/env bash
# Proves backup.sh and restore.sh actually round-trip, without AWS and without
# touching the developer's dev database.
#
# What it proves:
#   1. backup.sh writes a readable pg_dump custom archive
#   2. restore.sh restores it into a SEPARATE database
#   3. row counts match for users, documents and chunks
#   4. a restored chunk's embedding is byte-identical to the original
#   5. a chunk's embedding still answers the pgvector operator, so the restored
#      vectors are usable and not merely present
#
# Point 4 is the one that matters. The whole reason the backups bucket exists
# is to bring the corpus back WITHOUT re-embedding, which costs provider credit
# and about an hour. If the embedding did not survive the round trip, the
# restore would be useless for its stated purpose.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PG_USER=veriforge
SOURCE_DB=veriforge
TARGET_DB=veriforge_restore_test

pass=0; fail=0
ok() { printf 'ok   %s\n' "$1"; pass=$((pass + 1)); }
no() { printf 'FAIL %s\n     %s\n' "$1" "${2:-}"; fail=$((fail + 1)); }
say() { printf '%s\n' "$*"; }

# Found by container name, not by `docker compose ps`. The dev stack was
# started from the main checkout, so it belongs to that compose PROJECT; this
# worktree's project name is different and `compose ps` here finds nothing even
# though the database is right there and healthy.
DEV_DB="$(docker ps --filter "name=veriforge-db" --format '{{.Names}}' | head -1)"
[ -n "$DEV_DB" ] || { echo "the dev db is not running; start it with docker compose up -d db" >&2; exit 1; }

# The service name inside that container's own compose project, which is what
# backup.sh and restore.sh need for `compose exec`.
DEV_COMPOSE_FILE="${DEV_COMPOSE_FILE:-$HOME/dev/my-projects/veriforge/compose.yaml}"
[ -f "$DEV_COMPOSE_FILE" ] || DEV_COMPOSE_FILE="$(git rev-parse --path-format=absolute --git-common-dir)/../compose.yaml"
[ -f "$DEV_COMPOSE_FILE" ] || { echo "cannot find the dev compose.yaml; set DEV_COMPOSE_FILE" >&2; exit 1; }
echo "dev compose file:  $DEV_COMPOSE_FILE"
echo "dev database container: ${DEV_DB:0:12}"

# A scratch database for the restore target, on the SAME server. The restore
# must not be able to reach back into the source.
say ""
say "==> creating the restore target database $TARGET_DB"
docker exec "$DEV_DB" psql -U "$PG_USER" -d postgres -c "DROP DATABASE IF EXISTS $TARGET_DB;" >/dev/null
docker exec "$DEV_DB" psql -U "$PG_USER" -d postgres -c "CREATE DATABASE $TARGET_DB;" >/dev/null

# The developer's dev container runs with Docker's default 64 MB /dev/shm, and an
# HNSW index build over 14k chunks wants ~509 MB of dynamic shared memory:
#   could not resize shared segment ... to 509678304 bytes: No space left on
#   device
#   Command was: CREATE INDEX ix_chunks_embedding_hnsw ...
#
# That is why compose.prod.yaml sets shm_size: 1gb on postgres — found by this
# test rather than by reading anything. The dev container cannot be given more
# shm without being recreated, so for this round trip the index build is forced
# onto one worker, which needs a fraction of the memory. The DATA is what is
# under test; how many workers build the index is not.
docker exec "$DEV_DB" psql -U "$PG_USER" -d postgres -c \
  "ALTER DATABASE $TARGET_DB SET max_parallel_maintenance_workers = 0;" >/dev/null
docker exec "$DEV_DB" psql -U "$PG_USER" -d postgres -c \
  "ALTER DATABASE $TARGET_DB SET max_parallel_workers_per_gather = 0;" >/dev/null
ok "created $TARGET_DB (parallel index builds off: 64 MB /dev/shm here)"

# ---------------------------------------------------------------- backup ----

say ""
say "==> backup.sh --dest (a local directory, the same code path S3 uses)"
./scripts/backup.sh --compose "$DEV_COMPOSE_FILE" --pg-service db --dest "$TMP" > "$TMP/backup.log" 2>&1 \
  && ok "backup.sh exited 0" \
  || { no "backup.sh exited 0" "$(tail -5 "$TMP/backup.log")"; exit 1; }
sed 's/^/    /' "$TMP/backup.log"

DUMP="$(find "$TMP" -name 'db-veriforge-*.dump' | head -1)"
[ -n "$DUMP" ] && ok "a dump was written: $(basename "$DUMP")" || no "a dump was written" ""
[ -s "$DUMP" ] || { no "the dump is not empty" ""; exit 1; }

say ""
say "==> the archive is readable (pg_restore --list)"
LISTED="$(docker exec -i "$DEV_DB" pg_restore --list < "$DUMP" | grep -c 'TABLE DATA' || true)"
[ "$LISTED" -gt 0 ] && ok "pg_restore --list read $LISTED tables of data" \
  || no "pg_restore --list read the archive" "0 tables"

# --------------------------------------------------------------- restore ----

say ""
say "==> restore.sh into $TARGET_DB (a real invocation, not a reimplementation)"
# --pg-db and --pg-service exist so this can target a scratch database on the
# same server. An earlier version of this test killed restore.sh and ran
# pg_restore by hand, which proved nothing about the script.
if ./scripts/restore.sh "$DUMP" --compose "$DEV_COMPOSE_FILE" \
     --pg-service db --pg-db "$TARGET_DB" > "$TMP/restore.log" 2>&1; then
  ok "restore.sh exited 0"
else
  no "restore.sh exited 0" "$(tail -5 "$TMP/restore.log")"
  sed 's/^/    /' "$TMP/restore.log"
  exit 1
fi
sed 's/^/    /' "$TMP/restore.log"

# ------------------------------------------------------------ row counts ----

say ""
say "==> row counts, source vs restored"
for table in users documents chunks; do
  SRC="$(docker exec "$DEV_DB" psql -U "$PG_USER" -d "$SOURCE_DB" -tAc "select count(*) from $table;")"
  DST="$(docker exec "$DEV_DB" psql -U "$PG_USER" -d "$TARGET_DB" -tAc "select count(*) from $table;")"
  say "    $table: source=$SRC restored=$DST"
  if [ "$SRC" = "$DST" ] && [ "$SRC" != "0" ]; then
    ok "$table round-tripped ($SRC rows)"
  else
    no "$table round-tripped" "source=$SRC restored=$DST"
  fi
done

# ------------------------------------------------------------- embeddings ----

say ""
say "==> a restored chunk's embedding is byte-identical"

# Pick a chunk that actually has an embedding.
SAMPLE="$(docker exec "$DEV_DB" psql -U "$PG_USER" -d "$SOURCE_DB" -tAc \
  "select id from chunks where embedding is not null order by id limit 1;")"
[ -n "$SAMPLE" ] || { no "a chunk with an embedding exists" "the dev corpus has none"; exit 1; }

# md5 of the pgvector's textual representation. Identical md5 means the stored
# float4 values are the same, not merely the same dimension.
SRC_MD5="$(docker exec "$DEV_DB" psql -U "$PG_USER" -d "$SOURCE_DB" -tAc \
  "select md5(embedding::text) from chunks where id = '$SAMPLE';")"
DST_MD5="$(docker exec "$DEV_DB" psql -U "$PG_USER" -d "$TARGET_DB" -tAc \
  "select md5(embedding::text) from chunks where id = '$SAMPLE';")"
say "    chunk $SAMPLE"
say "    source  embedding md5: $SRC_MD5"
say "    restored embedding md5: $DST_MD5"
if [ -n "$SRC_MD5" ] && [ "$SRC_MD5" = "$DST_MD5" ]; then
  ok "the embedding is byte-identical after the round trip"
else
  no "the embedding is byte-identical" "source=$SRC_MD5 restored=$DST_MD5"
fi

# And it is still a usable vector, not just an opaque blob: a real 1-cosine
# query has to return the chunk it came from.
say ""
say "==> the restored vector still answers a pgvector query"
HIT="$(docker exec "$DEV_DB" psql -U "$PG_USER" -d "$TARGET_DB" -tAc \
  "select id from chunks where embedding is not null
     order by embedding <=> (select embedding from chunks where id = '$SAMPLE') limit 1;")"
say "    nearest neighbour of itself in the RESTORED database: $HIT"
[ "$HIT" = "$SAMPLE" ] && ok "the vector index/query path works on restored data" \
  || no "the vector query works on restored data" "got $HIT, expected $SAMPLE"

# ------------------------------------------------------------------ done ----

say ""
say "==> cleaning up the scratch database"
docker exec "$DEV_DB" psql -U "$PG_USER" -d postgres -c "DROP DATABASE IF EXISTS $TARGET_DB;" >/dev/null
ok "dropped $TARGET_DB"

say ""
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]