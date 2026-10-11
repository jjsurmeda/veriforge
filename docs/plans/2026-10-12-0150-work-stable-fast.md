# Plan: working, stable, fast — then UI, then deploy

Approved by the owner 2026-10-11/12. Replaces the deploy-first proposal in
`docs/reviews/2026-10-11-1545-state-measurements-and-plan.md` §6.
Rules that make this converge: `docs/conventions/agents.md`, "Finish lines and
measurement".

## Starting point (main, `6fda481`, not pushed)

Lane B2 merged: KI-68 (seq race, migration 0018), KI-66 (generator step),
KI-67 (variants-skip removed). pytest 1123, mypy --strict and ruff clean.
ADR-003: none of the four targets met (TTFT ≈ 6.6–7.4 s p50; the gap
between those two figures is a method difference, not chased — `check-fast`
settles it with one fixed method).

## Phases

Each phase's brief first builds its check target, then fixes until it passes.
Earlier targets must still pass.

| Phase | Target | Passes when |
| --- | --- | --- |
| 1. Work | `make check-work` | ruff, mypy, pytest, vitest, OpenAPI drift; eval gate (fast20 + counterfactual) passes against baseline; entity-mismatch 12/12 clean declines, 0 confident-wrong; no `:free` model reachable in a fresh database or in config defaults |
| 2. Stable | `make check-stable` | 10 parallel chats × 3 rounds: 0 dead runs; 30-min mixed soak: 0 failed or stuck runs, no memory growth; injected faults (OpenRouter timeout/5xx, Jev down, worker killed mid-run) end in a clean error or fallback with credits settled; gate verdict identical over 3 runs |
| 3. Fast | `make check-fast` | ADR-003: answers ≤ 5 s p50 / ≤ 8 s p95, declines ≤ 10 s p95, no trace gap > 2 s; per-stage budget table in ADR-003 asserted from `run_events` |

Phase 3 order: p95 tail SQL over existing `run_events` first (no spend), then
lane B3 — fold variants into the rewrite call (biggest stage, 1667 ms p50),
embed the question during ingress, skip/replace the rerank call when fusion
is clear, merge sanitize into the sufficiency batch, cap the retry. Every gate
kept; ownership-filter test for any changed retrieval path; prompt version
bump + gate rerun for changed prompts.

**Agreed in advance:** if `check-fast` still fails after B3, the owner decides
once — server-buffered speculative generation (no retraction) or accept the
measured speed in ADR-003. No new measurement lane either way.

## After

UI redesign (owner) → `check-work`, `check-stable`, `check-fast` rerun →
deploy (lane A, `infra/`) → checks rerun against AWS (ADR-003: deployed stack
is authoritative).

## Spend

About $8.7 OpenRouter credit left after B2. Phase 1 ≈ $2, phase 2 ≈ $2–3,
phase 3 ≈ $3–5. Top up before phase 3.
