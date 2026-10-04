# Backend production readiness, v3 (PRD v3, OKF in v1)

Supersedes `2026-10-01-0439-…` and `2026-10-01-0446-…-with-okf.md`.
Targets are PRD v3 §5. Latency is governed by ADR-003, OKF by ADR-004.
Conventions are in `docs/conventions/` (agents, testing).

## Where we are (2026-10-02, after D4, `d36a034`)

- **Done:**
  - harness and gate parity
  - the baseline (`baseline_fast20.json`, model-stamped)
  - attribution coverage 100%
  - judge coverage 100%
  - acceptance runs on an audited plan
  - CI green
- **Rating:** about 7.5/10 as a demo, about 5.5/10 for production.
- **Biggest gaps:**
  - latency (answers 7.8 s server / 9.2 s client p50)
  - grounding unproven on unseen text
  - gate stability (KI-32 faithfulness at the bar; overhead noise
    > 20%)
  - broad-question false declines

## Where we are (2026-10-05, after P2a, branch `p2a/answer-quality`)

P2a (answer quality) landed: no false absence sentences (KI-53),
one-checkable-fact claim extraction (KI-52), prose decline recorded as an
abstention, and the entity-match gate (KI-54) — 12/12 clean declines on
the new entity-mismatch set, 0 confident wrong, D7 5-run baseline
zero-spread. **Generator decision (P2 input, item-5 bake-off):** the
control `openai/gpt-4o-mini` **stays** — candidates gemini-3.8-flash and
claude-haiku-4.5 failed the pre-approved rule's first condition (0
confident wrong in every arm on every set; grounding tied: cf min support
1.0, 0/10 forbid hits); both score better proxy30 faithfulness (0.9462 /
0.9633 vs 0.8993 clean control arm) without a quality axis the control
misses, gemini TTFT +1.55 s and per-answer cost ≈2.7–3.5× / ≈2.8–3.1×.
KI-57 (fallback decide cap) fixed. Open for the owner: the 5 GHz
`abstain-10` label, adopting the entity-mismatch baseline, KI-56
(injection-bearing chunk swallows the RP-77 fact). Result doc:
`docs/prompts/2026-10-03-2338-p2a-answer-quality_result.md`.

## Phases

```
D5 → D6 burn-down → P1b → P2 → O1 → O2 → O3 → O4 → O5 → P3 → P7 → P8
      ↘ P4 ∥, P6 ∥ (any time after D5)      P5 after O3
```

Quality phases run one at a time. ∥ phases run on their own branch or
worktree.

| Phase | Content | Exit |
| --- | --- | --- |
| **D5** | **Gate stability and merge.** Pin temperature 0 for claim extraction, and measure the generator at about 0.3 (KI-32). Decide the overhead gate per its measured noise (owner). KI-36 label fixes. The conventions update. The first real CI gate run. Merge `fix/darcy` → `main`. | Gate passes in CI; `main` green |
| **P1b** | **Eval sets.** The counterfactual corpus (20/20). The books set raised to 20 should-abstain. Scripted label audit for every item (KI-36). Per-corpus ~10-item gate subsets. `min_support` and per-corpus summaries in the runner. Parallel isolated-stack runs. Eval corpora out of Shared (KI-24), with a re-baseline. **Judge validation:** about 30 claims labelled by a human (supported or not) against the reviewer's verdicts, and about 30 answers against the acceptance scorer and the eval judge, with agreement ≥ 90% each; disagreements become fixes or documented limits. About 2–3 dispatches, about $3, plus about 1 h of owner labelling. | Every label proven; graders validated; tiers runnable |
| **P2** | **Answerability (ADR).** An answerability `Noul` per passage (summary intents judged on coverage) replaces the rerank floor. A post-generation decline is recorded as an abstention and its citations are dropped. TR-8 ambiguity disclosure (≥ 3 ambiguity items first). KI-33 language detector. **Auto-escalation to Deep (PRD CH-2 v3.1):** a DecisionEngine threshold `auto_escalate` on ingress `complexity = multi`, plus escalation when Auto would abstain on a multi-part or compare question; a trace step at once; Deep credit reserve top-up (TRD §14); admin on/off. **Deep measured early (moved from O4):** a Deep eval set of ≥ 10 items per corpus, the real-session hop test (F21), Deep ≤ 30 s p50 checked. **Fallback calibration:** run the relevance and answerability gates once with `decision_engine_mode = fallback_only` and record the fallback's separation. | **Milestone:** full sets ×2. Decline accuracy ≥ 90%; confident wrong answers ≤ 1/100; false abstention ≤ 5% including broad |
| **O1** | OKF items before code (answer, near-miss abstain, multi-hop, link-borne injection), its own collection, flag `okf.enabled`, ADR-004 details | Items proven |
| **O2** | Bundle ingestion job, migration, OK-0 rules (tests first). **Isolation run**: OKF ingested out of scope must match the baseline. Measure the ingestion rate (provisional ≤ 10 min / 500). | K1 isolation |
| **O3** | Auto link expansion after the gates, the scope rule, no existence oracle, sanitizer, `okf_expand` timing, `RetrievedChunk` fields plus TS regen, threshold check on OKF (K6). KI-34 conflict sides (needed by OK-6). | OKF items pass; ownership tests |
| **O4** | Deep `follow_link` controller option (the Deep eval and hop test now land in P2) | Deep ≤ 30 s p50 |
| **O5** | OKF export: explicit "Verify" action, actual verdict engine, round-trip re-import | **Milestone:** full sets ×2 on 4 corpora |
| **P3** | **Latency** (TRD §7.1): publish steps and sub-steps; batched embeddings; parallel searches; skip variants on simple lookups; merge rewrite and variants; one Jev call when the sanitizer dropped nothing; skip retry far below the gate; time the conflict call. | CH-5 met, or an owner-approved ADR-003 entry |
| **P4 ∥** | Reliability: KI-23 honest error copy; outage tests per dependency; cancellation settle tests; KI-15; KI-8 replay route | R1, R2 |
| **P5** | Security after O3: ownership tests on every retrieval and link path; injection category including link-borne; security review; secrets audit; KI-35 real reset email (SES) | S1 |
| **P6 ∥** | Observability: KI-21 Langfuse; KI-22 backend payloads; structured logs; alerts | O1 (observability) |
| **P7** | Models and cost: final models per role, gated; cost per answer; quota calibration | Baseline on final models |
| **P8** | Slice 9: AWS deploy, restore test, load test, deployed smoke plus gate; **re-check every PRD §5 row on the deployed stack** | **Milestone:** v1 accepted |

## Budget

| Item | Cost |
| --- | --- |
| Per-phase gates (about 12 phases × about $0.6) | about $7 |
| Milestones (3 × about $2.6) | about $8 |
| P1b set building | about $3 |
| P7 model comparison | about $5 |
| CI gate runs (about 30 × $0.17) | about $5 |
| Development checks | about $5 |
| **Total** | **about $33** |

$9.88 was left at D4's end. Top up before P1b.

## Parallelism

Per `docs/conventions/agents.md`:
- code items go to sub-agents in worktrees
- quality runs go out concurrently on isolated stacks
- latency is measured alone

P4 and P6 overlap with the quality chain.
