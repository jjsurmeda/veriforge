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
## Recorded responses at every external boundary

Generalises the Jev fixture rule above. Any value our code *parses* from
outside the repo is tested against a **captured real response**, not a
hand-written fake:
- model outputs we parse: judge JSON, claim extraction, planner rows, chat
  titles, starter questions
- provider API fields: OpenRouter `/generation` stats, Jev response headers,
  rerank payloads

Fixtures live in `tests/fixtures/<provider>/<name>.json`, with the capture
date and model in the file. A hand-written fake may *add* edge cases, but it
never replaces the capture.

Parsers are tolerant: they extract the JSON from the prose around it. A parse
failure is **counted and surfaced** (a metric, a log line, a failure reason),
never a silent `None`.

Why: D2. Haiku wrote an explanation after the JSON, so 17–19 of 20 judge
scores came back null. Also D2: Jev's stats record carries `latency`, not
`generation_time`.

## Intent tests

When a comment, the TRD or an ADR states what code is *for*, a test asserts
that outcome, not just "no crash" or "within budget". Example: "children
first, parents only if room" means a test that every entity's child reaches
the judge.

Why: D2. The evidence code was fully covered and still contradicted its own
comment.

## Coverage numbers don't replace intent

The tiers above stay. A coverage percentage measures which lines ran, not
whether the behaviour is right. Covered code with no intent test counts as
untested in review.

## A changed default runs the full suite

Flipping a default (reranker, model, threshold, temperature, source) runs the
**whole** suite, not the area's tests.

Why: `1ba8f3f` switched the reranker to Jev and only the rerank tests ran,
which broke `test_sanitize_asks_only_about_the_reranked_top_k`.

## Test data is audited like code

Every acceptance and seed item carries proof of its label:
- `answer` items: the query that finds the answering passage (hit > 0,
  passage quoted)
- `not_in_sources` items: the zero-hit queries over everything the test user
  can retrieve, with spot-read notes on false hits
- one-referent questions are checked for a second valid answer in the corpus

`mention` checks accept every correct phrasing seen in a correct answer, with
the reason recorded in the item. Re-run the audit whenever the corpus changes.
A label that contradicts the corpus is a test bug: fix the item, never the
pipeline.

Why: KI-36. `outside-whitman`'s answer was in the corpus all along, and
`fact-weena`'s check rejected a correct answer.
