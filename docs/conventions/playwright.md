# Playwright conventions — end-to-end

Companion to `docs/conventions/testing.md` (unit/integration — read that
first for what's *not* e2e-worthy).

## What's e2e-worthy vs. what's just a unit test

Playwright specs exist for flows that cross the frontend/backend
boundary in a way no unit test can catch — auth, real navigation, a real
upload landing in a real (test) database, a real SSE connection. They are
not a substitute for component tests; a component's internal states
(loading, error, empty) are covered by `vitest`, not Playwright.

**Default to real backend, not mocked**, for the small set of true
end-to-end specs — these are the specs that catch integration bugs
component tests structurally can't:

- Sign up → sign in → create a chat → ask a Fast-mode question over a
  seeded document → see an answer with a hoverable citation.
- Upload a document → see ingestion status progress to `ready` → ask a
  question that must cite it.
- Hit the 5-hour quota limit → see the block message and reset countdown.
- Admin: change a guardrail threshold → see it take effect on the next
  run's decision trace.

Keep this list short (roughly 10–15 specs across the whole app) and
happy-path-plus-one-failure-mode per flow — this suite is meant to prove
the seams fit together, not to re-verify every branch already covered by
unit tests.

## Streaming (SSE) specs use a fixture, not the real backend

Testing chip-recoloring, the "Verifying…" hold state, cancel-mid-stream,
or trace-panel rendering against a *real* multi-second LLM run would make
these tests slow and flaky (timing-dependent assertions against network
and model latency). Instead:

- A recorded fixture — a JSON array of the SSE events TRD §12 defines,
  captured once from a real run per scenario — lives in
  `apps/web/e2e/fixtures/runs/*.json`.
- A test-only backend route (enabled only when `ENV=test`) serves a
  fixture's events back over the real SSE contract at a controllable
  pace, so Playwright drives the actual frontend code (`useRunStream`,
  the Zustand store, real components) against a deterministic stream
  instead of a live model.
- New fixtures are recorded when a new event type or a new UI reaction
  to one is added (e.g. the first abstain-flow spec needs a fixture with
  an `abstain` event) — check in the raw event JSON, not a hand-written
  approximation of it, so it stays honest to the real contract.

This is the same "replay a fixture sequence" approach `useRunStream`'s
own unit test uses (`testing.md`) — the fixture format is shared between
the two, so a fixture recorded for one can be reused by the other.

## Seed and demo data

E2e specs run against the seeded demo corpus (TRD §18 open question,
resolved before slice 8) via a `playwright.config.ts` global setup that
resets the test database to a known fixture state before the suite runs,
not before each spec — specs that mutate state (upload, sign up) create
their own uniquely-named data (e.g. `test-user-<uuid>@veriforge.test`) so
they don't collide with each other or leave the seed data dirty for the
next run.

## Structure

```
apps/web/e2e/
  specs/
    auth.spec.ts
    fast-mode-citation.spec.ts
    ingestion.spec.ts
    quota-limit.spec.ts
    admin-guardrail-threshold.spec.ts
    streaming/
      chip-recolor.spec.ts
      cancel-mid-stream.spec.ts
      abstain-flow.spec.ts
  fixtures/
    runs/*.json          Recorded SSE event sequences
  support/
    auth.ts               login() helper, reused across specs
    seed.ts                Global setup / database reset
```

One spec file per user-facing flow, not per page — `fast-mode-citation`
covers composer → stream → citation hover as one story, rather than
splitting "composer renders" and "citation hovers" into separate specs
that don't reflect how a person actually uses it.

## What's out of scope for v1

- **Visual regression** (pixel-diffing screenshots) is not set up for
  v1. The design system doc (§8, accessibility floor) and code review are
  the quality gate on visual correctness for now; revisit if the UI
  surface grows enough that regressions are slipping through review.
- **Cross-browser matrix**: Chromium only for v1 CI; Playwright's
  cross-browser support is available if a real bug report ever demands
  it, but running the full matrix on every PR isn't worth the CI time at
  this stage.

## CI

The e2e suite runs on PRs touching `apps/web`, `apps/api` routes, or
`e2e/**` itself — not on every push, since it's slower than the unit
suite. It runs against a freshly built container stack (the same
`docker compose` config used locally), not against a deployed
environment, so it can run entirely inside CI without touching AWS.