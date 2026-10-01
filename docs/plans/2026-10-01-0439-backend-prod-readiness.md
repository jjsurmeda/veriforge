# Backend production readiness: plan

Written 2026-10-01 (04:39 +08), while D2 is running on `fix/darcy`.
Scope: `apps/api` and infra only. Out of scope: frontend polish, OKF,
and OCR (slice 10, v1.1).

## Where we are (the evidence behind this plan)

Rated on D1's data and the 2026-10-01 review. Roughly 6/10 as a demo and
3–4/10 as a production system.

- Strong:
  - retrieval: recall@8 1.0, and Jev keeps the answer in the top 8
  - multilingual: 0 language mismatches across ~170 replies
  - safety design: generator without tools, wrapped sources, server-side
    ownership filter, sanitizer
- Weak:
  - **declining**: 10/14 correct on the should-abstain set
  - **measurement**: no valid baseline, and the eval measured the web path
    until D2
  - **latency**: TTFT ~10 s at p50, 25 s on compare items, against CH-5's
    **< 3 s**
  - **operations**: KI-21, KI-23 and KI-24, temporary models, no
    deployment

## Definition of done (backend v1)

Every line below is measured, not asserted. It is re-checked in the final
phase on the deployed stack.

| ID | Criterion | Now |
| --- | --- | --- |
| Q1 | Should-abstain accuracy ≥ 90% on ≥ 30 items across **2 corpora**, with **0 confident wrong answers**, in 3 consecutive runs | 10/14, 1 corpus |
| Q2 | Answerable items: pass ≥ 95%, answer rate ≥ 95% | 22/23 |
| Q3 | Faithfulness ≥ 0.90 on the seed set (TRD slice 6), documents-only, judge coverage ≥ 95% | not measured validly |
| Q4 | Baseline stored; fast20 gate runs in CI on every merge touching graph, retrieval, decisions or prompts; 3 reruns stay within the gate | none |
| L1 | Auto single-hop TTFT p50 < 3 s (CH-5); Deep p50 < 30 s (TRD slice 5) | ~10 s |
| L2 | ≥ 90% of eval items have attributed provider time, and our overhead is reported | 0% (null) |
| R1 | Degradation is proven by tests: Jev down, OpenRouter down, rerank down, and web down each give a correct, honest outcome (no spurious abstain, no "try again" on a quota or key failure) | partial |
| R2 | Credits reserve/settle stays correct under concurrency, cancellation and failure (TRD §14), proven by tests | built in slice 7; re-verify |
| S1 | Ownership filter tested on **every** retrieval path (hybrid, web, Deep hops, library intent); the injection eval category passes; security review done; eval corpus out of Shared (KI-24) | partial |
| O1 | Langfuse receives traces with Jev and stage spans (KI-21); structured logs; basic alerts | broken |
| O2 | Production models chosen and gated against the baseline; licensing clean; cost per answer known | temporary gpt-4o-mini |
| D1 | Slice 9: AWS deployment, restore test, load test, deployed smoke + gate | not started |

## Phases

Each phase is 1–2 dispatches of 2–4 items (`agents.md`), and it has an
exit gate. **Quality phases run in sequence**, one variable at a time,
each measured against the previous baseline. Phases marked ∥ don't move
the quality numbers, so they may run on their own branch in parallel.

### P0: D2 (running). Bugs and calibration

Test fixes, eval harness (documents-only, judge parse, attribution),
compare evidence ordering, Jev relevance gate at 0.60.

**Exit:** D2's report is verified by re-running its checks, and the
subset checks pass.

### P1: D3. Measurement foundation

1. Widen the **answer** side near the gate: add 4–6 broad/summarize items.
   Add should-abstain items to reach ≥ 30 across books and AW-2000.
2. **One path for acceptance and eval.** Both run through the same entry
   point and settings as the product (API, `source="upload"`), so the two
   harnesses can't drift again.
3. Run 2 full acceptance runs and 3 fast20 runs, then write the baseline.
   Put the fast20 gate in CI (Q4).
4. Merge `fix/darcy` → `main`, after re-running pytest, mypy, ruff, tsc
   and vitest.

**Exit:** Q4 and L2, a baseline on `main`, and CI gating.

### P2: D4. Answerability (ADR + change)

The design gap: answer vs decline is decided once, before generation, on
scalar floors that measure topical overlap, and nothing downstream can
overrule it.

1. **ADR:** answerability is an explicit decision.
2. A per-passage DecisionEngine `Noul` asks "does passage N contain the
   answer?" over the top-k. It replaces the rerank floor as the gate, and
   `sufficient` stays as a second check.
3. **Post-generation feedback:** if the reply declines, or the reviewer
   finds no supported claims, mark the run abstained and drop the
   citations. This uses the existing revision/diff path, so it fits
   answer-first.
4. **Ambiguity disclosure (KI-27):** when the sources support more than one
   answer, name each one. It's a prompt change, so it runs through the eval
   gate.

**Exit:** Q1 and Q2 hold on the new baseline, and no Q3 regression.

### P3: D5. Latency to CH-5 (likely an ADR)

Before the first token, Auto makes **≥ 6 sequential external calls**:
- ingress ∥ rewrite
- query variants, plus parts on multi-part questions
- N embeddings and hybrid searches
- Jev rerank
- Jev sanitize
- Jev sufficient
- Jev conflict
- then generation

Under 3 s isn't reachable by tuning alone.
1. Get the stage breakdown from the L2 attribution. The largest stages go
   first.
2. Candidate levers, each measured against the P2 baseline:
   - batch sanitize, sufficient and conflict into **one** `decide` call
     (DecisionEngine already takes several questions)
   - skip conflict for single-document evidence
   - fewer query variants on single-hop questions
   - variants in parallel with the first retrieval
   - cache embeddings of repeat questions
3. If CH-5 is still out of reach, write an ADR: stream an early,
   provisional first token or status, or revise CH-5. That's an owner
   decision against the PRD.

**Exit:** L1 met, or CH-5 formally revised. Quality within the gate.

### P4 ∥: Reliability and degradation

KI-23 (honest error codes and copy for key/quota/provider failures), with
outage tests for each dependency (R1). Timeouts and cancellation settle
tests (R2). KI-15 (test hang). KI-8, the backend half: a replay route so
e2e never needs a live LLM.

**Exit:** R1 and R2.

### P5 ∥: Security and data hygiene

KI-24 (eval corpus out of Shared, into its own collection). Audit
ownership-filter tests on every retrieval path, adding the missing ones
test-first. The injection eval category passes. Slice 8's security review.
Dependency and secret audit.

**Exit:** S1.

### P6 ∥: Observability

KI-21 (Langfuse region/config; Jev and stage spans). The backend payloads
behind KI-22 (the metrics Trace/Metrics need). Structured logs with run
ids. Alerts for error rate, breaker open, credit floor and latency p95.

**Exit:** O1.

### P7: Models and cost

Choose production models per role; gpt-4o-mini is temporary (owner
decision). Each candidate is gated against the baseline. Measure cost per
answer and calibrate the quota estimates. Credit monitoring. Record the
licensing position (Jev is production-licensed; NVIDIA's free tier is
not).

**Exit:** O2, with a new baseline on the final models.

### P8: Slice 9. Deploy

AWS via CDK (network, data, app, edge). Restore test. A load test at the
expected concurrency. A deployed smoke run plus the eval gate against the
deployed stack. Re-check every definition-of-done line there.

**Exit:** D1, and every line above rechecked.

### After v1: OKF

Starts only once P2's baseline is in CI. Its rules are the isolation run
first, items before code, a feature flag defaulting off, ownership tests
on link expansion, and its own threshold check (see the 2026-10-01
discussion; to be added to `docs/conventions/testing.md`).

## Order and dependencies

```
P0 → P1 → P2 → P3 → P7 → P8
          ↘ P4 ∥, P5 ∥, P6 ∥   (any time after P1; merge each through the gate)
```

P7 comes after P3 because model choice moves latency as well as quality.
P8 comes last because it re-verifies everything on the deployed stack.

## Budget

A full acceptance run is about $0.34 and fast20 about $0.17. A quality
phase costs about $2 (development checks plus 2 acceptance runs and 3
fast20 runs); P7's model comparison about $5.

**Plan for about $25 of OpenRouter credit** across P1–P8, and top up
before P1. The balance was $1.43 at the end of D1.

## Owner decisions this plan needs

1. **Now:** the targets in the definition-of-done table (especially Q1's
   90% / 0 confident wrong answers).
2. **P2:** approve the answerability ADR.
3. **P3:** if 3 s can't be met, choose between an early-token UX and
   revising CH-5.
4. **P7:** the final models per role, and the budget per answer.
5. **P8:** AWS account, region and cost ceiling.

## Risks

- Test sets are small and single-author. Mitigation: 2 corpora plus
  harvested thumbs-down items once deployed (TRD §15 dataset sources).
- Jev is a single provider on OpenRouter only. Mitigation: the breaker
  fallback is already built, and R1's tests prove it.
- The latency target may force a design change (P3). Better known early:
  the P3 measurement can be pulled forward, since L2 lands in D2.
