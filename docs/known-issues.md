# Known issues

Open defects only. Triaged 2026-10-12: every entry is either tied to the
phase whose `make check-*` target it breaks, or tagged `post-beta`.
The Phase column is authoritative; section placement below is from the first triage.

Rules (`docs/conventions/agents.md`, "Finish lines and measurement"):
- When you fix one, move it to the archive in the same commit, with the fixing commit hash.
- A new finding that breaks no check is added under **post-beta** and opens no lane.
- New IDs continue from KI-84.

## Index

| Phase | KI | Summary |
| --- | --- | --- |
| R3 (generator) | KI-78 | a false-premise question ("first name" of a man with none) is answered, not declined; IsUse passes it |
| R3 (generator) | KI-79 | the generator flakes on multi-passage facts (plot-speckled-band: right answer 1 of 4 draws on gpt-4o-mini) |
| R3 (label/rubric) | KI-80 | outside-whitman: the quoted sentence is in one chunk (preface) yet the books run abstains; the question may ask for content the preface does not state |
| R3 (floor) | KI-81 | the evidence floor flips on borderline items: the grade varies 0.444-0.468 around 0.455 between runs |
| check-work (CI) | KI-82 | Playwright specs are not run in CI; paid evals are manual |
| R3 (reviewer) | KI-83 | citation precision is claim-level support; per-citation verification is not done |
| phase 3 (latency) | KI-84 | `our_overhead_ms` subtracts overlapping provider calls (ingress and rewrite run together); it can go negative |
| check-stable | KI-76 | credits stay reserved if the process dies between completion and settlement |
| check-stable | KI-32 | record of faithfulness variance; gate tolerances already set |
| check-stable | KI-43 | absence-claim verdict flips between runs (grader quality) |
| check-stable | KI-49 | reviewer rarely makes an unsupported judgement itself |
| check-stable | KI-51 | cf subset spread 0.0667 vs 0.06 band |
| UI redesign | KI-22 | trace tab redesign; belongs to the UI pass |
| UI redesign | KI-74 | SR-6 filters exist in the API but the composer has no filter UI |
| UI redesign | KI-65 | screenshots and tab-order audit; redo after the UI pass |
| before deploy | KI-59 | uvicorn forwarded_allow_ips must match the deployed proxy |
| before deploy | KI-63 | demo credit-outstanding cap still open; only matters if DEMO_ENABLED=true |
| before deploy | KI-64 | owner data decision: conflict pair in Shared, eval corpus visibility |
| post-beta | KI-8 | six Playwright specs make live LLM runs instead of replaying fixtures |
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
- **Phase:** R3 (generator ladder), re-measured on the production generator.
- **Done when:** the held-out set passes with 0 confident wrong on the model that
  ships; do not tune for this one item.

## KI-79: the generator flakes on a fact spread over several passages

- **What:** `plot-speckled-band` ("what killed Julia Stoner?"). Retrieval is fine
  (evidence grade 0.64-0.67 in every draw); `gpt-4o-mini` wrote "fear and nervous
  shock" in 3 of 4 draws and "swamp adder" in 1; IsUse rejected the poor ones (0.29,
  0.32, 0.47). `gpt-4o` was right 2 of 2. The earlier "passed on retry" was luck,
  hidden by the retry that re-rolled completed answers (removed 2026-10-18).
- **Phase:** R3 (generator ladder): escalate to a stronger generator when IsUse fails.
- **Done when:** books acceptance holds its false-abstention bar on the shipping model.

## KI-80: outside-whitman abstains although the quote is in one chunk

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
