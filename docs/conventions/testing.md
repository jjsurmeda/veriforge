# Testing conventions — unit and integration

Companion to `docs/conventions/playwright.md` (end-to-end) and TRD §15
(the eval gate, which is a different thing from unit tests — evals judge
answer quality; this file governs code correctness).

## Coverage isn't uniform — three tiers

Coverage targets follow risk, not a blanket number.

| Tier | Packages | Target | Why |
| --- | --- | --- | --- |
| Critical | `apps/api/retrieval` (esp. ownership filters), `apps/api/quota` (reserve/settle), `apps/api/decisions` (DecisionEngine + fallback + breaker) | ~100% branch coverage on core logic | Bugs here mean data leaks across users or wrong billing — `CLAUDE.md` calls these out explicitly |
| Standard | `apps/api/graph`, `apps/api/ingest`, `apps/api/runbus`, `apps/web/src/features/*` | 70–80% | Normal correctness bar |
| Light | `apps/api/admin` routes (thin CRUD over already-tested services), generated code, `apps/web/src/components/ui` (shadcn primitives) | Smoke-tested only | Low complexity, low blast radius |

A change that lowers Critical-tier coverage fails CI; Standard and Light
tiers are reviewed by eye, not gated by a number.

## Layout and naming

**Python** (`pytest`): tests live in `apps/api/tests/`, mirroring the
package structure — `tests/retrieval/test_hybrid_search.py` for
`retrieval/hybrid_search.py`. File name `test_*.py`, function name
`test_<behavior>_<condition>` (e.g.
`test_retrieval_excludes_other_users_chunks`). Fixtures common across
packages live in `tests/conftest.py`; package-specific fixtures live in
that package's `tests/<package>/conftest.py`.

**TypeScript** (`vitest` + Testing Library): tests are co-located with
source as `ComponentName.test.tsx` / `useHook.test.ts`, not in a parallel
`__tests__` tree — keeps a moved/renamed component's test moving with it.

## What's mocked vs. real

- **Retrieval and quota tests run against a real test Postgres**
  (ParadeDB image, spun up per test session, migrations applied, reset
  between tests via transaction rollback) — these are exactly the
  packages where SQL correctness is the thing being tested, so mocking
  the database would test nothing.
- **`DecisionEngine` tests never call live Jev or a live LLM.** Use the
  fallback engine's structured-output path against a fixture LLM (a
  fake `LiteLLM` client that returns canned `Answer` objects) for
  routing/branching tests, and a small fixture set of real Jev
  request/response pairs (recorded once, checked into
  `tests/fixtures/jev/`) for testing the Jev client's parsing and error
  handling. Circuit-breaker and shadow-mode logic are tested with a fake
  engine that fails on command, not real network flakiness.
- **LangGraph node tests** mock the LLM and `DecisionEngine` calls a node
  makes, and assert on the node's output and any events it emits — a
  node test should not need a live model to pass.
- **React component tests** mock the generated API client and
  `fetch-event-source`; a feature's `useRunStream` test replays a fixture
  sequence of SSE events (see `playwright.md` for the shared fixture
  format) and asserts on resulting Zustand state, not on network
  internals.
- **S3, Tavily, Cohere Rerank, embeddings**: always mocked in unit tests
  behind their provider interfaces (`WebSearchProvider`, etc.) — these
  are exactly the seams the interfaces exist for.

## What a good test in each critical package looks like

- `retrieval`: given two users' chunks in the test DB, a query with no
  explicit filter from user A never returns user B's rows, even if B's
  collection is named similarly or the client sends a crafted filter
  trying to widen access.
- `quota`: a reserve followed by a settle for less than the reservation
  correctly frees the difference; two concurrent runs that would together
  exceed the 5-hour limit — the second is rejected, not both partially
  charged; a cancelled run still settles with actual (not reserved)
  usage.
- `decisions`: a Jev timeout falls back within the configured timeout
  and the resulting `Answer.engine == "fallback"`; three failures within
  60s open the circuit breaker and a subsequent call doesn't attempt Jev
  again until the cooldown elapses.

## CI

Unit tests (`pytest`, `vitest`) run on every push, fast (<3 min total on
this repo's expected size). They are separate from and run before the
20-item eval gate (TRD §15), which only runs on pushes touching
`graph`/`retrieval`/`decisions`/prompts and is slower — don't conflate
the two in CI config or in the slice's squash commit message; "tests
pass" and "eval gate passes" are reported and required separately.