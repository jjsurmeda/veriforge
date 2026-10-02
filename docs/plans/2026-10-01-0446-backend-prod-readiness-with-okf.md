# Backend production readiness, with OKF in v1: plan variant

A variant of `2026-10-01-0439-backend-prod-readiness.md`. Everything there
still applies. This file adds OKF to v1 and re-orders around it.

**Caveat:** the detailed OKF plan was written in another session and isn't
in the repo. What follows is built from the review notes in
`docs/handover/2026-09-30-2353-handover.md`, step 3:
- OKF concepts become `documents` (not a new `source_type`, which would
  bypass `build_scope`)
- `format` + `okf_meta` columns
- strip frontmatter before chunking
- sanitize and scope-filter every link-expanded chunk
- likely a new Deep-mode `Choice` option (TRD §8)
- an ADR

**Reconcile this with the other session's plan before O1.**

## What changes versus the base plan

- OKF becomes a **quality variable**, so it goes in the sequential chain,
  never in parallel.
- It lands **after P2** (answerability). The baseline it's measured
  against must already decline correctly, or OKF's effect can't be told
  apart from the old abstention bugs.
- It lands **before P3** (latency) and P7 (models). Link traversal adds
  latency, and a model's cost and quality depend on the final pipeline.
  Tuning either before OKF would mean doing it twice.
- The definition of done gains OKF rows, and every quality row must hold
  on **three** corpora: books, AW-2000 and OKF.

## Added definition-of-done rows

| ID | Criterion |
| --- | --- |
| K1 | Isolation: with OKF ingested but **out of scope**, acceptance and fast20 match the baseline within the gate |
| K2 | OKF items: Q1 (decline ≥ 90%, 0 confident wrong) and Q2 (answer ≥ 95%) hold on OKF's own set |
| K3 | Link expansion never widens scope: tested for each path (Auto expansion, Deep traversal, library intent); an out-of-scope link target is dropped, and the drop is visible in the trace |
| K4 | Sources reached through links pass the sanitizer, the same as direct chunks; the injection category includes a link-borne case |
| K5 | Deep with OKF traversal: p50 < 30 s; multi-hop OKF items beat Auto on faithfulness and recall (TRD slice 5 criterion) |
| K6 | The gate thresholds (`sufficient`, relevance/answerability) are checked on OKF items; either one global value holds or a documented per-format value exists |

## Phases

```
P0 → P1 → P2 → O1 → O2 → O3 → O4 → P3 → P7 → P8
          ↘ P4 ∥, P6 ∥                    P5 (after O3; must cover links)
```

P0–P2 are unchanged: D2; D3 (baseline, CI gate, merge); D4 (answerability).

### O1: OKF ADR and test set (docs and data only, no product code)

1. The ADR: data model (concepts as `documents`, `format`, `okf_meta`),
   frontmatter handling, link semantics, the scope rule for link targets,
   and the Deep `Choice` option. Reconcile it with the other session's
   plan.
2. An OKF corpus in **its own collection** (not Shared; KI-24's lesson).
3. **Items before code**, in both sets:
   - OKF answerable items
   - should-abstain items *near* OKF content
   - link-dependent multi-hop items
   - one link-borne injection case

   Prove each should-abstain item absent with a zero-hit search (D1's
   method).
4. The feature flag `okf.enabled` (runtime setting, off by default).

**Exit:** ADR accepted and items loaded. Nothing ships yet.

### O2: Ingestion behind the flag

Migration (`format`, `okf_meta`), the parser, frontmatter stripping, and
chunking through the existing chunker. Tests first for the migration and
the parser.

**Isolation run (K1):** OKF ingested and out of scope, then 1 acceptance
run and 1 fast20 run. They must match the P2 baseline. Then OKF in scope,
retrieval-only metrics (recall@8, rank of the expected passage). No gate
change.

**Exit:** K1, and retrieval recall on OKF items.

### O3: Link expansion in Auto

Expanded chunks go through `build_scope` / the ownership filter and the
sanitizer, **tests first** (K3 and K4). Expansion is bounded (hops, chunk
budget), and trace events come from existing decision/retrieval events
with no new SSE type (otherwise TRD §12 first, then TS regen). Check the
answerability gate's thresholds on OKF items (K6).

**Exit:** K2 (Auto), K3, K4 and K6. New baseline with OKF in scope.

### O4: Deep traversal

The new Deep `Choice` option goes through DecisionEngine (TRD §8), with
traversal bounded by the Deep budget.

**Exit:** K5, and K2 on multi-hop OKF items. Turn the flag on by default,
then write a new baseline on 3 corpora.

### Then P3 → P7 → P8 as in the base plan

With these changes:
- **P3 latency** measures the final pipeline, including traversal; link
  expansion is one more stage to budget.
- **P5 security** runs **after O3**, so its audit covers the link paths.
  P4 and P6 stay parallel.
- **P8** re-checks the K rows on the deployed stack too.

## Cost and size, against the base plan

| | Base | With OKF |
| --- | --- | --- |
| Dispatches to v1 | ~9–11 | ~13–16 |
| OpenRouter credit | ~$25 | ~$33 (OKF adds ~4 quality runs, the isolation run, and a larger eval set) |
| Quality baselines written | 3 | 5 |

## Added risks

- **Thresholds may not transfer.** Short concept documents with
  frontmatter may score differently on `sufficient` and relevance than
  book chunks. K6 makes this explicit rather than letting it be
  discovered in production.
- **Link expansion is a new way to widen scope.** It's the first path
  where retrieval follows data-supplied pointers. K3 and the P5 placement
  exist for this.
- **Latency pressure grows** on a pipeline already far from CH-5. The P3
  ADR may have to cover traversal (for example, Auto expands one hop at
  most; deeper traversal is Deep-only).
- **The other session's OKF plan may differ.** O1 reconciles it first;
  don't dispatch O2 from the handover notes alone.

## Owner decisions added

1. Is OKF in v1 at all (this plan) or after v1 (base plan)?
2. The link scope rule: may a link target outside the chat's scope ever
   be followed? Recommended: no; drop it and show the drop in the trace.
3. Is OKF on by default at launch, or opt-in per collection?
