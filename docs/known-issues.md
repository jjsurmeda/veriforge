# Known issues

Open defects only. Triaged 2026-10-12: every entry is either tied to the
phase whose `make check-*` target it breaks, or tagged `post-beta`.
Fixed and record-only entries live in `known-issues-archive.md`.
The Phase column is authoritative; section placement below is from the first triage.

Rules (`docs/conventions/agents.md`, "Finish lines and measurement"):
- When you fix one, move it to the archive in the same commit, with the fixing commit hash.
- A new finding that breaks no check is added under **post-beta** and opens no lane.
- New IDs continue from KI-69.

## Index

| Phase | KI | Summary |
| --- | --- | --- |
| check-work (acceptance) | KI-27 | xl-en-wukong-master answers the wrong person |
| check-work (acceptance) | KI-28 | neither reranker separates abstention cleanly |
| check-work (acceptance) | KI-56 | RP-77 answer chunk carries an injection block, so it false-abstains |
| check-stable | KI-15 | order-dependent hang in test_chats_runs.py; a flaky suite fails "repeatable" |
| check-stable | KI-31 | attribution cause still open; flaky overhead figure fails "gate 3x same verdict" |
| check-stable | KI-57 | degrade-to-fail when the decision fallback truncates; fault injection covers it |
| check-stable | KI-32 | record of faithfulness variance; gate tolerances already set |
| check-stable | KI-43 | absence-claim verdict flips between runs (grader quality) |
| check-stable | KI-49 | reviewer rarely makes an unsupported judgement itself |
| check-stable | KI-51 | cf subset spread 0.0667 vs 0.06 band |
| UI redesign | KI-22 | trace tab redesign; belongs to the UI pass |
| UI redesign | KI-65 | screenshots and tab-order audit; redo after the UI pass |
| before deploy | KI-59 | uvicorn forwarded_allow_ips must match the deployed proxy |
| before deploy | KI-63 | demo credit-outstanding cap still open; only matters if DEMO_ENABLED=true |
| before deploy | KI-64 | owner data decision: conflict pair in Shared, eval corpus visibility |
| post-beta | KI-8 | six Playwright specs make live LLM runs instead of replaying fixtures |
| post-beta | KI-39 | web-chunk sweep undercounts deletions (return value only) |
| post-beta | KI-69 | reasoning-mandatory retry in providers/llm.py only serves free endpoints; dead on supported config |

---

# check-stable

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

- **2026-10-02, lane 1 (S8): still not reproduced, and the two remaining
  mechanisms are now ruled out by measurement rather than by argument.** The
  file passed 8 consecutive runs (~4.5 s each) and `tests/chats/`,
  `tests/graph/`, `tests/evals/` together (233 tests) with
  `-o faulthandler_timeout=40`, which dumps every thread's stack if a test
  exceeds 40 s — no dump, no timeout. Two temporary pytest plugins (since
  deleted) probed the two things that could actually stall the next test, and
  both came back empty after every test in the file: `asyncio.all_tasks()`
  showed no pending task beyond the running one, and a second connection
  reading `pg_stat_activity` showed no session in a non-idle state and none
  waiting on a lock, so nothing was holding a row against the next test's
  `TRUNCATE ... CASCADE`. That is consistent with the drain working and does
  not explain the original report, which means the trigger is something this
  machine does not do. No code changed for S8. Next time it stalls, the
  decisive evidence is `faulthandler_timeout` plus the two probes above, in
  that order: a stack dump names the await, and the probes say whether it was
  a task or a lock.

- **Two harness hazards found while doing S8, both of which look like
  application bugs and are not.** (1) Two `pytest` processes sharing one
  `TEST_DATABASE_URL` corrupt each other: running `tests/chats` and
  `tests/runs` at the same time produced
  `ERROR tests/runs/test_sweep.py::test_sweep_marks_stale_run_failed`, and
  three consecutive full-suite runs reported 8, 0 and 4 errors purely from
  overlapping with my own probe runs; the same suite is 593 passed with
  nothing else touching the database. `conftest.py`'s per-test
  `TRUNCATE ... CASCADE` makes concurrent sessions against one database
  unsafe, so a worktree's test database must not be shared — which is what
  the per-lane `_test_lane1` names are for. (2) The `gitleaks` pre-commit hook
  rejects a literal assigned to a name containing `key` or `secret` once it
  passes its entropy floor, even in a test fixture: an HS256 id_token fixture
  needed `_HMAC_SECRET = "aaaa" * 8` before the commit went through. Neither
  is a code defect, and neither is fixed here.

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

## KI-57: The decision fallback's output cap (512) truncates the batched decision JSON, failing the whole item whenever jev degrades

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

# post-beta

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

## KI-56: The only chunk carrying the RP-77 answer embeds an injection block, so the sanitizer drops the answer with it

Logged 2026-10-04, P2a item 4, from a per-item probe (fix, don't analyse —
one paragraph, not a detour). "What torque should the RP-77 retaining
screw be tightened to?" false-abstains on fast20 and in the
counterfactual runs. Root cause: the only chunk carrying the 4 Nm figure
(`field_service_note.md`) embeds a prompt-injection block; the sanitizer
scores it `chunk_injection_0` 0.96 ≥ `chunk_injection_drop` 0.70 and drops
the chunk before the sufficiency judge ever sees it, so the judge scores
`sufficient` 0.02 and the run declines. Proven pre-existing, not caused by
the item-4 entity gate: a probe that spied on `DecisionEngine.decide`
shows the item-4 gate passing (entity values 0.74/0.67) with
`sufficient: 0.02` → abstain, and the identical probe on pre-item-4 code
(HEAD `8a5a622` swapped in temporarily) reproduces the same
`sufficient: 0.02` → abstain. Fix direction for a later dispatch: judge
sufficiency before the sanitizer drops a flagged chunk, let the generator
see flagged-but-not-dropped chunks, or re-chunk the corpus so the
injection block does not swallow the fact. Not fixed in P2a.

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
