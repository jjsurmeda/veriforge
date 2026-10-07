# Beta runbook

One week, one box, no domain. Bring it up when you want it, tear it down when
you are done. This is the whole operating manual.

The risk checks that justify the sizing and the CloudFront settings are in
[deploy-risk-checks.md](deploy-risk-checks.md). The operational signals the
alarms are built on are in [signals.md](signals.md).

## Before the first run, once

### SES, in `ap-southeast-1`

There is no domain, so SES stays in the **sandbox**. That is a hard limit, not a
setting:

> Mail only reaches addresses verified in this account and region.

So **password reset works for you and for nobody else.** When a beta user
forgets their password, mint them a new invite instead (`Add an invite` below).
Say this to them up front rather than letting them discover it.

1. SES console → *Email identities* → *Verify email address* → verify your own
   address. Instant, no production access needed.
2. SES console → *SMTP credentials* → *Create SMTP credentials*. You get a
   username and a password.
3. Put them in `infra/.env` as `SMTP_USERNAME` and `SMTP_PASSWORD`, with
   `SMTP_FROM` set to the verified address.
4. `chmod 600 infra/.env`.

**Order matters.** `compose.prod.yaml` sets `ENVIRONMENT=production` and
`EMAIL_TRANSPORT=smtp`, and `apps/api/main.py`'s lifespan calls
`build_email_transport` before it opens any connection —
`apps/api/auth/email.py` refuses to start without a host and a sender. Deploy
before these are in place and the api crash-loops while CloudFront serves 502s.

### `infra/.env`

```bash
cp infra/.env.example infra/.env
$EDITOR infra/.env      # every value; see the comments in the example
chmod 600 infra/.env
```

Every script refuses to run if the mode is not 600, and never prints a value —
only variable names. See `.env.example` for what each name is and where to get
it.

`POSTGRES_PASSWORD`, `JWT_SECRET` and `ORIGIN_VERIFY` are **not** in `.env`.
`up.sh` generates them into SSM on the first deploy and keeps them.

## Bring up

```bash
infra/up.sh --plan     # cdk diff + the dry run, nothing changes
infra/up.sh            # the real thing
```

Roughly 15 minutes: image builds are cached after the first run, so most of it
is ECR pulls and the database coming up. It ends by printing the URL, which
looks like `https://<something>.cloudfront.net`.

**The URL changes on every re-deploy of the edge stack.** With no domain there
is nothing holding it steady. `up.sh` rewrites `WEB_ORIGIN` in SSM after the
distribution exists, so re-running `up.sh` is always safe — but any invitation
you pasted the old URL into is stale.

`up.sh --restore` additionally restores the last database dump. See below.

## Tear down

```bash
infra/down.sh              # dump, destroy, sweep, report
infra/down.sh --no-backup  # skip the final dump
infra/down.sh --all        # also destroy persist (asks you to type the name)
```

`down.sh` takes a final `pg_dump` **first**, because destroying the instance
destroys the database with it. Then it destroys the edge, app and budget stacks,
deletes the SSM parameters, and sweeps everything tagged `project=veriforge`,
**printing anything that is still there**. That list is the point: "nothing is
left billing" is a claim you should see, not one you assume.

`--all` destroys `persist`, which **deletes the backups bucket and with it the
corpus.** It asks you to type the project name first. Without `--all` the
retained bucket and the two ECR repositories survive, which is what makes the
next bring-up cheap; they cost a few cents.

## Restore, without re-embedding

```bash
infra/up.sh --restore
# or, by hand:
scripts/restore.sh latest --bucket <the bucket from VeriforgePersist's outputs>
scripts/restore.sh /path/to/a/dump
```

The corpus comes back **with its embeddings**. That is the whole reason the
backups bucket exists: re-embedding costs provider credit and about an hour.
`infra/tests/test_backup_restore.sh` proves the round trip locally — 1353 users,
32 documents and 14,216 chunks, with a restored chunk's embedding md5
byte-identical to the original.

Restoring **replaces** the database, so every refresh token issued after the
dump is dead and everyone is logged out. That is why `--restore` is a flag and
not part of a plain `up.sh`.

## Add an invite

The admin API, over SSM Session Manager, so nothing is exposed to the internet:

```bash
aws ssm start-session --target <instance-id>
docker compose -f /opt/veriforge/compose.prod.yaml exec api \
  python -m admin.cli invite --email someone@example.com
```

With no domain the invitation email only reaches **verified** addresses, so in
practice you will hand the code over yourself. See
`docs/ops/runbook-admin.md` for the wider admin surface.

## Mint the first admin

The instance has no key pair and no SSH, so this is the only way in:

```bash
aws ssm start-session --target <instance-id>
docker compose -f /opt/veriforge/compose.prod.yaml exec api \
  python -m scripts.seed_admin --email you@example.com
```

`ADMIN_PASSWORD` is not in `infra/.env` by design — a password in a
600-mode file on a laptop is one laptop compromise away from being a
compromised admin. Set it in the session, or let the script generate one and
print it once.

## Read the logs

The api emits one JSON object per line and those lines are what the alarms read
([signals.md](signals.md)).

```bash
# Everything, live
aws logs tail /veriforge/beta/docker --follow --format short

# Just the failures
aws logs tail /veriforge/beta/docker --follow \\
  --filter-pattern '{ $.event = "run.failed" }'

# Historical
aws logs start-query --log-group-name /veriforge/beta/docker \\
  --start-time "$(($(date +%s) - 3600))" --end-time "$(date +%s)" \\
  --query-string 'fields @timestamp, event, error_code | filter event = "run.failed" | sort @timestamp desc | limit 50'
```

Caddy's own access log is discarded on purpose: it would be a second,
unstructured stream costing disk on a 30 GB volume for no operational gain.

## Rotate a secret

| secret | how | consequence |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | new value in `.env`, then `up.sh` | nothing; existing sessions keep working until the next run |
| `SMTP_PASSWORD` | new value in `.env`, then `up.sh` | nothing |
| `LANGFUSE_*` | new values in `.env`, then `up.sh` | traces resume from the new key |
| `POSTGRES_PASSWORD` | **do not** | rotating it locks the instance out of its own data unless you also change `POSTGRES_USER` in the database |
| `JWT_SECRET` | **do not** | logs every user out |
| `ORIGIN_VERIFY` | delete the SSM parameter, then `up.sh` | CloudFront and Caddy get the new value together, because the edge stack reads it from SSM at deploy time |

`up.sh` regenerates `POSTGRES_PASSWORD`, `JWT_SECRET` and `ORIGIN_VERIFY` only
when they are **absent**, which is why deleting one is the way to rotate it.

## The known limit, stated plainly

**CloudFront talks to the instance over plain HTTP on the public internet.**
There is no domain, so there is no origin certificate and no ACM. The viewer's
HTTPS is terminated by CloudFront; the hop from the CloudFront edge to the
instance is unencrypted.

That is acceptable for a throwaway showcase with a handful of invited users. It
is **not** acceptable for real user data. What mitigates it:

- the security group allows port 80 only from the CloudFront origin-facing
  prefix list, so nothing else can open a TCP connection;
- Caddy additionally refuses any request without the `X-Origin-Verify` header,
  whose value CloudFront adds and Caddy learns from SSM.

If this ever carries data anyone would mind leaking, stop and get a domain plus
ACM. The Caddyfile already has `auto_https off` and no `tls` directive, so
adding one is a deliberate change rather than a default.

## Only checkable on AWS

Everything below is asserted by the local tests except where noted. The full
ordered list with expected results is
[day2-checklist.md](day2-checklist.md).

| thing | why it cannot be checked here |
| --- | --- |
| `Accept` surviving CloudFront to the origin | `AllViewerExceptHostHeader` is what the docs require and the fix, but AWS's header table says CloudFront *removes* `Accept`. If it does, `/library` works in dev and 404s in production. |
| `{{resolve:ssm-secure:…}}` / custom-resource origin header | CloudFormation rejects dynamic references in `OriginCustomHeaders`, so the value comes from an `AwsCustomResource` reading SSM. Confirm the distribution's header value is non-empty. |
| The CloudFront prefix list id | `pl-31a34658` for `ap-southeast-1`, from AWS's own example. Verify with `aws ec2 describe-managed-prefix-lists`. |
| `OriginReadTimeout: 120` taking effect | Verified in the synthesized template, not against a live distribution. |
| A 60 s SSE run through CloudFront | Needs a real run, and a real run spends provider credit. |
| Docker's awslogs driver reaching CloudWatch Logs | The user data writes it; the alarms depend on it landing. |
| `shm_size: 1gb` on the deployed postgres | Found locally; the deployed volume's `/dev/shm` should be checked. |
| Graviton memory behaviour under load | Item 0's table is idle numbers against the dev stack. |
| The $9 cost estimate | Confirm against the AWS Pricing Calculator. |

## Running the local checks

```bash
python3 infra/tests/test_caddyfile_parity.py   # Caddyfile vs vite.config.ts
./infra/tests/test_scripts.sh                  # guard clauses + dry runs
./infra/tests/test_backup_restore.sh           # dump/restore round trip
./infra/prod_compose_check.sh                  # the whole stack, locally
(cd infra/cdk && npx jest && npx cdk synth)   # 31 template assertions
```

None of them read `infra/.env`, call AWS, or spend provider credit. The compose
check uses ports 18080/18000/18081 and a scratch database, so the dev stack on
8000/5173/5174/5432 is untouched.