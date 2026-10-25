# Known issues

Open defects only. Triaged 2026-10-12: every entry is either tied to the
phase whose `make check-*` target it breaks, or tagged `post-beta`.
The Phase column is authoritative; section placement below is from the first triage.

Rules (`docs/conventions/agents.md`, "Finish lines and measurement"):
- When you fix one, move it to the archive in the same commit, with the fixing commit hash.
- A new finding that breaks no check is added under **post-beta** and opens no lane.
- New IDs continue from KI-98.

## Index

| Phase | KI | Summary |
| --- | --- | --- |
| closed 2026-10-23 | KI-78 | `ho-near-vlad` declines cleanly on DeepSeek V4 Pro v6 (held-out, 2 runs); closed by the ADR-007 generator change |
| closed 2026-10-23 | KI-79 | `plot-speckled-band` passes in all 5 DeepSeek V4 Pro draws; closed by the ADR-007 generator change |
| before deploy | KI-86 | fixed in code (`47f83d5` retry on held answers, `7da07ec` language named up front for non-English questions); closes after a books draw shows no `language_mismatch` on two draws (paid, waits for the owner) |
| before deploy | KI-95 | fixed (`7da07ec`): the IsUse decline is translated to the question's language; closes with KI-86's draw |
| closed 2026-10-25 | KI-96 | web sources showed no title or URL anywhere; retrieval, citations and the UI now carry both (`1e1f7d1`) |
| closed 2026-10-25 | KI-88 | the decision fallback has one deadline over its retries and failover, `llm_timeout_seconds` = 90 s (`2b92d0c`); a tighter ceiling would break the slow judge-only rerank |
| closed 2026-10-26 | KI-93 | Deep runs Auto's conflict check and its trace matches Auto's stages (`da72a48`, `60d3214`) |
| R3 (Deep) | KI-97 | Deep false abstentions: replay found entity-guard stops (locator words, a starved second clause) and IsUse stops that look like the 2048-token generator budget used up by reasoning; the controller-grade change is merged but unverified |
| post-beta | KI-98 | Tesseract OCR (beta) reads text pages but not ruled tables (1 of 18 cells in the bake-off); no accuracy number on real scans yet |
| UI redesign | KI-92 | UI pass leftovers: duplicate Escape handlers, sub-44 px mobile targets, F-34 tiny text, live specs not run, F-25/F-26 checked on mocks only, two README nits |
| closed 2026-10-25 | KI-91 | usage recording selects only the run's aggregate ledger row (`781714a`) |
| closed 2026-10-25 | KI-90 | generator price constants set to the OpenRouter list price after a billed-rate check (53 calls billed 0.98x of it) |
| before deploy | KI-94 | every run triggers an async quality judge on Haiku 4.5 (about $0.007 per run, more than the generator); model is a role; deployed `trace_sample_rate` decided (0.1), set it at deploy |
| closed 2026-10-25 | KI-89 | the retrieval statement timeout is reset right after the statement (`2b92d0c`); two hops interleaving on one session can still briefly reset each other's bound |
| R3 (scorer) | KI-87 | decline detection is a regex over wordings; new phrasings slip past it (3 found in 3 days) |
| closed 2026-10-22 | KI-80 | outside-whitman removed from the books set: the only passage says a distinction exists but not what it is |
| R3 (floor) | KI-81 | the evidence floor flips on borderline items: the grade varies 0.444-0.468 around 0.455 between runs |
| check-work (CI) | KI-82 | Playwright specs are not run in CI; paid evals are manual |
| R3 (reviewer) | KI-83 | citation precision is claim-level support; per-citation verification is not done |
| phase 3 (latency) | KI-84 | `our_overhead_ms` subtracts overlapping provider calls (ingress and rewrite run together); it can go negative |
| closed 2026-10-25 | KI-76 | the sweep settles reserved ledger rows of terminal runs past a 5 minute grace (`781714a`) |
| check-stable | KI-32 | record of faithfulness variance; gate tolerances already set |
| check-stable | KI-43 | absence-claim verdict flips between runs (grader quality) |
| check-stable | KI-49 | reviewer rarely makes an unsupported judgement itself |
| check-stable | KI-51 | cf subset spread 0.0667 vs 0.06 band |
| UI redesign | KI-22 | mostly closed by UI slice B (`d8922a2`); leftovers: Trace section navigation, per-area decision numbers only in the static Benchmarks tab (reranker on live events done, `da72a48`) |
| closed 2026-10-24 | KI-74 | composer Filters popover with a Playwright spec (UI slice A, `c7275c6`) |
| UI redesign | KI-65 | screenshots and tab-order audit; the UI pass is merged, so the re-shoot and audit can run now |
| before deploy | KI-59 | uvicorn forwarded_allow_ips must match the deployed proxy |
| before deploy | KI-63 | demo credit-outstanding cap still open; only matters if DEMO_ENABLED=true |
| before deploy | KI-64 | owner data decision: conflict pair in Shared, eval corpus visibility |
| post-beta | KI-8 | six Playwright specs make live LLM runs instead of replaying fixtures |
| post-beta | KI-85 | decision-engine thresholds (`entity_match`, guards, IsUse) are keyed `"jev"` / `"fallback"` in code; decision-model pluggability (Laya, Microsoft-Decision-1) must make them per provider |
| post-beta | KI-39 | web-chunk sweep undercounts deletions (return value only) |
| post-beta | KI-69 | reasoning-mandatory retry in providers/llm.py only serves free endpoints; dead on supported config |

---

# check-stable

## CLOSED KI-57: The decision fallback's output cap (512) truncates the batched decision JSON, failing the whole item whenever jev degrades

Closed 2026-10-15 (phase R2a-2 item 3). The truncation cause was fixed on
2026-10-05 (P2a item 5, below); what stayed open was the behaviour behind it —
**a fallback failure still failed the item**. Both are fixed now.

The degradation half of it was confirmed live, not theorised. The R2a
acceptance run aborted at item 25 of 57 with exactly this, from its own logs:

```
WARNING:decisions.engine:jev failed, retrying on fallback: jev http error:
ERROR:decisions.engine:shadow fallback call failed
decisions.fallback.FallbackError: fallback returned non-JSON: Expecting value: line 1 column 1 (char 0)
ERROR:graph.runner:run failed
{"event":"run.failed","error_code":"decision_unavailable"}
```

A socket timeout, then one unreadable reply, then a whole turn lost. The
provider timeout is external; **the fail-the-run behaviour was ours.**

- **Fix, at the engine** (`decisions/fallback.py`): the output cap is now sized
  to the batch (`fallback_max_tokens`, never below the role's own cap) instead of
  fixed, so the rerank rubric's per-passage four-way distributions — the shape
  KI-57's note calls "bigger" — have somewhere to go; the call requests
  `response_format={"type": "json_object"}` instead of relying on the prompt's
  "no prose"; an unparseable reply is **retried once** and then the batch is
  **split in half, recursively, until it is one question**, because a truncated
  object truncates deterministically and re-asking the same batch returns the
  same cut.
- **Fix, at every stage** (`graph/stages/common.decide_or_degrade`, and the
  call sites): an unreachable decision layer is now each stage's **own**
  degradation, never a failed run. Ingress → the module's defaults (`lookup`,
  `both`, guards `pass`). Rerank → fused order (unchanged; it already caught
  `DecisionUnavailable`). **The gate → a FAILING gate**: below the floor, into
  the corrective retrieval, and — while the layer is down — a skipped retry and
  an abstention that cites nothing, because an unreachable grader is not
  evidence. The entity guard fails with it. The sanitizer keeps every chunk, the
  branch it already takes for a passage the grader skipped. The reviewer marks
  every claim `unsupported`. The output guard delivers as-is. Deep's controller
  takes another hop.
- **The trace can tell the two apart.** `Decision.engine` gains
  `unavailable`, a third value that is not an engine: a row reading 0.0 from
  `jev` says "the evidence was judged thin", and this says "nobody could judge
  it". `retry_skipped` carries it too, so a decline that skipped its corrective
  re-query because the layer was down does not read as a judgement that the
  evidence was clearly absent.

**Tests.** `tests/decisions/test_ki57_degrade.py` (15): the cap grows with the
batch and covers a 40-passage rubric batch; JSON output and the sized cap are
asserted on the request; non-JSON and truncated replies, the retry, and the
recursive split with its call bound; the Jev-timeout path unchanged; ingress's
defaults; a whole `prepare_auto_run` with a dead engine that still returns a
finished, abstaining run, records `unavailable` rows, and skips the corrective
re-query. Web: `DecisionTimeline.test.tsx` (5) on the third badge state.

**Log history, kept because the entry it closes is the record of it:**

**Still to do, not this entry's job:** `make check-stable` phase 2 injects a Jev
outage. That injection is what proves these paths on a live run; the tests here
are fakes, and a fake that agrees with itself proves the wiring, not the
provider.

Logged 2026-10-04, P2a item 5 (the generator bake-off), from the control
runs. During an OpenRouter degradation window (raw
`Cannot connect to host openrouter.ai:443` errors on ordinary generator
calls), the batched decide calls failed on the jev endpoint and fell to
the OpenRouter fallback model; the fallback's decision JSON came back
truncated (`FallbackError: fallback returned non-JSON: Unterminated
string` at ~1.7–2.1 K chars in every case) and the item failed. One
cf-gate run lost 5/10 items, one entity-mismatch run lost 10/12, while
healthy-window runs of the same sets lost 0/10 and 1/12. The
entity-mismatch set is the most exposed: its batched post-sanitize decide
carries 6–8 Noul questions — the largest decision JSON the system asks
for. Whether the truncation is mid-stream connection loss or the fallback
model's output cap does not fit the batched decision JSON is not
distinguishable from the error text; the affected control runs were
re-run on a healthy network and the bake-off numbers use those re-runs.
Reliability of the fallback path under degradation (truncate-or-fail,
and whether a cap check is warranted) is a question for a later
dispatch — not fixed in P2a.

- **Note (2026-10-05, cause found and fixed, P2a item 5):** re-runs of the
  affected sets truncated at the **same character offsets** (1859/1901/
  2044), which rules out mid-stream connection loss and identifies the
  deterministic cause: the `decision_fallback` role had no entry in
  `llm_max_tokens`, so the fallback call ran under the 512-token default.
  The batched decide response (sufficient + relevance + one Noul per
  top-k passage; 8–12 answers with reasoning) exceeds 512 completion
  tokens, so whenever jev degraded and the batch fell to the fallback
  engine, the JSON came back cut mid-string and the item failed —
  deterministically, on every re-run. Fix: `config.py` gives the
  `decision_fallback` role its own cap (`decision_fallback: 4096`, wide
  headroom over the largest observed response). Tests: a 12-question
  batch round-trips through `FallbackEngine.decide`
  (`tests/decisions/test_fallback.py`), and the 12-answer fixture
  response is asserted to exceed the old default cap while fitting the
  new one; `tests/providers/test_llm_limits.py` asserts the role's cap
  reaches the provider request (mutation: dropping the entry fails both).
  The affected control sets are being re-run on the fixed tree; the
  remaining open question is the degrade-to-fail behaviour itself
  (a fallback failure still fails the item) — later dispatch.

---

# UI redesign

## KI-22: Trace tab shows mostly Jev calls; Metrics missing quality detail

**Status: mostly closed 2026-10-24.** UI slice B (merge `d8922a2`) de-duplicated the Trace
(each step once, one evidence gate, decisions grouped by stage), added the "This run" block
to Metrics (mode, model, source, reranker), split the waterfall, and showed the reviewer
verdict on source cards and the Citations tab. Open leftovers:
- No section navigation inside the Trace tab.
- Done in `da72a48` (UI polish): the reranker is on `RunStarted`, so a live run shows it in Metrics.
- Per-area decision numbers (Jev vs judge) exist only in the static Benchmarks tab; the live
  API aggregates by decision name only.
- Batch 1 backend step coverage below was not part of slice B; check it before closing.

Original design (2026-09-30):

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

## KI-65: Lane E leftovers

Logged 2026-10-09 (lane E report). Open, low priority.

- The waterfall screenshot reads "TTFT not measured" (recorded before the
  field existed); a re-shoot costs one run.
- The six per-question tour screenshots are scripted but not captured.
- Tab order was spot-checked on two screens, not audited across auth, admin
  and the decision layer.
- "Show steps" has no focus ring by design (design-system exception).
- Deep (question 6) stays behind `DEMO_ALLOW_DEEP`; reserving about 30 000
  credits for an unauthenticated visitor is a spending decision.
- `apps/web/package-lock.json` changed by about 2.6k lines each way; confirm
  it is only the axe dependency.
- Observed TTFT in the rehearsal was 12.4 to 13.8 s; lane B's target, not E's.

---

# before deploy

## KI-59: The rate limiter's real security boundary is uvicorn's proxy-header trust list

Logged 2026-10-06 (lane C, item 4) while testing the signup limiter.

- **What:** `auth/router._client_ip` returns `request.client.host` and never
  reads a header, and its docstring claimed that was what makes the limiter
  safe from `X-Forwarded-For` spoofing. That claim is wrong, and a test
  written to check it failed rather than passed.
- **Evidence.** With two signups from one client and a third carrying
  `X-Forwarded-For: 203.0.113.7`, the limiter created a bucket keyed
  `ip:203.0.113.7` — the header value. Uvicorn runs `ProxyHeadersMiddleware`
  by default (`proxy_headers=True`) with `forwarded_allow_ips` defaulting to
  `127.0.0.1`, so it rewrites `scope["client"]` from the header *before* any
  handler runs. Quoting uvicorn's own signature:
  `proxy_headers: bool = True`, `forwarded_allow_ips: list[str] | str | None = None`.
- **So the real boundary:** an untrusted peer cannot spoof the bucket,
  because its connection is not from an allow-listed address — the safety
  comes from that list, not from our code. Ours only has to not read headers
  itself, which is what `tests/auth/test_invites_and_rate_limit.py` now pins.
- **The operational consequence, which is the part that matters.** Behind
  Caddy on the same host (127.0.0.1) the header is trusted, so the limiter
  sees the real client and everything works. **If Caddy runs in its own
  container**, its address is no longer `127.0.0.1`, uvicorn stops trusting
  the header, every request appears to come from Caddy, and the per-IP limit
  becomes a global one: one user exhausting their budget locks out
  everybody. Silent, and it looks like the limiter working. Lane A must set
  `forwarded_allow_ips` to Caddy's address (or `*` only if something else
  guarantees the proxy), and the deploy check should confirm two different
  clients get two different buckets rather than one shared.
- **Test that found it:** `test_the_ip_key_is_the_socket_peer_or_uvicorns_rewrite_of_it`,
  which also records that the obvious "a forged header does not reset the
  limiter" test is wrong for this stack.

## KI-63: `POST /auth/demo` has no kill switch and no global spend cap

Logged 2026-10-09 (lane E review). **Mostly fixed** on `beta/demo-guard`
(2026-10-11): `03b1977` (kill switch), `8e5ea76` (daily cap), `9de8a16`
(login page), plus this branch's runbook section. One part is **not** done —
see "Still open" below.

- **What:** the route is unauthenticated, mints an account and a credit
  budget, and is always on. The only limit is 5 per hour per IP, kept in
  process memory. Many source addresses, or a restart, defeat it, and nothing
  bounds the total credit demo accounts can spend. In production,
  `signup_mode=invite` does not apply to it.
- **Fix:** `DEMO_ENABLED` (default off; set only in the compose env when the
  owner wants the demo), plus a cap on demo accounts created per day and on
  total demo credits outstanding. Tests: disabled returns 404, the daily cap
  returns 429 across distinct IPs.
- **What landed.** `DEMO_ENABLED`, default **false**, checked before the rate
  limiter and before any database work: off answers 404 `demo_disabled` and
  creates nothing, and costs the visitor none of their hourly tries.
  `DEMO_DAILY_CAP`, default **50**, counted over a rolling 24 h **from the
  database** (demo-role users by `created_at`), so a restart or a second
  process cannot reset it; over the cap is 429 `demo_capacity` with a
  `Retry-After`. The check and the insert are one atomic step
  (`SELECT … FOR UPDATE` on the demo plan row), proven by a deterministic
  test that fails 8/8 without the lock — see the test docstring for why the
  obvious `asyncio.gather` versions of it proved nothing. Worst case at the
  shipped defaults: **$15.00 per rolling 24 h** ($20.00 ignoring the 24 h
  account TTL), derived in `docs/ops/runbook.md`. `GET /auth/demo/limits` is
  deliberately left outside the switch, so turning the demo off does not start
  erroring signed-in composers.
- **Still open.** The cap is on **accounts created**, not on **total demo
  credits outstanding**, so the second half of the original fix is not done.
  The exposure is bounded (the runbook figure) and each account is individually
  capped by the ordinary quota gate at 60 000 credits/5 h, but nothing stops
  the *sum* across 50 accounts from being spent slowly. Closing it needs a
  sum-over-demo-accounts check in the same locked section; not done here, and
  it is a deliberate omission rather than an oversight. Worth it only if the
  owner wants a hard ceiling below the $15/day figure.

## KI-64: The demo tour cannot show a conflict, and the eval corpus is shared

Logged 2026-10-09 (lane E review). Open; a data decision, not code.

- Tour question 3 abstains like question 2, because the Shared library is
  eleven novels and none contradicts another. A conflict needs two disagreeing
  documents (the warranty pair) put into Shared by the owner.
- `eval-seed-corpus` is `visibility='shared'`. `make seed-demo` warns but does
  not change it. Decide before the beta whether visitors may retrieve from it.

---

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

## KI-32: Faithfulness moves between runs because the generator rewrites the answer, not because the judge disagrees

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
- **Step 2 ran, and it did NOT work (2026-10-02, D5, three fast20 runs on
  `1008e08`).** The faithfulness means are **0.98056 / 0.90833 / 0.91583** —
  a spread of **0.0722**, against 0.0300 before the pin and a bar of 0.03.
  So pinning extraction to 0 did not reduce the spread; on these three runs it
  is 2.4x larger. **Proposal step 3 (raise `FAITHFULNESS_DROP`) is not the
  answer, because the spread is not variance** — see KI-37. One single item
  ("What does the AW-2000 package contain?") scores 1.000 / 0.000 / 0.000 and
  accounts for the entire failure: excluding it the spread is **0.0234**,
  inside the bar. Pinning extraction cannot fix a generator that intermittently
  answers with a list of filenames.
  - What the pin *did* do, for the record: the claim counts on the moving items
    still differ per run (5/2/2, 1/5/5, 3/2/2), which is expected and not
    evidence against the pin — extraction is deterministic *given an answer*,
    and the answers still differ. So the pin is still correct on its own terms
    (a parsing call should not be stochastic) and should stay, but it is not
    the lever for this metric.

- **Step 3 taken as a tolerance, not as a claim the variance is fixed (2026-10-02,
  D7, owner decisions A9/A10).** D6's four runs on the merged tree put the true
  spread at **0.05625** (1.00000 / 0.97500 / 0.98333 / 0.94375) — outside the
  0.03 bar and about what this entry predicted, and larger than the 0.0722 D5
  saw only because the KI-37 item is fixed. So the 0.03 bar is now **0.06**
  (A9), reset at P2's generator-temperature decision and again at P1b, and an
  absolute **0.90 floor** (A10, PRD v3 §5) sits under it.
  - **What the widening does and does not say.** It says the measurement is
    noisier than the bar assumed. It does **not** say the variance is handled:
    the cause identified above — generator temperature 1.0 changing how many
    checkable claims an answer makes, which moves the *denominator* of the mean
    — is untouched, because pinning the extractor cannot reach it. Proposal 1
    from this entry is still correct on its own terms and is still not the
    lever for this metric.
  - **The structural point, which the 0.06 makes sharper rather than softer.**
    Faithfulness on fast20 is a mean over ~50 claims drawn from 20 items, and
    four items decide it; a 0.06 window is 2% of that mean. So the gate now
    tolerates a move that is a whole item's worth of claims, and the floor is
    what stops that from compounding. **P2's generator-temperature decision and
    P1b's per-corpus subsets are still the real fix**, and both are named as the
    reset for the number — this entry stays open until one of them runs.
  - **Measurement of the fix is still owed.** Whether pinning the *generator*
    drops the spread below 0.02 has never been run, and this entry is where that
    result belongs when it is.

## KI-39: The web-chunk sweep's return value undercounts what it deleted

Logged 2026-10-02, found while scheduling the sweep (P6).
`retrieval/web.py`'s `sweep_expired_web_chunks` returns
`len(pages) + orphaned_chunk_rowcount`. The chunks that belong to an expired
`web_pages` row are deleted by the per-page `delete(Chunk)` statement and are
never counted, so a sweep that removes 6 rows by that path reports 2. Nothing
read the return value until P6 put it in an hourly log line, where an operator
comparing it against table counts will see a mismatch. Not fixed here: it is a
reporting nit in code this item did not otherwise touch, and the test asserts
the weaker true contract (rows gone, count non-zero) with the reason recorded.
The fix would be to accumulate the rowcount of the per-page deletes.

## KI-43: An absence claim is judged `unsupported` in one run and `supported` in the next, and it costs a third of the item's faithfulness

Logged 2026-10-02 (D8 item 5), from the per-item exports of CI runs
`36983971448`, `36984829138` and `36985348875` on `e3c66d5`. Found because D8
item 3 put `scripts/eval_dump_stages.py` into the eval-gate job — this question
was unanswerable before that, which is the point of the change.

- **What.** One fast20 item — *"Can the AW-2000-XE run the enterprise management
  protocol over 5 GHz Wi-Fi?"* — is **1.000 in all six local runs** and in two of
  the three CI runs, and **0.667 in the third**. It accounts for essentially the
  whole of CI's item-level difference from local. The three runs retrieved the
  same passage: the leading context digests are `7bf25cef4d1933c9` and
  `d2fd51b97845a164` in **all three**, so this is not retrieval.
- **The mechanism.** The answer in the failing run asserts an *absence* — "There
  is no mention of any capability to run the enterprise management protocol over
  5 GHz Wi-Fi" — and that claim was judged:

  | run | faithfulness | context_recall | the absence claim |
  | --- | --- | --- | --- |
  | 1 | 1.000 | 1.0 | not extracted |
  | 2 | **0.667** | **0.0** | **`unsupported`, p=0.0, `citation_ids: []`** |
  | 3 | 1.000 | 1.0 | `supported`, p=0.59, cites [1] |

  The same claim text, from the same context, got opposite verdicts. In run 2 it
  carries **no citation**, and an uncited claim scores 0 — so one negative claim
  takes a third off the item. `context_recall` going to **0.0** in the same run
  is the same judge disagreeing a second time on the same evidence.
- **Why it matters more than one item's score.** **KI-32** measured Jev's
  `claim_verdict` as stable across 64 claim texts that recurred between runs,
  and D7 leaned on that to argue the spread was *not* judge noise and was
  upstream of the judge. This is a direct counterexample on one claim: a text
  that recurred, with identical context digests, judged both ways. Absence and
  negative claims ("the sources do not say X") are the case where a
  support-verdict grader has nothing to point at, and they are exactly what the
  `not_in_sources` items depend on.
- **Not fixed here, deliberately.** This is a grader-quality question, it is
  P1b's ("validating the graders against human labels"), and the prompt for D8
  puts the eval sets and the graders out of scope. Recorded, not tuned: the
  tolerance was **not** widened and no item was re-labelled.
- **Next step.** At P1b, when the graders are validated against human labels,
  measure this case specifically — **uncited / absence claims** — rather than
  only well-cited affirmative ones. The useful question is whether a claim that
  can have no supporting citation should be routed to a different verdict than
  `unsupported`, since today it is scored as a faithfulness failure of the
  *answer* for asserting something the corpus genuinely does not say.

**Consequence for `fix/eval-baseline`: none.** Rule A applied, the branch's
baseline is unchanged, and the gate passed all three CI runs.
## KI-49: The reviewer's `unsupported` verdict is almost never made by a judgement

Logged 2026-10-02, from P1b item 6's sampling. Across D7's six runs the reviewer
returned 175 claim verdicts: 162 supported, 5 partial, 7 unsupported, 1 contradicted.
Six of the seven `unsupported` verdicts are not judgements at all — TRD §10 step 3
scores a factual claim with **no citation** `unsupported` without a Jev call. So the
reviewer made exactly one `unsupported` call and one `contradicted` call across 120
items, and those two are the only rows available to check either verdict against. The
judge-validation sheet excludes the six uncited claims (they have no passage to read,
so the owner would be judging how a claim sounds rather than whether the reviewer is
right) and says in its README that agreement on `unsupported` and `contradicted`
**cannot be computed from this pool**. The gate's faithfulness formula
(`supported + 0.5 × partial`) is not affected — the uncited claims score 0 either way
— but a claim-verdict agreement number over the whole pool would be ~95% agreement
decided entirely by the supported/partial split, and would look like evidence about
the reviewer when it is evidence about the corpus. Getting real `unsupported` and
`contradicted` traffic needs items whose answers assert things the sources do not
support: the counterfactual set's `forbid` items are built for exactly that.

## KI-51: The cf gate subset's first five-run spread is 0.0667, not 0.06

Logged 2026-10-03, from the first counterfactual baseline. Both D7 conditions
held except the faithfulness range: across 5 serial runs the cf gate subset
measured **1.0 / 0.975 / 1.0 / 0.9333 / 1.0** — mean **0.9817**, spread
**0.0667**. The one low run put a single item at 0.75 against a baseline of
1.0 — a 1-item tail outside the measured 0.06 band. Every run was ≥ 0.90,
10/10 items scored in every run, judge coverage 10/10, overhead attributed
10/10. The baseline file is written from the mean of those 5 runs with the
spread recorded. Not retuned: a ~10-item subset with ~0.06 spread means the
band is the size of one item, and the practical guard stays the 0.90 floor
plus the three-run retry. Revisit when the generator's temperature or the
subset's size changes.

## KI-69: `post-beta` — the reasoning-mandatory retry in `providers/llm.py` exists only for free endpoints

Logged 2026-10-12 (phase 1, `make check-work` on `beta/phase1-check-work`).
**post-beta:** breaks no check, so it is a note and not a lane.

- **What:** `_acomplete` (`apps/api/providers/llm.py:254`) retries once without
  `extra_body.reasoning.enabled` when the provider answers "Reasoning is
  mandatory". Its docstring names the only case it was written for:
  `openrouter/free` resolving to `nemotron-3.5-lightning:free`.

- **Why it matters now:** phase 1 made `openai/gpt-4o-mini` the model every
  non-Jev role and both fallbacks resolve to, and made production refuse to
  boot with a `:free` binding. So the branch is unreachable on any supported
  configuration, and it is a retry that doubles a call on a paid model — dead
  weight rather than a defect, which is why it breaks nothing.

- **What to do:** delete it once nothing in `scripts/seed_models.py --free`
  needs it, or keep it deliberately as a provider-compatibility retry and drop
  the free-model sentence from its docstring. Cheap either way; not a phase-1
  blocker and not a step-4/5 risk.

## KI-74: The composer has no filter UI (SR-6)

- **What:** retrieval filters (source type, document, tag, date range, file type) are accepted by the API and narrow results server-side, but the chat composer offers no control to set them.
- **Closed 2026-10-24** by UI slice A (merge `c7275c6`): Filters popover in the composer, mocked Playwright spec `composer-filters`.
- **Phase:** UI redesign.
- **Done when:** the composer sets every SR-6 filter the API accepts, with a Playwright spec proving a filter narrows the cited sources.

## KI-76: credits stay reserved if the process dies between completion and settlement

- **What:** `execute_run` marks a run `complete` with `settle_usage=False` while
  async scoring runs, and settles the ledger in a background task after scoring
  (`graph/runner.py`, the `_finalize` call and `_settle_after_scoring`). A hard
  crash in that window leaves the `usage_ledger` row `reserved`.
  `sweep_stale_runs` selects only `status == "running"`, so nothing ever
  reconciles it. TRD §14: credits are settled even on failure.
- **Found:** outside review, 2026-10-17; confirmed by reading the code, not reproduced.
- **Phase:** check-stable (the worker-kill fault).
- **Done when:** a sweep settles `reserved` ledger rows whose run is terminal
  and older than the scoring timeout, with a test that kills between
  `_finalize` and settlement and proves the row settles.

## KI-78: a false-premise question is answered, not declined

- **What:** "What is Count Dracula's first name?" (held-out `ho-near-vlad`). The
  books give none. The generator answered "Dracula", quoting "I am Dracula", and
  IsUse passed it (0.68-0.72) because the quote supports the sentence. Counted as a
  confident wrong answer; held-out bar is 0.
- **Found:** the held-out run, 2026-10-19 (R2a close). Reproduced twice on
  `gpt-4o-mini`; `gpt-4o` said "the sources do not provide Count Dracula's first
  name" where it generated.
- **Closed 2026-10-23:** on DeepSeek V4 Pro with prompt v6 the held-out set passed
  twice with 0 confident wrong and `ho-near-vlad` a clean decline (ADR-007). Not
  tuned for this item. Fixed by the generator change, not by a gate change.
- **Phase:** R3 (generator ladder), re-measured on the production generator.
- **Done when:** the held-out set passes with 0 confident wrong on the model that
  ships; do not tune for this one item.

## KI-79: the generator flakes on a fact spread over several passages

- **What:** `plot-speckled-band` ("what killed Julia Stoner?"). Retrieval is fine
  (evidence grade 0.64-0.67 in every draw); `gpt-4o-mini` wrote "fear and nervous
  shock" in 3 of 4 draws and "swamp adder" in 1; IsUse rejected the poor ones (0.29,
  0.32, 0.47). `gpt-4o` was right 2 of 2. The earlier "passed on retry" was luck,
  hidden by the retry that re-rolled completed answers (removed 2026-10-18).
- **Closed 2026-10-23:** `plot-speckled-band` passed in all five DeepSeek V4 Pro
  books draws (v5 ×3, v6 ×2); the false-abstention bar is held on the shipping
  model (ADR-007).
- **Phase:** R3 (generator ladder): escalate to a stronger generator when IsUse fails.
- **Done when:** books acceptance holds its false-abstention bar on the shipping model.

## KI-86: the reply language is not enforced

- **What:** the grounded prompt says to answer in the question's language, and
  both candidates ignore it on some draws. DeepSeek V4 Pro answered the Tagalog
  `ml-tl-maria-clara` in English (v5 draw 1, v6 draw 2); Sonnet 5.5 answered the
  English `xl-en-samsa` in German (v6). Each is a books content miss
  (`language_mismatch`), and they are the recurring cause of DeepSeek's misses.
- **Part 2 done 2026-10-25 (`7da07ec`):** `build_grounded_messages` adds the one-line language instruction on the first
  generation when the question's language is detected and is not English (English keeps the measured prompt; a
  rewrite that produced English cannot force English). Not yet verified by a draw.
- **Part 1 done 2026-10-25 (`47f83d5`):** `graph/stages/language_check.py` regenerates a HELD grounded answer
  once when `detect_language` says it differs from the question's. Deep always holds; Auto holds only below the
  stream line (about 20% of 187 replayed answers were held), and a streamed answer is not checked because a
  retry would retract text the user read. The check is correct but covers a minority of Auto answers. Part 2:
  name the question's language in the system prompt up front (code, applies to streamed answers too); that
  changes generation for every non-English question, so it needs a books draw before it ships.
- **Phase:** before deploy (owner 2026-10-25). `prompts/grounded_answer.md` already says to answer in the
  question's language, so more wording is weak. Plan: (1) a post-generation check with `textkit.detect_language`
  on question and answer, one retry with the language named (code, unit tests, $0; one extra generator call
  on a mismatch); (2) naming the language in the prompt is a prompt change (v7) and needs the eval gate and
  a disclosed exception, so decide it after (1).
- **Done when:** a books draw has no `language_mismatch` on two draws in a row, and the check has tests for a
  mismatch, a match and an undetectable language.

## KI-87: decline detection is a regex over wordings

- **What:** `says_not_in_sources` (`evals/abstention.py`) recognises a decline by
  phrase. Three wordings slipped past it in three days: a clause before "do not
  say" (`outside-holmes-boston`, fixed 7e73ffe), a closing scope caveat on a
  cited answer (`broad-sherlock`, fixed 7e73ffe), and a caveat inside a bullet
  list or "do not identify" (`compare-inventors`, `outside-holmes-boston` on
  Sonnet v6, not fixed). The scorer decides confident wrong, the product's most
  important number, so every miss either hides or invents one.
- **Phase:** R3: classify a reply by the abstention signal and IsUse, with the
  regex only for the answer-class caveat, instead of widening the regex again.
- **Done when:** the scorer classifies the recorded R3 runs the same way a reader
  does, with a test per recorded reply.

## KI-88: the decision fallback's LLM call has no effective timeout

- **What:** `deep-quixote-rosinante-birth` (Deep set, 2026-10-22): in hop 4 Jev
  threw an http error, the log read "jev failed, retrying on fallback: jev http
  error", and the `gpt-4o-mini` fallback call through OpenRouter then stalled about
  156 s with nothing cutting it off, until the harness gave up and the run ended
  `cancelled`. Any mode that falls back is exposed, not only Deep.
- **Phase:** before deploy (a stalled provider holds the run, its credit reservation
  and a worker).
- **Done when:** the fallback call has a bounded timeout shorter than the run
  timeout, a stall ends in the fail-closed path (KI-57), and a test with a hung
  provider proves it.

## KI-89: the retrieval statement timeout leaks onto the shared hop session

- **What:** the retry of the same item failed in 3 s with a Postgres "canceling
  statement due to statement timeout": our own `retrieval_statement_timeout_ms`
  (1.5 s), applied with `SET LOCAL`, stays in force on the session the hops share
  and tripped on the `query_cache` embedding write in `get_query_embedding`. The
  likely trigger is contention with the still-running first attempt (inferred; no
  `pg_locks` captured).
- **Phase:** before deploy.
- **Done when:** the timeout applies only to the retrieval statement it was set for,
  the embedding cache write is not under it, and a test runs two parallel hops on one
  session.

## KI-93: Deep lacks Auto's conflict check and its trace hides stages

- **What:** Auto runs a conflict batch over the evidence and discloses contradicting passages
  (`graph/stages/finish_stage.py`, `evidence_stage.py`). `graph/deep.py` and `run_deep.py` have
  no conflict handling that I found; whether `finish_stage.py` covers Deep is not traced, so
  this is a likely gap, not a confirmed one. Separately, Deep's trace shows `ingress+rewrite`,
  `plan`, `hop_N`, `controller_N`, `followup_N` and `isuse`: retrieve, rerank and sanitize run
  inside `hop_retrieve.py` and surface only as part of `hop_N`, and generation is timed outside a
  step (`run_deep.py`). Found 2026-10-25 when the owner asked why Deep shows fewer stages.
- **Trace half done in `da72a48`:** `generate` is its own step and each hop shows retrieve, rerank and sanitize sub-steps; Deep's `generate` latency no longer includes IsUse (as in Auto).
- **Phase:** the trace half goes in the UI polish pass (steps only, no behaviour change);
  the conflict check is a behaviour change, so it belongs to the post-deploy Deep rework
  (with G6/G10) and needs the eval gate.
- **Done when:** Deep's trace lists the same stages as Auto, and Deep either runs the conflict
  check or the TRD §7 table says why it does not.

## KI-98: OCR (beta) does not read ruled tables

- **What:** Tesseract reads 1 of 18 cells of a ruled table
  (`docs/history/reports/2026-10-26-0356-ocr-bakeoff.md`). A scanned table is
  indexed as scrambled text, and the page is not flagged `table_heavy` because
  that flag counts text-layer cells. Real-scan accuracy is unmeasured.
- **Phase:** post-beta. The engine is swappable (`ocr.engine`); a table-capable
  engine is one registry entry.

## KI-92: UI pass leftovers

- **What:** found while merging UI slices A, B and C (reports in `docs/history/reports/2026-10-24-*-ui-*.md`, not in git).
  - Duplicate Escape handler removed in `da72a48` (`ChatView.tsx` kept).
  - Model picker is still under 44 px on mobile (F-40), left untouched by rule (thread-header buttons done in `da72a48`).
  - `ChatSidebar` still has text under 11 px (F-34 fixed in `MessageList.tsx` only).
  - `npm run lint` prints a bogus JSON error; `npx oxlint` works.
  - The live specs `abstain.spec.ts` and `metrics.spec.ts` were edited but not run (they need the real stack and model calls).
  - F-25 (past-chat Trace and Metrics follow the latest answer) and F-26 (failed-run display) were verified against mocks only.
  - The blocked-composer message shows the reset time of the 5h window only, not the monthly one.
  - README: the "Quality" row is stale (faithfulness 0.976, 2 Oct); the Sonnet 5.5 v6 "1 confident wrong" row does not say it is the `outside-holmes-boston` decline-then-summarise case.
  - Deep's trace parity with Auto (steps only; the behaviour half is KI-93).
  - Deferred by owner decision: the Library page.
- **Phase:** UI redesign (polish); live specs at the pre-deploy recheck.
- **Done when:** each bullet is fixed or struck with a reason, the live specs pass at the pre-deploy `check-work`, and the README rows are corrected.

## KI-95: an IsUse decline for a non-English question is in English

- **What:** `usefulness_decline` (`graph/stages/usefulness_stage.py`) renders the found/missing template with
  `build_abstain_template`, which is English. The pre-generation abstain (`graph/abstain.py`) detects the
  question's language and has the generator translate the template; the IsUse decline does not. A replay of
  the 187 completed answers in the three acceptance databases found 4 declines in English for a Chinese,
  a Japanese and two French questions (one held, three streamed then retracted). Found 2026-10-25 while
  checking the KI-86 fix.
- **Phase:** before deploy (same user-visible defect as KI-86).
- **Done when:** the IsUse decline text is in the question's language (reuse `stream_abstention`'s
  translation path, English questions stay a fixed template with no model call), with a test per case.

## KI-97: Deep false abstentions on compound questions (replay 2026-10-26)

- **Evidence:** `docs/history/reports/2026-10-26-0030-deep-replay.md` ($0, 24 answerable current-era Deep
  items from draw 1: 6 ended in a decline, the evidence floor stopped none). Entity guard: 3 wrong stops,
  one a locator word ("Hertfordshire" read 0.47), one a starved second clause (Deep merges hop winners by
  rerank score with no per-sub-question share, so the top 5 were all one book), one Tagalog passages against
  an English entity plus the locator "San Diego". The wrong readings (.47, .42) sit inside the range of
  correct decoy stops (.46, .33): no threshold separates them. IsUse: 3 wrong stops (.13, .20, .45) whose
  drafts named the gold facts; two have a 40 s generate and a thinking stream that ends mid-sentence.
- **Mechanism (code read, not proven):** Deep calls the generator with `on_reasoning`, which turns reasoning
  on (`providers/llm.py`), and the reasoning shares `llm_max_tokens["generator"]` = 2048 with the answer, so a
  long thought can cut the answer off and IsUse scores a truncated or empty text. Auto does not request
  reasoning. `finish_reason` is not stored.
- **Done in `60d3214`:** the controller reads the pooled evidence line (G4), Deep runs the conflict check and uses
  the intent blocks. The controller line's wording is not replay-verified: replay it on the 14 Deep items and
  the books set (Jev calls only, a fraction of a cent) before trusting it.
- **Open:** (1) raise or cap the Deep generator's budget and check `finish_reason` (a setting change,
  disclose it); (2) a per-sub-question share when hop winners are merged; (3) partial answers (answer the
  supported clauses, name the missing one) with 0 confident wrong kept; (4) entity-guard locator wording is a
  Jev question text change, not a threshold change: leave it until (1) to (3) are measured.
- **Phase:** R3 (Deep); post-deploy unless the owner moves it earlier.
- **Done when:** a new frozen unseen Deep set (about 20 items) passes at least 80% of answerable items with
  0 confident wrong over 2 draws.

## KI-96: web sources showed no title or URL (closed 2026-10-25)

- **What:** a web chunk has no document, so `document_name` was null, and neither the retrieval event nor the
  saved citation carried a URL; the UI showed a web source with no name and no link. Reported by the owner.
- **Closed by** `1e1f7d1`: retrieval LEFT JOINs `web_pages` inside the chat scope (ownership test first), `url` is
  on `RetrievedChunk` and `CitationOut` (including persisted citations), and the UI shows the title and the
  host as a link only for `http` and `https`.

## KI-91: usage recording fails after a run's first async_judge ledger row

- **What:** `UsageContext.record_call` (`quota/usage.py:67-73`) selects every
  `UsageLedger` row of the run and reads it with `scalar_one_or_none()`. An
  `async_judge` call adds its own row (line 76), so from then on the run has two rows
  and the next call for that run, of any role, raises `MultipleResultsFound` after the
  provider has answered and billed. Found by the R3 shadow run: a shadow judge call that
  finished after its run settled hit it 34 times in 28 runs, and the measurement
  launcher swallowed the error. With the default `shadow_sample_rate` (0.02) and the
  normal `async_judge` claim review the same path can occur in production; how often is
  not measured. The user's answer is not affected; the ledger row of the late call is
  lost and the call is logged as a failure.
- **Phase:** before deploy (quota accounting, TRD §14).
- **Done when:** the aggregate-row query is restricted to the run's aggregate row (not
  `async_judge` rows), and a test records two `async_judge` calls and a late shadow call
  on one run without an error and with every call in the ledger.

## KI-94: the async quality judge runs on every run and costs more than the generator

- **What:** `graph/async_scoring.py` (`_SMALL_MODEL = "openrouter/anthropic/claude-haiku-4.5"`) scores
  context precision, context recall and answer relevance after each run and pushes them to Langfuse.
  It runs unless `trace_sample_rate` (default 1.0) skips it, uses a model id that is not in
  `model_roles`, and cost $0.116 over 17 runs in the KI-90 measurement (about $0.007 per run), more
  than the generator ($0.0735 for the same 17 runs). Found 2026-10-25 reading the KI-90 run.
- **Owner decision 2026-10-25:** keep Haiku 4.5 as the judge, but make it configurable. Done: the
  judge is the `async_judge` role (`ASYNC_JUDGE_MODEL_ID` in `config.py`, seeded once by
  `seed_models.py` without overwriting, changed on the admin Roles page); with no binding it still
  runs on Haiku. Needs a `seed_models.py` run on an existing database for the role to show on the page.
- **Phase:** before deploy (operator cost per user message; a public demo multiplies it).
- **Decided 2026-10-25 (owner):** deployed `trace_sample_rate` is 0.1 (about $0.0007 per run on average);
  keep 1.0 for local work and for the pre-deploy recheck run. The README and benchmark pages quote only
  decision-layer cost per run, so no figure there includes this judge (checked).
- **Done when:** `trace_sample_rate` is set to 0.1 in admin Settings on the deployed environment, then
  this entry moves to closed with that date.

## KI-90: generator price constants may be stale

- **What:** `GENERATOR_PRICE_IN/OUT` in `config.py` ($0.4427 / $0.8853 per 1M) feed the
  cost accounting for the generator role. The public OpenRouter model list on
  2026-10-23 shows `deepseek/deepseek-v4-pro` at $0.955 / $1.911. Whether the key is
  billed at that rate is not checked (the key and credit endpoints were not used).
- **Closed 2026-10-25.** 53 `deepseek-v4-pro` generation records (36 short shadow-run calls, 17 full generator
  prompts from a 16-item books run, $0.277 for the whole run) billed $0.240: 0.98x the cost at the list price
  ($0.955 / $1.911) and 2.12x the old constants. Single samples ran 0.77x and 1.12x; by provider 0.07x (cached)
  to 1.93x. `GENERATOR_PRICE_IN/OUT` and the catalogue row now use the list price; ADR-007, README and the
  benchmark pages are corrected. Credits still use a fixed price; settling from the record's `total_cost`
  would be exact if the drift matters (not opened).
- **Phase:** before deploy (quota settlement and the README cost claims use these).
- **Done when:** the billed rate is read from a generation record of a real run, the
  constants and `seed_models.py` row match it, and ADR-007's cost line is corrected.

## KI-80: outside-whitman abstains although the quote is in one chunk

- **Closed 2026-10-22 (owner decision): the item was removed from the books set.**
  The only Whitman passage (P&P preface, ord 0) says Whitman draws "a fine and
  just distinction between 'loving by allowance' and 'loving with personal love'"
  but never says what the distinction is, so the question is not answerable from
  the corpus and abstaining was the honest behaviour. The KI-36 relabel to `answer`
  matched on keywords, not on whether the passage answers the question. Removed
  after the R3 generator runs had seen it, so both results are reported: with the
  item, `gpt-4o-mini` scored 53/57 and DeepSeek V4 Pro 54/57 and 55/57; without it
  (56 items, 32 answerable), the same recorded runs rescore as control FAIL (2 false
  abstentions: `plot-speckled-band`, `followup-adler`), DeepSeek draw 1 FAIL (2 content
  misses: `ml-tl-maria-clara`, `ml-zh-xiyou-nezha`) and DeepSeek draw 2 PASS. The books
  set is now 56 items (32 answer, 20 decline, 2 smalltalk, 2 library); the gate counts,
  `answer_passages.json` and the pin tests moved with it. The reranker benchmark of
  2026-10-20 was computed with this item's passage label in the 33-item pool; a rerun
  uses 32. The item's old text is in git history before this commit.

- **What:** the sentence "loving by allowance ... loving with personal love" sits in
  one chunk (P&P preface, ord 0), yet the run abstains (rubric 0.22-0.37, IsUse
  0.11). The earlier "spans a chunk boundary" diagnosis was wrong (corrected
  2026-10-19 after the R2b measurement below). Likely the preface only says a
  distinction exists while the question asks what it is: check the label first.
- **Phase:** R3: owner reviews whether the corpus answers the question; the set is
  frozen, so a bad label is reported, not edited. No chunker change.
- **2026-10-19 (R2b-deep item 3, measurement only):** a dry run of the current
  chunker over the 16 cached Gutenberg books (detached helpers, no DB) counts
  11,998 chunk boundaries; 891 fall at a mid-sentence position on the end side
  (7.4%), of which 832 would snap cleanly to the containing sentence's end and 59
  could not (sentence itself over the 300-token child limit). Start-side
  mid-sentence starts (8,318) are overlap tails and move with their window's end.
  Against the stated mechanism: the Whitman sentence does **not** straddle — both
  quote halves land in one chunk in the dry run and in the live acceptance ingest
  (P&P preface, chunk ord 0, 282 tokens; sentence itself 32 tokens). If the books
  bar still misses `outside-whitman`, the cause is elsewhere (retrieval or rubric,
  not chunking); re-check before spending a chunker change.

## KI-81: the evidence floor is noisy on borderline items

- **What:** `ho-near-vlad` graded 0.444-0.468 across draws against the 0.455 floor,
  so the same item abstains or generates depending on the draw.
- **Phase:** R3: average the grade over the query variants, or add a margin band that
  generates and lets IsUse decide.

## KI-82: Playwright specs are not run in CI

- **What:** CI runs the api tests and, on the branch, vitest; the 11 Playwright specs
  and the paid evals run only by hand. Third-party review #7.
- **Phase:** check-work (CI).

## KI-83: citation precision is claim-level, not per citation

- **What:** the reviewer credits one claim verdict to every citation on the claim
  (documented as "claim-level citation support", TRD §10). A true per-citation check
  costs one check per claim-citation pair. Third-party review #6.
- **Phase:** R3, once the replay shows the cost.

## KI-84: the overhead metric subtracts overlapping provider calls

- **What:** `evals/attribution.py` subtracts the sum of provider durations from wall
  time, while ingress and rewrite run concurrently; the sum can exceed the wall time
  and the result can be negative. The latency check is warn-only until phase 3.
  Third-party review #11.
- **Phase:** phase 3 (latency).

## KI-85: decision-engine thresholds are keyed by "jev" and "fallback" only

- **What:** R2c made the reranker gates (`evidence_floor`, `stream_line`) per
  reranker. The decision engines still read `threshold(..., "jev")` literals:
  `entity_match` (`graph/stages/evidence_stage.py`, `deep_evidence_stage.py`),
  `is_use`, the guard thresholds and the library/prose/controller floors in
  `decisions/thresholds.py`. A second decision model (Laya,
  Microsoft-Decision-1) would be graded against Jev's scale with no error.
- **Phase:** post-deploy decision pluggability (ADR-005). Fix: key every
  decision threshold by provider id and refuse an uncalibrated one, as
  `reranker_threshold` does.
