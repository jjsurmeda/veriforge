# Decision layer: Jev vs an LLM judge

Measured 2026-10-22 and 2026-10-23 on the local Compose stack. Nothing here is a tuned
configuration of either side. Source runs are named in each section; the run reports
themselves are kept outside the repository, so the numbers are copied here.

## Read this first

- **Thresholds were calibrated on Jev.** The LLM judge ran on the same shipped
  thresholds (floor 0.455, IsUse 0.47, stream line 0.60, entity 0.50, injection 0.85,
  and so on). The "fallback" column in `decisions/thresholds.py` is a copy of Jev's
  values; nothing was calibrated for the judge (KI-85). Every comparison below is
  "Jev as calibrated" against "the judge uncalibrated". It does not show what a
  calibrated judge would score.
- **The judge is `openai/gpt-4o-mini`** (verified in the OpenRouter generation
  records for the shadow run). A second judge, `deepseek/deepseek-v4.1-flash-1017`,
  ran on 16 items only.
- **Judge latency is in-flight time.** In the shadow run the judge shared a
  per-model concurrency slot with the rewriter and claim extractor, so its wall time
  was inflated by our own queueing (34% of wall for rerank, 72 to 97% for the other
  areas, median). "In-flight" is the time inside the provider call with the slot wait
  removed. Use it for the judge's own speed. It was measured with concurrency 4 and
  every Jev batch shadowed, so it is not an isolated single-call benchmark; the wall
  column is a worst case and the in-flight column a best case.
- **Cost is exact for the decision-layer numbers in section 1.** It is the
  `total_cost` of each OpenRouter generation record (856 of 856 ids resolved), which
  matched the response cost of all 585 non-streamed calls exactly. It is not the
  usage ledger, whose prices are stale (KI-90).
- **One draw each, small n per area** (17 to 46 batches per stage). No confidence
  intervals were computed. p95 of fewer than 20 batches is close to the maximum.

## 1. Per decision area, paired on the same inputs

Run: shadow pairs on 28 of the 56 books items (every second item in file order),
`shadow_sample_rate = 1.0`, the user path served by Jev (4,830 of 4,830 decision
events `engine=jev`), generator DeepSeek V4 Pro, prompt v6, concurrency 4. Both engines
scored the same input in the same run. The log is per batch, so a 9-decision ingress or
a 71-passage rerank counts once for latency and cost. 244 judge batches, 232 returned
usable output, 12 failed.

| Area | Jev p50 ms | Judge p50 ms (in-flight) | Speed ratio (in-flight) | Jev $ / 1k decisions | Judge $ / 1k decisions | Cost ratio | Agreement at shipped thresholds |
|---|---|---|---|---|---|---|---|
| rerank (per passage, floor 0.455) | 786 | 95,317 | 121x | 0.029 | 0.217 | 7.5x | 2392/3195 (75%) |
| ingress / complexity (9 decisions per batch) | 500 | 5,773 | 12x | 0.006 | 0.052 | 8.6x | 234/256 (91%) |
| chunk_injection (sanitize, 0.85) | 481 | 4,450 | 9x | 0.015 | 0.076 | 5.0x | 300/300 (100%, benign input) |
| evidence: conflict (0.60) and entity (0.5) | 488 | 7,919 | 16x | 0.016 | 0.099 | 6.1x | 403/478 (84%) |
| IsUse (0.47) | 517 | 1,608 | 3x | 0.123 | 0.410 | 3.3x | 18/18 (100%) |
| prose_decline (0.70) | 467 | 2,013 | 4x | 0.027 | 0.132 | 4.8x | 9/9 (100%) |
| output_guard (secrets 0.60, toxicity 0.85) | 471 | 2,088 | 4x | 0.017 | 0.072 | 4.1x | 34/34 (100%, benign input) |
| claim_verdict (exact label) | 533 | 11,798 | 22x | 0.032 | 0.152 | 4.7x | 335/416 (81%) |
| all batches | 509 (p95 981) | n/a | n/a | 0.026 | 0.180 | 6.9x | n/a |

Wall-clock p50 for the judge, with our queueing included: rerank 149,607 ms (p95
643,787), ingress 39,406, chunk_injection 49,423, evidence 57,739, IsUse 60,409,
prose_decline 72,050, output_guard 33,318, claim_verdict 44,295; all batches 59,837
(p95 381,765). The wall-clock ratios (71x to 190x) are not the judge's speed.

Agreement rule: Noul and rerank agree when both sides fall on the same side of the
shipped threshold; Choice agrees on an exact label.

Decision-layer cost per run (32 runs with decision calls, real USD):

| Engine | Total | Per run |
|---|---|---|
| Jev decisions | $0.1252 | $0.0039 |
| LLM judge decisions (shadow) | $0.8706 | $0.0272 (7.0x Jev) |

The generator's cost is not quoted here. Its price constants in `config.py` were corrected on
2026-10-25 to the OpenRouter list price after a billed-rate check (KI-90, ADR-007); the runs on
this page were recorded before that.

### Caveats specific to this table

- **Agreement of 100% on guards, sanitize, output checks, conflict and prose_decline
  is agreement on benign input.** Neither engine flagged anything: 0 of 300
  chunk_injection pairs, 0 of 20 conflict keys, 0 of 9 prose_decline pairs, and all
  guard, PII, secrets and toxicity pairs were 0 on both sides. These rows do not show
  that either engine catches an attack or a leak. See "What is not measured yet" in
  the README.
- IsUse (18 pairs, 17 pass on both), prose_decline (9 usable pairs), conflict (20),
  output_guard (17) have too few pairs to rank the engines.
- Prose_decline: 8 of 17 judge calls returned unusable output ("missing or non-object
  answer", after 2 attempts); so did 3 of 41 evidence calls and 1 of 46 rerank calls.
  Their cost is in the table.
- The judge is more generous on rerank (913 passages over the floor against 302 for
  Jev; Spearman 0.43) and fires less often on the entity check (147 against 180).
  Thresholds are Jev-calibrated for both.
- Entity and claim-verdict have real n (458 and 416 pairs). Their effect on item
  pass/fail was not replayed: the flow follows Jev in this run, so the judge's verdicts
  never changed an outcome. The 28 items had identical pass/fail and class to the Jev
  v6 books run.
- Shadow at 1.0 slowed the user path about 8x in this run (TTFT p50 92.5 s against
  11.7 s on the same 28 items; cause inferred to be the shared judge slot, not proven).
  The 2% default sampling is not affected by this.
- Defect found while measuring (not fixed): a shadow judge call that finishes after its
  run has settled raises `MultipleResultsFound` in `UsageContext.record_call` (KI-91);
  34 calls on this run. Rare at 2% sampling.

### Rerank, same pools

| Measure | Jev | Judge |
|---|---|---|
| recall@8 against labelled gold passages, 15 answerable items (gold present in the pool for 14) | 14/15 | 12/15 |
| top-8 overlap between the two engines, 45 paired pools (71 passages on average) | mean 1.9 of 8 (min 0) | |
| per-pool Spearman | mean 0.18 (n = 42) | |
| item floor (mean of top 3 >= 0.455): same decision | 33 of 45 pools | |

Two items of 15 is not a reliable gap. 13 of 253 passage digests (5%) did not map back
to a chunk.

### Entity guard and claim verdict, where they fired or disagreed

- Entity guard (fires when no passage in a call matches at 0.5): both fire on
  `ml-fr-noli-baiser` and `outside-whitman-lilacs`. Jev only on `ml-es-outside`
  (judge 1 of 2 calls). The judge fires where Jev does not on `ml-de-outside` (4 of 4
  calls), `outside-emma` (2), `outside-moby-dick` (1) and `outside-dracula` (2 against 1).
  Neither fires on an answerable item. The effect on the item class is not replayed.
- Claim verdict, Jev to judge: supported to supported 321, partial to supported 21,
  supported to unsupported 17, unsupported to supported 13, unsupported to unsupported
  13, supported to contradicted 9, unsupported to contradicted 6, five smaller cells 15.

## 2. The judge as the only engine, books set

Run: `decision_engine_mode = fallback_only` (judge gpt-4o-mini for every decision,
rerank included), 56 books items, generator DeepSeek V4 Pro, prompt v6, one draw.
10,674 decision events over 71 runs, all `engine=fallback`, none `jev`. Jev reference:
the v6 books run `20261022-162510` (56/56, one draw; the second v6 Jev draw was 53/56
with 3 content misses and no false abstentions).

| Metric | Jev | LLM judge (fallback_only) |
|---|---|---|
| Passed | 56/56 | 40/56 |
| Answer items passed | 32/32 | 18/32 |
| Clean declines (should-abstain items) | 20/20 | 18/20 (1 timeout, 1 decline in the wrong language) |
| Confident wrong | 0 | 0 |
| False abstentions (answer item declined) | 0 | 11 |
| Content misses | 0 | 3 (character-collins, plot-speckled-band, broad-time-machine) |
| Smalltalk and library | 2/2, 2/2 | 2/2, 2/2 |
| p50 time to first token, all items | 11,089 ms | 159,864 ms (answer items 134,939; should-abstain items 216,710) |
| Judge decision latency | n/a | per call group p50 6.7 s over 561 groups; rerank p50 93 s (max 500 s); evidence 7.8 s; ingress 5.7 s; IsUse 2.0 s |

Sixteen items went from pass under Jev to fail under the judge; none went the other
way. False abstentions by stage (inferred from run events): 7 were IsUse rejections
after generation (the judge's IsUse is 0.0 or 1.0, so the 0.47 line is effectively
"the judge says no"), 4 abstained after generation with no IsUse decision recorded, 0
at the evidence floor or entity guard before generation. Whether the damage came from
the judge's rerank grades feeding the generator or from its IsUse was not separated; that
needs a replay.

The cost of this run was about $2.3 (ledger tokens priced at gpt-4o-mini and DeepSeek
list prices bracket it between $2.07 and $4.66). That figure is an estimate with the
stale-price problem described above, and is not exact. The exact decision-layer figure
is the per-run one in section 1.

Other observations from this run: the access token expired mid-run and about 12 items
needed a retry (a harness issue); a judge rerank batch can take up to 500 s; the
configured reranker id in `runs.metrics.reranker` still reads "jev" when the judge
graded, which is a label, not the engine. Held-out was not run on the judge.

## 3. A second judge: Flash, 16 items

`deepseek/deepseek-v4.1-flash-1017` as the fallback model (both fallback env vars set to
it), `fallback_only`, the DB and generator of section 2. 16 of the 28 shadow-subset
items were scored before the run was stopped on its spend cap; 12 were not. Descriptive
only: one draw, a partial subset, thresholds uncalibrated for both judges.

| Metric (same 16 items) | Jev | gpt-4o-mini judge | Flash judge |
|---|---|---|---|
| Passed | 16/16 | 13/16 | 12/16 |
| False abstentions | 0 | 2 (quote-darcy, scene-tea-party) | 3 (quote-darcy, scene-tea-party, fact-bennet-sisters) |
| Confident wrong | 0 | 0 | 0 |
| Content misses | 0 | 1 (compare-inventors) | 1 (plot-red-headed-league) |
| Clean declines | 4/4 | 4/4 | 4/4 |
| p50 TTFT | 10.0 s | 109.7 s | 235.9 s over 20 completed runs (not item-matched, includes retries) |

12 against 13 of 16 is not distinguishable with one draw each. Flash per-stage call-group
p50: ingress 6,158 ms, rerank 88,100 (p95 385,686), evidence 11,047, IsUse 1,643,
sanitize 4,698, claim_verdict 9,596, output_guard 2,488, prose_decline 1,489. Flash
returned unusable output for prose_decline (3 batches) and entity (3 batches); the token cap is
sized for gpt-4o-mini and the cause was not captured. The switch to Flash is proven by configuration and
by 3,464 of 3,464 decision events being `engine=fallback`; the events do not record the
model. Cost was an estimate (about $1.71, ledger tokens at Flash list price); no
generation record was available. Result: swapping the judge to Flash did not change the
picture.

## 4. Older latency sample (other question sets)

From `decision_shadow` rows in four local databases, 2% sampled, 2026-09-27 to
2026-10-11 (older code and rubrics, not the v6 books run), 69 call batches. The judge is
assumed to be gpt-4o-mini (the row does not record the model). Jev p50 is 0.3 to 0.6 s
per call for every kind; overall Jev p50 436 ms against 4,676 ms for the judge
(about 10.7x). Kinds with fewer than 8 calls are anecdotes: rerank (8 calls) 614 ms
against 34,347 ms (56x), ingress (15) 446 against 5,837 (13x), sanitize (21) 351 against
4,772 (14x). These are consistent with the in-flight column in section 1 except
rerank, where the books run is slower.

## 5. Rerankers

Pool replay of 33 labelled items (`docs/benchmarks/rerankers.md`, generated 2026-10-20),
recall@8: Jev 31/33, NVIDIA 27/33, Cohere 26/33, fused order 26/33, BGE 25/33; nDCG@10
0.7056, 0.5564, 0.5872, 0.4895, 0.551. Differences under 2 items are ties; Jev's losses
to each other reranker are 5 to 7 items against 1 win.

The judge as a reranker was added as a script-local row and run on 12 of the labelled items
(35 recorded queries, fused top 40 per query, the engine forced to `fallback_only`; Jev
was re-measured on the same pools):

| Reranker | recall@8 (12 items) | nDCG@10 | p50 ms | p95 ms | $ / 1k queries | cost source |
|---|---|---|---|---|---|---|
| Jev (this run) | 11/12 (0.917) | 0.5433 | 881 | 1,240 | 1.1464 | generation records |
| Judge (gpt-4o-mini) | 10/12 (0.833) | 0.3827 | 47,342 | 164,216 | 6.0601 | generation records |
| Fused order | 10/12 (0.833) | 0.2739 | 0 | 1 | 0 | none |

Judge against Jev: 1 win, 2 losses (`frame-walton`, `plot-red-headed-league`), a tie
under the file's rule. The judge cost 5.3x Jev per query and ran about 54x slower at p50.
It needed batch splitting 6 times (a 40-question batch it could not answer was split in
20 and 10), each split a further billed call. Jev's re-measured $1.146 per 1k queries is
within 1.4% of the published $1.162, which supports the cost method. The 12-item
comparison is small and is not edited into `rerankers.md`.

## What was spent

About $1.69 on the shadow measurement (pilot $0.11, a killed start $0.068, main run
$1.257, rerank step about $0.252, all from generation records), about $3.3 to $3.5 on the
fallback_only books run (estimate), about $1.71 on the Flash probe (estimate).
