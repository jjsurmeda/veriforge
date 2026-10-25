# Veriforge

**A RAG system that shows its work.** Veriforge answers from your documents
and the web with inline citations, **per-claim verification** and an explicit
"I don't know". Every routing and verification step goes through a
**decision model** with an LLM fallback, and is streamed live to a trace
panel. Its quality is guarded by an **eval gate in CI**.

→ **[The showcase](docs/showcase.md)**: architecture, why a decision model,
the decision-model and reranker comparison, the measured scorecard, and the bugs the evals caught.

| | |
| --- | --- |
| Modes | Auto: adaptive + hybrid RAG with a corrective evidence check. Deep: agentic RAG (search, read, search again or answer) |
| Retrieval | Hybrid BM25 + vector (weighted RRF), pluggable rerank, small-to-big, multi-query, section summaries for gist questions |
| Decision layer | Pluggable decision models (Jev and others) and rerankers (Cohere, NVIDIA, Jev, LLM judge), compared side by side |
| Benchmarks | Reranker, decision-layer and generator tables in [`docs/benchmarks/`](docs/benchmarks/); summary in [Measured results](#measured-results) |
| Trust | Claim verification, faithfulness and minimum support, abstention with no fabricated citations, conflict disclosure |
| Quality | Faithfulness **0.976** (mean of 5 runs, fast20, 2026-10-02); 7 languages |
| Engineering | Multi-user, quotas, admin and audit, resumable SSE, PRD/TRD/ADRs, known-issues log |

Adaptive agentic RAG chatbot showcase. See [`CLAUDE.md`](CLAUDE.md) for
working instructions and [`docs/PRD.md`](docs/PRD.md) / [`docs/TRD.md`](docs/TRD.md)
for the numbered requirements (`CH-`, `TR-`, `SR-`, `TX-`, `AC-`, `AD-`)
referenced in commits.

## Measured results

Local Compose stack, 2026-10-20 to 2026-10-23. Each figure is from a named run; "one draw"
means one run, so it can move between runs (the same DeepSeek configuration scored 56/56 and
53/56 on two books draws). Details, method and caveats:
[`decision-layer.md`](docs/benchmarks/decision-layer.md),
[`results.md`](docs/benchmarks/results.md), [`rerankers.md`](docs/benchmarks/rerankers.md).

| Area | Result | Run |
| --- | --- | --- |
| Generator, books (56 items) | DeepSeek V4 Pro, prompt v6: 56/56 and 53/56 (2 draws); 0 confident wrong, 0 false abstentions in both; content-miss bar met in 1 of 2 | books, 2 draws |
| Generator, held-out (31 items) | DeepSeek V4 Pro: 31/31 on v5 and on v6; 0 confident wrong; the known false-premise trap declined | one draw each |
| Generator alternatives | gpt-4o-mini failed the books gate (53/57); Sonnet 5.5 v6 had 1 confident wrong (54/56) | one draw each |
| Decision layer, books | Jev 56/56 (53/56 on a second draw); LLM judge gpt-4o-mini as the only engine 40/56: 11 false abstentions, 3 content misses, 0 confident wrong | one draw each |
| Decision latency (28 items, paired) | Jev p50 about 0.5 s per call batch; judge 1.6 to 11.8 s in flight per area, rerank 95 s | shadow run |
| Decision cost (exact, OpenRouter records) | Jev $0.026 per 1k decisions, judge $0.180 (6.9x); per run $0.0039 against $0.0272 | shadow run |
| Rerankers (33 items, recall@8) | Jev 31, NVIDIA 27, Cohere 26, fused order 26, BGE 25; judge 10/12 against Jev 11/12 on a 12-item subset | pool replay |
| Deep mode, draw 1 | Did not meet its bar on any of three frozen splits (below) | b885ac2, one draw per split |

### What the numbers do not say

- **The thresholds were calibrated on Jev.** The LLM judge ran on the same values, uncalibrated
  (the "fallback" thresholds are a copy of Jev's). The comparison is Jev as calibrated against the
  judge as not calibrated.
- **The judge is gpt-4o-mini.** `deepseek-v4.1-flash-1017` was also tried on 16 items only: 12/16
  against 13/16 for gpt-4o-mini, not distinguishable.
- **Judge latency is in-flight time.** Wall time in the shadow run was inflated by our own
  queueing (rerank wall p50 150 s, in flight 95 s).
- **Generator cost is not quoted.** The generator price in the config was corrected to OpenRouter's
  list price after a billed-rate check (53 calls billed 0.98x of it; single runs swing 0.77x to 1.12x
  with provider routing; KI-90, ADR-007). Decision-layer costs are exact from OpenRouter generation records.
- **Three changes were made after results, each approved by the owner:** `outside-whitman` was removed
  from the books set (57 to 56 items; DeepSeek v5 had scored 54, 55 and 52 of 57); prompt v6 replaced
  v5; the scorer's decline detection was widened (`7e73ffe`; Sonnet 5.5 v5's reply to
  `outside-holmes-boston` went from confident wrong to a decline). Old and new numbers are in
  [`results.md`](docs/benchmarks/results.md).

### Deep mode

Draw 1 on the frozen dev (14), test (16) and held-out (8) splits passed 6/14, 10/16 and 5/8 and did
not meet the bar declared beforehand on any of them.

- **Scorer artifacts (KI-87).** The gate counted 1, 3 and 2 confident wrong. Each of the 6 read is a
  cited prose decline ("the sources do not give the Time Traveller's full name") that the decline
  regex does not recognise. n = 1 per item and only the start of most replies was read.
- **Real.** False abstentions on compound questions (4 of 10 on test), and p50 item wall clock of 33.6 s
  on dev and 30.8 s on held-out against a 30 s target.

Deep is being improved. Before the last change dev scored 4 false abstentions of 10; it now scores 2.

### What is not measured yet

- Entity-guard mismatch cases (a question naming something the passages do not): only incidental
  firings on 28 items, no designed set.
- Injection and jailbreak firing: every guard pair so far was benign input, so 100% agreement
  there shows no detection.
- Held-out on the LLM judge: not run.
- A second unseen set: the held-out set has been run several times and is one set.
- OCR and multimodal inputs.
- Laya and Microsoft-Decision-1 as decision models (not pluggable yet; KI-85).

## Layout

```
apps/web     React SPA (Vite, TanStack Query, Tailwind, shadcn/ui)
apps/api     FastAPI + LangGraph (uv, ruff, mypy --strict)
infra/cdk    AWS CDK stacks: network, data, app, edge
evals/seed   50-item seed eval set (TRD §15)
docs         Design system, glossary, ADRs, conventions
```

## Quick start

```sh
cp .env.example .env   # optional: fill in API keys
docker compose up
```

- API on http://localhost:8000 (`curl localhost:8000/healthz` →
  `{"status":"ok","db":"ok"}` once Postgres is up)
- SPA on http://localhost:5173
- Postgres (pgvector) on localhost:5432, `veriforge`/`veriforge`

Regenerate the web API client against the running API with
`npm run codegen` in `apps/web` (output in `apps/web/src/generated/`,
gitignored — never hand-edit it).

Manual fallback (no Docker): run a local Postgres at `DATABASE_URL`, then
`cd apps/api && uv sync && uv run uvicorn main:app --reload` and
`cd apps/web && npm ci && npm run dev`.

## Demo corpus

The Library ships empty. Two seeders fill it, both idempotent:

```sh
make seed-models   # free OpenRouter models + role bindings (item 9)
make seed-books    # five public-domain books as Shared documents
```

`make seed-books` downloads the plain-text UTF-8 editions of *Pride and
Prejudice*, *The Adventures of Sherlock Holmes*, *Frankenstein*, *Alice's
Adventures in Wonderland* and *The Time Machine* from
[gutenberg.org](https://www.gutenberg.org), strips the Project Gutenberg
header and footer, and ingests them through the normal upload pipeline as
Shared Library documents owned by the admin user. Reruns are no-ops: the
cache and the sha256 dedupe skip anything already present.

The texts are **not** committed. They are cached under `.data/gutenberg/`
(gitignored) and fetched on demand, one request per book with a pause
between them and a real User-Agent. Project Gutenberg's licence terms are at
<https://www.gutenberg.org/policy/license.html>; the works themselves are in
the public domain in the United States, which is why this is safe to
redistribute if you ever choose to — Veriforge does not.

Set `GUTENBERG_ADMIN_EMAIL` to pick which admin owns the Shared collection;
without it the oldest admin is used. Promote one first if none exists:

```sql
UPDATE users SET role = 'admin' WHERE email = 'you@example.com';
```

`make smoke` then replays five fixed turns against the corpus and prints the
routed intent, the answer and the citations for each.

Commits follow `docs/conventions/git.md`; a gitleaks pre-commit hook runs
via `core.hooksPath` (already configured after `git init` — if you cloned,
run `git config core.hooksPath .githooks`).
