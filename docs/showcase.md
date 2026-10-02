# Veriforge: a RAG system that shows its work

Veriforge answers questions from your documents and the web with **inline
citations, per-claim verification and an explicit "I don't know"**, and it
streams every decision it makes while it works. It's built production-shaped:
multi-user accounts, quotas, an admin console, versioned settings, an eval
gate in CI, and a written record of every decision and defect.

> **Status (2026-10-02).** Core RAG, trust layer, eval gate and multilingual
> support are built and merged. OKF support and the latency work are planned
> (see [Roadmap](#roadmap)). Every number on this page carries the date it
> was measured. Where something isn't measured yet, it says so.

---

## What's different from a typical RAG demo

| | Typical RAG demo | Veriforge |
| --- | --- | --- |
| **Retrieval** | Vector search | Hybrid BM25 + vector search fused with weighted RRF, reranked, expanded small-to-big; multi-query and multi-part splitting |
| **Trust** | Citations, maybe | Claim-level verification, faithfulness and minimum-support scores, risk-based delivery, conflict disclosure, **abstention with no fabricated citations** |
| **Decisions** | `if` statements or one LLM call | Every routing, scoring and verification step goes through a **decision model** (Jev), with an LLM fallback, a circuit breaker and shadow mode |
| **Evaluation** | None, or a notebook | A seed set and an acceptance set, a baseline built from 5 runs, a **CI eval gate**, attribution of provider time vs our overhead |
| **Languages** | English | 7 languages; the reply follows the question's language |
| **Engineering** | Single user | Multi-user, credit quotas with reserve/settle, admin with audit log, a resumable SSE run stream |
| **Process** | README | PRD, TRD, ADRs, conventions, and a known-issues log with evidence for every entry |

---

## How an answer is made

```mermaid
flowchart TD
  Q[Question] --> I[Ingress — one decision-model call<br/>guardrails · intent · complexity · risk]
  I -->|chitchat / library| D1[Direct reply, no retrieval]
  I --> R[Rewrite + query variants]
  R --> H[Hybrid search<br/>BM25 + vector, weighted RRF]
  H --> RR[Rerank — decision model scores each passage]
  RR --> S[Sanitize — injection check per passage]
  S --> G{Evidence gates<br/>sufficiency AND relevance}
  G -->|weak: rewrite + retry once| H
  G -->|still weak| A[Abstain — what was found, what is missing,<br/>no citations, in the question's language]
  G -->|pass| C[Conflict check — per passage pair]
  C --> GEN[Generate — tool-less, sources wrapped as data]
  GEN --> V[Review — extract claims, verify each,<br/>faithfulness + minimum support, optional revision]
  V --> OUT[Answer with coloured citation chips]
```

**Auto** mode is single-hop with multi-query and one retry. **Deep** mode plans
sub-questions and runs multi-hop retrieval under a controller. Every box
publishes its step and decision, with probabilities, to the live **Trace
panel**.

**Stack:** FastAPI + LangGraph, Postgres with pgvector and ParadeDB
`pg_search` (ICU tokenizer for CJK), Procrastinate workers, React + TanStack
Query, OpenRouter models, `text-embedding-3-large` at 1536 dimensions.

---

## Why a decision model

Retrieval, routing and verification involve many small judgements: is this
passage relevant, is the evidence sufficient, does this claim follow from that
source, which intent is this? Veriforge sends **every one of them** through one
`DecisionEngine` interface, backed by **Jev**, a decision model, with an LLM
fallback. It never makes ad-hoc LLM calls for them.

What that buys, measured:

| | Jev | NVIDIA reranker | Measured |
| --- | --- | --- | --- |
| Answer text kept in the top 8 | **1.00** | 0.82 | 2026-09-30, 23 items |
| Recall@8 | 1.00 | 1.00 | 2026-09-30 |
| Rerank p50 latency | **431 ms** | 839 ms | 2026-09-30 |
| Cost per query | ~$0.0006 | free tier (not production-licensed) | 2026-09-30 |

And the engineering it demands:
- **Thresholds are per engine.** A fallback 0.7 isn't a Jev 0.7.
- **A circuit breaker** (3 failures in 60 s) moves decisions to the fallback,
  then probes Jev again. **Shadow mode** records the fallback's answer on a 2%
  sample, to measure agreement.
- **Calibration is evidence-based.** The relevance gate's floor (0.60) was
  fitted from measured separation: every should-answer item scored ≥ 0.70 and
  every should-abstain item ≤ 0.52, in both runs.
- **Where it misfired, and what we learned.** A borderline intent score
  routed "What does the package contain?" to the "list my documents" path in
  2 of 3 runs. Fix: a confidence floor for that route and a clearer criterion.
  Now 0 of 10.

---

## OKF and RAG: better together *(planned, ADR-004)*

[Google's Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog)
(v0.2) is a bundle of markdown concept files with frontmatter, links between
concepts, and trust signals: who generated it, who verified it, its status
and when it goes stale.

**OKF doesn't replace RAG.** It's only a format. It has no search, no ranking,
no verification and no generation. Something still has to find the right
concept, check it answers the question, and write a cited reply. That's RAG.

| | RAG alone | OKF alone | Together |
| --- | --- | --- | --- |
| Finding information | Hybrid search over chunks | None | One search over documents **and** concepts |
| Structure | Inferred from text | Explicit links | Links followed in Auto (1 hop) and Deep (a decision-model choice), **inside scope only** |
| Trust | Claims checked after generation | Declared by the author | Deprecated excluded, stale flagged, human-verified preferred, status breaks conflict ties |
| Coverage | Any document | Only curated concepts | Curated knowledge where it exists, raw documents everywhere else |
| Output | A chat answer | — | **Verified answers exported as OKF concepts**, reusable by other systems and agents |

It's a loop: documents feed answers, verified answers become concepts, and
concepts improve later answers.

One guardrail: **trust signals change ranking only, after the evidence checks,
and a link never widens what a user can access.** A "verified" label can't
make an unsupported answer pass.

---

## Evaluation: measured, not asserted

Two sets, two purposes:
- **Seed set:** 63 items, mostly over a fictional product's manuals, in 6 categories (lookup,
  multi-hop, keyword-heavy, conflicting sources, should-abstain, injection in
  the document text). Its **fast20** subset gates every relevant merge in CI.
- **Acceptance set:** 48 items over 11 public-domain books in 7 languages,
  covering answer, decline, small talk and library questions.

### Scorecard

| Metric | Value | Measured | Notes |
| --- | --- | --- | --- |
| Faithfulness (fast20) | **0.976** mean of 5 runs (range 0.964–1.000) | 2026-10-02 | Share of claims the reviewer finds supported by their citations |
| Abstention, should-abstain items (fast20) | 7 / 8 | every run since 2026-10-01 | — |
| Answer rate, answerable items (fast20) | 11 / 12 | every run since 2026-10-01 | — |
| Acceptance (books, 7 languages) | 44 / 47 and 43 / 47 | 2026-10-01 (re-scored after label fixes) | Remaining failures: broad-summary declines and an ambiguous question |
| Overhead attribution | 20 / 20 items | 2026-10-02 | Provider time separated from our own processing time |
| Time to first token, answers (client-side) | ~8.0–8.5 s p50 | 2026-10-01 | Target ≤ 5 s (ADR-003); latency work planned |
| Declines delivered (client-side) | ~12.7–13.3 s p50 | 2026-10-01 | Target ≤ 10 s p95 |

**Not yet measured:**
- grounding on text the models can't already know (a counterfactual corpus
  is being built)
- agreement between the automated graders and human labels
- faithfulness per corpus beyond the product manuals

### Bugs the evals caught

Each was found by the measurement, proven, fixed with a test that fails without
the fix, and recorded with its evidence:

- **Every decline came back in Turkish.** The decline template was
  "translated into the language of the question", with the question buried in
  the system prompt. Now English needs no model call, and other languages name
  their target.
- **The eval measured the web, not the documents.** The eval harness used a
  source mode no user ever sends, so should-abstain questions were answered
  from web pages. Abstention read 0–1 of 8 until that was fixed.
- **"What does the package contain?" got a file list.** An intent-routing
  misfire on a borderline score. Fixed with a confidence floor; now 0 of 10.
- **A test item was mislabelled.** A "not in the sources" Whitman question is
  quoted in the *Pride and Prejudice* preface. The pipeline was right; the
  test was wrong.
- **Compare questions showed the judge the wrong book.** The evidence budget
  held about two passages, and junk was sorted first. After the fix, every
  answer item's sufficiency score went up.
- **Latency attribution dropped the slowest items.** Provider stats can take
  up to 124 s to appear, and the lookup waited 21 s. Coverage went from 80% to
  100%.

The full record, including the claims that didn't hold up, is in
[`docs/known-issues.md`](known-issues.md).

---

## Roadmap

From [the production-readiness plan](plans/2026-10-02-0430-backend-prod-readiness-v3.md):

1. **Eval sets:** a counterfactual corpus, a label audit of every item,
   per-corpus gates, and graders validated against human labels
2. **Answerability:** decline when no passage contains the answer; stop
   declining broad questions; ambiguity disclosure
3. **OKF:** import, link traversal and export (ADR-004)
4. **Latency:** answers ≤ 5 s p50, declines ≤ 10 s p95 (ADR-003)
5. Reliability, observability and security hardening
6. Deployment

---

## Read more

- [PRD](PRD.md) and [TRD](TRD.md): numbered requirements and technical design
- [ADRs](adr/): no Redis at Stage 1, chat-scoped sources, latency targets, OKF
- [Conventions](conventions/): testing, review, agents, git
- [Known issues](known-issues.md): every defect, with evidence
