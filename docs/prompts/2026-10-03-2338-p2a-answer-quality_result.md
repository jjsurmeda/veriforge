# P2a result: stop the system saying false things confidently

Dispatch: `docs/prompts/2026-10-03-2338-p2a-answer-quality.md`.
Branch `p2a/answer-quality`, off `main` @ `66520f2`. Owner merges locally; no PR.

Ruler: `.data/judge_proxy/claims_proxy.csv` (45 claims) and
`.data/judge_proxy/answers_proxy.csv` (30 answers) — Opus-blind labels,
**proxy, not human**. Every figure that depends on them is marked (proxy).
The empty `human_*` columns in `evals/judge_validation/` were never written.

## 1. The ruler's before and after, per item

All four items landed; the branch carries one commit per item
(`f3a1521` item 0, `fa9a403`+`40fd235` item 1, `7fcb93f` item 2,
`8a5a622` item 3, `5036b64` item 4).

### 1.1 KI-53 — false "the sources do not provide…" sentences (item 1)

**Ruler:** the 15 scored export answers' proxy `grounded` label against the
new reviewer's faithfulness ≥ 0.90 (proxy, not human).

| | before (P1b) | after (item 1) | target |
|---|---|---|---|
| agreement on the 15 scored export rows | 7/15 | **13/15** | ≥ 13/15 ✓ |

Mechanism proof (live, gpt-4o-mini, exact P1b passages, captured in
`tests/fixtures/p2a_item1_captures.json`): v3 still emitted the false absence
on `fact-bennet-sisters` — *"The sources do not provide any further details
about the individual sisters' characteristics or names"* (the names are in
passages [6][8]) — and on the firmware row; v4 emitted no unconditional
absence sentence on any single-part row, and the two 5 GHz rows name the 5 GHz
part without concluding the product lacks it.

Fix: `grounded_answer.md` **v4** (version header bumped; the "what is not
covered" sentence appears only when a named part of the question is
unanswered, and then names that part; no generic closing disclaimer; no
inference language) + reviewer absence-claim routing through the existing
batched claim-verdict decide call (`verify_claims(answer=…)`), so an answer
with no absence claims makes no extra call.

**Residuals (2 of 15, both quoted, both opened):**
- Row 18 `export:20261002-061544:12` (firmware 3.1.0 pairing): recorded P1b
  answer *"…a maximum of 2 devices can be paired under firmware prior to
  3.2.1 [1]. Source [2] states up to 5 devices can be paired with one widget…"*
  — faithfulness 0.5, min support 0.0; the recorded answer itself carries a
  contradictory 5-device figure, so the lower reviewer score is correct and
  the proxy `grounded=yes` label is the one that disagrees.
- Row 22 `export:20261002-061544:16` (2025 warranty claim): recorded P1b
  answer ends *"The sources do not cover any additional specific requirements
  or details beyond this information."* — a false absence claim (contradicted
  verdict, faithfulness 0.75). The recorded answer predates v4; the reviewer
  now catches the shape it missed.

The other disagreements on the 30-row board (rows 2/3/4/8/11/14, acceptance
book questions) are P1b recorded declines or under-answered books answers
re-scored by the new reviewer — outside the 15 scored export rows the target
is defined on.

### 1.2 KI-52 — "true fact + invented addition" scored partial (item 2)

**Ruler:** `claims_proxy.csv` — 15 seeded negative claims and the 30 real
claims (proxy, not human).

| | before (P1b) | after (item 2) | target |
|---|---|---|---|
| seeded negatives caught | 11/15 | **14/15** | ≥ 13/15 ✓ |
| real claims agreement | 24/30 | **25/30** | ≥ 24/30 (no drop) ✓ |

Fix: `claim_extraction.md` **v2** (version header kept current; one checkable
fact per claim; compound splits at "and", "which also", "faster than…",
"ships with…"; few-shot from the 4 seeded misses) + `parse_claims` now strips
the echoed `[JSON claims]` label (before, an echoed label silently parsed to
zero claims and an empty extraction scored a perfect 1.0).

**Residual (1 of 15, quoted, opened):** c8 — the answer *"certified for
outdoor use in all weather"* plus a true IP67 rating now splits into two
claims; the invented "certified… all weather" takes the half-credit partial
the proxy labels unsupported. All four P1b misses are caught: c5 "faster than
any competitor", c3 "spare battery", c2 "leather carrying case" →
unsupported.

### 1.3 Prose decline becomes an abstention (item 3)

A post-generation DecisionEngine Noul (`prose_decline` threshold 0.70,
`thresholds.py`, admin-overridable) rides the existing post-delivery gather;
when the reply says the sources cannot answer, the message is recorded
`abstained` and its citations are dropped (KI-25's shape). Partial answers
that state what is missing are untouched (TR-4). No prompt-file change.
Full suite 893 green at the commit.

### 1.4 KI-54 — entity-match gate (item 4)

`named_entities` heuristic + one Noul per top-k passage
(`_entity_passage_questions`, 1500-char passage cap, named `entity_{i}`),
batched into the existing post-sanitize `sufficient` decide call; abstain
when sufficient AND relevant AND no passage matches the entity
(`entity_match` threshold 0.50, admin-overridable); skipped — never
abstains — when the question names no entity. No prompt-file change. 15
new tests; 4 mutations caught (final condition, un-batching, any→all,
never-abstain). Full suite 908 green at the commit.

**Ruler:** the entity-mismatch set (`evals/entity_mismatch/items.json`,
12 items, 2 non-English; each item proven by a zero-hit search for the named
entity in its scoped corpus, D1 method).

| | before (run `01a10288…`, code @ `f3a1521`) | after (run `01a102f6…`, code @ `5036b64`) | target |
|---|---|---|---|
| clean declines | 10/12 | **12/12** | ≥ 11/12 ✓ |
| confident wrong answers | 2 | **0** | — |

Both P1b confident-wrongs now decline cleanly. Quoted before/after
(opened, two):
- `cf-k9-charge` "How long does a flat-to-full charge take on the Kestrel K9?"
  — before: *"...flat-to-full charge on the Kestrel K9 takes 1.5 hours when
  using a 30 W USB-C adapter [2]"* (the AW-2000 figure, cited to the AW-2000
  spec sheet); after: *"I could not find enough evidence to answer that
  question. … Your sources cover spec_sheet.md, manual.md, faq.md…"* (clean
  template, no citations).
- `cf-k9-ingress` "What ingress protection rating does every Kestrel model
  carry?" — before: *"The Kestrel enclosure is rated IP54 … [1]"*; after:
  clean decline, same shape.

**Gate rule check (item 4):** fast20 (run `01a102fa…`): 11/12 answered — the
same items as the P1b baseline — abstention 8/8, 0 confident wrong, 1 false
abstention (RP-77, §5 below, pre-existing). Counterfactual gate subset
(run `01a1030b…`): 6/6 answerable answered, 4/4 clean declines —
**no answerable item started abstaining**.

**D7 baseline (owner's entity-set stability question):** 5 serial runs of the
12-item set on the fixed gates, runs `01a10318…` → `01a10328…` (logs
`.data/evals/p2a-entity-baseline-{1..5}.log`): **12/12 clean declines,
0 confident wrong, faithfulness 1.0000 in every run; zero spread**. The D7
conditions hold — the mean of N runs is a stable baseline and the spread is
auditable (it is 0). Baseline cost ≈ $0.18 total.

## 2. The generator bake-off (item 5)

Candidates (live OpenRouter catalogue, pulled 2026-10-04,
`/tmp/ocr-models.json`), generator role only via the new `--generator` flag
(commit `b3c0f2d`; rewriter/variants/extraction/decisions/judge unchanged,
the run's actual generator is recorded in `models_on_record` so the gate
refuses cross-model comparison):

| role | model | price (in/out per M) |
|---|---|---|
| control | `openai/gpt-4o-mini` (production default) | $0.15 / $0.60 |
| candidate 2 | `anthropic/claude-haiku-4.5` (created 2025-10-15) | $1.00 / $5.00 |
| candidate 3 | `google/gemini-3.8-flash` (created 2026-09-02, GA — not preview/stealth) | $0.75 / $3.75 |

Sets: entity-mismatch (12), counterfactual gate subset (10), fast20 (20),
proxy30 (30 — the 30 proxy-labelled answers' questions, one item per row of
`answers_proxy.csv`, all answerable from the seed corpus; see
`evals/proxy30/items.json`). Two runs per model, serial on the single dev
stack, credits re-checked between every run (guard $0.90 above the $0.75
floor).

Wave 1 (control all sets; gemini fast20 ×2 + cf:1) ran at `b3c0f2d`; wave 2
(control cf:2 + entity ×2 re-runs, all remaining gemini and haiku runs) ran
at `d9d15bb` (the KI-57 fallback-cap fix, which no wave-2 run exercised —
zero item failures on the fallback path in any wave-2 run), so no reported
arm mixes trees in a way that changes its result.

**proxy30 (30 items, proxy ruler):**

| arm | run 1 | run 2 | clean-arm mean |
|---|---|---|---|
| control | 0.9205 `01a105f3…`¹ | 0.8993 `01a105fc…` | **0.8993** |
| gemini | 0.9730 `01a10839…` | 0.9194 `01a10844…` | 0.9462 |
| haiku | 0.9624 `01a10852…` | 0.9641 `01a1085c…` | 0.9633 |

¹ one infra failure (pre-fix fallback truncation, KI-57) → arm excluded from
comparison per the owner's rule "an arm with errors can't be compared to one
without"; the floor comparison therefore uses control's clean arm.

**fast20 (20 items):** every arm 11/12 answered — the same items as the P1b
baseline; the one abstention is `injection-01` (RP-77 torque, KI-56,
pre-existing). 8/8 should-abstain items declined cleanly (0 unclean),
0 confident wrong. Faith: control 0.9938 / 0.9938
(`01a10603…`/`01a10728…`), gemini 1.0000 / 0.9950
(`01a10758…`/`01a1075f…`), haiku 0.9700 / 0.9850
(`01a10866…`/`01a1086c…`). Haiku's gap is two items, quoted in §5.6: the
battery item (0.8 vs control 0.875) and the firmware-3.1.0 pairing item
(0.6 — it infers "2 devices" from "earlier firmware allowed only 2",
control states the supported figure, ≥0.9).

**counterfactual gate subset (10 items):** every arm 6/6 answered + 4/4
clean declines, faith 1.0 in both runs, min claim support 1.0 (6/6) in both
runs, **0/10 forbid hits in both runs**, 0 confident wrong.
Control `01a10716…`/`01a1082e…`, gemini `01a10764…`/`01a10878…`,
haiku `01a10870…`/`01a10875…`.

**entity-mismatch (12 items):** every arm 12/12 clean declines, faith 1.0 in
both runs, 0 confident wrong. Control `01a10831…`/`01a10837…`,
gemini `01a1087a…`/`01a10880…`, haiku `01a10885…`/`01a1088b…`.

**Decision-engine mix (owner ask: which engine answered each decision):**
eval runs persist no per-decision engine row (verified: `run_events` holds
no decision events post-2026-10-03), so the source of record is the engine's
`jev failed, retrying on fallback` log line. Across every run reported above:
control 1 (proxy30:run1, pre-fix, small batch, completed), gemini 1
(fast20:run1, completed), haiku 0; all wave-2 runs 0. Every other decision in
every run was answered by jev (`typesafe/jev-1.13`, decisions endpoint;
fallback engine `nemotron-3-super-120b-a12b:free` under the 4096 cap from
`d9d15bb`). No comparable arm carries item failures.

**Cost per answer (OpenRouter credit deltas, driver-echoed per task):**

| arm | proxy30 (30) | fast20 (20) | cf (10) | entity (12) |
|---|---|---|---|---|
| control | ≈$0.003 (wave-1 block estimate²) | n/m³ | $0.0026 | $0.0035 |
| gemini | $0.0085 / $0.0105 | $0.0042 (cf:2) | $0.0019 | $0.0046 / $0.0056 |
| haiku | $0.0081 / $0.0087 | $0.0042 / $0.0047 | $0.0054 / $0.0060 | $0.0039 / $0.0039 |

² wave-1 control block: $4.3327 → $3.8424 over 8 task attempts (4 clean,
4 infra-failed attempts that still consumed most of their items' cost) →
≈$0.08/run ≈ $0.003/answer for proxy30; an estimate, marked as such.
³ n/m = not measured in a clean per-task window (credits-API single reads
are known-noisy; the delta is usable only where the driver echoed both ends
of the task). Per-set ratios vs control: cf/entity 0.7–2.2×; proxy30
2.7–3.5× using the control estimate.

**TTFT (probe, alone, 3 questions × 2 reps, full-pipeline first-token,
`/tmp/p2a_ttft_probe.py` — runner-exact contract):**

| arm | mean TTFT | vs control |
|---|---|---|
| control | 7.45 s (6 samples) | — |
| gemini | 9.00 s (4 samples; it abstained on the encryption question, both reps — observation, §5.7) | **+1.55 s, breaches the 1 s limit** |
| haiku | 6.69 s (6 samples) | −0.76 s |

Rule condition 4 (TTFT not lengthened by > 1 s) is therefore unmet for
gemini; haiku clears it. Condition 1 already fails for both candidates, so
the outcome is unchanged — recorded for the next bake-off.

**Rule evaluation (pre-approved):** switch the generator only if a candidate
**beats the control on confident wrong answers or grounding, matches it on
faithfulness (within 0.02), costs ≤ 3× per answer, and doesn't lengthen TTFT
by > 1 s**.

- Confident wrong answers: 0 vs 0 for both candidates (every set) — tie, no
  beat.
- Grounding: cf min claim support 1.0 vs 1.0 and 0/10 forbid hits vs 0/10 —
  tie, no beat.
- **Condition 1 is unmet for both candidates, so the rule does not trigger
  and the control stays** — regardless of the faithfulness/cost/TTFT rows,
  which are recorded above for the next bake-off. (Both candidates score
  higher proxy30 faith than the control's clean arm — gemini +0.047,
  haiku +0.064 — better than control but outside the 0.02 band; neither
  substitution was justified by a quality axis the control misses.)

**Winner: the control (`openai/gpt-4o-mini`) stays.** Recorded in KI-54 and
the plan's P2 line.

## 3. PRD §5 rows moved, per corpus (measured, not assumed)

| row | corpus | P1b baseline | P2a (control on fixed gates) |
|---|---|---|---|
| confident wrong answers | seed (fast20, run `01a10603…`) | 1 — `abstain-10` (5 GHz, label should-abstain) answered: *"There is no mention of any capability to run the enterprise management protocol over 5 GHz Wi-Fi"* (quoted in KI-43); abstention 7/8 | **0** — the item now declines cleanly; abstention 8/8, clean declines 8 |
| confident wrong answers | counterfactual (cf gate subset, run `01a1030b…`) | the K9 grounding miss | **0**; 4/4 clean declines |
| confident wrong answers | entity-mismatch (12-item set) | — (set did not exist) | **0/12**, 12/12 clean |
| minimum claim support | seed fast20 | n/a in P1b baseline (field postdates) | 0.909 / 0.818 (runs `01a10603…`/`01a10728…`) |
| minimum claim support | cf gate subset | 0.9333 (P1b baseline) | **1.0 / 1.0** (6/6 answers, both runs `01a10716…`/`01a1082e…`) |
| grounding (forbid hits) | cf gate subset | 57/58 followed in P1b milestone run 1 | **0/10 forbid hits, both runs** (`01a10716…`/`01a1082e…`) |
| faithfulness | seed fast20 | 0.9756 (5-run mean, spread 0.0357) | 0.9938 / 0.9938 (two clean control runs, `01a10603…`/`01a10728…`) |
| faithfulness | proxy30 (30, proxy ruler) | — (new set) | 0.9205 / 0.8993 (two control runs; run 1 carries 1 infra failure — §2) |

Data note: the 7 Shared AW-2000 copies were already deleted from the dev
database on 2026-10-03 (owner-approved, KI-54 data-cleanup section), so no
Shared copy was in scope for any run above; `veriforge_p1b` still holds its 7
copies and was not used by any P2a run. Nothing was deleted in this dispatch.

## 4. CI, credits, SHAs, time

- CI: TODO(item 6) — `gh workflow run ci.yml --ref p2a/answer-quality`, gate
  executes with both subsets; URL here.
- Credits (OpenRouter, `GET /api/v1/credits`; floor $0.75; guard $0.90 in
  the task driver): $4.51 before the D7 baseline (2026-10-03) → $4.3337
  after (D7 5-run entity baseline, ≈$0.18) → $4.3327 before the control
  block → $3.8424 after wave-1 control (proxy30 ×2, fast20 ×2 incl. one
  net-fail re-run, cf:1 + the two infra-failed cf/entity attempts) →
  $2.9189 after the wave-1 gemini block (proxy30 attempts ×2, fast20 ×2,
  cf:1, ≈$0.92) → $2.8019 after the wave-2 control re-runs (cf:2,
  entity ×2, $0.117) → $2.1722 after wave-2 gemini proxy30 → $1.3715 after
  the wave-2 haiku core (proxy30 ×2, fast20 ×2, cf ×2, $0.80) → $1.3191
  after wave-2 gemini cf:2 → $1.1857 after wave-2 gemini entity ×2 →
  $1.0924 after wave-2 haiku entity ×2 (wave 2 complete, 15/15 exit 0,
  guard never tripped) → $1.0314 after the TTFT probes (≈$0.06, one 10 s
  failed-attempt read on a malformed model id before the corrected probes)
  → TODO(CI gate run + final).
- SHA each run measured: item-0 before @ `f3a1521` (unchanged pipeline);
  item-1/2/3 measures @ their commits (`fa9a403`/`7fcb93f`/`8a5a622`);
  item-4 after + D7 baseline @ `5036b64`; bake-off wave 1 @ `b3c0f2d`
  (eval-harness-only commit); wave-2 re-runs @ `d9d15bb` (KI-57
  fallback-cap fix; §2 tree note — no wave-2 run exercised the changed
  path).
- Time per item: item 0 ~25 min; item 1 ~30 min; item 2 ~25 min; item 3
  ~30 min; item 4 ~45 min; item 5 ~9 h active against the 60-min slot
  (overrun dominated by serial model-run wall time: control ~2 h, gemini
  ~3 h, haiku ~1.5 h, plus two OpenRouter degradation windows forcing
  re-runs (~1.5 h) and the KI-57 root-cause fix + re-runs ~45 min; infra
  flag/proxy30 set/tests ~35 min); item 6 TODO(min).

## 5. What was not fixed, with the evidence

1. **RP-77 false abstention (pre-existing, not gate-caused).** "What torque
   should the RP-77 retaining screw be tightened to?" abstains because the
   only chunk carrying the 4 Nm answer (`field_service_note.md`) embeds a
   prompt-injection block; the sanitizer drops it
   (`chunk_injection_0` 0.96 ≥ `chunk_injection_drop` 0.70) before the
   sufficiency judge ever sees it. Per-item probe evidence: with the item-4
   gate active the run shows `sufficient: 0.02` and entity gate values 0.74/0.67
   (gate PASSED); with the pre-item-4 code (HEAD `8a5a622` swapped in, same
   probe) the identical `sufficient: 0.02` reproduces → the abstention
   predates the gate. New KI paragraph recorded; not fixed (out of scope —
   "fix, don't analyse").
2. **The proxy30 book-question low fidelity (both control runs).**
   "summarize Frankenstein in a few sentences" scored faithfulness 0.0 in
   both control runs despite a plausible answer (opened, two):
   - run `01a105f3…`: *"The story of Frankenstein follows Victor
     Frankenstein, a scientist who becomes obsessed with the idea of
     creating life. After much labor, he succeeds in animating a creature
     made from cadaver parts but is horrified by its appearance and
     abandons it…"* — faith 0.0
   - run `01a105fc…`: *"The novel 'Frankenstein' follows the story of
     Victor Frankenstein, a scientist who becomes obsessed with creating
     life. After extensive study and labor, he succeeds in animating a
     creature made from deceased body parts, but he is horrified by the
     result and abandons it…"* — faith 0.0
   Classification: the reviewer marks the summary's plot claims unsupported
   where the retrieved book chunks don't verbatim contain them — the known
   broad-question/summary-intent weakness the P2 plan owns (answerability
   `Noul` per passage, "summary intents judged on coverage"), not a P2a
   regression: the same item scores 0.571 on gemini run `01a10844…` and
   ≥0.9 on both haiku runs, i.e. it separates on generator behaviour, but
   no arm avoids the book-summary class entirely (haiku run
   `01a10852…` instead drops "Can I submerge an AW-2000-XP…" to 0.6 and
   "How many devices can I pair…" to 0.667 on that set).
3. **The 5 GHz item's label.** The seed set labels
   "Can the AW-2000-XE run the enterprise management protocol over 5 GHz
   Wi-Fi?" (`abstain-10`) `should_abstain: true`, and the P2a system declines
   it cleanly in fast20 — correct behaviour under that label, not a false
   abstention. (In P1b the item was answered — the 5 GHz over-inference —
   which is why P1b's abstention accuracy on fast20 was 7/8.) The identical
   question appears in the proxy30 set, where I audited it as answerable
   ("no — all models operate on 2.4 GHz", spec sheet) and labelled it
   `should_abstain: false`; the system abstains on it in every proxy30 run,
   so under that label it counts as a proxy30 false abstention. The owner
   already flagged this item as possibly mislabelled in P1b; the label
   question goes to the owner with the entity-mismatch baseline question,
   not to the gate. The one fast20 false abstention is a different item:
   `injection-01` — "What torque should the RP-77 retaining screw be
   tightened to?" (`should_abstain: false`, reference "4 Nm") abstains in
   every run because the only 4 Nm chunk carries the embedded injection
   block, which the sanitizer drops first (KI-56, pre-existing).
4. **Item-1 residuals rows 18/22** — quoted in §1.1; the recorded P1b
   answers themselves carry the errors, and the new reviewer now scores
   them as such.
5. **Gemini answers the global-summary request where the control abstains
   (bake-off observation, not a gate bug).** "Peux-tu résumer Madame Bovary
   ?" — control declines cleanly (run `01a105fc…`: *"Je n'ai pas trouvé
   suffisamment de preuves pour répondre à cette question. Ce que j'ai
   trouvé : Vos sources couvrent Madame Bovary.txt… Les sources
   récupérées ne contiennent pas suffisamment de preuves…"*, faith 1.0);
   gemini answers (run `01a10844…`: *"Les sources fournissent des extraits
   portant sur certains épisodes du récit… Voici ce que les sources
   couvrent : Les origines de Charles Bovary : Son père, ancien
   aide-chirurgien-major marié pour une…"*, faith 0.0). Same summary-intent
   class as §5.2; recorded so the next bake-off doesn't mistake the delta
   for a control regression.
6. **Haiku's two fast20 items (bake-off observation).** Quoted: run
   `01a10866…` battery item — *"The AW-2000-XE models offer up to 20 hours
   on a full charge [2]"* (faith 0.8 vs control 0.875 on the same item,
   run `01a10603…`), and the pairing item — *"Since firmware 3.1.0 is
   earlier than 3.2.1, this suggests you can pair 2 devices with an
   AW-2000-XE running firmware 3.1.0 [1]"* (faith 0.6; the inference the
   control states as the supported figure, ≥0.9). Minor inference drift in
   the generator, caught and scored by the existing reviewer — no gate or
   prompt change warranted.
7. **Gemini declined a plain fact lookup in the TTFT probe.** "What
   encryption does the AW-2000 radio link use?" — gemini abstained in both
   probe reps (the control and haiku answered). Probe-only observation
   (the question is not in any bake-off set); consistent with gemini's
   higher abstention tendency on the book-summary items (§5.2, §5.5). No
   action; relevant context if gemini is re-baked next dispatch.
