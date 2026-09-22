# Veriforge

Adaptive agentic RAG chatbot showcase. See [`CLAUDE.md`](CLAUDE.md) for
working instructions and [`docs/PRD.md`](docs/PRD.md) / [`docs/TRD.md`](docs/TRD.md)
for the numbered requirements (`CH-`, `TR-`, `SR-`, `TX-`, `AC-`, `AD-`)
referenced in commits and PRs.

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
cd apps/api && uv sync && uv run pytest
cd apps/web && npm install && npm run dev
```

Commits follow `docs/conventions/git.md`; a gitleaks pre-commit hook runs
via `core.hooksPath` (already configured after `git init` — if you cloned,
run `git config core.hooksPath .githooks`).
