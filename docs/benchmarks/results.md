# Generator, books, held-out and Deep results

Measured 2026-10-22 on the local Compose stack with the acceptance runner and gate
(`scripts/acceptance.py`, `evals.acceptance_gate`). Every row is one draw unless it says
otherwise. Reports are kept outside the repository; the numbers are copied here. For the
decision layer see [`decision-layer.md`](decision-layer.md); for rerankers see
[`rerankers.md`](rerankers.md).

## Sets

- **Books**: 56 items over public-domain books in several languages (32 answerable, 20
  should-decline, 2 smalltalk, 2 library). It was 57 items until `outside-whitman` was
  removed on 2026-10-22 (see "Changes made after results").
- **Held-out**: 31 items over five books not used to set any threshold (21 answerable, 10
  should-decline).
- **Deep**: three splits for the agentic mode: dev 14 items, test 16, held-out 8.

## Changes made after results

Three changes were made after seeing results, each approved by the owner. The old numbers
stay below.

| Change | Before | After |
|---|---|---|
| `outside-whitman` removed from the books set (KI-80: the only passage says a distinction exists but not what it is, so the label was wrong) | 57 items; DeepSeek v5 draws 54/57, 55/57, 52/57; gpt-4o-mini 53/57 | 56 items |
| Grounded prompt v6 (v5 before) | DeepSeek books 54, 55, 52 of 57 | 56/56, 53/56 |
| Scorer fix `7e73ffe`, `98135f7` (decline detection widened: a clause before "do not say"; a closing scope caveat on a cited answer) | Sonnet 5.5 v5 on `outside-holmes-boston` counted as confident wrong | counted as a decline; the Sonnet v5 replay passes |

The scorer fix still misses some wordings (KI-87), which affects the Deep numbers below.

## Generator comparison (books, 56 or 57 items)

| Generator and prompt | Draws | Result per draw | Confident wrong | Gate |
|---|---|---|---|---|
| gpt-4o-mini, v5 (57 items) | 1 | 53/57 | 0 | fail: 3 of 33 answerable declined, 1 content miss |
| DeepSeek V4 Pro, v5, scorer before fix (57 items) | 3 | 54/57, 55/57, 52/57 | 0 | all three fail: 2, 2 and 3 false abstentions; content misses 2, 1 and 3 |
| Sonnet 5.5, v5 (56 items) | 1 | 55/56 | 1 under the scorer then in use (`outside-holmes-boston`) | fail |
| DeepSeek V4 Pro, v6, scorer after fix (56 items) | 2 | 56/56, 53/56 | 0 | draw 1 pass; draw 2 fail: 3 content misses (`quote-darcy`, `ml-tl-maria-clara`, `ml-zh-xiyou-nezha`) against a bar of 1 |
| Sonnet 5.5, v6 (56 items) | 1 | 54/56 | 1 (`outside-holmes-boston`) | fail; also `xl-en-samsa` answered in German |

Reading it: DeepSeek V4 Pro on v6 had no confident wrong and no false abstention in either
draw. Its books content-miss bar (at most 1) was met in 1 of 2 draws; the recurring misses are
multilingual and quote items, mostly a reply in the wrong language (KI-86). Sonnet 5.5 had no
false abstentions in either draw and no content miss on v5 (one wrong-language reply on v6), but a confident wrong on a
should-decline item in its v6 draw (and in v5 under the earlier scorer); that reply is counted by the
scorer, and a reader may classify it differently (KI-87). p50 time to first token: DeepSeek 10.7 to 12.1 s,
Sonnet 12.9 to 14.9 s. Mean answer length on 32 answer items: DeepSeek v6 607 and 606
characters, Sonnet v6 995. The generator choice (ADR-007) rests on these draws; two draws is a
small sample.

DeepSeek is third-party served through OpenRouter, so latency and data handling vary by
provider.

Cost: the generator price recorded in `config.py` ($0.4427 / $0.8853 per 1M tokens) may be stale
against the public list ($0.955 / $1.911) and has not been checked against the billed rate
(KI-90). This page therefore quotes quality, not generator cost.

## Held-out (31 items)

| Run | Result | Confident wrong | False abstentions | Content misses |
|---|---|---|---|---|
| gpt-4o-mini (R2a close, 2026-10-19) | 29/31 | 1 (`ho-near-vlad`, a false-premise question; KI-78) | 0 of 21 | 1 allowed |
| DeepSeek V4 Pro, v5 | 31/31 | 0 | 1 of 21 | 0 |
| DeepSeek V4 Pro, v6 | 31/31 | 0 | 0 of 21 | 0 |

`ho-near-vlad` declined cleanly on DeepSeek. Sonnet 5.5 was not run on held-out (its books
v6 draw failed, and the run rule was to stop there). The gate values (floor 0.455, IsUse 0.47,
stream line 0.60, entity guard 0.5) run on Jev, not on the generator. One held-out draw
per generator is evidence, not proof.

## Deep mode, draw 1 on the frozen splits

Build `b885ac2`: a Deep run that reaches the hop cap now goes through the same evidence
floor, entity guard, generation and IsUse as one the controller called sufficient (ADR-006
amendment 2026-10-23). DeepSeek V4 Pro, prompt v6, one draw per split, no errors or
timeouts. All 38 questions and answers were in English.

Gate verdict: fail on all three splits against the bars that were declared before the run.

| Split | Passed | Confident wrong (gate-counted; bar 0) | False abstentions (bar <= 1 test and held-out, <= 2 dev) | Content misses (bar <= 1) | Clean declines | p50 item wall clock (target 30 s) | p50 TTFT |
|---|---|---|---|---|---|---|---|
| test (16) | 10/16 | 1 | 4 of 10 | 1 | 5 of 6 clean, 1 counted as confident wrong | 25.3 s | 24.3 s |
| dev (14) | 6/14 | 3 | 2 of 10 | 2 | 1 of 4 clean | 33.6 s | 32.5 s |
| held-out (8) | 5/8 | 2 | 0 of 4 | 0 | 1 of 4 clean | 30.8 s | 29.8 s |

Clauses met: false abstentions on dev (2 against 2) and held-out (0 against 1); content
misses on test (1) and held-out (0). Clauses not met: confident wrong on all three
(counted by the gate), false abstentions on test (4 against 1), content misses on dev (2
against 1), and the 30 s p50 on dev and held-out.

### Which failures are scorer artifacts and which are real

**Scorer artifact (KI-87).** I read the first 330 characters or so of every reply the gate
counts as confident wrong (6 across the three splits). All are prose declines that carry citations, for example "The sources do not name
an advocate who defends Justine Moritz", "The sources do not give the Time Traveller's
full name". The scorer's decline detector is a regex over wordings and does not match these,
so it counts them as asserted answers. Two that it does match (`sherlock-eurus`,
`twocities-stryver-first-name`) are scored as unclean declines. By reading, no decoy asserted
a fabricated fact; n = 1 per item and only the start of most replies was read. The
confident-wrong clause cannot be met until prose declines are classified correctly or the
decoys decline without generating.

**Real.**

- **False abstentions on compound questions.** Test 4 of 10 and dev 2 of 10. Several are a
  hop-1 "sufficient" verdict followed by an entity-guard or IsUse decline, not a cap-out
  (`pride-pemberley-netherfield`, `sherlock-two-stepfathers`, `cross-two-elizabeths`,
  `noli-ibarra-project`); two more were generated after the cap and declined by IsUse
  (`frankenstein-first-and-clerval` 0.20, `bovary-emma-poison` 0.45 against 0.47). The cause
  of the test-split abstentions was not diagnosed. Change A (generate after the cap) fixed
  one earlier dev false abstention (`frankenstein-creature-books` now answers).
- **Latency.** p50 item wall clock 33.6 s on dev and 30.8 s on held-out, over the 30 s
  target (25.3 s on test).
- **Noli entity guard.** The entity guard declines `noli-ibarra-project` (Spanish passages
  against an English question) both times, with entity readings of at most 0.46 to 0.51
  against the 0.5 line.

**Label dependent, not counted either way:** `verwandlung-apple` ("An apple" where the label
wants the German "Apfel") and `rashomon-servant-theft` (correct English facts; the label
requires a Japanese mention) are content misses by label, not by fact.

**Before Change A** (dev, 14 items, ADR-006 amendment evidence): 4 false abstentions of 10, 1
content miss, 0 confident wrong, and one harness timeout on a decline item (`quixote-rosinante-birth`; traced
to a stalled decision fallback call with no timeout and a database statement timeout, KI-88
and KI-89, not fixed). Offline replays of the stored pools found the needed fact in the
first hop's pool at rank 1 to 3 for three of the four, the controller deciding "need more"
because the second clause of the question was interpretive, and the pooled floor grade
unable to separate those items from the decoys (0.82 to 0.91 against 0.61 to 0.75, floor
0.455).

Deep is not at its bar. It is being improved; the next changes are listed in the plan, not
claimed here.

## Cost of these runs

Key-usage deltas, upper bounds that include non-generator roles: DeepSeek v6 books $1.30 and
$1.43, held-out $0.77, Sonnet v6 books $1.73; Deep draw 1 $0.34 (test), $0.38 (dev), $0.26
(held-out); stack builds about $0.37 to $1.0 each. They are credit deltas, not per-call
generation records, and are not a cost-per-query claim for the generator.
