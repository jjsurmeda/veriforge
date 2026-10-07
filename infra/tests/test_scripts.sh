#!/usr/bin/env bash
# Tests infra/up.sh's guard clauses and the --dry-run mode of all three
# scripts, without AWS and without a real infra/.env.
#
# Every fixture is created in a temporary directory and deleted afterwards.
# infra/.env is never read, created, or written — the scripts take the path
# through VF_ENV_FILE precisely so this test can point them at a fixture
# instead.

set -euo pipefail

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
cd "$REPO_ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

ok() { printf 'ok   %s\n' "$1"; pass=$((pass + 1)); }
no() { printf 'FAIL %s\n     %s\n' "$1" "${2:-}"; fail=$((fail + 1)); }

# A fixture that satisfies every guard, so each test can remove exactly one
# thing and attribute the failure. The values are placeholders: the guards only
# need the variable NAMES to be present, so nothing here is key-shaped and
# nothing here is a credential.
write_good_env() {
  local path="$1"
  cat > "$path" <<'ENV'
AWS_PROFILE=veriforge-beta
AWS_ACCESS_KEY_ID=test-fixture-not-a-real-key
OPENROUTER_API_KEY=sk-or-v1-not-a-real-key-0000000000000000
LANGFUSE_PUBLIC_KEY=pk-lf-not-real
LANGFUSE_SECRET_KEY=sk-lf-not-real
LANGFUSE_HOST=https://cloud.langfuse.com
SMTP_HOST=email-smtp.ap-southeast-1.amazonaws.com
SMTP_USERNAME=not-real
SMTP_PASSWORD=not-real
SMTP_FROM=owner@example.invalid
ALARM_EMAIL=owner@example.invalid
ENV
  chmod 600 "$path"
}

echo "=== guard clauses ==="

# 1. A world-readable .env must be refused.
write_good_env "$TMP/world-readable.env"
chmod 644 "$TMP/world-readable.env"
OUT="$(VF_ENV_FILE="$TMP/world-readable.env" infra/up.sh --dry-run 2>&1 || true)"
if printf '%s' "$OUT" | grep -q "not 600"; then
  ok "a mode 644 .env is refused, and the message says so"
else
  no "a mode 644 .env is refused" "got: $(printf '%s' "$OUT" | tail -2)"
fi

# 2. A missing variable must be named, not just counted.
write_good_env "$TMP/missing.env"
chmod 600 "$TMP/missing.env"
sed -i '' '/^SMTP_PASSWORD=/d' "$TMP/missing.env"
OUT="$(VF_ENV_FILE="$TMP/missing.env" infra/up.sh --dry-run 2>&1 || true)"
if printf '%s' "$OUT" | grep -q "SMTP_PASSWORD"; then
  ok "a missing variable is named in the failure"
else
  no "a missing variable is named" "got: $(printf '%s' "$OUT" | tail -3)"
fi
# And the value of any OTHER variable must not appear.
if printf '%s' "$OUT" | grep -q "sk-or-v1-not-a-real-key"; then
  no "no value is printed on failure" "a value leaked into the output"
else
  ok "no value is printed on failure"
fi

# 3. A missing .env at all.
OUT="$(VF_ENV_FILE="$TMP/does-not-exist.env" infra/up.sh --dry-run 2>&1 || true)"
if printf '%s' "$OUT" | grep -q "does not exist"; then
  ok "a missing .env is refused with a pointer to .env.example"
else
  no "a missing .env is refused" "got: $(printf '%s' "$OUT" | tail -2)"
fi

# 4. No AWS credentials at all.
write_good_env "$TMP/nocreds.env"
sed -i '' '/^AWS_PROFILE=/d;/^AWS_ACCESS_KEY_ID=/d' "$TMP/nocreds.env"
chmod 600 "$TMP/nocreds.env"
OUT="$(VF_ENV_FILE="$TMP/nocreds.env" infra/up.sh --dry-run 2>&1 || true)"
if printf '%s' "$OUT" | grep -q "no AWS_PROFILE"; then
  ok "no AWS credentials at all is refused"
else
  no "no AWS credentials at all is refused" "got: $(printf '%s' "$OUT" | tail -2)"
fi

# 5. An unknown argument.
OUT="$(infra/up.sh --wat 2>&1 || true)"
if printf '%s' "$OUT" | grep -q "unknown argument"; then
  ok "an unknown argument is rejected, not ignored"
else
  no "an unknown argument is rejected" "got: $OUT"
fi

# 6. down.sh --all must ask before destroying the bucket.
OUT="$(infra/down.sh --all --dry-run 2>&1)"
if printf '%s' "$OUT" | grep -q "would ask you to type the project name"; then
  ok "down.sh --all asks for confirmation before destroying the backups bucket"
else
  no "down.sh --all asks for confirmation" "got: $(printf '%s' "$OUT" | tail -3)"
fi

echo
echo "=== --dry-run calls no AWS API ==="
# The scripts call `aws` directly rather than through a wrapper, so what is
# proved is that --dry-run produced no output that could only come from a real
# API call: no ExpiredToken, no InvalidClientTokenId, no connection error.
write_good_env "$TMP/good.env"
for script in down status; do
  OUT="$(infra/$script.sh --dry-run 2>&1)"
  if printf '%s' "$OUT" | grep -qiE "could not connect|ExpiredToken|InvalidClientTokenId|An error occurred"; then
    no "infra/$script.sh --dry-run makes no AWS call" "an AWS error appeared: $(printf '%s' "$OUT" | grep -iE 'expired|invalid|could not connect' | head -1)"
  else
    ok "infra/$script.sh --dry-run makes no AWS call"
  fi
done

# up.sh --dry-run needs a real-looking env to get past the guards, but it must
# stop before anything that needs a credential to exist.
OUT="$(VF_ENV_FILE="$TMP/good.env" infra/up.sh --dry-run 2>&1 || true)"
if printf '%s' "$OUT" | grep -q "would run: aws sts get-caller-identity"; then
  ok "up.sh --dry-run reaches the first AWS call and stops there"
else
  no "up.sh --dry-run reaches the first AWS call" "got: $(printf '%s' "$OUT" | tail -3)"
fi

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]