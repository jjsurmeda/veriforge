#!/usr/bin/env bash
# Tear the beta down. One command, and nothing left billing.
#
#   ./down.sh               dump, destroy edge + app, delete SSM, sweep the tag
#   ./down.sh --no-backup   skip the final dump
#   ./down.sh --all         also destroy persist (asks you to type the name)
#   ./down.sh --dry-run     print what it would do, call no AWS API
#
# Order: dump first, because destroying the instance destroys the database with
# it. Then edge, then app, then the SSM parameters, then a sweep by the
# project=veriforge tag for anything the stack templates missed — and whatever
# the sweep finds is listed, because "nothing billable remains" is a claim that
# has to be printed, not assumed.

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
cd "$REPO_ROOT"

REGION="ap-southeast-1"
PROJECT_TAG="veriforge"
STACK_PERSIST="VeriforgePersist"
STACK_APP="VeriforgeApp"
STACK_EDGE="VeriforgeEdge"
STACK_BUDGET="VeriforgeBudget"
SSM_PREFIX="/veriforge/beta"

NO_BACKUP=0
ALL=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --no-backup) NO_BACKUP=1 ;;
    --all) ALL=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
step() { say ""; say "==> $*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
run() { if [ "$DRY_RUN" -eq 1 ]; then printf '  would run: %s\n' "$*"; else "$@"; fi; }

# --------------------------------------------------------------- the dump ---

if [ "$NO_BACKUP" -eq 0 ]; then
  step "taking a final database dump"
  # Run on the instance while it still exists and still has the database. The
  # cron entry uploads daily, so this is belt and braces rather than the only
  # copy.
  if [ "$DRY_RUN" -eq 1 ]; then
    say "  would run the dump on the instance over SSM Run Command"
    say "  would run: aws ssm send-command --document-name AWS-RunShellScript /opt/veriforge/backup.sh"
  else
    INSTANCE_ID="$(aws ec2 describe-instances --region "$REGION" \
      --filters "Name=tag:project,Values=$PROJECT_TAG" "Name=instance-state-name,Values=running" \
      --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)"
    if [ -z "$INSTANCE_ID" ]; then
      say "    no running instance; nothing to dump (is the beta already down?)"
    else
      CMD="$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE_ID" \
        --document-name AWS-RunShellScript \
        --parameters 'commands=[/opt/veriforge/backup.sh]' \
        --query 'Command.CommandId' --output text)"
      say "    waiting for the dump (command $CMD)"
      for _ in $(seq 1 60); do
        STATUS="$(aws ssm get-command-invocation --region "$REGION" --command-id "$CMD" \
          --instance-id "$INSTANCE_ID" --query Status --output text)"
        case "$STATUS" in
          Success) say "    dump uploaded"; break ;;
          Failed|Timeout|Cancelled|Aborted)
            say "    the dump reported $STATUS; the daily cron copies may still be intact"
            break ;;
        esac
        sleep 10
      done
    fi
  fi
else
  step "skipping the final dump (--no-backup)"
fi

# ------------------------------------------------------------- the stacks ---

step "destroying $STACK_EDGE"
run bash -c "cd '$REPO_ROOT/infra/cdk' && npx cdk destroy $STACK_EDGE --region $REGION --require-approval never"

step "destroying $STACK_APP"
run bash -c "cd '$REPO_ROOT/infra/cdk' && npx cdk destroy $STACK_APP --region $REGION --require-approval never"

step "destroying $STACK_BUDGET"
run bash -c "cd '$REPO_ROOT/infra/cdk' && npx cdk destroy $STACK_BUDGET --region $REGION --require-approval never"

# ------------------------------------------------------------------- SSM ----

step "deleting the SSM parameters under $SSM_PREFIX"
# --force-deletion exists for parameters an earlier interrupted run left behind.
run aws ssm delete-parameter --region "$REGION" --name "$SSM_PREFIX" --recursive --force-deletion

# ------------------------------------------------------------------ sweep ---

step "sweeping everything tagged project=$PROJECT_TAG"
say "Anything listed below is billable and was NOT destroyed by the stacks above."
say "This is the check, not a formality: the point of down.sh is that the owner"
say "never has to wonder whether something is still charging."

if [ "$DRY_RUN" -eq 1 ]; then
  say "  would run, and list anything found:"
  say "    aws ec2 describe-instances            --filters tag:project=$PROJECT_TAG"
  say "    aws elbv2 describe-load-balancers    --query 'LoadBalancers[?Tags[?Key==\`project\` && Value==\`$PROJECT_TAG\`]]'"
  say "    aws cloudfront list-distributions    --query 'DistributionList.Items[?Comment&&\`$PROJECT_TAG\`]'"
  say "    aws logs describe-log-groups          --query 'logGroups[?logGroupName&&\`$PROJECT_TAG\`]'"
  say "    aws s3api list-buckets               --query 'Buckets[?Name&&\`$PROJECT_TAG\`]'"
  say "    aws sqs list-queues                   --query 'QueueUrls[?contains(@, \`$PROJECT_TAG\`)]'"
  say "    aws rds describe-db-instances         --query 'DBInstances[?contains(DBInstanceIdentifier, \`$PROJECT_TAG\`)]'"
  say "    aws budgets describe-budgets          --query 'Budgets[?contains(BudgetName, \`$PROJECT_TAG\`)]'"
else
  found=0
  report() { # label json
    local label="$1" json="$2"
    if [ "$(printf '%s' "$json" | tr -d ' \n')" != "[]" ] && [ -n "$json" ]; then
      found=$((found + 1))
      say "  STILL PRESENT ($label):"
      printf '%s\n' "$json" | sed 's/^/    /'
    fi
  }

  report "ec2 instances" "$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:project,Values=$PROJECT_TAG" \
    --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name]' --output json)"
  report "security groups" "$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=tag:project,Values=$PROJECT_TAG" \
    --query 'SecurityGroups[].[GroupId,GroupName]' --output json)"
  report "ebs volumes" "$(aws ec2 describe-volumes --region "$REGION" \
    --filters "Name=tag:project,Values=$PROJECT_TAG" \
    --query 'Volumes[].[VolumeId,Size,State]' --output json)"
  report "cloudfront distributions" "$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment&&\`$PROJECT_TAG\`].[Id,DomainName,Comment]" --output json)"
  report "cloudwatch log groups" "$(aws logs describe-log-groups --region "$REGION" \
    --query "logGroups[?contains(logGroupName, \`$PROJECT_TAG\`)].[logGroupName,storedBytes]" --output json)"
  report "s3 buckets" "$(aws s3api list-buckets \
    --query "Buckets[?contains(Name, \`$PROJECT_TAG\`)].Name" --output json)"
  report "ecr repositories" "$(aws ecr describe-repositories --region "$REGION" \
    --query "repositories[?contains(repositoryName, \`$PROJECT_TAG\`)].[repositoryName,repositoryArn]" --output json)"
  report "budgets" "$(aws budgets describe-budgets --region "$REGION" \
    --account-id "$(aws sts get-caller-identity --query Account --output text)" \
    --query "Budgets[?contains(BudgetName, \`$PROJECT_TAG\`)].[BudgetName,BudgetLimit.Amount]" --output json)"
  report "sns topics" "$(aws sns list-topics --region "$REGION" \
    --query "Topics[?contains(TopicArn, \`$PROJECT_TAG\`)].TopicArn" --output json)"

  if [ "$found" -eq 0 ]; then
    say "  nothing found: no instance, volume, distribution, log group, bucket,"
    say "  repository, budget or topic is left. Nothing should still be billing."
  else
    say "  $found resource group(s) still present — see above."
  fi
fi

# ---------------------------------------------------------------- persist ---

step "persist stack"
if [ "$ALL" -eq 0 ]; then
  say "  left alone (it holds the backups bucket and the repositories, so the next"
  say "  up.sh --restore can bring the corpus back without re-embedding)."
  say "  Its cost is a few cents: a retained bucket of daily dumps and two"
  say "  repositories of images. Destroy it with: infra/down.sh --all"
else
  if [ "$DRY_RUN" -eq 1 ]; then
    say "  would ask you to type the project name, then destroy $STACK_PERSIST"
  else
    say ""
    say "  --all also destroys $STACK_PERSIST, which DELETES the backups bucket."
    say "  That is the database. With no dump anywhere else, the corpus is gone and"
    say "  the books would have to be re-embedded."
    printf '  Type %s to confirm: ' "$PROJECT_TAG"
    read -r CONFIRM
    if [ "$CONFIRM" != "$PROJECT_TAG" ]; then
      die "that is not the project name; $STACK_PERSIST left alone"
    fi
    run bash -c "cd '$REPO_ROOT/infra/cdk' && npx cdk destroy $STACK_PERSIST --region $REGION --require-approval never"
  fi
fi

step "done"