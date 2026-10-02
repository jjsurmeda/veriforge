# Veriforge

**A RAG system that shows its work.** Veriforge answers from your documents
and the web with inline citations, **per-claim verification** and an explicit
"I don't know". Every routing and verification step goes through a
**decision model** with an LLM fallback, and is streamed live to a trace
panel. Its quality is guarded by an **eval gate in CI**.

→ **[The showcase](docs/showcase.md)**: architecture, why a decision model,
OKF + RAG, the measured scorecard, and the bugs the evals caught.

| | |
| --- | --- |
| Retrieval | Hybrid BM25 + vector (weighted RRF), decision-model rerank, small-to-big, multi-query |
| Trust | Claim verification, faithfulness and minimum support, abstention with no fabricated citations, conflict disclosure |
| Quality | Faithfulness **0.976** (mean of 5 runs, fast20, 2026-10-02); 7 languages |
| Engineering | Multi-user, quotas, admin and audit, resumable SSE, PRD/TRD/ADRs, known-issues log |

Adaptive agentic RAG chatbot showcase. See [`CLAUDE.md`](CLAUDE.md) for
working instructions and [`docs/PRD.md`](docs/PRD.md) / [`docs/TRD.md`](docs/TRD.md)
for the numbered requirements (`CH-`, `TR-`, `SR-`, `TX-`, `AC-`, `AD-`)
referenced in commits.

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
