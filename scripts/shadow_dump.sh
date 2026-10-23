#!/usr/bin/env bash
# Dump everything a shadow run left in the database to JSON files, BEFORE the
# stack is stopped (the DB is the only copy of the run_events).
#   scripts/shadow_dump.sh <since-timestamp> <out-dir>
# e.g. scripts/shadow_dump.sh '2026-10-23 08:13:45+00' .data/shadow/dump
set -euo pipefail
since="$1"; out="$2"; db="${ACCEPTANCE_DB:-veriforge_accept_r3dec}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$out"
q() { # name, sql
  (cd "$root/../veriforge" && docker compose -p veriforge -f compose.yaml exec -T db \
    psql -U veriforge -d "$db" -qtAX -c "select coalesce(json_agg(t),'[]'::json) from ($2) t") >"$out/$1.json"
}
r="(select id from runs where created_at > '$since')"
q runs "select * from runs where created_at > '$since' order by created_at"
q decision_shadow "select * from decision_shadow where run_id in $r order by created_at"
q decision_events "select run_id, seq, payload from run_events where type='decision' and run_id in $r order by run_id, seq"
q retrieval_events "select run_id, seq, payload from run_events where type='retrieval' and run_id in $r order by run_id, seq"
q other_events "select run_id, seq, type, payload from run_events where type not in ('decision','retrieval','heartbeat','answer.delta') and run_id in $r order by run_id, seq"
q usage_ledger "select * from usage_ledger where run_id in $r order by ts"
q messages "select m.id, m.chat_id, m.role, m.content, m.created_at, ru.id as run_id from runs ru join messages a on a.id = ru.message_id join messages m on m.chat_id = a.chat_id where ru.created_at > '$since' order by m.created_at"
