# CLAUDE.md — Veriforge

Working instructions for Claude Code building **Veriforge**, an adaptive
agentic RAG chatbot showcase. Read this before writing code, every slice.

## Source of truth, in order

1. **PRD & TRD** (Claude Doc — link this repo's README to it): numbered
   requirements (`CH-`, `TR-`, `SR-`, `TX-`, `AC-`, `AD-`). Reference the ID
   in commits and PR descriptions when a change implements or touches one.
2. **This file** — conventions and non-negotiables that apply across slices.
3. **`docs/design-system.md`** — visual language and components for
   `apps/web`. Follow it for anything with a UI; don't improvise a look.
4. **`docs/glossary.md`** — terms used throughout the PRD/TRD (Jev, hop,
   faithfulness, RunBus, ...). Check it before guessing what a term means.
5. **`docs/adr/`** — one file per accepted architectural decision. Read the
   relevant ADR before changing anything it governs.
6. **`docs/conventions/`** — the concrete how-to for each area, so it's
   answered the same way across slices and sessions:
   `react.md`, `python.md`, `testing.md`, `playwright.md`, `git.md`.
   Read the relevant one before adding a new component, package, test,
   e2e spec, or opening a branch/PR.

If a change would contradict the PRD/TRD, don't silently diverge — flag it
and propose the change against the doc first.

## Build order

Eleven vertical slices (TRD §17), each merged and demoable **locally**
before the next starts. **No AWS deployment happens until slice 9** —
slices 0–8 run entirely on the local Docker Compose stack, including
auth, streaming, retrieval, Deep mode, the reviewer, quotas and admin.
Slice 9 stands up AWS for the first time against the completed v1
product; slice 10 (OCR) is v1.1 and ships through the pipeline slice 9
establishes. Don't add CDK deploy steps, AWS credentials, or "first
deploy" language to a slice-1-through-8 prompt — that's slice 9's job.

Don't begin a slice until the previous one's acceptance criteria pass.
**From slice 3 on, the eval gate (TRD §15) must pass before merge** —
a 20-item fast subset run in CI against the stored baseline for faithfulness,
abstention accuracy and p50 latency.

## Non-negotiables

- **No Redis at Stage 1** (ADR-001). Use `PostgresRunBus`, Procrastinate and
  Postgres tables behind their interfaces. Don't add Redis speculatively —
  the Redis adapters are scoped to slice 8 only, behind the `redis` Compose
  profile, and stay off by default.
- **All routing, classification, scoring and verification decisions go
  through `DecisionEngine`** (Jev primary via OpenRouter System One, LLM
  fallback, circuit breaker). Never call an LLM directly for something that
  fits a `Noul`, `Choice` or `Score` question — see TRD §8.
- **Every retrieval query gets its ownership filter injected server-side.**
  Client-supplied filters (collection, tags, date range, etc.) may only
  narrow results, never widen them. Write a test for this on every new
  retrieval path.
- **The generator model has no tools** and never sees unescaped instruction
  text from a source; sources are wrapped and treated as data, per TRD §11.
- **Generated TypeScript is generated, not written.** Never hand-edit
  anything under `apps/web/src/generated/**`; change the Pydantic model in
  `apps/api` and rerun codegen.
- **Prompts live in `apps/api/prompts/*.md`** with a version header at the
  top. Changing a prompt requires rerunning the eval gate before merge.
- **Credits are reserved before a run and settled after**, even on
  cancellation or failure (TRD §14). Never charge or refund outside that
  flow.

## Conventions

- **Python:** `uv` for envs/deps, `ruff` + `mypy --strict` on `apps/api`,
  Pydantic v2 everywhere, async SQLAlchemy only (no sync sessions).
- **TypeScript:** strict mode, no `any`. TanStack Query for all server
  state; Zustand only for live run/stream state (trace, deltas, metrics).
- **SSE events** are the Pydantic discriminated union in TRD §12 — add new
  event types there first, then regenerate the TS union. Don't invent an
  event shape ad hoc in a component.
- **Tests before code** for retrieval SQL, the quota gate, and ownership
  filters — these are the highest-cost-of-bug areas in the system.
- **Commits** reference the requirement ID(s) they implement and, when
  relevant, the ADR they follow.

## Repo layout

```
apps/web/            React SPA (Vite, TanStack, Tailwind, shadcn/ui)
apps/api/
  graph/              LangGraph nodes, agent graph wiring
  retrieval/          Hybrid search, fusion, rerank, small-to-big
  ingest/             Parsing, chunking, embedding, page-quality flags
  decisions/          DecisionEngine, Jev client, LLM fallback, breaker
  providers/          LiteLLM wrapper, model catalogue
  quota/              Ledger, gate, reserve/settle
  evals/              Eval runner, dataset loaders
  admin/              Admin API routes
  prompts/            Versioned prompt files (*.md)
infra/cdk/            AWS CDK stacks: network, data, app, edge
evals/seed/           The 50-item seed eval set (TRD §15)
docs/
  design-system.md
  glossary.md
  adr/
```

## Where things live (quick index)

| Concept | Lives in |
| --- | --- |
| Agent graph nodes, mode routing | `apps/api/graph` |
| `DecisionEngine`, Jev + fallback | `apps/api/decisions` |
| Hybrid retrieval SQL, RRF, rerank | `apps/api/retrieval` |
| Claim extraction, verification, faithfulness scoring | `apps/api/graph/review.py` |
| `RunBus` (Postgres default, Redis slice-8 adapter) | `apps/api/runbus` |
| SSE event schema | `apps/api/schemas/events.py` |
| Quota ledger, reserve/settle | `apps/api/quota` |
| Trace panel, citation chips | `apps/web/src/features/trace` |
| Design tokens | `apps/web/src/styles/tokens.css` (mirrors `docs/design-system.md`) |