# Day-2 checklist for the owner

Run this in order after the first `infra/up.sh`. Each item says what to do, what
to expect, and — where it matters — what it means if you do **not** get it.

Everything here is unchecked by this lane, because it needs AWS or provider
credit. The local proofs that *were* run are listed at the bottom so you can
tell the difference.

**Have open:** the `infra/up.sh` terminal, the CloudWatch log group
`/veriforge/beta/docker`, and this file.

---

## 1. `up.sh` finished and printed a URL

```bash
infra/status.sh
```

Expect the instance `running`, a `https://<id>.cloudfront.net` URL, and
`/healthz -> 200` with `status: ok`, `db: ok`.

**If /healthz is 502:** Caddy is up but cannot reach the api container. The api
refuses to start without SMTP settings — check the bootstrap output, which
`up.sh` prints on failure, and confirm `SMTP_HOST`/`SMTP_FROM` are in
`infra/.env`.

**If /healthz is 403:** the origin-verify value did not match. The most likely
cause is that the distribution was deployed before the SSM parameter existed.
Re-run `infra/up.sh`, which re-reads SSM and bumps the origin-verify version.

## 2. A direct request to the instance is refused

```bash
PUBLIC_DNS=$(aws ec2 describe-instances --region ap-southeast-1 \
  --filters "Name=tag:project,Values=veriforge" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
curl -sS -o /dev/null -w '%{http_code}\n' "http://$PUBLIC_DNS/"
```

Expect **403**. Anything else — 200 especially — means the origin is open and
the whole point of the security group plus the origin-verify header is not
holding.

Also confirm the security group has no rule but the CloudFront prefix list:

```bash
aws ec2 describe-security-groups --region ap-southeast-1 \
  --filters "Name=group-id,Values=<sg-id from the App stack outputs>" \
  --query 'SecurityGroups[0].IpPermissions'
```

Expect exactly one: tcp 80, `SourcePrefixListId: pl-31a34658`. No port 22.

And verify that prefix list id is what it claims to be:

```bash
aws ec2 describe-managed-prefix-lists --region ap-southeast-1 \
  --prefix-list-ids pl-31a34658 \
  --query 'PrefixLists[0].PrefixListName'
```

Expect `com.amazonaws.global.cloudfront.origin-facing`. **If this prints
something else**, the security group is allowing the wrong ranges — stop and
pass the right id via the `CloudFrontPrefixListId` parameter.

## 3. `/library` works in the browser

Open `https://<id>.cloudfront.net/library` and navigate to it by clicking a
link, not by typing the URL.

Expect the SPA's library page. **If you get JSON, or a 404**, then CloudFront
is not forwarding the browser's `Accept: text/html` header to the origin and
Caddy's collision rule cannot tell a document navigation from an XHR. This is
the single most likely production-only failure in the whole design, and it is
the reason the origin request policy is `AllViewerExceptHostHeader`. Confirm
with the browser devtools' network tab: the request to `/library` should carry
an `Accept` header containing `text/html`.

## 4. Sign-up with an invite, then login

Add an invite (see the runbook), sign up in the browser, then log out and log
back in.

Expect it to work, and expect the **silent refresh** to work: with the access
token expired the SPA should call `/auth/refresh` without you noticing.

**Check the cookie** in devtools → Application → Cookies. `vf_refresh` must
have `Secure`, `HttpOnly`, `SameSite=Strict`, and `Path=/auth`. If `Secure` is
missing, `COOKIE_SECURE` did not reach the api.

`SameSite=Strict` with `Path=/auth` on `*.cloudfront.net` is the combination
the SPA was built around — `apps/web/vite.config.ts` uses relative URLs
(`baseUrl: ''`) precisely so one origin serves both. If the refresh cookie is
dropped, that pairing is the thing to look at.

## 5. The rate limiter sees the viewer, not CloudFront

Watch the api log while you hammer a login endpoint from your browser:

```bash
aws logs tail /veriforge/beta/docker --follow --format short | grep -i rate
```

Then, from **two different machines or networks** (two viewers), confirm the
limiter treats them separately: 10 login attempts each, both getting 401, and
the 11th on each getting 429. **If the second viewer starts getting 429 while
the first still has budget**, the limiter is keyed on one shared address and
`--forwarded-allow-ips` is not matching Caddy — the KI-59 failure, which is
silent and looks exactly like a working limiter.

You can see the same thing locally and it was proven there:
`infra/prod_compose_check.sh` step 6 shows two viewers with two buckets and a
spoofed `X-Forwarded-For` prefix not resetting either.

## 6. An SSE run streams for 60 s without stalling

Ask a question that takes a minute — Deep mode, several hops. Watch the tokens
arrive one at a time.

Expect a heartbeat every ~15 s (`heartbeat_interval_seconds = 15`) and no
long gap. **If the stream stalls and then dumps everything at once**, something
is buffering. In order of likelihood:

1. `OriginReadTimeout` is not 120s on the distribution, and a >30 s gap between
   packets broke the stream. Check:
   ```bash
   aws cloudfront get-distribution --id <id> \
     --query 'Distribution.DistributionConfig.Origins[0].OriginCustomConfig'
   ```
2. Caddy is buffering — it should not be, and `flush_interval -1` is set
   (though Caddy exempts `text/event-stream` from buffering on its own).

This is the check the local suite deliberately could **not** do: a real 60 s run
spends provider credit, and this lane spends none.

## 7. `/healthz` shows the breaker and Jev state

```bash
curl -sS "https://<id>.cloudfront.net/healthz" | python3 -m json.tool
```

Expect `status: ok`, `db: ok`, `breaker: closed`, `jev: ok`, and
`worker_heartbeat_age_s` as a number **after** a run has happened (`null`
before the first run is correct and expected — see `docs/ops/signals.md`).

**If `breaker` is `open` or `jev` is `degraded`**, routing is on the LLM
fallback and the alarm `BreakerOpenedAlarm` should have fired. Check whether it
did — that is item 8.

## 8. The alarms fire

In the CloudWatch console, or:

```bash
aws cloudwatch describe-alarms --region ap-southeast-1 \
  --alarm-name-prefix VeriforgeBudget
```

Expect five alarms, all `OK`, and all wired to the SNS topic:

- `RunFailedAlarm` — `run.failed`
- `BreakerOpenedAlarm` — `breaker.opened`
- `ProviderCreditLowAlarm` — `provider.credit_low`
- `HighCpuAlarm` — `AWS/EC2 CPUUtilization`
- `DiskFullAlarm` — `Veriforge/Beta disk_used_percent` (the CloudWatch agent)

**Test one on purpose.** Put a run in and let it fail, or fill the disk, and
confirm the alarm transitions to `ALARM` and the email arrives. An alarm that
has never been seen to fire is not known to work.

Two things to check while you are there:

- **The metric filters match.** If the JSON signal lines never reached the log
  group, all three signal alarms sit at `OK` forever and mean nothing. Confirm
  lines are arriving first:
  ```bash
  aws logs tail /veriforge/beta/docker --since 30m --format short | head -20
  ```
  You should see the api's structured lines. If the log group is empty, the
  `awslogs` log driver is not configured on the instance.
- **The budget email.** The budget is `MONTHLY`, `$20`, notifying at 80% of
  actual and forecast. You cannot wait for it; confirm the subscription is
  accepted by checking the SES-verified address has the confirmation, and
  accept the SNS topic subscription email that AWS sent.

## 9. The daily `pg_dump` cron lands in S3

```bash
aws ssm start-session --target <instance-id> --command "/opt/veriforge/backup.sh"
aws s3 ls s3://<backups-bucket>/db/
```

Expect a `.dump` file and the script to print `dump uploaded to ...`. The cron
entry itself is at `/etc/cron.d/veriforge-backup`, daily at 03:17 UTC.

## 10. A restore brings the books back with no re-embedding

The important one:

```bash
infra/up.sh --restore
```

Then open the site and ask a question about a document you uploaded before the
tear-down. Expect a grounded answer with citations, **immediately** — no
re-ingestion, no waiting, no provider charge.

Then confirm the row counts came back:

```bash
aws ssm start-session --target <instance-id> --command \
  "docker compose -f /opt/veriforge/compose.prod.yaml exec postgres \
     psql -U veriforge -d veriforge -tAc \
     \"select 'users='||(select count(*) from users)||' documents='||(select count(*) from documents)||' chunks='||(select count(*) from chunks);\""
```

Expect non-zero counts matching what you had. This was proven locally on a
14,216-chunk corpus with a byte-identical embedding; what is new here is the
S3 path and the deployed instance.

## 11. `down.sh` leaves nothing billable

```bash
infra/down.sh
```

Read the sweep section of the output. Expect the two lines:

```
  nothing found: no instance, volume, distribution, log group, bucket,
  repository, budget or topic is left. Nothing should still be billing.
```

**Anything under `STILL PRESENT` is still charging you.** Work through it before
you stop. Then:

```bash
infra/down.sh --all      # optional: also drops the backups bucket
```

---

## What was actually verified locally

So you know what these checks are adding to, and what they are not re-testing:

| proven locally | how |
| --- | --- |
| every image has a `linux/arm64` build, ParadeDB included | `docker manifest inspect` |
| the memory table, against a 14,216-chunk database | `docker stats`, 3 identical samples |
| the origin lock refuses an unverified request with 403 | the whole production compose, item 1 of the check |
| `/library` serves the SPA with `Accept: text/html` and the api without | same |
| the limiter gives two viewers two buckets and ignores a spoofed prefix | same |
| SSE arrives unbuffered through the real Caddyfile | a timed synthetic origin through the same Caddyfile |
| a dump/restore round trip preserves 1353 users, 32 documents, 14,216 chunks and a byte-identical embedding | `infra/tests/test_backup_restore.sh` |
| `cdk synth` for all four stacks, 31 assertions on the template | `npx jest` |
| the scripts' guard clauses and `--dry-run` | `infra/tests/test_scripts.sh` |

**Not verified here, and why:** anything needing AWS credentials, anything
needing the real distribution or instance, and anything spending provider
credit — chiefly the 60 s live SSE run and a real end-to-end question. Those
are items 3, 6 and 10 above, and they are the reason this list exists.