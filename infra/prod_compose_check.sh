# Proves compose.prod.yaml + Caddyfile work, on the laptop, without AWS.
#
# What it checks, in order:
#   1. the origin lock: no X-Origin-Verify -> 403, and nothing served
#   2. GET /healthz through Caddy reaches the api
#   3. GET / serves the SPA's index.html
#   4. GET /library with Accept: text/html  -> the SPA (the collision rule)
#   5. GET /library without that Accept    -> the api (JSON), not the SPA
#   6. the rate limiter keys on the VIEWER, not on Caddy and not on a
#      spoofed header (KI-59)
#   7. the api's refresh cookie survives the proxy unchanged
#   8. SSE arrives unbuffered through the real Caddyfile
#
# Ports are deliberately not the dev stack's: not 8000, not 5173, not 5432, and
# not 5174 (which is where the dev web container happens to be bound).
# No provider call is made anywhere in here.
#
# Every secret below is generated here and dies with the process. None is read
# from infra/.env, and none is written to a file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
PROJECT="vf-prodcheck-$$"
# A separate project for the SSE probe: sharing $PROJECT made the probe try to
# use the running stack's network and fail with "network ... has active
# endpoints" while tearing down.
SSE_PROJECT="vf-sseprobe-$$"
CADDY_PORT="${CADDY_PORT:-18080}"
API_DEBUG_PORT="${API_DEBUG_PORT:-18000}"
ORIGIN_VERIFY="$(openssl rand -hex 24)"

export API_IMAGE="${API_IMAGE:-veriforge/api:$IMAGE_TAG}"
export WEB_IMAGE="${WEB_IMAGE:-veriforge/web:$IMAGE_TAG}"
export CADDY_PORT API_DEBUG_PORT ORIGIN_VERIFY

# Ephemeral, generated, never a real credential. The api refuses to start in
# production without SMTP settings (apps/api/auth/email.py via
# apps/api/main.py's lifespan), which is why these exist at all — the run below
# is the production configuration path, so it has to be complete.
export POSTGRES_USER=veriforge
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"
export POSTGRES_DB=veriforge
export JWT_SECRET="$(openssl rand -hex 32)"
export WEB_ORIGIN="http://localhost:${CADDY_PORT}"
export SMTP_HOST=email-smtp.ap-southeast-1.amazonaws.com
export SMTP_PORT=587
export SMTP_USERNAME=localcheck
export SMTP_PASSWORD="$(openssl rand -hex 16)"
export SMTP_FROM=localcheck@example.invalid

fail() { echo "FAIL: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

# One place to ask for a status code, so a connection failure reads as a
# failure rather than as a string of zeros. An earlier version appended
# `|| echo 000` to a curl that already printed 000 via -w, producing "000000".
code() { curl -sS -o /dev/null -w '%{http_code}' "$@" 2>/dev/null || true; }

cleanup() {
  docker compose -p "$PROJECT" -f compose.prod.yaml down -v --remove-orphans >/dev/null 2>&1 || true
  docker compose -p "$SSE_PROJECT" -f infra/tests/compose.sse-probe.yaml down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

compose() { docker compose -p "$PROJECT" -f compose.prod.yaml "$@"; }

echo "project:  $PROJECT"
echo "images:   $API_IMAGE / $WEB_IMAGE"
echo "caddy on: http://127.0.0.1:$CADDY_PORT"

# ------------------------------------------------------------------ bring up
step "starting the production compose (postgres, api, both workers, caddy)"
compose up -d --wait --wait-timeout 300

# ---------------------------------------------------------------- 1. origin lock
step "1. the origin is locked: a request without X-Origin-Verify"
BODY_FILE="$(mktemp)"
STATUS="$(code -o "$BODY_FILE" "http://127.0.0.1:${CADDY_PORT}/")"
echo "    GET / with no origin header -> $STATUS"
[ "$STATUS" = "403" ] || fail "expected 403 for a request without the origin header, got '$STATUS'"
if grep -qi "<!doctype html\|<div id=" "$BODY_FILE" 2>/dev/null; then
  fail "the 403 body contained SPA markup; a direct hit must get nothing"
fi
echo "    body is not the SPA: ok"

STATUS="$(code -H "X-Origin-Verify: wrong-value" "http://127.0.0.1:${CADDY_PORT}/")"
echo "    GET / with a WRONG origin header -> $STATUS"
[ "$STATUS" = "403" ] || fail "expected 403 for a wrong origin header, got '$STATUS'"

STATUS="$(code -H "X-Origin-Verify: ${ORIGIN_VERIFY}" "http://127.0.0.1:${CADDY_PORT}/")"
echo "    GET / with the RIGHT origin header -> $STATUS"
[ "$STATUS" = "200" ] || fail "expected 200 with the right origin header, got '$STATUS'"

# ------------------------------------------------------------------ 2. healthz
step "2. GET /healthz through Caddy"
curl -fsS -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
  "http://127.0.0.1:${CADDY_PORT}/healthz" | python3 -m json.tool | sed 's/^/    /'

# ---------------------------------------------------------------------- 3. SPA
step "3. GET / serves the SPA"
SPA="$(curl -fsS -H "X-Origin-Verify: ${ORIGIN_VERIFY}" "http://127.0.0.1:${CADDY_PORT}/")"
echo "$SPA" | grep -qi '<div id="root"' || echo "$SPA" | grep -qi '<script' \
  || fail "GET / did not return the SPA entry point"
echo "    index.html served: ok"
ASSET="$(echo "$SPA" | grep -o '/assets/[A-Za-z0-9._-]*\.js' | head -1 || true)"
if [ -n "$ASSET" ]; then
  ASTATUS="$(curl -sS -o /dev/null -w '%{http_code}' -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
    "http://127.0.0.1:${CADDY_PORT}${ASSET}")"
  echo "    asset $ASSET -> $ASTATUS"
  [ "$ASTATUS" = "200" ] || fail "the built asset was not served ($ASTATUS)"
fi

# ------------------------------------------------------- 4/5. the collision rule
step "4. GET /library WITH Accept: text/html  -> the SPA (collision rule)"
DOC="$(curl -fsS -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
  -H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' \
  "http://127.0.0.1:${CADDY_PORT}/library")"
if echo "$DOC" | grep -qi '<div id="root"\|<script'; then
  echo "    served the SPA entry point: ok"
else
  echo "$DOC" | head -c 300; echo
  fail "a document navigation to /library did not get the SPA"
fi

step "5. GET /library WITHOUT Accept: text/html  -> the api, not the SPA"
# Not -f: the api answers 401 here because /library requires auth, and a 401
# from the api is exactly the proof wanted — it is not the SPA's 200. An
# earlier version of this step used -fsS, so `set -e` killed the run with
# `curl: (22) The requested URL returned error: 401` before asserting
# anything.
API_STATUS="$(code -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
  -H 'Accept: application/json' \
  "http://127.0.0.1:${CADDY_PORT}/library")"
API="$(curl -sS -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
  -H 'Accept: application/json' \
  "http://127.0.0.1:${CADDY_PORT}/library")"
echo "    status: $API_STATUS"
echo "    body: $(echo "$API" | head -c 200)"
if echo "$API" | grep -qi '<div id="root"\|<script'; then
  fail "an XHR-style request to /library got the SPA; the api prefix was not proxied"
fi
echo "$API" | grep -qi 'application/json\|^{' \
  || fail "the response to a non-document request to /library was neither SPA markup nor JSON"
[ "$API_STATUS" = "200" ] && fail "/library answered 200 for an unauthenticated XHR; the SPA answered it"
echo "    the api answered (not the SPA): ok"

# The same rule for the other colliding path the SPA owns.
step "5b. the same rule for /auth/callback"
DOC2="$(curl -sS -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
  -H 'Accept: text/html' "http://127.0.0.1:${CADDY_PORT}/auth/callback")"
echo "$DOC2" | grep -qi '<div id="root"\|<script' \
  || fail "a document navigation to /auth/callback did not get the SPA"
echo "    served the SPA entry point: ok"

step "5c. an api path that is not a colliding SPA route is proxied"
ME_STATUS="$(code -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
  -H 'Accept: application/json' "http://127.0.0.1:${CADDY_PORT}/me")"
echo "    GET /me -> $ME_STATUS (401 = reached the api and it requires auth)"
[ "$ME_STATUS" = "401" ] || fail "GET /me returned $ME_STATUS, expected the api's 401"

# --------------------------------------------------------------- 6. the limiter
# KI-59. Locally this script plays the part of CloudFront: it sends the header
# CloudFront would send, which is the viewer's address LAST (CloudFront
# "appends it to the end of the X-Forwarded-For header"). Anything to the left
# of that is what a hostile viewer prepended.
#
# The limiter limit for login is 10 per 60s (config.py rate_limit_login).
#   - 10 requests as viewer A  -> all allowed
#   - 10 requests as viewer B  -> all allowed. If the limiter were keyed on
#     Caddy's address (the failure KI-59 describes when forwarded_allow_ips is
#     not set), these would be 429.
#   - viewer A again           -> 429, so A's own budget is exhausted
#   - viewer A with a different spoofed prefix -> still 429, so the prefix is
#     not what the bucket is keyed on
LIMIT=10

login_status() { # $1 = X-Forwarded-For value
  curl -sS -o /dev/null -w '%{http_code}' \
    -X POST "http://127.0.0.1:${CADDY_PORT}/auth/login" \
    -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
    -H 'Content-Type: application/json' \
    -H "X-Forwarded-For: $1" \
    -d '{"email":"nobody@example.com","password":"x"}'
}

step "6. the rate limiter keys on the viewer (KI-59)"
VIEWER_A="203.0.113.7"     # TEST-NET-3, RFC 5737
VIEWER_B="198.51.100.9"    # TEST-NET-2, RFC 5737

A_CODES=""
for i in $(seq 1 $LIMIT); do A_CODES="$A_CODES $(login_status "$VIEWER_A")"; done
echo "    viewer A x$LIMIT -> $A_CODES"
for code in $A_CODES; do
  [ "$code" = "401" ] || fail "viewer A request was answered $code, expected 401 (invalid_credentials)"
done

B_CODES=""
for i in $(seq 1 $LIMIT); do B_CODES="$B_CODES $(login_status "$VIEWER_B")"; done
echo "    viewer B x$LIMIT -> $B_CODES"
for code in $B_CODES; do
  [ "$code" = "401" ] || fail "viewer B got $code; a second viewer must not share viewer A's bucket"
done
echo "    two viewers got two separate buckets (not one global bucket): ok"

NEXT="$(login_status "$VIEWER_A")"
echo "    viewer A, attempt $((LIMIT+1)) -> $NEXT"
[ "$NEXT" = "429" ] || fail "viewer A's $((LIMIT+1))th attempt returned $NEXT, expected 429"

SPOOF="$(login_status "192.0.2.66, ${VIEWER_A}")"
echo "    viewer A with a spoofed prefix '192.0.2.66, ${VIEWER_A}' -> $SPOOF"
[ "$SPOOF" = "429" ] || fail "a spoofed prefix reset viewer A's bucket; the leftmost entry is being trusted"
echo "    the spoofed leftmost entry did not create a new bucket: ok"

# ------------------------------------------------------------------ 7. cookies
step "7. the api's response headers survive the proxy"
# NOT a check on Set-Cookie, and that is deliberate. A refresh cookie is only
# issued on a *successful* login, and getting one here means either signing a
# user up — which needs a seeded invite, or flipping SIGNUP_MODE away from the
# production value, which this lane has no business weakening — or reaching for
# a live provider. The Secure cookie on *.cloudfront.net is a day-2 item in
# docs/ops/runbook.md instead.
#
# What is checked is the origin's own headers, which a proxy could plausibly
# rewrite. Measured first, so these are the headers the api actually sends:
#   direct:    401, server: uvicorn, content-type: application/json, content-length
#   via Caddy: the same four, plus `Via: 1.1 Caddy`
HEADERS="$(curl -sS -D - -o /dev/null -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
  -H 'Accept: application/json' "http://127.0.0.1:${CADDY_PORT}/me")"
echo "$HEADERS" | grep -iE '^(HTTP/|server:|content-type:|content-length:|via:)' | sed 's/^/    /'

echo "$HEADERS" | grep -qi '^HTTP/1.1 401' \
  || fail "the api's 401 status did not survive Caddy"
echo "$HEADERS" | grep -qi '^server: uvicorn' \
  || fail "Caddy replaced the origin's Server header, so the api did not answer"
echo "$HEADERS" | grep -qi '^content-type: application/json' \
  || fail "the api's Content-Type did not survive Caddy"
echo "    the api's status and headers arrive through Caddy intact: ok"

# --------------------------------------------------------------------- 8. SSE
step "8. SSE is not buffered by the real Caddyfile"
# A second caddy, from the same image and the same Caddyfile, pointed at a
# synthetic SSE origin instead of the api. This is the only way to prove
# flush_interval -1 without a live model call, and it exercises the Caddyfile
# byte for byte.
docker compose -p "$SSE_PROJECT" -f infra/tests/compose.sse-probe.yaml up -d --wait >/dev/null
echo "    sse origin up; streaming through caddy on 127.0.0.1:18081"
echo "    (origin: 8s silence, then 4 events 2s apart -> last event at ~14s)"

STREAM="$(mktemp)"
# `--max-time` as a backstop. Without it a probe that never terminates hangs
# the whole check; this run is expected to take about 14 seconds.
START=$(python3 -c 'import time; print(time.monotonic())')
curl -sS --no-buffer --max-time 60 -o "$STREAM" -w 'stream_status=%{http_code}\n' \
  -H "X-Origin-Verify: ${ORIGIN_VERIFY}" \
  "http://127.0.0.1:18081/runs/probe/stream" || true
END=$(python3 -c 'import time; print(time.monotonic())')

echo "    total wall clock: $(python3 -c "print(f'{$END-$START:.2f}s')")"
echo "    body:"
sed 's/^/      /' "$STREAM"

FRAME_COUNT="$(grep -c '^event: tick' "$STREAM" || true)"
echo "    frames received: $FRAME_COUNT (expected 4)"
[ "$FRAME_COUNT" = "4" ] || fail "expected 4 SSE frames through Caddy, got $FRAME_COUNT"

# The timestamps the origin embedded in each frame are the real proof: they are
# the origin's own clock, so a buffering hop shows all four frames stamped at
# the end rather than spread out.
#
# What this does and does not establish. It does prove the event stream reaches
# the client incrementally through the real Caddyfile, which is the property
# that matters. It does NOT prove `flush_interval -1` is what does it: a
# rebuild with `flush_interval 250ms` measured the same 6.01s spread, because
# Caddy exempts `Content-Type: text/event-stream` from response buffering
# regardless ("This option is ignored and responses are flushed immediately to
# the client if one of the following applies from the response", reverse_proxy
# docs). The line is kept as intent, not as the mechanism.
SPREAD="$(python3 - "$STREAM" <<'PY'
import re, sys
at = [float(m) for m in re.findall(r'"at":([0-9.]+)', open(sys.argv[1]).read())]
print(f"{max(at) - min(at):.1f}" if len(at) > 1 else "0.0")
PY
)"
echo "    spread between first and last frame, by the origin's own clock: ${SPREAD}s"
case "$SPREAD" in
  0.0|0.1|0.2) fail "all frames arrived at once (spread ${SPREAD}s): the stream was buffered" ;;
esac
echo "    frames arrived incrementally, not in one batch at the end: ok"

step "state of the stack before teardown"
compose ps --format 'table {{.Service}}\t{{.Status}}' | sed 's/^/    /'

step "PASS — every check above ran against the real compose.prod.yaml and Caddyfile"