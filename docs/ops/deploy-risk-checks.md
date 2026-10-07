# Deployment risk checks (lane A, item 0)

The three facts the rest of the beta deployment is sized against, established
before anything was built. Every number here was measured or quoted from a
primary source on 2026-10-07; nothing is an estimate presented as a measurement.

## 1. arm64: every image the deployment pulls has a `linux/arm64` build

`docker manifest inspect`, run from the worktree:

```
paradedb/paradedb:0.25.9-pg16               linux/amd64, linux/arm64, unknown/unknown
ghcr.io/astral-sh/uv:python3.12-bookworm-slim linux/amd64, linux/arm64, unknown/unknown
node:22-alpine                              linux/amd64, linux/arm, linux/arm64, linux/s390x, ...
caddy:2-alpine                              linux/amd64, linux/arm, linux/arm64, linux/ppc64le, ...
```

**ParadeDB publishes an arm64 build**, so `t4g` (Graviton) is available and the
instance type does not change. The arm64 manifest digest for ParadeDB, for
pinning if the tag is ever mutable:

```
linux/arm64  sha256:eaf900b9715c31f712defc41352579688a1af82cab5e875171f749d5a28e8629
```

The gate in the dispatch was "stop and report if ParadeDB has no arm64 build".
It does, so the lane continues.

## 2. Memory on 4 GB

Measured with `docker stats --no-stream` against the running dev stack, three
samples, all three identical to the byte. This is not an empty database: the
dev database holds **14,216 chunks** in an **814 MB** database, so the Postgres
number below already carries a real vector + BM25 working set.

| container | measured RSS | in the production shape? |
| --- | ---: | --- |
| `db` (paradedb 0.25.9-pg16) | 1057 MiB | yes, same image |
| `api` (uvicorn `--reload`, dev venv) | 375 MiB | yes, same app, heavier image |
| `worker-ingest` | 286 MiB | yes |
| `worker-light` | 309 MiB | yes |
| `web` (Vite dev server) | 617 MiB | **no** — replaced by Caddy |
| `caddy:2-alpine` (measured separately) | 10 MiB | yes |

Production-shape total of the measured services: **2037 MiB (1.99 GiB)**.

The dev containers are an *over*-estimate of the production ones, not an
under-estimate: the dev api runs `--reload` (a supervisor plus a file watcher)
and `uv sync` installs dev dependencies, while the production image is non-root
with `--frozen` and no dev dependencies. Nothing in the dev stack is lighter in
production.

### Limits to set, and why they fit

`mem_limit` is per container, so the *sum* is what has to fit the box, and each
ratio is what decides which container the kernel kills first.

| service | limit | measured | headroom |
| --- | ---: | ---: | ---: |
| `postgres` | 1400 MiB | 1057 MiB | 1.32x |
| `api` | 650 MiB | 375 MiB | 1.73x |
| `worker-ingest` | 500 MiB | 286 MiB | 1.75x |
| `worker-light` | 450 MiB | 309 MiB | 1.46x |
| `caddy` | 128 MiB | 10 MiB | 12.8x |
| **sum** | **3128 MiB** | 2037 MiB | |

`3128 MiB` of containers plus roughly `450 MiB` for Amazon Linux 2023,
`dockerd` and systemd is about `3578 MiB` of the `4096 MiB` a `t4g.medium` has —
leaving ~`518 MiB` (12.6%) of box slack.

### Instance recommendation

**`t4g.medium` (2 vCPU, 4 GiB) fits.** No change to the design is needed.

Two honest caveats, both unmeasurable without AWS:

- **The dominant memory risk is Postgres during index build**, not steady state.
  A `CREATE INDEX` or an autovacuum on a grown corpus peaks well above the
  steady 1057 MiB, and the 1.32x headroom above is a judgement, not a
  measurement. If the beta corpus grows past roughly 50k chunks, move to
  **`t4g.large`** (8 GiB, ~2x the price, about +$7 for the week).
- **These are idle numbers.** A real ingest run (parsing a PDF, embedding
  batches of 100 x 1536 floats) was not measured, because doing it would spend
  provider credit. The worker limits carry 1.75x/1.46x for that reason.

`mem_limit` on Postgres deserves one explicit warning: exceeding it does not
slow Postgres down, the kernel OOM-kills it, and the database restarts. Postgres
therefore gets the largest limit of the five. Docker OOM behaviour and
`vm.overcommit_memory` on Graviton are day-2 checklist items, not local proofs.

Cost for one week, consistent with the ~$9 in the dispatch: `t4g.medium` at
roughly $0.04/h in `ap-southeast-1` x 168 h is about $6.7, plus 30 GB gp3 at
about $2.40/month, plus a CloudFront free tier that this traffic will not leave.
Confirm against the AWS Pricing Calculator on day 2 — pricing was not fetched
here because it needs no credential but was not independently verified.

## 3. CloudFront and server-sent events

### The timeout bounds, from the API reference

[`CustomOriginConfig.OriginReadTimeout`](https://docs.aws.amazon.com/cloudfront/latest/APIReference/API_CustomOriginConfig.html):

> Specifies how long, in seconds, CloudFront waits for a response from the
> origin. This is also known as the *origin response timeout*. The minimum
> timeout is 1 second, the maximum is 120 seconds, and the default (if you
> don't specify otherwise) is 30 seconds.

So: **default 30 s, maximum 120 s**, and it is the maximum that matters here,
not the default.

### Why the default is not safe enough, and 120 s is

The single most important sentence is on
[Request and response behavior for custom origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/RequestAndResponseBehaviorCustomOrigin.html),
under *Origin response timeout*:

> The *origin response timeout*, also known as the *origin read timeout* or
> *origin request timeout*, applies to both of the following:
> + The amount of time, in seconds, that CloudFront waits for a response after
>   forwarding a request to the origin.
> + **The amount of time, in seconds, that CloudFront waits after receiving a
>   packet of a response from the origin and before receiving the next packet.**

**It is an inter-packet idle timeout, not a total-stream budget.** A run may
stream for ten minutes without hitting it, provided a packet arrives inside the
window each time. That is exactly the SSE shape.

The api sends a heartbeat every 15 s (`heartbeat_interval_seconds: int = 15`,
`apps/api/config.py`). So:

| setting | vs. the 15 s heartbeat | verdict |
| --- | --- | --- |
| default 30 s | 2.0x | survives, thin |
| **120 s (max)** | **8.0x** | **chosen** |

`originReadTimeout` must be **120**. 30 s works only if no heartbeat is ever
late, and on a 4 GiB box running a Postgres index build next to the api, a
30-second stall is a normal event rather than an exotic one. 120 s is 8x the
heartbeat interval, so no plausible pause can trip it.

### Streamed responses pass through unbuffered

Same page, under the `Transfer-Encoding` header:

> CloudFront supports only the `chunked` value of the `Transfer-Encoding`
> header. If your origin returns `Transfer-Encoding: chunked`, CloudFront
> returns the object to the client as the object is received at the edge
> location, and caches the object in chunked format for subsequent requests.

And under *Dropped TCP connections*:

> **Transfer-Encoding: Chunked** – CloudFront returns the object to the viewer
> as it gets the object from your origin. However, if the chunked response is
> not complete, CloudFront does not cache the object.

So chunked responses are relayed as they arrive — no buffering, no
accumulation-until-complete. The "does not cache" half of that sentence is also
why the "caching disabled" requirement matters: an incomplete chunked response
would otherwise sit in an edge cache. CloudFront also rewrites the header to
`chunked` for the viewer.

**Caddy is the only hop left, and it is not buffering.** CloudFront relays a
chunked response as it arrives, and Caddy's `reverse_proxy` documents that
`flush_interval` "is ignored and responses are flushed immediately to the
client if one of the following applies from the response: `Content-Type:
text/event-stream`" — which is what `apps/api/runs/router.py` sends. The
Caddyfile sets `flush_interval -1` anyway, as explicit intent and because it
is the setting that would matter for any other content type.

**Correction, measured later in item 2.** This section originally said Caddy
"must" set `flush_interval -1` because it was the only buffering hop. That
overstated it. Rebuilding the image with `flush_interval 250ms` produced an
identical frame spread (6.01 s between first and last frame) through the same
Caddyfile, because the `text/event-stream` exemption applies regardless. The
setting is harmless and worth stating; it is not the mechanism.

### The CDK accepts 120, and two of its defaults are wrong for us

`HttpOrigin` in the pinned `aws-cdk-lib` (2.270.0) validates the timeout with
`validateMinimumSeconds("readTimeout", 1, props.readTimeout)`
(`node_modules/aws-cdk-lib/aws-cloudfront-origins/lib/http-origin.js`), and
that helper only rejects `value < min` — **there is no upper bound in this
version**, so `readTimeout: Duration.seconds(120)` synthesises. (Older CDK
versions capped an HTTP origin at 60 s and threw above it; that cap is gone
here, and `cdk synth` in item 3 is what proves it for the real template.)

The same constructor shows the defaults that have to be overridden explicitly,
because each one silently does the wrong thing for this deployment:

| CDK default | from | must become | why |
| --- | --- | --- | --- |
| `originProtocolPolicy ?? HTTPS_ONLY` | `http-origin.js` | `HTTP_ONLY` | no domain means no origin certificate; the origin is plain `:80` |
| `originReadTimeout: props.readTimeout?.toSeconds()` | `http-origin.js` | explicit `120` | left unset it emits no value, and CloudFront applies its own 30 s |
| `originSslProtocols ?? [TLS_V1_2]` | `http-origin.js` | irrelevant | `HTTPS_ONLY` is replaced, so these never apply |

## 4. Three findings from reading the code against the docs

These came out of the risk checks and change what item 2 must build. Each is
quoted from the file it is about.

### 4a. The limiter's IP: uvicorn walks `X-Forwarded-For` right-to-left, so Caddy must NOT append its own address

KI-59 says the trust boundary is uvicorn's `forwarded_allow_ips`, and warns that
if Caddy runs in its own container the per-IP limit silently becomes global. The
obvious fix — trust Caddy, let it pass the header through — is **wrong**, and the
uvicorn in this venv says why.
(`/app/.venv/lib/python3.12/site-packages/uvicorn/middleware/proxy_headers.py`,
`apps/api/auth/router.py:53`):

```python
def get_trusted_client_address(self, x_forwarded_for: str) -> tuple[str, int]:
    """Extract the client address from x_forwarded_for header.

    In general this is the first "untrusted" host in the forwarded for list.
    """
    ...
    # Note: each proxy appends to the header list so check it in reverse order
    for host_port in reversed(x_forwarded_for_hosts):
        host, port = _parse_host_port(host_port)
        if host not in self:
            return host, port
```

It does **not** take the leftmost entry. It scans from the right and returns the
first address that is not itself a trusted proxy. Put `forwarded_allow_ips` on
Caddy's container and combine that with Caddy's *default* behaviour (append the
peer address), and the chain arriving at uvicorn is:

```
spoofed, viewer, <cloudfront-edge-ip>      <- Caddy appended this last
```

Scanning from the right, the first untrusted host is `<cloudfront-edge-ip>`.
**Every request would be keyed on a CloudFront edge address**, which is the
"all viewers share one bucket" failure KI-59 warned about, arrived at from the
opposite direction.

The fix, and the reason it is still correct:

- Caddy **replaces** `X-Forwarded-For` with the header it received
  (`header_up X-Forwarded-For {http.request.header.X-Forwarded-For}`), so
  Caddy's own peer address is never appended.
- What CloudFront sends is documented as: *"CloudFront gets the IP address of
  the viewer from the TCP connection, **appends it to the end** of the
  X-Forwarded-For header"*. So the genuine viewer address is always the
  **rightmost** entry, and anything a viewer prepended is to its left.
- uvicorn scanning from the right therefore returns the real viewer and never
  sees the forged prefix. Spoofing is defeated by the same mechanism that
  forwards it.

`forwarded_allow_ips` is set to the Caddy container. Not `*`.

### 4b. `Accept: text/html` must survive CloudFront, or the SPA's `/library` breaks in production only

The collision rule from `apps/web/vite.config.ts` — a document navigation to
`/library` must be served `index.html`, not proxied — keys on the browser's
`Accept` header. The CloudFront developer guide's header table says of `Accept`:

> `Accept` | CloudFront removes the header.

So the origin request policy must forward it. The dispatch already specifies the
right policy ("forward all headers except `Host`, all cookies and all query
strings"), which is the managed `AllViewerExceptHostHeader` origin request policy
— all viewer headers including `Accept`, plus `CachingDisabled`. Implemented that
way. **Whether `Accept` in fact arrives is a day-2 checklist item**, because it
cannot be observed from here, and the symptom would be confusing: `/library`
works in dev and 404s or returns JSON through CloudFront.

### 4c. `ENVIRONMENT=production` makes SMTP settings mandatory, or the api will not boot

Lane C's startup refusal is real and is in the right place — `main.py:43` calls
`build_email_transport(settings)` as the first statement of `lifespan`, before
any connection is opened, and `auth/email.py:147` refuses `dev_log` when
`environment == "production"`, with `smtp` without a host or sender also refused.

The consequence for this deployment: with `ENVIRONMENT=production`, the api
refuses to start unless `EMAIL_TRANSPORT=smtp` **and** the SES SMTP host, sender
and credentials are all present. If the SES SMTP credentials are not in
`infra/.env` yet, the api crash-loops on boot and CloudFront serves 502s. `up.sh`
must therefore treat those variables as required, not optional, and the runbook
must say the order: SES verification and SMTP credentials first, deploy second.

The safe defaults need no setting: `signup_mode` defaults to `invite` and
`cookie_secure` defaults to `True`. There is **no** production check on
`jwt_secret`, which still defaults to `dev-only-insecure-secret-change-me` — so
`up.sh` must generate that one and refuse to deploy without it. That check
belongs in `up.sh`, not in the app, because `apps/` is out of this lane's scope.