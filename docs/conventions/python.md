# Python conventions — `apps/api`

Companion to `CLAUDE.md` (non-negotiables) and the TRD (§6–§14 define the
packages this file governs the internals of).

## Package boundaries

```
apps/api/
  graph/         LangGraph nodes and the graph wiring (TRD §7)
  retrieval/     Hybrid search SQL, RRF, rerank, small-to-big (TRD §9)
  ingest/        Parsing, chunking, embedding, page-quality flags (TRD §9.1)
  decisions/     DecisionEngine, Jev client, LLM fallback, breaker (TRD §8)
  providers/     LiteLLM wrapper, model catalogue, WebSearchProvider
  quota/         Ledger, gate, reserve/settle (TRD §14)
  evals/         Eval runner, dataset loaders, CI gate (TRD §15)
  admin/         Admin API routes only — no business logic lives here
  auth/          Signup/login, JWT + refresh rotation, OAuth, password reset
  chats/         Chat CRUD, messages listing, run creation routes
  runs/          Run stream (SSE) and cancel routes
  runbus/        RunBus interface + PostgresRunBus / RedisRunBus (ADR-001)
  schemas/       Pydantic models: API request/response + SSE event union
  prompts/       Versioned prompt files (*.md), loaded by graph/ and decisions/
```

**The dependency direction is one-way:** `graph` depends on `retrieval`,
`decisions`, `providers` and `runbus`; those packages never import from
`graph`. `admin` depends on the same lower packages `graph` does, but
nothing depends on `admin`. If you find yourself importing from `graph`
inside `retrieval`, the logic is in the wrong package.

A new LangGraph node's business logic goes in the package that owns the
concept (a new decision → `decisions`, a new retrieval step →
`retrieval`), not inline in `graph/`. `graph/` should mostly read as
wiring: which node calls which package function, and the edges between
them.

## Models: Pydantic vs. SQLAlchemy, never conflated

- **Pydantic v2 models** (`schemas/`) are the wire format: API
  request/response bodies and the SSE event union. They're what
  `openapi-ts` codegens from — never rename or restructure one without
  checking what depends on the generated TS type.
- **SQLAlchemy 2 models** (`db/models.py`, mapped to TRD §13's tables) are
  the storage format. They are async-mapped and never imported by
  `apps/web`-facing code directly — a route handler reads a SQLAlchemy
  row and returns a Pydantic model, it never returns the ORM object.
- If a field exists in both, the Pydantic model is allowed to be a subset
  or reshaping of the SQLAlchemy model (e.g. hiding `owner_id`), never the
  reverse.

## Async and sessions

- Async SQLAlchemy only, no sync sessions or sync engine anywhere in
  `apps/api` (`CLAUDE.md`).
- One request-scoped `AsyncSession` per request via FastAPI dependency
  injection; don't create ad hoc sessions inside a service function.
- Background jobs (Procrastinate tasks) get their own session per task
  invocation, not a shared/global one — tasks can run concurrently.
- Any query touching `chunks`, `citations`, `usage_ledger` or anything
  filtered by ownership must go through the repository function that
  injects the ownership filter (TRD §9.2, §11) — never construct that
  query inline in a route handler.

## Error and exception shape

- Domain errors are typed exceptions in the owning package (e.g.
  `QuotaExceeded` in `quota/`, `RetrievalTimeout` in `retrieval/`), caught
  once at the FastAPI exception-handler layer and turned into a
  consistent JSON error body: `{"error_code": str, "message": str,
  "detail": dict | null}`.
- Never let a raw SQLAlchemy or httpx exception reach the client — catch
  it at the boundary where it's thrown and re-raise as a domain
  exception, or let it become a generic 500 with a logged stack trace,
  never a raw traceback string in the response.
- `DecisionEngine` failures are not exceptions to the caller — the
  fallback and circuit breaker (TRD §8) mean a decision call always
  returns an `Answer`; only total failure of both engines raises.

## Logging

Structured JSON logs (CloudWatch, TRD §15). Every log line inside a run's
execution includes `run_id` and, where applicable, `user_id` and `node`.
Log at `info` for node transitions and decision outcomes (mirrors what
the trace panel shows, useful for debugging without replaying the run),
`warning` for fallback/circuit-breaker activity and dropped chunks,
`error` for anything that reaches the exception handler. Never log
provider API keys, raw document content beyond a short excerpt, or full
prompts at `info` — prompt-level detail is a `debug`-only concern, off by
default.

## Prompts

Every prompt file in `prompts/` starts with a version header:

```
---
version: 3
role: claim-extraction
---
```

A prompt change bumps the version and requires the eval gate (TRD §15) to
pass before merge — this is what lets an eval diff say which prompt
version changed the numbers.

## Style and tooling

- `uv` for environment and dependency management; `ruff` for lint and
  format; `mypy --strict` on the whole of `apps/api`.
- Type hints on every function signature, including private helpers —
  `mypy --strict` enforces this, so it's a CI failure, not a style
  preference.
- Prefer small, pure functions in `retrieval/`, `decisions/` and `quota/`
  specifically, since those are the packages with the highest unit-test
  bar (see `docs/conventions/testing.md`) — a function that's hard to
  unit test without a database or a live API call is usually a sign it's
  doing two things at once.