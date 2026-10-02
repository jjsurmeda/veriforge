# Backend maintainability review

Reviewed 2026-09-29. Scope: `apps/api` conventions, readability, duplication, and complexity. This is separate from the earlier backend correctness/security review and is read-only.

## Findings

### P2 — The application has two independent database session-factory lifecycles

Evidence: [`apps/api/db/session.py:13-24`](../apps/api/db/session.py#L13-L24) creates a module-global engine and factory used by `SessionDep`. [`apps/api/main.py:33-51`](../apps/api/main.py#L33-L51) creates a second engine/factory for the run bus and background work, and disposes only that second engine on shutdown.

Why it matters: request handlers and background runs do not share an explicit database-resource owner. Pool configuration, lifecycle handling, tests, and any future connection instrumentation must be maintained in two places; the module-global engine is not disposed by the application lifespan.

Recommendation: make `db.session` the sole factory owner and inject/use that factory from the lifespan, or make the lifespan factory the sole owner and have the request dependency obtain it from app state. Do not retain both paths.

### P2 — `execute_run` is a 436-line orchestration function with three near-parallel lifecycles

Evidence: [`apps/api/graph/runner.py:584-970`](../apps/api/graph/runner.py#L584-L970) combines setup, event emission, mode selection, streaming, batching, heartbeats, token accounting, persistence, finalization, cancellation, and failure handling. The auto branch at [`:679-772`](../apps/api/graph/runner.py#L679-L772), deep branch at [`:774-862`](../apps/api/graph/runner.py#L774-L862), and fast branch at [`:864-937`](../apps/api/graph/runner.py#L864-L937) repeat most of the stream/batch/heartbeat/account/finalize sequence.

Why it matters: every lifecycle change must be synchronized across three branches, while the surrounding error/cancellation state makes omissions hard to spot in review. The earlier stale-run and deep-stream findings demonstrate that this is a high-change-risk area.

Recommendation: extract the genuinely shared stream-draining and terminal-finalization steps, leaving each mode responsible only for preparing its run-specific object and publishing its distinct events. Do not introduce a generic graph-mode class hierarchy; the three modes have meaningful behavioural differences.

### P2 — `admin.service` combines unrelated administrative domains and contradicts the package guide

Evidence: [`apps/api/admin/service.py:1-794`](../apps/api/admin/service.py) owns runtime-settings validation/versioning, provider credentials, model catalogue, roles, plans, users, audit records, and decision statistics. For example, settings logic is at [`:37-277`](../apps/api/admin/service.py#L37-L277), providers/models at [`:278-441`](../apps/api/admin/service.py#L278-L441), and users/audit/statistics from [`:558-794`](../apps/api/admin/service.py#L558-L794). The package guide describes `admin/` as “API routes only — no business logic” in [`docs/conventions/python.md:6-25`](conventions/python.md#L6-L25).

Why it matters: the 794-line module has no natural change boundary. A change to provider security or settings validation is surrounded by unrelated plan/user/audit logic, and the written boundary no longer tells contributors where new logic belongs.

Recommendation: split at existing domain boundaries (`settings`, `providers`, `catalogue`, `users`, `audit`) while keeping the current explicit service functions. Update the convention to describe `admin` as a routing-plus-domain-service package, or move the services to their owning lower-level packages; do not add a CRUD framework.

### P3 — The evaluation harness duplicates Auto and Deep execution plumbing

Evidence: [`apps/api/evals/runner.py:142-186`](../apps/api/evals/runner.py#L142-L186) builds, streams, measures, counts tokens, finalizes, and extracts results for Deep mode; [`:187-219`](../apps/api/evals/runner.py#L187-L219) repeats the same lifecycle for Auto mode with a different run type.

Why it matters: benchmark behaviour can drift from production or between modes when changes land in only one branch—for example, timing, token accounting, or finalization semantics.

Recommendation: factor the shared measurement/result extraction around the existing `prepare_*_run` functions, retaining explicit mode-specific preparation and stream shape. The harness does not need to mirror all production-run infrastructure.

### P3 — The chat route contains repository and response-assembly logic that its conventions assign elsewhere

Evidence: [`apps/api/chats/router.py:232-282`](../apps/api/chats/router.py#L232-L282) directly queries messages, citations, chunks, documents, sections, and runs, then groups and maps them into response data. The backend convention says ownership-filtered queries involving chunks/citations should go through repository functions at [`docs/conventions/python.md:37-56`](conventions/python.md#L37-L56).

Why it matters: this large handler mixes authorization, relational query shape, presentation mapping, and API transport. Future citation or ownership changes have no reusable repository boundary and are harder to test without a route-level setup.

Recommendation: move the message/citation loading and mapping into a chat-specific repository/service function that accepts the already-authorized chat ID, leaving the route to authorize and return the result. Keep the response model construction explicit rather than creating a generic ORM serializer.

## Review notes

- The package separation is otherwise clear, and small pure helpers in quota, retrieval, and decisions are generally well-contained.
- I did not flag the central SQLAlchemy model file or ordinary mode-specific branches merely for being large; they are reasonable until a specific ownership boundary emerges.
- No source code or tests were changed.
