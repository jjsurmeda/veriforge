#!/usr/bin/env bash
# Is it up, where, for how long, and what has it cost?
#
#   ./status.sh            report
#   ./status.sh --dry-run  print the calls it would make, call no AWS API

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
cd "$REPO_ROOT"

REGION="ap-southeast-1"
PROJECT_TAG="veriforge"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
step() { say ""; say "==> $*"; }

if [ "$DRY_RUN" -eq 1 ]; then
  step "status (dry run — no AWS API called)"
  say "  would run, in order:"
  say "    aws ec2 describe-instances    --filters tag:project=$PROJECT_TAG"
  say "    aws cloudfront list-distributions --query '...Comment contains $PROJECT_TAG'"
  say "    curl -sS -o /dev/null -w '%{http_code}' https://<id>.cloudfront.net/healthz"
  say "    aws ce get-cost-and-usage     --time-period Start=<month-start>,End=<today>"
  exit 0
fi

# ------------------------------------------------------------------- up? ----

step "the instance"
INSTANCE_JSON="$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:project,Values=$PROJECT_TAG" \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,LaunchTime,PublicIpAddress]' \
  --output json)"

INSTANCE_ID="$(printf '%s' "$INSTANCE_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0][0] if d else "")')"
if [ -z "$INSTANCE_ID" ]; then
  say "  no instance tagged project=$PROJECT_TAG in $REGION."
  say "  The beta is down. Nothing is billing except, possibly, the persist stack:"
  say "  ./down.sh prints the sweep; ./down.sh --all removes it too."
  exit 0
fi

printf '%s' "$INSTANCE_JSON" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
for iid, itype, state, launched, ip in rows:
    print(f"  {iid}  {itype}  {state}  since {launched}  {ip}")
'

# --------------------------------------------------------------- the url ----

step "the URL"
DIST_ID="$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment&&\`$PROJECT_TAG\`].Id | [0]" --output text)"
if [ -z "$DIST_ID" ]; then
  say "  no CloudFront distribution found. up.sh may not have finished."
  exit 0
fi
URL="https://${DIST_ID}.cloudfront.net"
say "  $URL"

# ----------------------------------------------------------------- alive ----

step "is it answering"
CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$URL/healthz" 2>/dev/null || true)"
case "$CODE" in
  200)
    say "  /healthz -> 200"
    curl -fsS --max-time 15 "$URL/healthz" | python3 -m json.tool | sed 's/^/    /' 2>/dev/null || true
    ;;
  000) say "  /healthz did not answer at all — the distribution exists but the origin is not reachable through it." ;;
  *)   say "  /healthz -> $CODE. 502 means Caddy could not reach the api on the instance." ;;
esac

# ----------------------------------------------------------------- uptime ---

step "uptime"
say "  instance launched at the time above."
if command -v uptime >/dev/null 2>&1; then :; fi
python3 - <<'PY'
import json, subprocess, datetime
raw = subprocess.run(
    ["aws", "ec2", "describe-instances", "--region", "ap-southeast-1",
     "--filters", "Name=tag:project,Values=veriforge",
     "--query", "Reservations[].Instances[].LaunchTime", "--output", "text"],
    capture_output=True, text=True)
first = raw.stdout.strip().splitlines()
if not first:
    raise SystemExit
launched = datetime.datetime.fromisoformat(first[0].replace("Z", "+00:00"))
now = datetime.datetime.now(datetime.timezone.utc)
delta = now - launched
hours = delta.total_seconds() / 3600
print(f"  up for {hours:.1f} hours ({delta.days} d {delta.seconds // 3600} h)")
# Item 0's estimate: about $0.04/h for t4g.medium in ap-southeast-1. Rough on
# purpose, and it says so; the authoritative number is the budget email.
print(f"  instance cost so far, roughly: ${hours * 0.04:.2f} at ~$0.04/h (estimate, not billing data)")
PY

# ------------------------------------------------------------------ cost ----

step "cost so far (Cost Explorer — the real number, up to 24h behind)"
TODAY="$(date -u +%Y-%m-%d)"
MONTH_START="$(date -u +%Y-%m-01)"
aws ce get-cost-and-usage --region "$REGION" \
  --time-period "Start=$MONTH_START,End=$TODAY" \
  --granularity MONTHLY --metrics UnblendedCost \
  --query 'ResultsByTime[].[TimePeriod.Start,Total.UnblendedCost.Amount]' --output text 2>/dev/null \
  | sed 's/^/  /' \
  || say "  Cost Explorer is unavailable on this account (it needs billing permissions)."
say "  Cost Explorer lags by up to a day, and the budget email is the authoritative alarm."

step "alarms in breach"
aws cloudwatch describe-alarms --region "$REGION" \
  --alarm-name-prefix VeriforgeBudget \
  --state-value ALARM \
  --query 'MetricAlarms[].[AlarmName,StateValue,NewStateReason]' --output text 2>/dev/null \
  | sed 's/^/  /' || say "  could not read alarms"
say "  (no lines above means nothing is in ALARM)"