#!/usr/bin/env bash
# Bring the beta up, or show what bringing it up would do.
#
#   ./up.sh              deploy everything
#   ./up.sh --plan       cdk diff + the dry run, and stop
#   ./up.sh --restore    deploy, then restore the last dump (no re-embedding)
#   ./up.sh --dry-run    print every command, call no AWS API
#
# Secrets: read from infra/.env (mode 600, git-ignored) and never printed.
# Names are checked; values are never echoed, logged, or passed on a command
# line where a process list could see them. Generated secrets (the database
# password, JWT_SECRET, the origin-verify value) are created here if absent and
# live only in SSM.
#
# Order matters and is not arbitrary:
#   persist → images → SSM → app → edge → bootstrap → wait
# SSM before app because the instance's bootstrap reads it; app before edge
# because the distribution needs the instance's public DNS name; edge before
# bootstrap because the api needs WEB_ORIGIN, which is the distribution's
# domain and does not exist until edge is deployed.

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Overridable so infra/tests can exercise the guards against a fixture without
# anyone having to create a real infra/.env.
ENV_FILE="${VF_ENV_FILE:-$INFRA_DIR/.env}"
ENV_EXAMPLE="$INFRA_DIR/.env.example"

DRY_RUN=0
PLAN=0
RESTORE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --plan) PLAN=1 ;;
    --restore) RESTORE=1 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2 ;;
  esac
done

REGION="ap-southeast-1"
STACK_PERSIST="VeriforgePersist"
STACK_APP="VeriforgeApp"
STACK_EDGE="VeriforgeEdge"
SSM_PREFIX="/veriforge/beta"

# ---------------------------------------------------------------- helpers ----

# Every command that talks to AWS goes through here, so --dry-run is one branch
# and cannot be forgotten at a call site.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  would run: %s\n' "$*"
  else
    "$@"
  fi
}

say() { printf '%s\n' "$*"; }
step() { say ""; say "==> $*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# Names only. Never a value.
require_names() {
  local missing=()
  local name
  for name in "$@"; do
    if ! grep -qE "^[[:space:]]*(export[[:space:]]+)?${name}=" "$ENV_FILE" 2>/dev/null; then
      missing+=("$name")
    fi
  done
  if [ ${#missing[@]} -gt 0 ]; then
    printf 'FAIL: %s is missing these variable NAMES:\n' "$(basename "$ENV_FILE")" >&2
    printf '  %s\n' "${missing[@]}" >&2
    printf 'See %s for what each one is and where to get it.\n' "$ENV_EXAMPLE" >&2
    exit 1
  fi
  say "    all required variable names are present in $(basename "$ENV_FILE")"
}

# ---------------------------------------------------------------- guards -----

step "checking $ENV_FILE"

if [ ! -f "$ENV_FILE" ]; then
  die "$ENV_FILE does not exist. Copy $ENV_EXAMPLE to it and fill it in."
fi

MODE="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")"
if [ "$MODE" != "600" ]; then
  die "$ENV_FILE has mode $MODE, not 600. It holds AWS and provider keys.
  chmod 600 $ENV_FILE"
fi
say "    mode 600, ok"

# Values are read into the environment but never printed. `set -a` + source
# means compose and cdk see them; nothing echoes them.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

AWS_PROFILE="${AWS_PROFILE:-${AWS_DEFAULT_PROFILE:-}}"
if [ -z "$AWS_PROFILE" ] && [ -z "${AWS_ACCESS_KEY_ID:-}" ]; then
  die "no AWS_PROFILE or AWS_ACCESS_KEY_ID in $(basename "$ENV_FILE")"
fi

ALARM_EMAIL="${ALARM_EMAIL:-}"

# These have no safe default. EMAIL_TRANSPORT=smtp in compose.prod.yaml plus
# ENVIRONMENT=production means apps/api/auth/email.py refuses to start without
# SMTP settings, so the api would crash-loop and CloudFront would serve 502s.
# See docs/ops/deploy-risk-checks.md finding 4c.
require_names \
  OPENROUTER_API_KEY \
  SMTP_HOST SMTP_USERNAME SMTP_PASSWORD SMTP_FROM \
  LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY

step "checking AWS credentials"
if [ "$DRY_RUN" -eq 1 ]; then
  printf '  would run: aws sts get-caller-identity --region %s\n' "$REGION"
  # Placeholders, so `set -u` does not kill the dry run at the first thing that
  # would have come back from a real call. An earlier version died here with
  # "ACCOUNT_ID: unbound variable" and printed nothing past the first step.
  ACCOUNT_ID="000000000000-dry-run"
else
  # The account id is printed by AWS itself. Nothing from .env is involved.
  ACCOUNT_ID="$(aws sts get-caller-identity --region "$REGION" --query Account --output text)"
  [ -n "$ACCOUNT_ID" ] || die "aws sts get-caller-identity returned no account"
  say "    authenticated to account $ACCOUNT_ID in $REGION"
fi

IMAGE_TAG="$(git rev-parse --short HEAD)"
API_LOCAL="veriforge/api:$IMAGE_TAG"
WEB_LOCAL="veriforge/web:$IMAGE_TAG"

# ------------------------------------------------------------------ plan ----

if [ "$PLAN" -eq 1 ]; then
  step "cdk diff (this is what would change)"
  for stack in "$STACK_PERSIST" "$STACK_APP" "$STACK_EDGE"; do
    say "  --- $stack ---"
    (cd infra/cdk && npx cdk diff "$stack" --region "$REGION" 2>&1 | head -60) || true
  done
  step "dry run"
  DRY_RUN=1
  "$0" --dry-run
  exit 0
fi

# ----------------------------------------------------------------- synth ----

step "cdk bootstrap (skipped if this account/region is already bootstrapped)"
run bash -c "cd '$REPO_ROOT/infra/cdk' && npx cdk bootstrap aws://$ACCOUNT_ID/$REGION --region $REGION"

step "deploying $STACK_PERSIST (ECR + the retained backups bucket)"
# Through run, not a bare subshell: `cdk deploy` synthesises AND calls AWS, so
# a dry run that invoked it directly reached "Unable to resolve AWS account to
# use" and died instead of printing the rest of the plan.
run bash -c "cd '$REPO_ROOT/infra/cdk' && npx cdk deploy $STACK_PERSIST --region $REGION --require-approval never" \
  || die "$STACK_PERSIST failed. The ECR URIs come from it, so nothing after this can run."

if [ "$DRY_RUN" -eq 1 ]; then
  say "  would read the repository URIs and the bucket name from $STACK_PERSIST's outputs"
  API_REPO="000000000000.dkr.ecr.$REGION.amazonaws.com/veriforge-beta-api"
  WEB_REPO="000000000000.dkr.ecr.$REGION.amazonaws.com/veriforge-beta-web"
  BACKUP_BUCKET="veriforge-beta-backups-dry-run"
else
  API_REPO="$(aws ecr describe-repositories --region "$REGION" \
    --query 'repositories[?repositoryName==\`veriforge-beta-api\`].repositoryUri' --output text)"
  WEB_REPO="$(aws ecr describe-repositories --region "$REGION" \
    --query 'repositories[?repositoryName==\`veriforge-beta-web\`].repositoryUri' --output text)"
  BACKUP_BUCKET="$(aws cloudformation describe-stacks --region "$REGION" \
    --stack-name "$STACK_PERSIST" \
    --query "Stacks[0].Outputs[?OutputKey=='BackupsBucketName'].OutputValue" --output text)"
  [ -n "$BACKUP_BUCKET" ] || die "could not read the backups bucket name from $STACK_PERSIST"
fi

# --------------------------------------------------------------- images ----

step "building and pushing images tagged $IMAGE_TAG"
if [ "$DRY_RUN" -eq 1 ]; then
  say "  would run: make image-build"
else
  make image-build
fi
API_IMAGE="$API_REPO:$IMAGE_TAG"
WEB_IMAGE="$WEB_REPO:$IMAGE_TAG"

if [ "$DRY_RUN" -eq 1 ]; then
  printf '  would run: docker tag %s %s && docker push\n' "$API_LOCAL" "$API_IMAGE"
  printf '  would run: docker tag %s %s && docker push\n' "$WEB_LOCAL" "$WEB_IMAGE"
  say "  would run: aws s3 cp compose.prod.yaml s3://$BACKUP_BUCKET/compose/compose.prod.yaml"
else
  for pair in "$API_LOCAL:$API_IMAGE" "$WEB_LOCAL:$WEB_IMAGE"; do
    docker tag "${pair%%:*}:${pair##*:}" "${pair}"
    docker push "${pair}"
  done
  # The instance fetches compose.prod.yaml from S3: it is a root file, so it is
  # not in any image, and git stays the single source of truth.
  aws s3 cp compose.prod.yaml "s3://$BACKUP_BUCKET/compose/compose.prod.yaml" --region "$REGION"
fi

# ------------------------------------------------------------------ SSM ----

step "writing SSM parameters under $SSM_PREFIX"

# Generated once and then kept: rotating the database password after a deploy
# would lock the instance out of its own data, and rotating JWT_SECRET logs
# every user out. `aws ssm get-parameter` returns non-zero when absent, which is
# the test for "generate me".
ssm_exists() { aws ssm get-parameter --region "$REGION" --name "$1" >/dev/null 2>&1; }

ssm_put() { # name value
  aws ssm put-parameter --region "$REGION" --name "$1" --value "$2" --type SecureString --overwrite >/dev/null
}

generate() { # length-in-bytes -> hex
  openssl rand -hex "$1"
}

if [ "$DRY_RUN" -eq 1 ]; then
  say "  would write SecureString parameters for every name in $ENV_EXAMPLE that is set,"
  say "  plus generated POSTGRES_PASSWORD, JWT_SECRET and ORIGIN_VERIFY if absent."
  say "  (values are never printed)"
else
  # Generated secrets. Never echoed, never in a file in the repo.
  if ssm_exists "$SSM_PREFIX/POSTGRES_PASSWORD"; then
    say "    POSTGRES_PASSWORD already exists; keeping it (rotating it locks the instance out of its data)"
  else
    ssm_put "$SSM_PREFIX/POSTGRES_PASSWORD" "$(generate 16)"
    say "    generated POSTGRES_PASSWORD"
  fi

  if ssm_exists "$SSM_PREFIX/JWT_SECRET"; then
    say "    JWT_SECRET already exists; keeping it (rotating it logs every user out)"
  else
    ssm_put "$SSM_PREFIX/JWT_SECRET" "$(generate 32)"
    say "    generated JWT_SECRET"
  fi

  if ssm_exists "$SSM_PREFIX/ORIGIN_VERIFY"; then
    say "    ORIGIN_VERIFY already exists; keeping it"
  else
    ssm_put "$SSM_PREFIX/ORIGIN_VERIFY" "$(generate 24)"
    say "    generated ORIGIN_VERIFY"
  fi

  # Everything else comes from infra/.env. Names only in the output.
  put_env_names=(
    OPENROUTER_API_KEY LITELLM_MASTER_KEY PROVIDER_ENCRYPTION_KEY
    EMBEDDING_MODEL REFERENCE_MODEL_ID
    TAVILY_API_KEY BRAVE_API_KEY COHERE_API_KEY NVIDIA_API_KEY
    LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST
    SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM
  )
  written=0
  for name in "${put_env_names[@]}"; do
    if [ -n "${!name:-}" ]; then
      ssm_put "$SSM_PREFIX/$name" "${!name}"
      written=$((written + 1))
    fi
  done
  say "    wrote $written values from $(basename "$ENV_FILE") (names only, no values printed)"
  unset OPENROUTER_API_KEY SMTP_PASSWORD JWT_SECRET POSTGRES_PASSWORD ORIGIN_VERIFY
fi

# ------------------------------------------------------------- app + edge ---

step "deploying $STACK_APP (instance, security group, log group)"
run bash -c "cd '$REPO_ROOT/infra/cdk' && npx cdk deploy $STACK_APP --region $REGION --require-approval never --parameters AlarmEmail='$ALARM_EMAIL'"

step "deploying $STACK_EDGE (CloudFront)"
# A counter, not a secret. It exists only to make the ssm:GetParameter read in
# the edge stack happen again, because ORIGIN_VERIFY changes on a fresh deploy.
ORIGIN_VERIFY_VERSION="$(date +%s)"
run bash -c "cd '$REPO_ROOT/infra/cdk' && ORIGIN_VERIFY_VERSION=$ORIGIN_VERIFY_VERSION npx cdk deploy $STACK_EDGE --region $REGION --require-approval never"

step "the CloudFront URL"
if [ "$DRY_RUN" -eq 1 ]; then
  DISTRIBUTION_ID="E000000000-dry-run"
else
  DISTRIBUTION_ID="$(aws cloudfront list-distributions --query \
    "DistributionList.Items[?Comment&&\`veriforge\`].Id | [0]" --output text)"
fi
WEB_ORIGIN="https://${DISTRIBUTION_ID}.cloudfront.net"
say "    $WEB_ORIGIN"
say "    (this changes on every re-deploy of the edge stack — there is no domain to hold it)"

# The api needs WEB_ORIGIN, which only exists now.
if [ "$DRY_RUN" -eq 1 ]; then
  printf '  would run: aws ssm put-parameter --name %s/WEB_ORIGIN --value <the URL above> --type SecureString\n' "$SSM_PREFIX"
else
  ssm_put "$SSM_PREFIX/WEB_ORIGIN" "$WEB_ORIGIN"
fi

# ------------------------------------------------------------- bootstrap ----

step "starting the stack on the instance (SSM Run Command)"
if [ "$DRY_RUN" -eq 1 ]; then
  INSTANCE_ID="i-0000000000000000-dry-run"
  say "  would find the running instance tagged project=veriforge"
else
  INSTANCE_ID="$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:project,Values=veriforge" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text)"
  [ -n "$INSTANCE_ID" ] || die "no running instance tagged project=veriforge in $REGION"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  COMMAND_ID="00000000-0000-0000-0000-000000000000-dry-run"
  say "  would run: aws ssm send-command --document-name AWS-RunShellScript"
  say "            API_IMAGE=$API_IMAGE WEB_IMAGE=$WEB_IMAGE \\"
  say "            BACKUP_BUCKET=$BACKUP_BUCKET /opt/veriforge/bootstrap.sh"
else
  COMMAND_ID="$(aws ssm send-command --region "$REGION" \
    --instance-ids "$INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[\
API_IMAGE=$API_IMAGE,WEB_IMAGE=$WEB_IMAGE,BACKUP_BUCKET=$BACKUP_BUCKET \
/opt/veriforge/bootstrap.sh]" \
    --query 'Command.CommandId' --output text)"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  say "  would poll SSM command $COMMAND_ID"
else
  say "    waiting for the bootstrap to finish (docker pull + migrations, a few minutes)"
  for _ in $(seq 1 90); do
    STATUS="$(aws ssm get-command-invocation --region "$REGION" \
      --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
      --query 'Status' --output text)"
    case "$STATUS" in
      Success) say "    bootstrap succeeded"; break ;;
      Failed|Timeout|Cancelled|Aborted)
        echo "FAIL: the bootstrap on the instance reported $STATUS. Its output:" >&2
        aws ssm get-command-invocation --region "$REGION" \
          --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
          --query 'StandardOutputContent' --output text >&2
        exit 1
        ;;
    esac
    sleep 10
  done
fi

# ----------------------------------------------------------------- wait -----

step "waiting for /healthz to answer THROUGH CloudFront"
if [ "$DRY_RUN" -eq 1 ]; then
  say "  would poll https://$DISTRIBUTION_ID.cloudfront.net/healthz"
  say "  a non-200 here means the origin is not answering through the edge"
else
  ok=0
  for _ in $(seq 1 60); do
    CODE="$(curl -sS -o /dev/null -w '%{http_code}' "$WEB_ORIGIN/healthz" 2>/dev/null || true)"
    if [ "$CODE" = "200" ]; then ok=1; break; fi
    sleep 10
  done
  [ "$ok" -eq 1 ] || die "/healthz never answered 200 through CloudFront (last: ${CODE:-000}).
  Check the distribution exists, the instance's security group allows the
  CloudFront prefix list, and the bootstrap's output above."
  say "    200 through CloudFront"
  curl -fsS "$WEB_ORIGIN/healthz" | sed 's/^/    /'
fi

# --------------------------------------------------------------- restore ----

if [ "$RESTORE" -eq 1 ]; then
  step "restoring the last dump (no re-embedding)"
  if [ "$DRY_RUN" -eq 1 ]; then
    say "  would run: ./scripts/restore.sh latest --bucket $BACKUP_BUCKET"
  else
    "$REPO_ROOT/scripts/restore.sh" latest --bucket "$BACKUP_BUCKET" || \
      die "the restore failed. See docs/ops/runbook.md."
  fi
fi

step "up"
say "    $WEB_ORIGIN"
say "    admin: mint one over SSM Session Manager, per docs/ops/runbook.md"
say "    tear down with: infra/down.sh"