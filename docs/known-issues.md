# Known issues

Open defects and process debt that were found but deliberately left for later.
Each item says what's wrong, why it matters, where it lives, and what the
fix is. When you fix one, delete it and put its ID in the commit body.

Logged 2026-09-26, after the UX pass and Gutenberg demo (`ea16d2b..725bbc5`).

**Order:** KI-5 and KI-12 are done (2026-09-30), so KI-6's eval gate is
the next unblocked piece of process debt. KI-1, KI-2 and KI-7 were fixed
in `b600bed`, and KI-3 in the sources-panel merge. KI-8 is independent. Do it
before the next Playwright run.

**Batch A** (`6d9a2ab`, 2026-09-28) shipped answer-first + the greeting
fast path. **Wave 1** (2026-09-29) fixed KI-16, KI-17, KI-18 and removed
the stale KI-4. **C1** (2026-09-30) removed KI-5 and KI-12: `quote-darcy`
passes 3/3 and `make smoke` meets its spec, both because the
proposal-led re-chunking put the Darcy child inside the reranked top 8
(NVIDIA ranks it 3rd on the compound query, 8th/5th on the decomposed
parts) — **so window-level rerank is not needed.** Next: KI-19 (CJK
BM25) with the reranker comparison, then KI-8. KI-6's gate is still
unrun.
**Pending (2026-09-30):** KI-21 (Langfuse host/coverage) and KI-22 (trace
tab + metrics redesign) — independent; KI-21's stage spans build on
KI-22 batch 1. New this round: KI-23 (misleading key/quota failure copy),
KI-24 (eval corpus in the Shared library). **C2** (2026-09-30) closed
KI-25 (abstain no longer cites; `not_in_sources` 0/4 → 3/4) and split its
leftover into KI-26. C2 also closed KI-19: the BM25 index is re-tokenised
with `icu` (migration 0013), which is what makes the CJK lexical leg
return rows (0 → 2478 on a Chinese question). Note that the two CJK
acceptance items already passed before that change — the dead leg was
real but the vector leg was carrying them. KI-28 records the Jev reranker
rejection. **C3** (2026-09-30) closed KI-29 (decline messages rendered in
Turkish) in `68a1b02` and added the reply-language check to the acceptance
scorer in `42267f1`; `b1259b4` pins that a baseline records `answer_rate`
and `p50_our_overhead_ms`, so KI-6's two unverifiable conditions become
checkable once a new baseline is written.
**D4** (2026-10-02) closed the three things standing between KI-6 and a
baseline and **wrote `baseline_fast20.json`** from the median of three
fast20 runs on `692f073`: KI-31's cause was a lookup budget shorter than the
landing tail (`692f073`), acceptance no longer edits `free` (KI-20/23), and the
faithfulness variance is decomposed in the new **KI-32**. Two numbers need the
owner's ruling, both recorded in KI-6 and KI-32 rather than tuned away: the
faithfulness spread is 0.0300, exactly `FAITHFULNESS_DROP`, and run-to-run
`p50_our_overhead_ms` noise (2317–2848 ms, +22.9%) is wider than the gate's 20%
`LATENCY_RISE_FACTOR`. Next: P3's latency work, which is what should move the
overhead number.

---

## KI-6: Graph change merged without the eval gate (process debt)

- **What:** `6b865fc` (the chitchat branch and the `chitchat.md` prompt)
  and `44fe80e` (the model swap) merged to `main` without the TRD §15
  eval gate. CLAUDE.md requires the gate for graph and prompt changes
  from slice 3 on. It was reported as blocked by KI-2. Being blocked
  should have held the merge.
- **Note:** `evals/runner.py` already pins paid models (`gpt-4o-mini` as the
  generator, Haiku as the small model), so the gate doesn't depend on the
  free pool. A run costs cents plus Jev.
- **Fix:** once KI-5 passes, run the 20-item fast subset. Because the
  models changed, record a **new baseline** with before/after numbers
  for faithfulness, abstention accuracy and p50 latency. If faithfulness
  or abstention regress beyond the gate, revert or fix before any further
  graph work.
- **Unblocked (2026-09-30):** KI-5 and KI-12 are both closed, so the
  remaining work here is only the unrecorded baseline plus whatever the
  p50 row below says. `make acceptance` is not the gate, but it now runs
  end to end (23/31) if a cheaper sanity pass is wanted first.
- **Note (2026-09-30, C2): the gate ran three times and the baseline was
  still NOT written.** Two conditions in the dispatch failed, and one could
  not be checked at all. Stored baseline: faithfulness 0.9875,
  context_recall 1.0, abstention 0.25, p50 14384.5 ms, and **no
  `answer_rate` and no `p50_our_overhead_ms`** — which is itself the
  reason two of the conditions are unverifiable.

  | run | items | scored | failed | faithfulness | ctx recall | abstention | answer rate | p50 ms | p50 overhead ms |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | baseline | 20 | – | – | 0.9875 | 1.00 | 0.25 | – | 14384.5 | – |
  | 1 | 20 | 20 | **0** | 0.9868 | 1.00 | **0.00** | 0.9375 | 17306.0 | 11748.5 |
  | 2 | 20 | 20 | **0** | 0.9759 | 1.00 | **0.00** | 0.9375 | 14338.0 | 8457.0 |
  | 3 | 20 | 20 | **0** | 0.9813 | null | **0.25** | 0.9375 | 14878.5 | 10977.5 |

  - **0 errored items: PASS**, all three runs (`failed` 0, `scored` 20).
  - **faithfulness within the gate: PASS.** Worst run 0.9759 against
    0.9875 is a 0.012 drop, inside `FAITHFULNESS_DROP = 0.03`.
  - **our-overhead p50 within the gate: FAIL on run 1.** The stored
    baseline has no `p50_our_overhead_ms`, so `compare` falls back to
    gating total `p50_latency_ms`; run 1's 17306 ms exceeds
    14384.5 × 1.20 = 17261. Runs 2 and 3 pass, so this is at the edge,
    not a clear regression — but "at the edge on one of three" is not a
    pass.
  - **abstention accuracy: FAIL.** `ABSTENTION_DROP_POINTS` is 5.0 and
    runs 1 and 2 score 0.00 against a 0.25 baseline — a 25-point drop.
    Run 3 recovers to exactly 0.25. **Do not write a baseline on a
    metric that swings 0.00 / 0.00 / 0.25.**
  - **answer rate at least the last run's: UNVERIFIABLE.** All three
    runs report 0.9375, but no prior run ever recorded an answer rate —
    it is absent from the stored baseline and from the batch-4 table
    above, so there is nothing to compare against.

  **The abstention spread is the real finding, and 4 items is too few to
  act on.** All four `should_abstain` items in fast20 are English
  AW-2000 spec questions, and the three runs abstained on 0, 0 and 1 of
  them. Ruled out as causes, with measurements rather than argument:
  - *The CJK tokenizer work (item 3).* Those four items are English, and
    the BM25 leg's selectivity for an English question is unchanged by
    it: `paradedb.match(...)` returns 6920 rows where the previous
    `paradedb.parse(..., lenient => true)` returned 6829 — +1.3%, not a
    flood. `lex_limit` is 50, so both were already returning their cap.
  - *The citation change (item 1).* `abstention_accuracy` is computed
    from `run.abstain_event is not None` alone
    (`evals/runner.py:392-394`); it never reads citations.
  - *The Jev reranker (item 4).* Reverted in settings version 137 before
    these three runs; see KI-28.

  **Next step, in order:** (a) add the four abstention items' *and* some
  answerable items to a larger abstention set — 4 items cannot resolve a
  0.00-vs-0.25 question, and widening fast20 is cheaper than
  re-deciding the threshold on n=4; (b) record `answer_rate` and
  `p50_our_overhead_ms` in the stored baseline so the two unverifiable
  conditions become checkable, which means the baseline has to be written
  once by hand from a run whose abstention number is stable; (c) only
  then write a new baseline.
- **(b) is proven done, (c) deliberately not done (2026-09-30, C3).**
  `b1259b4` shows by test that `--baseline` records both fields and
  `compare` gates on both when the stored baseline has them — so the only
  thing missing is the *stored file*, and that is (c). No new baseline was
  written, per the dispatch: the abstention swing above (0.00/0.00/0.25 on
  4 should-abstain items) has to be resolved by (a) first. Also unchanged,
  because no reranker or threshold moved: see KI-28's C3 section.
  Do not lower `ABSTENTION_DROP_POINTS` and do
  not re-baseline the 0.00 rows — that would store an abstention
  regression as normal, which is the mistake this entry already records
  once for latency.
- **(a) done, (c) attempted and blocked again (2026-10-01, D1).** The
  abstention set is widened: acceptance 31 → 41 items (`not_in_sources`
  4 → 14, 4 non-English, each proven absent by zero-hit corpus searches
  before adding) and seed 50 → 60 (`abstain-11..20`), fast20 still 20
  with **8 should-abstain**. Two full Jev acceptance runs (settings
  v142): 36/41 both, identical failures, `sufficient` groups overlap
  (margin −0.06 both runs — see KI-28). Three fast20 gate runs, all
  20 scored / 0 failed:

  | run | faithfulness | ctx recall | abstention (of 8) | answer rate | p50 ms | p50 overhead ms |
  | --- | --- | --- | --- | --- | --- | --- |
  | 1 | 0.9882 | 1.00 | 0.125 (1) | 0.9167 | 18288 | null |
  | 2 | 0.9492 | 0.67 | 0.000 (0) | 0.9167 | 15001.5 | null |
  | 3 | 0.9761 | 0.98 | 0.125 (1) | 0.9167 | 15229 | null |

  **Baseline still NOT written** — two of the four dispatch conditions
  failed:
  - *Faithfulness:* run 2's 0.9492 is a 0.0383 drop from the stored
    0.9875, past `FAITHFULNESS_DROP` 0.03. (context_recall also swings
    1.00 / 0.67 / 0.98 — judge noise worth its own look.)
  - *Latency/overhead:* `p50_our_overhead_ms` is **null in all three
    runs** — only 3–4 of 20 items reached complete attribution inside
    `attribution.py`'s 8×3 s polling budget, and `aggregate()` reports
    null unless every item is attributed. A written baseline would have
    carried null, defeating (b). On the total-p50 fallback, run 1's
    18288 ms exceeds the 17261 ceiling (+6%), partly compositional: the
    new should-abstain items take 17–26 s when they fail to abstain.
  - *Passed:* 0 errored items in every run; abstention spread exactly
    0.125 (counts 1/0/1 of 8), meeting the ≤ 0.125 bar — but that bar
    being met on 0–1 correct abstentions of 8 says the should-abstain
    pipeline, not the metric, is the open problem (the acceptance runs
    show the same: 4 of 14 hallucinate, KI-26's mechanism).
  **Next:** fix `attribution.py` polling so overhead is attributable
  (else the fast20 gate can never carry `p50_our_overhead_ms`), then
  KI-26's `sufficient_min_rerank` gate, then re-attempt the baseline.
- **(2026-10-01, D2: the harness was the blocker; baseline still waits
  for D3).** All three `Next` items are done on `fix/darcy` — KI-30
  (2a/2b/2c: documents-only runs, the judge parser, and overhead
  attribution incl. Jev generation ids) and KI-26's relevance gate
  (closed above) — and none of D1's three fast20 rows are valid
  measurements of the product: 16 of 20 items were answered from the web
  (2a), context precision/recall were unparsed on 17–19 of 20 (2b), and
  `p50_our_overhead_ms` was null because every item had to be fully
  attributed (2c). **No baseline was written, deliberately:** the
  baseline has to come from runs on the fixed harness, which is D3's
  acceptance + fast20 sequence, after the owner's review. Do not
  re-baseline against the numbers above.

- **(2026-10-01, D3 item 4: measured on the fixed harness, and the baseline
  is STILL not written — two of six conditions failed.)** Three fast20 runs
  via `make eval-gate-local`, each against its own fresh ephemeral database
  (KI-24's half-fix, so the corpus is the seed corpus only), commit
  `5bb3986`, 0 errored items in all three:

  | run | faithfulness | ctx recall | abstention (of 8) | answer rate | p50 ms | p50 overhead ms | overhead attributed | judge coverage |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | 1 | 0.9707 | 0.96 | 0.875 (7) | 0.9167 | 8665.5 | 2344.0 | 17/20 (85%) | not captured |
  | 2 | 0.9250 | 0.89 | 0.875 (7) | 0.9167 | 8467.0 | 2551.0 | 18/20 (90%) | not captured |
  | 3 | 0.9771 | 0.86 | 0.875 (7) | 0.9167 | 8754.5 | 2691.5 | 16/20 (80%) | 19/20 (95%) |

  **PASS:** 0 errored items (all three, and this is the first clean set of
  three on the fixed harness); abstention spread **0.000** (0.875 in all
  three, 7 of 8 every time — against 0.125/0.000/0.125 in D1 and
  0.00/0.00/0.25 in C2); answer-rate spread **0.000** (0.9167 every run,
  and `answer_rate` is now recorded); judge coverage 95% on run 3, exactly
  at the bar. **FAIL:**
  - *Faithfulness spread 0.0521 > 0.03* (0.9250 in run 2 against 0.9771 in
    run 3). The variance is concentrated, not spread: on run 3 two items carry
    it — `multihop-05` (AW-2000-XE pairing under firmware 3.1.0) at 0.667
    and `lookup-01` (battery life) at 0.875 — with the other 18 at 1.0.
    `context_recall` swings 0.96 / 0.89 / 0.86, and per item it is 0.0 on
    `abstain-10`, 0.5 on both `conflict` items, 0.6 on `multihop-02`. So one
    or two borderline items decide the metric at n=20.
  - *Overhead attributed on only 80–90% of items, against a ≥ 90% bar.*
    D1's blocker is much improved (3–4 of 20 → 16–18 of 20) but not closed.
    The mechanism is unchanged and is by design: `attribution.py` records
    `our_overhead_ms` only when `Attribution.complete`, i.e. **every**
    generation id on that item resolved to a stats record inside the
    8 × 3 s budget. On run 3 the four uncovered items *do* carry a
    `provider_ms` (3481 / 6202 / 3622 / 3472 ms) — so it is not that the
    calls went unrecorded, it is that one generation id among them never
    came back, which discards the item's whole figure. See **KI-31**.

  Per the dispatch, a baseline is written only when all six hold, so none
  was written. `baseline_fast20.json` still carries D1-era numbers with no
  `models` key, and `evals.gate` now *refuses* to compare against it by name
  — which is why all three runs exited 1 on the model check. That refusal is
  correct, not a regression to work around: **do not relax it to make the
  gate green, and do not re-baseline against these rows until KI-31 and the
  faithfulness variance are resolved.**
- **BASELINE WRITTEN (2026-10-02, D4 item 4, `2f9f8f1` and `a1c3d55`).** Both
  blockers are closed — KI-31's cause was a lookup budget shorter than the
  landing tail (`692f073`), and the variance source is named below — so all six
  conditions hold on commit `692f073` and the baseline is written from the
  **median** of three `make eval-gate-local` runs, each on its own fresh
  ephemeral database, 0 errored items in all three:

  | run | faithfulness | ctx recall | abstention (of 8) | answer rate | p50 ms | p50 overhead ms | attributed | judge coverage |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | 1 | 0.96833 | 0.8875 | 0.875 (7) | 0.9167 | 8548.5 | 2317.5 | 20/20 | 20/20 |
  | 2 | 0.98000 | 0.8982 | 0.875 (7) | 0.9167 | 9548.5 | 2632.5 | 20/20 | 20/20 |
  | 3 | 0.95000 | 0.8825 | 0.875 (7) | 0.9167 | 9531.5 | 2348.5 | 20/20 | 20/20 |
  | **median (1)** | **0.96833** | **0.8875** | **0.875** | **0.9167** | **8548.5** | **2317.5** | | |

  | condition | limit | result | |
  | --- | --- | --- | --- |
  | errored items | 0 | 0, 0, 0 | **PASS** |
  | abstention spread | ≤ 0.125 | **0.000** | **PASS** |
  | answer-rate spread | ≤ 0.05 | **0.000** | **PASS** |
  | judge coverage | ≥ 95% | **100%** (20/20, all three) | **PASS** |
  | faithfulness spread | ≤ 0.03 | **0.0300** | **PASS, at the bar exactly** |
  | overhead attributed | ≥ 90% of items | **100%** (20/20, all three) | **PASS** |

  Per-stage p50 (ms), all three runs — this is what P3 starts from:

  | stage | run 1 | run 2 | run 3 |
  | --- | --- | --- | --- |
  | retrieve | 4083.5 | 4427.0 | 4668.0 |
  | review | 8139.5 | 7859.0 | 6628.0 |
  | generate | 1095.5 | 1113.0 | 981.5 |
  | ingress+rewrite | 1530.5 | 1504.5 | 1238.5 |
  | rerank | 396.5 | 449.0 | 405.5 |
  | sanitize | 382.5 | 436.0 | 343.0 |
  | sufficient | 419.5 | 377.0 | 341.0 |
  | provider_ms (attributed) | 6367.0 | 6473.0 | 6956.0 |
  | our_overhead_ms | 2317.5 | 2632.5 | 2348.5 |

  `retrieve` at 4.1–4.7 s is the largest stage inside the answer path, and it
  runs *before* generation, so it is nearly all of the pre-first-token budget —
  that is where P3 should start. `review` is post-hoc and outside the path the
  user waits on, which is why it can exceed the total's own p50 contributors.

  **Two things the owner must decide, neither of which I changed.**

  1. **The faithfulness spread is 0.0300 exactly — the bar, with zero margin.**
     It passes, and it is not a rounding accident: computed in exact rational
     arithmetic the three means are 29/30·…, 49/50 and 19/20, so the spread is
     exactly 3/100. One more run at 0.95 would make it 0.0333 and fail. The
     gate's `FAITHFULNESS_DROP` is 0.03 and TRD §15 owns it; **do not read
     this as "the variance is resolved".** It is inside the bar by one item.
  2. **`p50_our_overhead_ms` is the number that will flap.** A fourth
     confirmation run measured **2848 ms** against a 2317.5 baseline — a 22.9%
     rise, past the gate's 20% `LATENCY_RISE_FACTOR` — while its faithfulness
     (0.9575) passed comfortably. The three baseline runs span 2317.5–2632.5
     (+13.6%) and the fourth is 2848: run-to-run overhead noise is larger than
     the factor the gate allows. Choosing the *highest* of the three baseline
     runs would have hidden it, which is why the median was used and this is
     being reported instead. P3's latency work is what should move this; the
     alternative is the owner's call on `LATENCY_RISE_FACTOR`, not mine.

- **Both rulings landed: the gate's limits are widened, deliberately
  (2026-10-02, owner decisions A6 and A7).** Item 2 above is answered by A6,
  and the abstention arithmetic by A7. `evals/gate.py`, `evals/runner.py`,
  TRD §15 and `tests/evals/test_gate_thresholds.py` change together.
  - **A6 — `OVERHEAD_RISE_FACTOR` 1.20 → 1.35, on `p50_our_overhead_ms`
    only.** The total-latency fallback keeps `LATENCY_RISE_FACTOR = 1.20`, and
    the two are now chosen together with the key they apply to, so the failure
    message names the factor that actually ran — it used to hardcode "20%",
    naming a limit the gate does not apply. *Reset at P3 exit:* re-measure
    **≥ 5 fast20 runs** and set the factor to `max(1.20, 1 + 2 × spread)` on
    the observed run-to-run spread of `p50_our_overhead_ms`.
  - **A7 — abstention accuracy and answer rate are gated in items, failing at
    ≥ 2 items with a 1-item warning.** fast20 holds **8 should-abstain and 12
    answerable** items, so one flip is **12.5** and **8.3** points against a
    5-point tolerance: the old gate failed on a single item. `aggregate()` now
    records `should_abstain_correct` and `answerable_answered`, and the gate
    compares those counts. *Reset at P1b*, when per-corpus resolution makes
    percentage points meaningful again.
  - **These are relaxations, made to stop noise failing the gate. They are not
    evidence that the product improved** — nothing about the product was
    measured to justify them, and both rest on the spread numbers already
    recorded in this entry. `FAITHFULNESS_DROP` is untouched at **0.03** and
    remains the gate's strictest condition; item 1 above is still open and is
    still exactly at the bar.
  - **Consequence to action now:** `baseline_fast20.json` predates the two
    counts, so the next gate run reports those two metrics **UNVERIFIED** — a
    warning, not a pass, and not a failure, since an old baseline is not a
    regression. They become checkable again on the next `--baseline` run, which
    this entry already needs. The counts are deliberately **not** back-filled by
    hand from the stored rates: those rates are a median of three runs and the
    denominator is not in the file, so any number written there would be
    invented.
  - **The honest cost of A7, stated rather than buried:** a baseline that
    predates the two counts can no longer catch *any* run-level failure in
    those two metrics — including the abstain-everything case the answer-rate
    counterweight exists for, which the old rate comparison did catch. It is
    reported UNVERIFIED instead, so until the next `--baseline` run the gate
    is **blind** to both, not merely noisy on them. Rewriting the baseline
    from runs measured on this code closes it; until then, treat a green
    abstention/answer-rate row in CI as unchecked rather than as passing.
- **What did improve, and is worth not losing.** `context_recall` is
  non-null on every run (0.86–0.96) against C2's `null` and D1's 17–19 of 20
  null — the judge parser fix (KI-30 2b) is holding. `abstention_accuracy`
  is the same 0.875 in all three runs, where it used to swing across three
  values; and the six AW-2000 near-misses that replaced the book twins in
  fast20 are the reason it is a real number (D1's 0.125 meant 1 of 8). The
  new fast20 composition is doing its job.
- **`abstain-10` may be mislabelled, and the owner should decide.** It is
  the single item that answers in all three runs ("Can the AW-2000-XE run the
  enterprise management protocol over 5 GHz Wi-Fi?"). The corpus says
  *"All models operate on 2.4 GHz"*, so answering "no" is arguably correct
  and grounded — it scores faithfulness 1.0 with `context_recall` **0.0**,
  which is the tell: the reviewer found the answer supported, the judge found
  it unsupported. It is a should-abstain item by label, not by fact. D3 did
  not retune it (no item is tuned against the pipeline), so it stays and the
  owner decides whether the label or the question changes.

- **Note (2026-09-27, batch 4):** the gate **ran** — `python -m evals.gate`
  exited 0, "eval gate passed" — but **no new baseline was written**, for
  two reasons. Both are in the numbers.

  Three fast20 runs, same commit, against the stored
  `baseline_fast20.json` (faithfulness 0.9875, context_recall 1.0,
  abstention 0.25, p50 14384.5 ms):

  | run | persisted | failed | faithfulness | context_recall | abstention | p50 ms |
  | --- | --- | --- | --- | --- | --- | --- |
  | 1 | 19/20 | 1 | 0.9868 | 1.00 | 0.75 | 16435 |
  | 2 (gate) | 12/20 | 8 | 1.0000 | null | 0.50 | 6656 |
  | 3 | 18/20 | 2 | 1.0000 | 1.00 | 0.75 | 20447 |

  **1. p50 latency regressed past the gate.** Run 3, the most complete
  run, is 20447 ms against a 14384.5 ms baseline: **+42%**, where the gate
  allows +20%. The likely cause is this batch's own change — the
  sufficiency evidence budget went from 2,000 to up to 4,000 characters,
  roughly doubling the tokens in the `sufficient` Noul, which every retry
  re-sends. Run 1 (+14%) is the same effect measured smaller. Reporting,
  not fixing, and **not lowering `LATENCY_RISE_FACTOR`**.

  **2. The harness cannot measure latency while items fail.**
  `run_eval`'s `except` branch builds an `EvalResult` and appends it to
  `results`, but never adds it to a session — so a failed item is never
  persisted *and* still enters `aggregate()` with `latency_ms=0`,
  `faithfulness=None`, `abstained=None`. A zero pulls the median down, so
  every p50 above is an **under**-estimate; `abstained=None` counts as
  "did not abstain", so abstention accuracy is an under-estimate too.
  The 3× spread across the three p50 values is that bias varying with how
  many items died.

  The failures are environmental, not a product regression: all 8 in run 2
  were `asyncpg.exceptions.CannotConnectNowError` /
  `ConnectionDoesNotExistError`, raised on the *first* statement of
  `_run_item` (the pool was already exhausted). `db/session.py` builds the
  engine with SQLAlchemy defaults (`pool_size=5`, `max_overflow=10`,
  `pool_pre_ping=True`) and four Compose services share one Postgres, so
  the runner can find no free connection.

  **What changed since the last baseline:** generator/small models
  (`gpt-4o-mini` / Haiku 4.5), sanitizer moved after rerank onto the
  top-k only, NVIDIA rerank (was fused-order fallback — the old baseline
  was recorded with no rerank provider), sufficiency evidence now leads
  with each matched passage and is budgeted per source, the retry gate and
  the abstention gate split into `sufficient_retry` / `sufficient_abstain`,
  the Reviewer computes faithfulness (the interim judge is out of the
  gate), and compare runs retrieve per named entity with a balanced
  rerank share.

  **Next step, in order:** (a) fix the two harness bugs — persist the
  unscored fallback, and make `aggregate` skip unscored items instead of
  counting them as 0 ms; (b) give the runner its own pool or raise
  `pool_size` so items stop dying; (c) then re-run and *only then* write
  `baseline_fast20.json`. Do not baseline the table above: it would store
  a +42% latency regression as normal and make every later gate pass.

  **Cost of the first real gate run:** $0.26 of OpenRouter credit for
  three fast20 runs plus one `make smoke` — about **$0.09 per fast20
  run**, matching this note's "costs cents plus Jev".
- **Note (2026-09-27, batch 5, fixed in `faad4a2`):** both next-step bugs are
  fixed. A failed item is now persisted with a new `eval_results.error`
  column, excluded from every aggregate and every latency percentile, counted
  as `failed`, and the gate refuses a run that lost any item. `faad4a2` also
  **overturns the pool diagnosis in this entry**: the errors were not pool
  exhaustion, so nothing was raised. Measured —
  - `max_connections=100` with **19** client backends connected. pg was not
    the constraint.
  - A SQLAlchemy pool that is exhausted raises `TimeoutError: QueuePool limit
    of size N overflow M reached`, never an asyncpg error. Reproduced with
    `pool_size=1, max_overflow=0`.
  - The db log has the actual cause at `2026-09-27 07:24:47`:
    `server process (PID 779029) exited with exit code 2` →
    `terminating any other active server processes` →
    `all server processes terminated; reinitializing` →
    `the database system is not yet accepting connections`, ~30 s of it.
    A ParadeDB backend crash, which drops every client connection and refuses
    new ones. `CannotConnectNowError` (the database is in recovery) and
    `ConnectionDoesNotExistError` (a killed backend's prepared statement) are
    exactly what that window produces — and the burst shape of 8 items dying
    at once is that window, not gradual pool growth.
  The harness now runs on its own small pool and retries a transient DB
  error rather than losing the item. The retry cannot hide a product defect:
  an item that still fails is persisted and fails the gate.
- **Note (2026-09-27, batch 5):** **still no baseline, and this time the
  harness is trustworthy** — 6 runs, 120 items, **0 failed**, so every number
  below is a real measurement. The gate is red on latency in all six, so
  baselining would store a +52% to +70% regression as normal and make every
  later gate pass. Current p50 sits in **21815–24465 ms** against a stored
  baseline of 14384.5 ms; the gate allows +20% (17261 ms).

  | variant | p50 ms | faith | abstain | failed |
  | --- | --- | --- | --- | --- |
  | baseline (stored) | 14384.5 | 0.9875 | 0.25 | — |
  | 500 chars/src r1 | 22632.5 | 1.0000 | 0.50 | 0 |
  | 500 chars/src r2 | 24088.0 | 0.9875 | 0.75 | 0 |
  | 500 chars/src r3 | 24465.5 | 0.9875 | 0.50 | 0 |
  | 250 chars/src r1 | 24016.0 | 1.0000 | 1.00 | 0 |
  | 250 chars/src r2 | 21815.0 | 1.0000 | 1.00 | 0 |
  | 250 chars/src r3 | 22822.0 | 0.9875 | 1.00 | 0 |

  **The evidence-budget theory for the regression is dead** (see the commit
  that sets it to 250): halving the budget moves median p50 by 5.3%, less than
  the within-variant spread. Something else in this batch's changes added
  ~8 s per item, and it is not yet identified. Suspects, in the order worth
  checking:
  1. **Sanitize after rerank** (`4b0c878`, KI-11) puts a DecisionEngine call
     on every one of the top-k chunks instead of a cheaper layer, and NVIDIA
     rerank is a network hop per run on top.
  2. **The Reviewer** (`review_answer`) runs claim extraction *and*
     verification after generation, on the small model, every run — the
     `abstention_accuracy` 0.25 → 1.00 shift suggests the run is spending its
     time deciding, not generating.
  3. Per-item **OpenRouter embedding** calls: one per query variant, and the
     multi-part fix adds more variants for those items.

  Note the faithfulness comparison between the two budget variants is
  **confounded** and should not be read as 250 being better:
  `evals/runner.py` sets `faithfulness = 1.0` for any abstention, so a
  variant that abstains more scores higher faithfulness without answering more
  questions. Abstention accuracy is 4 Bernoulli trials in fast20, and the
  baseline's own 0.25 has been swinging ±25 points between runs. Settling
  this needs a metric that is not defined in terms of the outcome it measures
  — that is a change to what the gate is, so it wants its own decision.
-   **Rule going forward:** no graph, prompt or model change lands on
  `main` until the gate has run green.
- **Note (2026-09-28, batch 6):** the gate metric itself is fixed and the
  latency is finally attributed. `answer_rate` is a fourth gate metric
  (TRD §15 amended): an abstention scores faithfulness 1.0, so a run that
  abstains on everything reports perfect faithfulness *and* perfect
  abstention accuracy. Measured on the batch-6 runs it is **0.50–0.56** —
  the pipeline answers barely half the answerable items, which is what the
  faithfulness column was hiding.

  `eval_results.stage_ms` (migration 0012) now stores the per-stage
  breakdown, and two measurement bugs that under-reported are fixed:
  `make_step_timer` overwrote a repeated label, so the Auto retry loop's
  second and third `retrieve`/`sanitize` passes were dropped from the
  totals; and `rerank`, the `sufficient` decision and the Reviewer were
  never timed in the eval path at all.

  Three fast20 runs at the current code:

  | run | p50 ms | faith | abstain | answer rate | failed |
  | --- | --- | --- | --- | --- | --- |
  | baseline (slice 6) | 14384.5 | 0.9875 | 0.25 | — | — |
  | `01a0e36d` | 22402.0 | 1.0000 | 0.75 | — | 1 |
  | `01a0e377` | 21028.5 | 0.9889 | 0.50 | 0.5625 | 0 |
  | `01a0e380` | 21509.5 | 1.0000 | 0.75 | 0.5000 | 0 |

  Per-stage p50 (19–20 scored items per run, 11 of them abstentions):

  | stage | n | p50 ms | p95 ms |
  | --- | --- | --- | --- |
  | retrieve | 20 | 5059 | 10679 |
  | rerank | 20 | 3756 | 4976 |
  | review | 11 | 1773 | 4384 |
  | ingress+rewrite | 20 | 1066 | 2223 |
  | sanitize | 20 | 974 | 1327 |
  | sufficient | 20 | 968 | 1462 |
  | generate | 20 | 696 | 1989 |

  Sum of stages p50 13236 ms against a measured total p50 of 22402 ms:
  **a 5059 ms residual is still unattributed.** That residual is the reason
  no re-baseline is written — "every second explained as intended work"
  cannot be claimed while a quarter of the item is unaccounted for.

  **The three suspects from batch 5 are settled.** The evidence budget is
  not the driver (already halved in `bd34057`, and the stage table shows
  `sufficient` at 968 ms p50). The Reviewer is 1773 ms and only runs on
  non-abstentions. The dominant cost is `rerank` at 3756 ms p50, which is a
  **network hop per retry attempt** — the slice-6 baseline was recorded
  with no rerank provider at all, where this step was free.

  **Nemotron Ultra is not in the eval path.** The prompt suspected
  eval-path roles resolving to the `model_roles` table. They do not: the
  harness sets no usage context, so `providers.llm._resolved_model`
  returns the requested model unchanged and `model_roles` is never read.
  Generator is `gpt-4o-mini`, the small role is Haiku 4.5, the decision
  layer is Jev with `config.fallback_model` (Nemotron 3 **Super**, not
  Ultra). There was nothing to pin.

  **TTFT (PRD CH-5) is violated by 6x.** Measured from `run_events` on the
  `make smoke` runs, first `answer.delta` minus `runs.created_at`, Auto
  single-hop: **18826 ms** against a < 3 s target. TTFT is the whole
  prepare phase — ingress+rewrite, retrieve, rerank, sanitize, sufficiency
  — so it inherits the rerank cost directly.


## KI-15: `tests/chats/test_chats_runs.py` hangs when its tests run in sequence

- **What:** running the file as a whole hangs indefinitely partway through;
  each of the affected tests passes in 4–5 s when run alone. Reproduced on
  `6670475` with the batch-5 work stashed, so it predates it. A full
  `pytest -q` also hung once and passed 263/263 in 52 s another time — it is
  order- or timing-dependent, not deterministic.
- **Where:** `tests/chats/test_chats_runs.py`, hanging somewhere around
  `test_first_run_sets_instant_title_then_refines` /
  `test_title_llm_failure_keeps_instant_title`. The title-refinement path
  (`graph/chat_title.py`, dispatched as a background task by
  `graph/runner.py`) is the first suspect: `pyproject.toml` pins
  `asyncio_default_test_loop_scope = "session"`, so a task left pending by one
  test can still be running on the shared loop when the next test's
  `server` fixture (a real uvicorn socket) takes over.
- **Impact:** a hung suite cannot report a regression, so it can only ever
  look green. It burns an agent's whole time box.
- **Fix:** make every test that starts a run await the title task, and give
  the title-refinement task an explicit handle the test can join or cancel.
  Bisect by running the file with `-p no:randomly` and the suspect tests
  paired, which narrows it in minutes.
- **Done when:** the file runs 40+ times in a row with no hang.
- **Note (2026-09-28, batch 6): the title-refinement hypothesis is wrong,
  the hang did not reproduce, and a different real leak was found instead.**
  `graph/runner.py:493` awaits `refine_title` inline — there is no
  background title task, so the suspect in the note above cannot be it.
  The file passed **10 consecutive runs**, ~25 s each, plus 101 tests across
  `tests/chats/`, `tests/graph/` and `tests/evals/`. Nothing hung.

  What *is* real, and is proven: `_finish_answer` publishes `run.completed`
  while `score_run_async` and `_settle_after_scoring` are still pending and
  unowned — `_active_tasks` only held the already-finished `execute_run`.
  A probe after `run.completed` reached the client listed both as live. The
  product consequence stands on its own: `main.lifespan` never awaits them,
  so a shutdown mid-run leaves the `usage_ledger` row `reserved` forever
  (TRD §14). `9840f95` tracks and drains that work at both lifecycle
  boundaries and asserts the row reaches `settled`.

  **This entry stays open.** The leak is fixed; the reported hang is not
  explained and not reproduced. If it returns, the drain is no longer a
  candidate — look at what else is pending when it stalls, and dump it.

- **Not the cause of the red `ci` (2026-10-01, D3 item 1).** The `ci` run
  that was red on `main` (`36723227681`) failed
  `test_chats_runs.py` three times and
  `test_cache_and_web.py` once, and it is worth recording *why*, because the
  file is a suspect here and was not: the log shows `litellm` POSTing to
  `https://openrouter.ai/api/v1/chat/completions` and receiving
  `401 {"error":{"message":"No cookie auth credentials found"}}`. Those four
  tests reached a live provider, which `testing.md` forbids. `main` had no key
  to blank — `git show fae47a5:apps/api/tests/conftest.py` contains no
  `OPENROUTER_API_KEY` — and locally `.env` supplies a real key, so the call
  succeeded and the test passed. Nothing hung. `060845e` blanked the key on
  `fix/darcy`; re-running the same two files with every outbound HTTPS request
  proxied to a closed port and only localhost exempt passes 22/22, so the
  branch's suite makes no live provider call. This entry is unchanged by D3:
  the hang is still unexplained, and 467 passed in 50 s on the D3 tree.

## KI-8: Six Playwright specs drive live LLM runs

- **What:** `abstain`, `suggestions`, `cancel-mid-stream`,
  `decision-layer`, `metrics` and `citations` specs import
  `e2e/support/live.ts` and start real runs. `docs/conventions/playwright.md`
  says streaming UI specs replay recorded SSE fixtures
  (`e2e/fixtures/runs/*.json`) through the `ENV=test` replay route.
- **Impact:** e2e burns rate limit and budget, and is slow and flaky on
  provider latency.
- **Fix:** move each spec whose assertions are about UI (chip colours,
  hold state, trace rendering, metrics, suggestions, abstain actions,
  cancel) to fixture replay, recording a fixture from one real run where
  none exists. Anything that must hit the real stack gets tagged `@live`
  and is excluded by default (`grepInvert` in `playwright.config.ts`), and
  is run manually before a release.
- **Done when:** a default `playwright test` run makes zero LLM calls.
  Assert this by checking that the provider usage ledger is unchanged
  across the run.
- **Note (2026-09-27, batch 3 — xfail):** the documented `ENV=test`
  fixture-replay route does not exist in the API, and only `basic-stream.json`
  exists. The six specs still call `startSeededRun`, which posts real runs.
  Do not hide them with `grepInvert`: add the test-only replay route, record
  one raw SSE fixture per UI scenario, then assert an unchanged
  `usage_ledger` around the default suite.

## KI-20: OpenRouter account credit is nearly spent (key cap lifted)

**Status: live calls work again; the account balance is now the binding
constraint.** Raised 2026-09-30.

- The key cap was raised to **$120/monthly** (`GET /api/v1/key` →
  `limit: 120`, `limit_remaining: 102.66`, `usage_monthly: 17.34`), so
  the 403s (`Key limit exceeded (total limit)`) are gone and Jev, the
  fallback LLM and embeddings all answer 200 again.
- **What binds now is the account balance:** `GET /api/v1/credits` →
  `total_credits: 105`, `total_usage: 100.03` on 2026-09-29, i.e. **~$4.97
  left**, and ~$4.42 after this round's measurement. Check it before each
  live run; stop below $3.
- The 34 `status='failed'` documents from the 403 window are **gone** —
  they were all in the duplicate-test-upload categories, deleted by
  `scripts/cleanup_test_data.py` (documents 192 → 21). Nothing to
  re-queue.
- The four live-provider leaks the cap exposed are **fixed** (`060845e`):
  the post-delivery review/suggestions/output guard in
  `tests/chats/test_chats_runs.py` are faked at the `graph.runner`
  boundary, the pin test now takes the existing `embed_calls` fixture, and
  `tests/conftest.py` blanks `OPENROUTER_API_KEY` alongside the Cohere,
  NVIDIA, Tavily and Brave keys. Full pytest (311) passes with every
  provider key blank, so a future unfaked seam fails offline instead of
  spending money.
- **Unrelated but found while measuring:** a 31-item `make acceptance` run
  costs ~310k quota credits and the free plan's 5h window is 200k, so a
  full run 429s (`quota_exceeded`) at ~item 19. The local plan limit was
  raised for the measurement run and restored after; the harness should
  either use a per-user override or split the set. Logged as part of
  KI-23's fix.

## KI-21: Langfuse likely receives nothing; Jev and stages untraced

**Status: pending** (logged 2026-09-30, not yet verified against the
Langfuse dashboard; if the JP project is empty, this is the cause).

- **Note (2026-10-01, D2):** the fast20-era LiteLLM callback warnings are
  confirmed present in the live stack: 1374 `Langfuse trace_id mismatch:
  set , but langfuse returned <uuid>` warnings in `veriforge-api-1` logs
  (0 in worker-light) — the "set ," shows litellm passing an *empty*
  intended trace id. Logged here per the D2 dispatch; **not fixed** —
  this KI's existing host/keys diagnosis is the first thing to check
  before touching the callback.

- **Host never reaches the SDK.** `.env` sets
  `LANGFUSE_BASE_URL="https://jp.cloud.langfuse.com"`, but `config.py`
  reads only the two keys, `compose.yaml` forwards only the two keys
  (api/worker services, lines ~45/78/106), and the pinned SDK
  (`langfuse<3`) reads `LANGFUSE_HOST`, not `LANGFUSE_BASE_URL`. The SDK
  falls back to the EU default, where the JP keys don't authenticate.
  Push failures are log-only (`graph/async_scoring.py:74`), so it fails
  silently. Fix: `langfuse_host` in `config.py`, export as
  `LANGFUSE_HOST` in `_configure_langfuse` (`providers/llm.py:174`) and
  in `async_scoring.py`, forward it in `compose.yaml`, add to
  `.env.example`.
- **Jev calls aren't traced.** `decisions/jev.py` uses raw `httpx`, not
  LiteLLM, so only fallback decisions appear. Fix: `DecisionEngine`
  records each call as a Langfuse span/generation under the run trace.
- **No stage spans.** TRD §15 promises node-level spans; today only
  LLM generations (LiteLLM callback, grouped by `trace_id=run_id`) and
  post-hoc scores land. Fix: `make_step_timer` (`graph/timing.py`)
  opens a span per stage — every mode's stages already pass through it
  (after KI-22 adds the missing ones).
- **Auto mode publishes no `step.*` events either (2026-10-01, D2
  finding).** `prepare_auto_run` takes a `publish` argument and
  `make_step_timer` publishes through it, but `graph/runner.py` calls
  `prepare_auto_run` **without** `publish`, so the argument is `None` in
  production and no `step.started`/`step.completed` event reaches
  `run_events` — the same gap as Fast mode, one layer up, and the cause
  of it. Latency-by-stage still lands in `runs.metrics` (D2 read it back
  from the DB), so only the trace is affected. Found while publishing
  KI-26's `relevance` decision, which had to be published from the
  runner instead. Not fixed in D2: emitting step events changes the SSE
  stream for every subscriber, which is KI-22's batch 1 to schedule.
- UI keeps reading Postgres only (TRD §3: "UI never reads Langfuse").

## KI-22: Trace tab shows mostly Jev calls; Metrics missing quality detail

**Status: pending** (design agreed 2026-09-30, not dispatched).

**Problem.** The Trace tab renders `step.*` events as a small flat list
and Jev decisions as a separate, much longer timeline
(`apps/web/src/features/trace/components/TracePanel.tsx:166-176`), so it
reads as "just Jev calls". Step coverage also has holes:
- Fast mode emits no `step.*` events — it writes `rewrite`/`retrieve`/
  `generate` straight into `latency_ms` (`graph/fast.py:195`, `:225`).
- `generate` and `review` appear in Metrics' latency but never as steps,
  in any mode.

**Batch 1 — backend step coverage.** Route Fast's rewrite/retrieve/
generate and every mode's generate/review through `_step`
(`make_step_timer`). Ensure every `Decision` carries `stage`. Test: every
mode emits started/completed per stage and `latency_ms` keys match step
labels. Graph change → eval gate before merge.

**Batch 2 — stage timeline (Trace tab).** New `StageTimeline` replaces
`StepRow` + standalone `DecisionTimeline` in the Trace tab: one row per
stage (status dot, duration, bar scaled to run total, live while
streaming); Jev decisions nest under their stage by `stage`, collapsed
(unmatched → "other"); retries shown as `retrieve ×2`, summed like
`latency_ms`. Verify replayed past runs (`ChatView.tsx:82`) show steps.
No new SSE event types.

**Batch 3 — Metrics additions.** Keep "Latency by stage" (not
redundant: trace = order/why, metrics = where time went; zero cost),
sorted by duration desc. Add:
- **Citation precision** — computed in `ReviewScores`
  (`graph/review.py:55`) but dropped at `graph/runner.py:536`; add field
  to `Metrics` (`schemas/events.py:64`), regenerate TS.
- **Review breakdown** — supported/partial/unsupported claim counts from
  `run.claims` (frontend only).
- **Retrieval/rerank funnel** — retrieved → reranked → kept (sanitizer
  dropped) → cited; rerank top/median; frontend only from chunk scores.
- **Context use** (cited ÷ kept) as a labelled *proxy* — true context
  precision needs ground truth or a judge call, eval-only.
- Fast mode: show "not run in Fast" for rerank/review, not blanks.
  Greeting/abstain: "no factual claims", not faithfulness 1.0
  (`review.py:92`).

No extra model calls; only citation precision touches the schema.

## KI-23: A key or quota failure tells the user to "try again"

Logged 2026-09-30, measured twice this round (the KI-20 key cap, and the
5h-quota 429 that killed the acceptance run at item 19).

- **What:** every terminal failure the run can't fix lands on the same
  string, "The run could not finish. Try again."
  (`apps/web/src/features/chat/pages/ChatView.tsx:20`,
  `runFailureMessage`), which only special-cases the two web-search codes.
  A provider key limit (403), an account-balance exhaustion and the
  app's own `quota_exceeded` 429 all say the same thing — and for all
  three, retrying cannot help.
- **Why it matters:** it sends the user into a retry loop that spends
  nothing and succeeds never, and it hides a self-inflicted outage
  (an exhausted key is an operator problem, not a user problem).
- **Fix:** carry a real error code end to end and give each one its own
  copy — at minimum `provider_quota_exhausted` ("Our model provider is
  out of credit. Nothing will run until it's topped up; your chats and
  documents are fine.") and `provider_auth_failed`. The API side is
  `graph/runner.py:961`, where a provider exception collapses to
  `error_code="run_error"`; catch the provider exceptions there and
  publish the specific code.
- **Also in scope:** the admin page should show the key's **remaining
  limit**, not just configured plans. Today the only way to learn the
  OpenRouter key was capped is to see every run fail (`GET
  /api/v1/key` → `limit_remaining`). Show that number in admin and treat
  it as the leading indicator for this whole class of failure.
- **Harness note:** `make acceptance` (31 items, ~310k quota credits)
  exceeds the free plan's 200k/5h window, so the measurement run needs a
  per-user quota override (`credits_5h` override on the acceptance user)
  or the set must be split. Done by hand on 2026-09-30: plan limit
  raised for the run, then restored. C3 repeated it: `plans.credits_5h`
  for `free` went 200000 → 5000000 for four consecutive runs and back to
  200000 after.
- **The 429 is ours, not OpenRouter's (C3).** The `quota_exceeded` that
  killed C2's acceptance run comes from **Veriforge's own local plan
  limit** — `quota/service.py::_limits` resolves `credits_5h` from the
  user's `plans` row (or a `user_quota_overrides` row) and the gate
  rejects the run locally. It has nothing to do with the OpenRouter
  dashboard's balance or its free-tier request cap. Do not go looking at
  `GET /api/v1/credits` for it; check `plans.credits_5h` for the plan the
  run's user is on. The two limits are unrelated and both can fire.
- **CLOSED for the harness (2026-10-02, D4 item 1, `47fd376`): acceptance no
  longer touches `free`.** Migration 0014 seeds a third plan, `internal-eval`,
  at 20M/200M — about 2× a full 47-item run against `free`'s 200k per 5 h
  window — and `scripts/acceptance.py` moves its throwaway run user onto it
  through `PATCH /admin/users/{id}` before the first turn. That is the product
  path, so the change is audited; it needs `ADMIN_EMAIL`/`ADMIN_PASSWORD` in
  `.env` and `make seed-admin` (new; there is no admin bootstrap in the
  product, since signup hardcodes `role="user"` and only an admin can grant the
  role). Without the credentials the script exits naming them rather than
  falling back to editing a plan. `free` and `pro` are never written, pinned by
  test, and verified unchanged at 200000/2000000 after two live runs.
  `ON CONFLICT (name) DO NOTHING`, so an operator's tuned limit survives a
  replayed migration.
- **What still applies to real users.** The gate is unchanged — credits are
  still reserved before a run and settled after, including on cancellation and
  failure (TRD §14) — and the 429 above is still what a real user on `free`
  hits at ~19 items into a 47-item set. So: the ~310k cost of a full acceptance
  run is still the measured shape of a session that asks more of `free` than
  `free` allows, and **the misleading copy in
  `ChatView.tsx:runFailureMessage` is still open.** A real user who exhausts
  their window is still told "The run could not finish. Try again.", which
  cannot help. The harness no longer trips the wire; the user still does.
  Separately, `internal-eval` is a local-dev plan: nothing publishes it to a
  deployed environment, and P5 has to decide whether a non-`free`/`pro` plan
  needs handling in signup, the admin UI or billing at all.

## KI-24: The eval corpus sits in the Shared library, so every user searches it

Logged 2026-09-30, from the item-2 cleanup (the accounts that must never
be deleted are exactly the ones holding this corpus).

- **What:** the 7 eval-corpus documents owned by `evals@veriforge.local`
  — `faq.md`, `field_service_note.md`, `manual.md`, `returns.md`,
  `spec_sheet.md`, `warranty_2025.md`, `warranty_legacy.md` — live in a
  `visibility='shared'` collection, so `build_scope`'s
  `col.visibility = 'shared'` clause puts them in every user's
  retrieval scope for every question, in every mode. The acceptance
  items `library-list`/`library-count` answer from them, and
  `outside-whitman`/`outside-general` abstain *because* they're in scope.
- **Why it matters:** fine locally, wrong for production. Two problems:
  the benchmark fixture is user-visible product content (a user could be
  cited a warranty spec that isn't theirs), and the eval numbers are
  measuring retrieval over a corpus the real corpus doesn't contain, so
  `not_in_sources` items only pass because the out-of-scope answer is
  sitting right there.

  > **Correction, 2026-10-02 (KI-36).** The parenthetical above is wrong
  > about `outside-whitman`, on both halves. That item was **not** an
  > example of the fixture answering a should-abstain question: the
  > Pride and Prejudice preface is *books* corpus and contains the Whitman
  > passage the item claimed was absent, so the fixture was never what it
  > passed on. `outside-whitman` is relabelled `answer` (cite Pride and
  > Prejudice + mention "allowance"), and a genuinely off-corpus Whitman
  > abstention item (`outside-whitman-lilacs`, zero-hit proof recorded in
  > the item) now carries that role. The rest of this entry — the fixture
  > being user-visible product content, and `outside-general` behaving as
  > described — is untouched.
- **Fix:** before any AWS slice, decide the eval corpus's home. Cheapest
  honest option: keep it owned by `evals@veriforge.local` but make its
  collection `visibility='private'`, and have the eval runner create its
  own signed-in user that includes it explicitly (the eval set already
  signs up a throwaway user per run). Then re-baseline — the
  `not_in_sources` items will legitimately change.
- **Half-fixed (2026-10-01, D3 item 2): fast20 no longer depends on the
  Shared library.** The corpus is still `visibility='shared'` and still in
  every user's retrieval scope — that half is untouched and stays open until
  P5. What D3 fixed is the *measurement*: the gate's fast20 subset is now the
  seed-corpus domain only. The six literary twins (`abstain-11..16`, questions
  about Moriarty, Dracula, the Looking-Glass, Cosette, 賈寶玉) left fast20
  because in CI they are near-misses against an empty topic and decline
  trivially, while locally they met real passages through the Shared library —
  so a local baseline and the CI gate were not comparable. They stay in the
  full seed set, so the full run and acceptance still measure abstention over
  two corpora (Q1). `make eval-gate-local` also runs the loader and the gate
  against a fresh ephemeral database, the way `ci.yml` does, so a local
  baseline is measured on the corpus CI loads. Books belong to acceptance,
  which is still measured against the Shared library by design.

## KI-26: `outside-study-in-scarlet` answers at 0.12 sufficient, above the 0.05 floor

Logged 2026-09-30, from the KI-25 fix (the citation half of that issue is
closed; this is the leftover failure).

- **What:** with citations fixed, 3 of the 4 `not_in_sources` items pass.
  `outside-study-in-scarlet` still `message_status='complete'` — its
  sufficiency lands at 0.12, well above the default `sufficient_abstain`
  floor of 0.05, so it generates an answer and cites 7 chunks. Its scene
  (Watson's limp after the Reichenbach fall) is not in the corpus.
- **Why it matters:** abstention accuracy is 3/4 in the gate because the
  scorer is right and the pipeline is wrong, not because the reviewer
  misjudges this one item.
- **Fix:** the sufficiency question is asked over the reranked top-k, so
  the likely cause is that the top-k it was shown contained a Holmes/Watson
  passage close enough to the query to read as "sufficient". Check what it
  was shown before touching the threshold — raising `sufficient_abstain`
  above 0.12 would also push `outside-whitman` (0.03) and `ml-es-outside`
  (0.02) further from the floor without addressing the cause.
- **Mechanism proven (2026-10-01, D1): topically-adjacent-but-answerless
  evidence; the prompt lever does not hold.** Captured exactly what the
  `sufficient` noul was shown, through the app's own `prepare_auto_run`
  (settings v142, reranker jev, top_k 8; capture in
  `.data/ki26/capture.json`): rank 1 (rerank 0.28) is Adventures ch. I's
  opening — Holmes deducing Watson's recent past, whose parent window
  literally name-drops "the dark incidents of the Study in Scarlet" —
  followed by the boot-scoring, "has been in China", limp and hat
  deductions. The corpus's best match, and **"Afghanistan" appears in
  none of the chunks**: topically adjacent, answerless. Jev reads that as
  0.10 (acceptance history 0.12–0.14); its true-negative bucket
  (0.01–0.04, per `decisions/thresholds.py`) is reserved for zero-overlap
  evidence, which scarlet's wording overlap never reaches. Not a
  rerank/fusion artefact. Three `_sufficient_question` prompt variants,
  each re-measured live: scarlet wobbles 0.08–0.12 under every wording
  while the floor is 0.05, and each nudge toward scarlet pushed
  `compare-inventors` toward the floor. The signal that *does* separate
  the two is the Jev rerank score itself — scarlet top-1 **0.28** vs
  compare-inventors **0.97** — the second signal `thresholds.py` already
  reserves for this case. **Next:** calibrate a `sufficient_min_rerank`
  gate (≈0.5 candidate) at the `p_sufficient >= abstain_threshold` break
  in `auto.py`, against a full acceptance run — a new threshold cell that
  needs calibration across the gate set, too big for the D1 box. Repro:
  `tests/graph/test_chitchat.py::test_answerless_but_topical_evidence_abstains`
  (xfail, strict=False) seeds the captured-style answerless chunks, stubs
  sufficient at the measured 0.10, and flips to passing when a real fix
  lands. `sufficient_abstain` unchanged at 0.05; the item untouched.
- **CLOSED by the gate (2026-10-01, D2 item 4, `953e337` + `97a3da5`).**
  The rerank score separated the classes where `sufficient` could not, so
  the second signal `thresholds.py` reserved became `rerank_abstain`
  `{"jev": 0.60, "fallback": 0.60}` (fallback **unmeasured** — only
  Jev-answered scores were seen). Offline replay of D1's two acceptance
  runs (max rerank score of the final retrieval event's scored chunks,
  gate = `sufficient >= 0.05` AND `max >= T`, keep the run's own content
  checks):

  | T    | run 183311 | run 184634 | beyond KI-27                    |
  | 0.50 | 40/41      | 39/41      | ml-fr-outside answers (max 0.52) |
  | 0.55 | 40/41      | 40/41      | —                                |
  | 0.60 | 40/41      | 40/41      | —                                |
  | 0.65 | 40/41      | 40/41      | —                                |

  Margins at 0.60: answer-side min 0.70/0.73, should-abstain max
  0.49/0.52. In `prepare_auto_run`'s loop evidence is adequate only if
  **both** signals clear — same single retry, one bar — and a `Decision`
  named `relevance` (value = that max, `threshold` set, `stage="rerank"`)
  is published so the trace shows why a run abstained; no schema change,
  no TS regen, no new SSE event type. The gate reads only scores
  `JevRerank` answered (`JevRerank.relevance_engine()`); NVIDIA, Cohere
  and fused order (1/(1+i), top always 1.0) are skipped, and an outage —
  no passage got a real answer — skips the gate so it can never abstain.
  `b4ecde7`'s xfail **now passes and the marker is gone**: the repro pins
  the captured sufficient 0.10 *and* the captured rerank 0.28 through the
  real `JevRerank`. Live subset (8 items, one pass, `20260930-210218`
  then re-run after the publish fix): 8/8, the four hallucinating
  `not_in_sources` items now abstain and the four answer items still
  answer. Out of scope, unchanged: Deep mode (`controller_sufficient`
  0.50) and Fast mode (no DecisionEngine).
- **Caveat on the replay (addendum):** it validates only the **rerank**
  half. Item 3 (children-first sufficiency evidence, `30f3e98`) changed
  every item's `sufficient` view, so the live subset — not the replay —
  is the real check of the combined rule.

## KI-27: `xl-en-wukong-master` answers with the wrong person (pre-existing, not retrieval)

Logged 2026-09-30, from the C2 KI-19 live check. **Not caused by the
CJK tokenizer work** — the C1 23/31 run (`.data/acceptance/20260929-180258.json`)
already failed it with the same answer.

- **What:** the item asks who Sun Wukong's master is and expects Tang
  Sanzang / 唐僧 / 三藏 / Tripitaka / Xuanzang. The run answers "the Bodhi
  Patriarch (菩提祖师) who teaches him various magical skills". Retrieval is
  fine: all six citations are 西遊記.txt, so the book was found and the
  `answer` class is correct. Only the `mention` check fails.
- **Why it matters:** it is a generation-side entity confusion between the
  two figures a reader of Journey to the West would name first — the
  teacher of the seventy-two transformations and the master of the
  pilgrimage — not a retrieval or scope failure.
- **Fix:** worth one look at whether the retrieved top-k actually contains
  the passage naming 唐僧 as the pilgrimage master. If it does, this is a
  generator/grounding problem and belongs with the reviewer; if it does not,
  the chunking of the 西遊記 corpus is dropping the introduction. Do not
  "fix" it by adding 菩提祖师 to the item's `mention` list — that would
  make the check pass while the product is still wrong.
- **Reviewer finding (2026-10-01, D2):** the passage **is** in the top-k —
  rank 2, rerank 0.94, 「賤號三藏…小徒…第一個名孫悟空」 — but 6 of the 8
  chunks are Bodhi Patriarch scenes where Wukong calls him 師父, so the
  generator's top-of-mind master is Bodhi. The question itself is
  ambiguous: both figures are Wukong's master (菩提祖师 for the skills,
  唐僧 for the pilgrimage), so the "right" answer is a judgement call the
  owner has to make. **The owner decides the fix (D3); the item was not
  edited.** It is the only item the KI-26 replay leaves failing at every
  threshold, and it fails on content (`mention`), not on the
  answer/abstain decision.

## KI-28: Jev reranker — switched to Jev (owner decision); abstention separation still open

**Decision, 2026-09-30 (owner): switched to Jev — settings version 142,
`retrieval.reranker = jev`, `sufficient_abstain` unchanged at 0.05; code
defaults (`runtime.DEFAULT_DATA`, `get_reranker`) now `jev`.** Basis, from
C3's three full acceptance runs: pass rate is equal within run-to-run
noise (NVIDIA 27 and 29 on identical code, Jev 28 on one run — C3's rule
compared Jev's single run with NVIDIA's best of two, which is biased); Jev
separates the should-answer / should-abstain `sufficient` groups best
(margin 0.00 vs NVIDIA −0.07 / −0.04), keeps the answer text in the top 8
on every item (1.00 vs 0.82), reranks ~2x faster (431 vs 839 ms p50) at
~$0.0006/query, and is production-licensed where the NVIDIA free tier is
not. The C2 regression that caused the revert was measured before the
Turkish-decline (KI-29) and abstain-citation (KI-25) fixes. Remaining
open: a second Jev run was never completed, and neither reranker separates
the groups until KI-26 (`outside-study-in-scarlet`) is fixed and the
abstention set is widened (KI-6). Fast mode has no DecisionEngine, so with
`jev` selected it falls back to the provider reranker, not fused order.

**Second and third Jev runs done (2026-10-01, D1).** Two full acceptance
runs on the widened 41-item set (14 `not_in_sources`, KI-6), settings
v142, back to back: **36/41 both runs, identical failure sets** —
`outside-study-in-scarlet` (0.11/0.12, KI-26), the new `outside-emma`
(0.07/0.06), `outside-looking-glass` (0.07/0.07), `ml-fr-outside`
(0.08/0.08) answering when they should abstain, and `xl-en-wukong-master`
(0.67/0.69, KI-27, fails on content at every threshold). Per class both
runs: answer 22/23, not_in_sources 10/14, smalltalk 2/2, library 2/2;
per language: en 26/30, es 2/2, fr 1/2, de 2/2, ja 2/2, tl 1/1, zh 2/2;
0 language mismatches. `sufficient` last-score distributions: answer
0.05/0.73/0.98 and 0.06/0.77/0.96 (min/median/max) vs not_in_sources
0.01/0.03/0.11 and 0.01/0.025/0.12 — **margin −0.06 in both runs; no
cut-off separates the groups.** `compare-inventors` (answer) sits at
0.05/0.06 inside the abstain band while the four hallucinating
not_in_sources items sit at 0.06–0.12. Threshold replay on the recorded
scores: 36/41 at the shipped 0.05 in both runs; ceiling **39/41 at
T ≈ 0.13–0.25 in both runs** (gates all four hallucinations, loses
`compare-inventors`; a trade, not a separator). Recommendation reported
to the owner: T ≈ 0.15–0.20 is the best replay zone in both runs — the
owner decides. `sufficient_abstain` stays **0.05** until then. The four
outliers are the same items with stable scores across runs — consistent
with the KI-26 mechanism (topically-adjacent-answerless evidence),
not threshold noise.
**Compare's evidence view was broken too (2026-10-01, D2 item 3,
`30f3e98`).** Two evidence-shaping defects, both fixed: `_rerank_candidates`
returned `picked` in group insertion order, so the "" (no-entity) share
led whatever it scored (compare's citations [1]–[3] were *Noli Me
Tangere* at rerank 0.01–0.02, ahead of Frankenstein and The Time
Machine); and `_sufficient_question` interleaved each entry's parent
before the next entry's child, so with ~4,000-char entries the 9,000-char
budget held ~2 entries and the judge saw only Noli. Both now follow the
order the code's own comment described (children first, parent only if
there's room; shares sorted by rerank score). Live subset (7 items,
`20260930-205630`): `compare-inventors` sufficient **0.05/0.06 → 0.20**
(0.23 in the item-4 run), still answering; no answer item dropped below
0.20 or abstained, so the addendum's `SUFFICIENT_EVIDENCE_CHARS` guard was
not needed; the `sufficient` step's latency is unchanged (before median
330 ms, after 321 ms — it holds more evidence at the same cost). Note the
item-4 run's `compare-inventors` TTFT was 35.9 s against a 9.8 s p50 for
the set — one slow generation, not a step cost; worth watching in D3's
runs.

Logged 2026-09-30, from the C2 reranker comparison and the full acceptance
run that followed it. **Reverted — `retrieval.reranker` is back to the
`nvidia` default in settings version 137.** Read this before the next
reranker change.

`retrieval.reranker` was set to `jev` in runtime settings version 136 on
the strength of that table, and **that setting was reverted in version 137
after the full acceptance run regressed the abstention class in both
directions.** The table below is the reranker comparison, not the verdict.

| reranker | recall@8 | mean rank of expected | mention@8 | p50 ms | $/query | fell back |
| --- | --- | --- | --- | --- | --- | --- |
| jev | 1.000 | 1.0 | 1.000 | 431 | 0.000607 | 0/23 |
| nvidia | 1.000 | 1.0 | 0.818 | 839 | 0.0 | 0/23 |

Both arms saw byte-identical fused candidates (top 40) and no generation
happened, so the reranker was the only variable.

- **Why the comparison was not enough:** it measured *ranking* quality —
  which book lands first, whether a `mention` term survives into the top
  8. It did not measure the effect on the `sufficient` noul, which is
  asked over the reranked top-k and is what actually decides answer vs
  abstain. A reranker can be better at putting the right book on top and
  still change sufficiency in both directions. On the full run it did:

  | item | C1 (nvidia) | with jev |
  | --- | --- | --- |
  | `fact-bennet-sisters` | answer PASS (0.90) | not_in_sources FAIL |
  | `fact-irene-adler` | answer PASS (0.65) | not_in_sources FAIL |
  | `outside-whitman` | not_in_sources (0.03) | **answer** FAIL |
  | `outside-study-in-scarlet` | answer (0.14) | answer FAIL |

  `outside-whitman` answering a Walt Whitman question from a corpus that
  does not contain it is the worst outcome in the product, and it is
  strictly worse than the abstention it replaced. That settles it:
  shipping the latency win is not worth it.

  > **Correction, 2026-10-02 (KI-36). The corpus *did* contain it.** The
  > `outside-whitman` answer read as the worst outcome in the product
  > because the item asserted the corpus had no Whitman passage. It has
  > one: the Pride and Prejudice preface states the "loving by
  > allowance" / "loving with personal love" distinction verbatim (read
  > back by zero-hit/hit search over the 10,733 chunks an acceptance run
  > user can retrieve — the only `%whitman%` chunk in scope is Pride and
  > Prejudice.txt ord 0). So the answer in the C2 run was **correct**,
  > and this is an item defect, not a product defect. The item is now
  > `answer`, with a Pride and Prejudice cite check and an "allowance"
  > mention check. The reasoning above still stands for the reranker
  > decision it was used in — C2's `not_in_sources` classes scored
  > against labels that were partly wrong, so the abstention evidence in
  > this section is softer than it reads — but the specific "worst
  > outcome in the product" claim about this item is retracted.
- **What a real decision needs:** the comparison harness has to carry the
  reranked top-k through the `sufficient` noul and record the
  answer/abstain verdict per item, not just the rank. That is a
  generation-cost measurement, not an offline replay, so it cannot live in
  `scripts/compare_rerankers.py` as written.
- **Still true:** Jev is the better *ranker* here and 1.9x faster, and it
  keeps the `mention` term in the top 8 on four items NVIDIA drops
  (`plot-red-headed-league`, `fact-weena`, `ml-fr-bovary-death`,
  `xl-en-bovary-death`). The three-way replay with Cohere (below) should
  measure the sufficiency effect, not the rank.
- **Licensing, unchanged:** the $0 NVIDIA column is the free,
  evaluation-only tier. It is not shippable, so production still needs
  Cohere Rerank via Bedrock per the earlier provider analysis.
  `CohereRerank` is implemented and already takes precedence when
  `COHERE_API_KEY` is set, so that arm is a config change.
- **Also worth knowing:** Fast mode cannot use Jev — it has no
  DecisionEngine, so it falls back to fused order and logs a warning.

### C3 measured this at the decision level. **Decision: stay on NVIDIA.**

The C2 gap above — that the ranking comparison says nothing about the
answer/abstain decision — was closed on 2026-09-30. Three full 31-item
acceptance runs (nvidia ×2, jev ×1), each in its own active settings
version so `retrieval.reranker` was the only variable, with KI-29 and the
language scorer in place:

| run | settings | pass | answer | not_in_sources | smalltalk | library | `language_mismatch` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nvidia 1 (`20260930-140558`) | v138 | 27/31 | 20/23 | 3/4 | 2/2 | 2/2 | 0 |
| jev 1 (`20260930-144733`) | v139 | 28/31 | 21/23 | 3/4 | 2/2 | 2/2 | 0 |
| nvidia 2 (`20260930-152951`) | v140 | 29/31 | 22/23 | 3/4 | 2/2 | 2/2 | 0 |

Per question language, all three runs: en 21-22/24, es 2/2, fr 0-1/1, de
1/1, ja 1/1, tl 1/1, zh 1/1. Every failure in every run is
`wrong_class_or_content` — **no run produced a language mismatch**, which is
the independent confirmation that KI-29's fix holds across a full set.

**The `sufficient` distributions, and the answer to "does a cut-off
separate the two groups?":**

| run | should abstain (n=4) min / median / max | should answer (n=23) min / median / max | margin |
| --- | --- | --- | --- |
| nvidia 1 | 0.02 / 0.025 / **0.13** | **0.06** / 0.61 / 0.96 | **−0.07** |
| jev 1 | 0.02 / 0.03 / **0.09** | **0.09** / 0.73 / 0.95 | **0.00** |
| nvidia 2 | 0.02 / 0.025 / **0.13** | **0.09** / 0.62 / 0.97 | **−0.04** |

**No arm separates the two groups.** In every run the highest
should-abstain score is `outside-study-in-scarlet`, and in every run it is
at or above the lowest should-answer score, which is `compare-inventors`.
Under Jev the two are **exactly equal at 0.09**: there is no threshold at
which `outside-study-in-scarlet` abstains and `compare-inventors` still
answers, because they scored the same number.

Replaying each run's own recorded scores against every candidate
`sufficient_abstain` (a run answers at or above the floor, so the decision
at any threshold is exactly replayable):

| run | at the shipped 0.05 | best over all thresholds | at that threshold |
| --- | --- | --- | --- |
| nvidia 1 | 27/31 | **27/31** | 0.05 (already optimal) |
| jev 1 | 28/31 | **28/31** | ~0.09 (gains one, loses one) |
| nvidia 2 | 29/31 | **29/31** | ~0.13 (gains one, loses one) |

Raising the floor buys exactly one `not_in_sources` item
(`outside-study-in-scarlet`) and costs exactly one answer-class item at or
below the new floor, in every run and both arms. It is a wash, which is why
0.05 stays.

**Against the decision rule.** Jev fails on the *first* clause, before
stability is reached: it must reach a score at least equal to NVIDIA's best
(29/31) and its ceiling is 28/31. It also fails the second — no threshold
gives a score with **no `not_in_sources` item answering**, because
`outside-study-in-scarlet` and `compare-inventors` are tied at 0.09. So:
**stay on NVIDIA, `sufficient_abstain` stays 0.05, nothing was changed.**

- **Not verified:** the rule's third clause, *stable across both Jev runs*.
  The second Jev run was stopped at 14/31 items. It can only confirm or
  widen a margin of exactly 0.00, and the first clause already fails, so it
  could not have changed the decision — but it is not done, and it is the
  one number here I did not measure. Four runs at ~45 min each did not fit
  the dispatch's 60-minute box; that conflict should have been raised
  before starting, not discovered three hours in.
- **What this does and does not say about Jev.** It says Jev does not beat
  NVIDIA *on this corpus, on this 31-item set, at this threshold*. It does
  not retract the ranking result above: Jev is still the better ranker and
  ~1.9x faster. The blocker is that `sufficient` has no headroom on either
  side of the floor, so a reranker change cannot be evaluated by threshold
  tuning — only by fixing `outside-study-in-scarlet` (KI-26) and adding
  abstention items (KI-6).

## KI-29: Every decline message came back in Turkish — **FIXED** in `68a1b02`

Logged and closed 2026-09-30 (C3). Fixed in `68a1b02`; the scorer half in
`42267f1`. Kept as a record because the same prompt shape can reappear.

- **What:** `graph/abstain.py::stream_abstention` sent gpt-4o-mini a single
  system message — `prompts/abstain.md` v1 — asking it to render the fixed
  decline template "in the language of their question", with the question
  pasted **inside the system prompt** and no user turn at all. In
  `.data/acceptance/20260929-194405.json` the English `outside-whitman`
  and the English `outside-general` both returned "Bu sorunun yanıtını
  vermek için yeterli kanıt bulamadım…", and the Spanish `ml-es-outside`
  returned Turkish too.
- **Proof, before any fix:** called `stream_abstention` directly against the
  live model with the real acceptance questions. English question → Turkish.
  Spanish question → Turkish. Same template, same Turkish, both times. So
  the defect is the instruction, not the corpus or the items.
  `question` arrives as `self.rewritten` in `auto.py` and `deep.py` alike.
- **Fix:** `apps/api/textkit.py` detects the question's language
  deterministically (Unicode script + a small stop-word table; no
  dependency, no DecisionEngine call). An English question now returns the
  English template with **no model call at all** — it is already English,
  so there is nothing to translate. Any other language gets the target
  named outright ("Translate the fixed message below into German") with
  the question in the **user** message, labelled and followed by "Do not
  answer the question" — sent bare, the model translated one and answered
  the next. `abstain.md` v1 → v3.
- **Why it was invisible:** `scripts/acceptance.py` only checked *that* a
  run declined. It now scores the reply's language on every item and
  reports `language_mismatch` as its own reason (`42267f1`).
- **Checked and left alone:** `chitchat.md`, `library.md` and
  `grounded_answer.md` carry the same vague "same language as the user's
  message" rule, but their input already arrives as a user message and all
  seven `ml-*`/`xl-*` items answered in the question's language in run
  `20260929-180258`. Changing them would add risk with nothing behind it.
- **Known limit, still open:** the model appends a training-data aside
  ("You are trained on data up to October 2023" / "Eğitim verileriniz Ekim
  2023'e kadar.") to the translated decline, in the right language, even
  with an explicit rule against it. It is cosmetic and does not affect the
  language check. Also open: a very short reply with no stop-word or script
  signal is reported as *undetectable* rather than English, so the scorer
  does not fail it — a deliberately conservative choice, not a clean bill of
  health.

## KI-30: The eval harness measured itself, not the product (fast20 D1 runs)

Logged 2026-10-01 (D2 items 2a/2b/2c); all three fixed on `fix/darcy`
(commits `ac6fed4`, `495047f`, `624ccf9`). Kept as a record because every
number recorded before D2 — including D1's three fast20 gate runs and the
KI-6 tables — was produced by this harness.

- **2a — eval runs searched the web.** `evals/runner.py` passed
  `source="auto"`, which ingress routes to Tavily; the UI never sends
  `auto` (`ChatComposer.tsx:19` sends `upload`/`both`, acceptance sends
  `upload`). In D1's three fast20 runs 16 of 20 items cited
  `source_type='web'` chunks and some in-corpus AW-2000 items cited web
  only; the should-abstain items (Dracula, War of the Worlds,
  Looking-Glass, Cosette, Moriarty, 賈寶玉) were answered from web pages,
  making abstention 0–1 of 8 an artefact (the answers were faithful to
  the web pages, so faithfulness 1.0 was legitimate; web variance also
  explains most of the faithfulness dip — HomeKit, web-only:
  1.00 / 0.50 / 1.00). **Fixed:** `source="upload"` in both runner
  branches; TRD §15 records the rule.
- **2b — the judge's output was dropped.** `context_precision` /
  `context_recall` were null on 17–19 of 20 items in every D1 run, read
  as "judge noise". Captured raw Haiku 4.5 responses show fenced JSON
  followed by "**Explanation:**"/"**Justification:**"/"**Reasoning:**"
  prose, which the whole-string fence match could not parse, and one
  missing field nulled all three. Not the KI-29 message-shape failure —
  the model scores, then explains. **Fixed:** `parse_judge_response`
  raw-decodes the first JSON object wherever it sits and keeps each field
  that parses; `eval_judge.md` stays at v2.
- **2c — `p50_our_overhead_ms` was always null, and Jev time was never
  recorded.** (i) `aggregate()` reported null unless *every* scored item
  was fully attributed, against TRD §15's rule (an unattributable item
  records no figure; the summary is null only when no call was
  attributed). Now the median runs over the attributed items and the
  summary carries `overhead_items_attributed`. (ii) `decisions/jev.py`
  uses raw httpx, so all Jev time (rerank batches, sufficient, sanitize,
  conflict, ingress, review verification) counted as "our overhead";
  Jev's OpenRouter response **does** carry `x-generation-id` (verified
  live), and `JevClient` now reports it through an eval-only
  `generation_id_sink`. Two live probes show the stats record lands but
  `generation_time` reads **0** for `api_type="decisions"` (the duration
  sits in `latency`, 241–242 ms): under the TRD-owned method (KI-18) Jev
  provider time therefore contributes 0 and its wall time counts as
  ours. Reported, not re-measured — switching fields would change a
  TRD-owned method. (iii) The per-item stats wait (~20 s per item, the
  record's landing delay) now runs once, after the whole run, so one
  wait covers it. (iv) Negative per-item overhead (concurrent calls
  summed) is logged and reported, never clamped.
- **External calls on the eval path, attribution after D2:**
  `litellm.acompletion` (generation, rewrite, fallback decisions) —
  attributed inside the timed window; reviewer + judge `acompletion` —
  deliberately outside it; `litellm.aembedding` (query embed on cache
  miss) — no generation record exists for embeddings, counted as ours;
  Jev — recorded, `generation_time` 0 (above); NVIDIA/Cohere rerank (only
  when `retrieval.reranker != "jev"`) — not OpenRouter, counted as ours;
  fused order — local, no call.
- **Consequence:** D1's three fast20 runs and their KI-6 table are not
  valid measurements of the product. The baseline attempt that failed on
  them (faithfulness 0.9492, null overhead) is explained by 2a and 2b.
  Re-measure from D3 on the fixed harness; do not backfill comparisons
  across the fix.
- **A3 applied (2026-10-01, D3 item 3): the Jev field is now `latency`.**
  Owner decision A3 records Jev's provider time from the stats record's
  `latency` rather than its `generation_time`, because
  `api_type == "decisions"` reports the latter as 0. `evals/attribution.py`'s
  `_record_provider_ms` dispatches on the record: `latency` for a `decisions`
  record, `generation_time` for a chat completion, and *no* figure when
  neither field is present — a record with no `latency` is left unattributed
  rather than credited 0 ms, because 0 would put the whole call back on our
  overhead through the other door. TRD §15's latency paragraph now states
  which field each call type reports and why.
- **Coverage, and what A3 does not reach.** The attribution still cannot see
  `litellm.aembedding` (no generation record exists for an embedding) or a
  NVIDIA/Cohere rerank (not OpenRouter, and only used when
  `retrieval.reranker != "jev"`). Both remain counted as *our* overhead, so
  `p50_our_overhead_ms` still overstates our share by whatever those cost.
  D3's own measurement of that gap is in the D3 report: the per-stage p50s
  from `stage_ms`, now dumped by `scripts/eval_dump_stages.py` before
  `make eval-gate-local` drops its database. A3's effect is visible in the
  item-3 test (`latency` 240 → 240 ms of provider time; a 5000 ms item with
  one Jev call in it is 4760 ms of ours, not 5000 ms).

## KI-31: One unresolvable generation id discards an item's whole overhead figure

Logged 2026-10-01 (D3 item 4), found while deciding whether the fast20
baseline could be written. It is the last thing standing between D3 and a
baseline.

- **What:** `evals/attribution.py` records `our_overhead_ms` for an item
  only when `Attribution.complete` is true, and `complete` is
  `unattributed == 0 and attributed > 0` — i.e. when **every** generation id
  on that item resolved to a stats record within `STATS_ATTEMPTS` (8) ×
  `STATS_BACKOFF_SECONDS` (3.0) ≈ 24 s. One id that never comes back throws
  away the item's entire figure, including the provider time that *did*
  resolve. Across D3's three fast20 runs, 16, 18 and 17 of 20 items were
  attributed (80% / 90% / 85%), against a ≥ 90% bar.
- **Evidence, run 3:** the four uncovered items — "Does the AW-2000 work with
  Zigbee smart-home hubs?" (abstained), "When will the AW-3000 be released?"
  (abstained), "How much does the AW-2000 weigh with the mounting bracket?",
  "How long is the warranty on an AW-2000?" — each carry a real
  `provider_ms` of 3481 / 6202 / 3622 / 3472 ms and a null
  `our_overhead_ms`. So the calls *were* recorded; one id per item did not
  resolve. Their wall clocks were 11545 / 10140 / 7747 / 6866 ms, which is
  33706 ms of pipeline time silently counted as nobody's.
- **Why it matters beyond the bar:** `p50_our_overhead_ms` is the figure the
  gate hard-limits (TRD §15, KI-18). It is a median over the *attributed*
  items, so dropping the slow items biases it **downward** — the gate is
  currently comparing a flattering subset. That is the opposite of the
  conservative direction, which is why this is a defect and not a coverage
  footnote.
- **PARTIALLY FIXED (2026-10-02, D4 item 2, `de725d4`); the cause is still
  undiagnosed.** Two changes, one of which was the instrumentation this entry
  asked for:
  - *Partial attribution is reported instead of discarded.* A generation that
    resolves contributes its `provider_ms` even when a sibling on the same item
    does not; `stage_ms` records `generations_unattributed` and a one-line
    description of each unresolved id. `our_overhead_ms` is **still withheld**
    on a partial item — a partial sum understates provider time and would
    overstate our overhead, and the gated figure must not be a guess. The
    summary gains `p50_total_ms_unattributed_items`: the median wall clock of
    exactly the items the gated median excludes, so the downward bias has a
    number next to it. No figure is invented for a miss (KI-18).
  - *The miss is now diagnosable.* `record_generation_ids` returns
    `GenerationRef` — id, source (`litellm`/`jev`), model, role, job and call
    time — instead of a bare id, and `_stats` returns the HTTP status of its
    last lookup alongside the record. Every unresolved id is logged with its
    call site, final status, attempt count and age. Role and job come off the
    request metadata `providers/llm.py` already sends, so nothing is threaded
    through the graph. `eval_dump_stages.py` carries all of it into the
    `.data/evals/<timestamp>-<sha>.json` export, so it survives the database
    drop that destroyed the evidence three times running.
  - **Still open: the cause.** The narrowed candidates, none ruled in or out:
    OpenRouter never indexing a stats record for some requests; Jev's
    `gen-dec-*` ids behaving differently from `gen-*` ones; a stream that died
    and restarted, recording the first attempt's id with no completed
    generation behind it; or a transient 5xx. The landing delay is **ruled
    out as the whole story** for any id abandoned well past ~20 s, which the
    new `age_ms` makes visible per id. Read the ids back by hand with
    `curl https://openrouter.ai/api/v1/generation?id=…` from the export before
    theorising further.
  - Note a second, *distinguishable* failure now reported separately: a record
    that lands but carries no duration field (`api_type` set, no `latency` and
    no `generation_time`) contributes nothing and used to look identical to a
    404. That class is reported with `last_status=200` and its `api_type`.
- **CAUSE FOUND AND FIXED (2026-10-02, `692f073`); the entry closes.** The
  budget, not the calls: measured 0.4 s / 0.4 s / 0.4 s / **123.6 s** for four
  consecutive calls' records to land, against a 21 s budget. Every candidate
  class this entry listed is ruled out — the three ids that 404'd for a whole
  fast20 budget (one Jev `decisions`, two `gpt-4o-mini` `rewriter`) all answered
  **200** on a manual read a minute later with their durations intact. Budget
  now 30 × 6.0 s ≈ 174 s, pinned by a test against the measured 123.6 s.
- **Do not** fix this by loosening the gate's thresholds or by writing a
  baseline on the current coverage. That is the mistake KI-6 has already
  recorded once for latency. TRD §15's "coverage must not bias the median
  downward" paragraph landed with the fix.

## KI-32: Faithfulness moves 0.0300 between runs, exactly at the gate's tolerance

Logged 2026-10-02 (D4 item 3), while deciding whether the fast20 baseline could
be written. It was written — this is the record of what the variance is made
of, and of the two numbers the owner has to rule on.

- **What:** three `make eval-gate-local` runs on commit `692f073`, each on a
  fresh ephemeral database, score faithfulness **0.96833 / 0.98000 / 0.95000**.
  The spread is **exactly 0.0300**, which is `FAITHFULNESS_DROP` to the digit —
  in exact rational arithmetic the means are 29/30·…, 49/50 and 19/20, so the
  spread is 3/100 with no floating-point slack either way. One more run at 0.95
  makes it 0.0333 and the stability condition fails.
- **The source is generator variance, and it is measured, not inferred.** With
  item 3's per-item export the variance decomposes cleanly. Four of 20 items
  move at all; for **each of the four, all three runs produced a different
  answer** and a different set of extracted claims (claim counts 2/5/4, 5/4/6,
  1/1/3, 3/1/1). So it is not one claim being re-judged: it is the whole answer
  being regenerated, with the claim extraction faithfully reporting whatever it
  was handed.
  - **Verification variance: ruled out.** Across the 64 claim texts that appear
    in more than one run, **zero** were given a different verdict in a later
    run. Jev's `claim_verdict` is stable on identical text.
  - **Context/citation variance: real but not sufficient.** Context sets differ
    in 2 of the 4 moving items (identical in 2), so retrieval jitter contributes
    — but the answer and the claims differ in all four, which retrieval jitter
    alone cannot produce.
  - The mechanism is visible in the claim text: the same *fact* is asserted with
    or without a citation marker between runs, and an uncited factual claim
    scores `unsupported` by design (`graph/review.py`, TRD §10 step 3). Run 3's
    battery item split one supported claim into three, one of them `partial`,
    for a mean of 0.833 against 1.000 — **the denominator moved**, not the
    judging.
- **No temperature is pinned anywhere.** `grep temperature` over
  `config.py`, `providers/llm.py`, `graph/review.py` and `decisions/fallback.py`
  returns nothing: extraction and generation both run at the provider's default,
  which is 1.0 for gpt-4o-mini. So the variance is *expected* from the current
  configuration, and claim extraction — a parsing task whose output feeds a
  mean — is the least justified place to leave it stochastic.
- **Not fixed here, deliberately.** Setting `temperature: 0` for the
  `claim_extractor` role would change a product prompt parameter, which CLAUDE.md
  requires an eval-gate run to validate, and the gate's own tolerance is
  TRD §15's to set. Both are the owner's calls. **Proposal, for the owner:**
  1. pin `temperature: 0` for `claim_extractor` (a parsing call — the textbook
     case for it) and leave generation alone, since answer variety is a product
     choice;
  2. re-measure three runs and check whether the spread drops below 0.02, which
     would put the 0.03 bar back inside its margin;
  3. only if (1) does not help, raise `FAITHFULNESS_DROP` — and then say so in
     TRD §15, because 0.03 was chosen before any of this was measurable.
- **Do not** resolve this by re-baselining on a favourable run or by widening
  the composition until the spread looks small. The spread is real and it is
  concentrated in 4 items; at n=20 those 4 decide the metric.
- **Step 1 landed (2026-10-02, owner decision A4), not the measurement.**
  `extract_claims` now pins `temperature=0` (`graph/review.py`), which is
  proposal 1 above. `providers/llm.complete` / `stream_completion` gained a
  keyword-only `temperature` whose `None` default sends nothing at all, so no
  other caller changed behaviour; the pin is re-applied on the open failover,
  the mid-stream restart (KI-17) and the reasoning 400-retry, all three of
  which rebuild the kwargs. The generator reads a new
  `generation_temperature` setting that is **unset by default**, so generation
  is byte-identical to before — the generator's value is for phase P2 on the
  full eval sets. **Step 2 has not run:** whether the spread actually drops
  below 0.02 is unmeasured, and per the note above it needs an eval-gate run
  (provider credit), which this work did not spend. Do not read the merged
  change as the variance being closed.

## KI-33: The language detector reads short French as Spanish

Logged 2026-10-02, from the PRD v3 review (F4). Verified:
`textkit.detect_language("Peux-tu résumer Madame Bovary ?")` returns `es`.

- **What:** `textkit.py`'s detector uses a stop-word table plus script
  detection. In this question the only stop word that matches is "tu",
  which is in the es, fr, pt and pl tables alike. The tie is broken by dict
  order, and `es` comes first. (Corrected by the second PRD review: an
  earlier wording blamed the accented title.)
- **Why it matters:** three things depend on it.
  - TR-4's "decline in the question's language": `broad-bovary` declined
    **in Spanish** in D4 run 2.
  - SR-7.
  - The acceptance scorer, which uses the same detector: run 1's correct
    French answer to `broad-bovary` was scored `language_mismatch`.
  A detector bug looks like a product bug **and** like a scorer bug.
- **Fix:** prove it on a captured set of short questions per language
  first, then fix it at the root, in `detect_language`. **A tie must never
  be resolved by dict order.** Return `None` (undetectable) on a tie or a
  thin margin, and use distinctive characters or words (e.g. `ç`, `ê`,
  "peux", "résumer") to break real ties. The scorer already treats
  undetectable as "no evidence". Test: the captured short-question set, every language in
  SR-7.

## KI-34: Conflict disclosure splits document ids at the midpoint, not by side

Logged 2026-10-02, from the PRD v3 review (F7). Verified at `graph/auto.py`
(the conflict branch after the `conflict_disclose` threshold).

- **What:** when the conflict decision fires, the code takes the document
  ids of the top 5 winners and assigns the first half to
  `citation_ids_left` and the rest to `citation_ids_right`. These aren't
  the passages that disagree, just a list cut in two. The conflict call is
  also outside `_step`, so it isn't timed.
- **Why it matters:** TR-5 promises "cites both sides". The UI can show a
  conflict whose "sides" agree with each other. OKF's OK-6 (status breaks
  the tie) builds on this.
- **Fix:** the conflict decision has to say *which* passages disagree. One
  option is a DecisionEngine question per candidate pair, or a Choice over
  the passages for each side; that's a TRD §8 decision, not a code
  shortcut. Time the step. Test: two passages asserting different values
  for the same fact land on opposite sides.

## KI-35: Password-reset email is logged, never sent

Logged 2026-10-02, from the PRD v3 review (F13). Verified:
`auth/router.py` wires `DevLogEmailTransport`.

- **What:** AC-1's password reset generates the token and link, but the
  transport writes the email to the log. A real user who forgets their
  password can't recover their account.
- **Why it matters:** it's a production blocker for AC-1 and invisible
  locally, where the log is right there.
- **Fix:** a real transport behind the existing interface (SES fits the AWS
  plan, slice 9/P8), selected by settings, with the dev-log transport kept
  for local. Test: the production transport is selected when configured,
  and the dev transport never runs with production settings.

## KI-36: Two acceptance items are wrong, not the pipeline

Logged 2026-10-02, verified against the corpus and the D4 runs.

- **`outside-whitman` is mislabelled `not_in_sources`.** The Pride and
  Prejudice preface in the corpus reads: *"Walt Whitman has somewhere a fine
  and just distinction between 'loving by allowance' and 'loving with
  personal love.'"* The answer is in the sources, and the pipeline is right
  to answer. It "passed" before only because retrieval missed that passage.
- **`fact-weena`'s check is too narrow.** The answer is correct (it cites
  The Time Machine 7 times and describes Weena accurately), but the item
  requires the word "Eloi".
- **Why it matters:** both read as product failures and distort the
  abstention and answer rates. The original 31 items never got D1's
  label audit.
- **Fix:**
  - Relabel `outside-whitman` as `answer`, requiring a Pride and Prejudice
    citation **and** the mention "allowance". The D4 answers cite the
    preface as [1] alongside 7 unrelated citations, so the cite check alone
    is too weak. Add a genuinely off-corpus Whitman question.
  - Widen `fact-weena`'s accepted mentions to **"flower"**, which both D4
    answers contain (the garland of flowers), **with the reason in the
    item**. Not "Time Traveller": run 1's correct answer never says it.
  - Annotate KI-28's "worst outcome in the product" note and KI-24's
    `outside-whitman` references: that "answer" was correct.
  - Then audit **every** item's label: a hit search for answer items, a
    zero-hit search for should-abstain items (PRD v3.1 §5).

**Fixed 2026-10-02 (labels only, no pipeline change).** `outside-whitman`
is `answer` (`cite: ["Pride and Prejudice"]`, `mention: ["allowance"]`, with
the reason both checks are kept recorded in the item). `fact-weena`'s
accepted mentions are `["Eloi", "flower"]`, with "flower" justified from the
two D4 answers and "Time Traveller" recorded as considered-and-rejected (run
1's correct answer says "the protagonist"). New abstention item
`outside-whitman-lilacs` ("When Lilacs Last in the Dooryard Bloom" /
Lincoln) carries a zero-hit proof over the 10,733 chunks an acceptance run
user can retrieve, with spot-read notes on the false hits. KI-28's "worst
outcome in the product" claim and KI-24's `outside-whitman` reference are
annotated as retracted item defects.

Offline re-score of D4's two recorded result files under the new labels
(no live run, $0): `20261001-170931` 42/47 → 44/48 and `20261001-172911`
41/47 → 43/48, the two gained items being `outside-whitman` and
`fact-weena` in both runs (`wrong_class_or_content` → pass). Per class after
relabelling: answer 30, not_in_sources 14, library 2, smalltalk 2 = 48. Note
`outside-whitman-lilacs` has no recorded result — it is counted as not-run,
so the "after" denominators are 48 with 47 scored.

**Still open:** the remaining 45 items' labels are still unaudited (the fix
above covers the two this issue names). The class-count test in
`tests/scripts/test_acceptance_books.py` and the label-replay tests in
`tests/scripts/test_acceptance_ki36_labels.py` pin what was changed.

## Reference: provider findings, 2026-09-26
These aren't defects, but check them before changing models or providers.

- **Nemotron reasoning is on by default on OpenRouter.** It adds 5–10 s
  and, under a tight `max_tokens`, spills into `content`.
  `providers/llm.py` sends `extra_body={"reasoning": {"enabled": false}}`
  except for `llm_reasoning_roles` and thinking-stream callers.
- **LiteLLM's built-in `fallbacks=` kwarg returned an empty stream with no
  error** when the primary failed (live test, streaming). Don't switch to
  it. The explicit one-hop failover in `providers/llm._open` is
  deliberate.
- **Free OpenRouter models that work:** Nemotron 3 Super (1–2 s, clean
  JSON, correct `[n]`) and Nemotron 3 Ultra (4–6 s). `openrouter/free`
  routes to whatever free model is up.
  - Unusable that day: Qwen3.8 and Gemma 4 (429), Inkling (403: coding
    harnesses only), Nemotron 3.5 Lightning (prints its reasoning), LFM
    2.5 and Dots 3 (empty output on one task).
- **Jev exists only on OpenRouter** (System One endpoint,
  `typesafe/jev-1.13`; the public list shows `typesafe/jev-router` at
  price `-1`). It isn't in NVIDIA's catalogue.
- **NVIDIA API catalogue** (`integrate.api.nvidia.com/v1`, free key from
  build.nvidia.com): 82 models, including Nemotron 3 Super/Ultra, Kimi K3,
  GLM 5.3 / 5.3 Flash and DeepSeek V4.1 Flash, plus rerank and embedding
  models.
  - Its terms are for prototyping and evaluation, roughly 40 req/min.
  - A candidate second provider and a free reranker (KI-10). ~~Keep the
    embeddings on `text-embedding-3-small`, because
    `chunks.embedding` is `vector(1536)`.~~ Superseded 2026-09-29:
    embeddings moved to `text-embedding-3-large` with
    `dimensions=1536` — same column, no schema change (round 2, owner
    decision).
- **The Kimi and GLM subscriptions are coding plans.** They're licensed
  for coding tools only, so they're not for Veriforge's runtime or evals.
- **The OpenRouter key** had $4.99 of $100 left. Free models cost
  nothing, so the spend is Jev, the old Haiku fallback, eval runs or
  embeddings. See KI-11.
- **Cohere:** the trial key is 10 calls/min and 1,000/month.
- **Latency attribution (2026-09-29, `scripts/diagnose_latency.py`):**
  on `openai/gpt-4o-mini` via OpenRouter, our overhead p50 was 72 ms
  (44–85 ms); total p50 1,511 ms, 96% provider time. OpenRouter's
  `GET /api/v1/generation?id=` gives the provider figure reliably
  (10/10). Slow LLM stages are the provider unless this says otherwise.
