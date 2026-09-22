# Veriforge

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

Commits follow `docs/conventions/git.md`; a gitleaks pre-commit hook runs
via `core.hooksPath` (already configured after `git init` — if you cloned,
run `git config core.hooksPath .githooks`).
