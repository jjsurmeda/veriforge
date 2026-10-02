# Python backend code review

Reviewed 2026-09-29. Scope: `apps/api` production Python and its test harness. This was a read-only review; no code or tests were changed.

## Findings

### P1 — OAuth callback silently drops refresh and state-cookie changes

Evidence: [`apps/api/auth/router.py:203`](../apps/api/auth/router.py#L203) deletes the OAuth state cookie and [`apps/api/auth/router.py:244`](../apps/api/auth/router.py#L244) sets the refresh cookie on FastAPI's injected `response`. The handler then returns a *different* [`RedirectResponse` at :245](../apps/api/auth/router.py#L245), so neither mutation is included in the response sent to the browser.

Impact: Google-authenticated users receive an access token but no refresh cookie, so their session cannot refresh. The OAuth state cookie also survives until expiry.

Recommendation: construct the final redirect once, delete the state cookie and set the refresh cookie on that same response, then return it. Add an end-to-end callback test that asserts both `Set-Cookie` effects.

### P1 — Google OAuth links an external subject to a local account using an unchecked email-verification claim

Evidence: [`apps/api/auth/google.py:69-76`](../apps/api/auth/google.py#L69-L76) verifies issuer, audience, and expiry but does not require `email_verified`; it returns the `email` claim. [`apps/api/auth/router.py:228-239`](../apps/api/auth/router.py#L228-L239) finds an existing user by that email and attaches the Google subject to it.

Impact: an identity whose email claim is not verified can be linked to an existing password account with the same address, creating an account-takeover path if such a claim is accepted by the provider.

Recommendation: require `email_verified is True` before account lookup/linking. Prefer an explicit, authenticated account-linking flow for existing accounts.

### P1 — A deep-run producer error can leave the run streaming indefinitely

Evidence: [`apps/api/graph/deep.py:96-109`](../apps/api/graph/deep.py#L96-L109) puts the `None` queue sentinel only after `stream_grounded_answer` completes normally. The consumer waits for that sentinel at [`:113-117`](../apps/api/graph/deep.py#L113-L117); if the producer raises, it waits forever and never reaches `await task` in the `finally` block.

Impact: a provider/stream failure can leave the client SSE stream open and the run marked running until the stale-heartbeat sweeper intervenes, masking the actual error.

Recommendation: send the terminal signal in a producer `finally`, retain and re-raise its exception after the consumer exits, and cover a mid-stream exception.

### P1 — Brave result fetching permits SSRF through public results and redirects

Evidence: [`apps/api/retrieval/web.py:97-99`](../apps/api/retrieval/web.py#L97-L99) fetches each result URL. [`:109-114`](../apps/api/retrieval/web.py#L109-L114) performs that fetch with `follow_redirects=True`, without validating the initial or final destination address and without a response-size cap.

Impact: a result controlled by an attacker can redirect the API process to private, link-local, or cloud-metadata addresses. It can also force the process to download and convert an oversized response.

Recommendation: resolve and reject loopback, private, link-local, multicast, and reserved IPs for every hop; disable redirects or revalidate each redirect; set a strict streaming byte limit before conversion.

### P2 — Provider URL validation leaves private-network SSRF routes open

Evidence: [`apps/api/admin/service.py:283-299`](../apps/api/admin/service.py#L283-L299) rejects only three literal loopback host names. [`:365-369`](../apps/api/admin/service.py#L365-L369) then sends a request with the decrypted provider credential to the configured URL.

Impact: an admin account (or an attacker using one) can direct the backend to RFC1918, link-local/metadata, or other reserved addresses. The provider bearer credential is sent to that target.

Recommendation: use the same DNS/IP allow-or-deny policy as the web fetcher, validate the resolved peer address, and do not send credentials until the destination is approved.

### P2 — A cancelled Jev half-open probe can permanently disable probes

Evidence: [`apps/api/decisions/breaker.py:56-61`](../apps/api/decisions/breaker.py#L56-L61) changes the breaker to `PROBING` and rejects every later Jev attempt. [`apps/api/decisions/engine.py:132-140`](../apps/api/decisions/engine.py#L132-L140) resolves that state only on success, `JevError`, or `TimeoutError`.

Impact: cancellation or any other unexpected exception during the sole probe leaves the singleton breaker in `PROBING`; all later auto decisions use the fallback indefinitely.

Recommendation: make probe finalisation exception-safe—record a failed probe or restore a retryable state for every unsuccessful exit, including cancellation.

### P2 — The stale-run sweeper can fail a run after it heartbeats

Evidence: [`apps/api/graph/runner.py:981-990`](../apps/api/graph/runner.py#L981-L990) selects stale rows, then [`:991-997`](../apps/api/graph/runner.py#L991-L997) changes each row by ID alone. A heartbeat that lands between selection and update is not considered.

Impact: under normal concurrent execution, the sweeper can mark a live run and its message as failed, settle its usage, and publish a false terminal failure.

Recommendation: put `status = 'running' AND heartbeat_at < cutoff` in the `UPDATE` predicate; only mutate the message, settle usage, and publish an event when that conditional update succeeds.

### P1 — A test environment variable can point the destructive test fixture at a non-test database

Evidence: [`apps/api/tests/conftest.py:12-16`](../apps/api/tests/conftest.py#L12-L16) accepts any `TEST_DATABASE_URL` and assigns it to `DATABASE_URL`. The autouse fixture then executes `TRUNCATE ... CASCADE` for every mapped table at [`:132-143`](../apps/api/tests/conftest.py#L132-L143).

Impact: an inherited or mistyped environment variable can erase production or shared development data merely by starting pytest.

Recommendation: before creating, migrating, or truncating, reject database names that do not match a strict test-only convention (for example, an exact configured name or a `_test` suffix) and consider rejecting production hosts as defense in depth.

### P3 — The integration-test server uses a fixed port

Evidence: [`apps/api/tests/conftest.py:153-164`](../apps/api/tests/conftest.py#L153-L164) always binds Uvicorn to `127.0.0.1:8765`.

Impact: parallel test workers or another local process can make the test suite fail at startup.

Recommendation: bind an ephemeral port and expose the selected port through the fixture.

## Review notes

- Findings are ordered by impact, not file order. P1 is an urgent security or correctness issue; P2 is material but more conditional; P3 is test reliability.
- The test suite contains coverage for password login and refresh rotation, but no callback test that would catch the Google response-cookie defect.
- Dependency version ranges are backed by `apps/api/uv.lock`, so they are not reported as a reproducibility issue.
