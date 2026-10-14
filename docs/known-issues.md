# Known issues

Open defects only. Triaged 2026-10-12: every entry is either tied to the
phase whose `make check-*` target it breaks, or tagged `post-beta`.
The Phase column is authoritative; section placement below is from the first triage.

Rules (`docs/conventions/agents.md`, "Finish lines and measurement"):
- When you fix one, move it to the archive in the same commit, with the fixing commit hash.
- A new finding that breaks no check is added under **post-beta** and opens no lane.
- New IDs continue from KI-75.

## Index

| Phase | KI | Summary |
| --- | --- | --- |
| check-work (acceptance) | KI-70 | the relevance gate abstains on broad/summary answerables; no threshold separates |
| check-work (1d) | KI-15 | order-dependent hang in test_chats_runs.py; a flaky suite fails "repeatable" |
| check-stable | KI-57 | degrade-to-fail when the decision fallback truncates; fault injection covers it |
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
| check-work (acceptance) | KI-71 | ingress routes content questions to `chitchat`: ungrounded answer, no citations |
| check-work (acceptance) | KI-73 | the rewriter's prose becomes the retrieval query, so a message with no question can answer |
| check-work (acceptance) | KI-75 | an answer that cites the right book and states the wrong content is a failure no count caught |

---

# check-stable

## CLOSED KI-15: `tests/chats/test_chats_runs.py` hangs when its tests run in sequence (fixed f821d09)

Moved out of the open list: root cause found for the reproducible deadlock —
an in-flight `execute_run` task stayed pending across `clean_db` and held
an active transaction/session, racing `TRUNCATE`. Fix in `graph/runner.py`:
`drain_background_tasks` now cancels and awaits `_active_tasks` (and
`_shadow_tasks`) as well as the settle/judge tails. Commit f821d09.
Guards added: per-test `faulthandler_timeout = 60` in pyproject,
`SET lock_timeout = '5s'` before TRUNCATE.

## CLOSED KI-75: an answer that cites the right book and states the wrong content is a failure no count caught

Logged 2026-10-14 (phase R2a item 1, the bar line for the R2 row of the
plan), closed in the same commit.

- **What:** the gate measured decline accuracy, false abstention and
  citations. It never measured whether the answer was **right**.
  `scripts/acceptance.py` computed `mention_hit` per item and `passes()`
  required it, so a content miss was visible only as a name in `failed_ids` —
  which nothing counted and no clause read. A run could hold every number,
  cite the right document on every answerable item, and be wrong about all of
  them. `rag-reference.md`'s Evaluation row said the same thing in one line:
  "not only safety".
- **Fix:** `content_misses` / `content_miss_ids` in `summarise()`, counted
  for an answer-class item that **answered, cited, and did not state the
  required content**. `MAX_CONTENT_MISSES = 1` in `evals/acceptance_gate.py`,
  which is the plan's bar line ("≤ 1 content miss of 32 answerables") and the
  same arithmetic as the false-abstention rate at this mix.
- **Not a rate, deliberately:** `content_miss` is disjoint from
  `false_abstention` (which did not answer), `uncited_answers` (cited
  nothing) and `confident_wrong` (a should-decline item that answered). One
  item is counted once, in the class that describes what the run did.
- **`mention_hit` moved onto the row.** The item's `mention` / `mention_all` /
  `alt_mention` lists stay in `books.json`; the runner scores them once at
  play time against the answer and records the boolean, so the number the gate
  reads cannot disagree with `passes()`.
- **Tests:** `tests/scripts/test_acceptance_summary.py` — a cited answer that
  misses its content is a content miss and no other class; a declined answer
  item is a false abstention and *not* also a content miss; a cited answer
  that states the content is clean. `tests/evals/test_acceptance_gate.py` —
  2 fails with both ids named, 1 passes (the boundary), and a content miss is
  none of the other three classes. Fakes only; no provider call.

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

- **Phase 1d item 3b (2026-10-13): still not reproduced, and no code changed.**
  Measured on `f7cd86d` with the brief's own proof shape:
  `tests/chats/test_chats_runs.py` as a whole file, `-p no:randomly` with
  `-o faulthandler_timeout=40`, **5 consecutive runs: 13 passed each, 4.4-4.6 s,
  no hang and no faulthandler dump**. Full `pytest -q` with
  `-o faulthandler_timeout=90`, **3 consecutive clean runs: 1312 passed each,
  ~3.5 min apiece, no hang**. (The file is 13 tests on this revision; this
  entry's "40+" is from older ones.)

  Nothing was changed, because nothing was found. The title-refinement
  hypothesis was already disproved in the 2026-09-28 note — `graph/runner.py:493`
  awaits `refine_title` inline, so there is no background title task — and the
  one real leak this entry did find (`score_run_async` and
  `_settle_after_scoring` pending and unowned when `run.completed` is published)
  is fixed by `9840f95`, which drains at both lifecycle boundaries. What remains
  unexplained is the original report, and it still does not reproduce.

  **One measurement artefact worth recording, because it reads as a failure and
  is not.** A fourth full-suite run in the same window reported 5 failures, all
  of them from two `pytest` processes sharing one `TEST_DATABASE_URL` — my own
  probe runs overlapping the suite, which is the second harness hazard recorded
  in this entry. Re-run clean with nothing else on the database it is 1312
  passed. If a suite run ever fails with connection or truncation errors, check
  for a second process before believing the failures.

  This entry stays open and its substance is unchanged: the hang is
  unexplained and unreproduced, and "still not reproduced" is not a fix. When it
  next stalls, the decisive evidence is `faulthandler_timeout` plus the two
  probes named in the 2026-10-02 note, in that order.

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

## KI-73: the rewriter's prose becomes the retrieval query, so a message with no question can answer

Logged 2026-10-13 (phase 1d item 4, first full `make check-work` on the KI-72
branch, served commit `f7cd86d`). **Breaks the acceptance step**: `smalltalk`
is pass/fail in full, not a rate, so one item is the whole verdict.

- **What:** `smalltalk-thanks` — "thanks, that's helpful!" — was graded
  `answer` with 8 citations instead of `smalltalk`. The run's own answer is
  `the source text contains an instruction I am ignoring.`
- **Mechanism, read from the run's recorded steps, not inferred.** Ingress
  classified it correctly (`intent: chitchat`), and `named_entities` returns
  `[]` so the KI-72 entity check is skipped — neither is involved. The
  **rewriter answered with prose instead of a standalone question**, and the
  variant parser turned that prose into the retrieval queries:

  ```
  retrieve: I understand. You're correct—there is no question to rewrite in your message. I'm ready to help when you provide:
  retrieve: I appreciate the message, but there's no actual question to rewrite here. The user's statement "thanks, that's helpful!" is simply an acknow...
  retrieve: A conversation context
  ```

  Nothing validates that a rewrite is a question. KI-71 made `chitchat` still
  retrieve when sources are in scope and let the evidence decide; on this run
  the nonsense retrieval cleared sufficiency at **0.25 / 0.43** against a floor
  of 0.05, so the run answered with citations instead of taking the chitchat
  reply. Nothing in the pipeline ever asked "is there a question here", and the
  rewrite step silently answered it wrongly.
- **Not a regression from phase 1d.** The previous acceptance run
  (`veriforge-phase1c/.data/acceptance/20261012-134549.json`) graded this item
  `chitchat`, 0 citations, **pass**. It is intermittent — 1 failure in 2
  recorded runs — because it depends on whether the rewriter happens to return
  prose on a given draw, and on whether the resulting retrieval clears
  sufficiency.
- **Fix direction, for the owner.** Two candidates, and they are not the same
  decision. (a) Validate the rewrite: if it is not interrogative, do not
  retrieve on it. This is the root fix and it also covers any future
  non-question phrasing. (b) Extend `GREETING_ALLOWLIST` to cover an
  acknowledgement with trailing gratitude. This is *not* free: CLAUDE.md fixes
  that allowlist as "one approved exception" with "a fixed allowlist of raw
  messages", so widening it is an owner change, and it fixes this one phrasing
  while leaving the general defect in place.
- **Done when:** a message containing no question never produces an
  `answer`-class reply with citations, and `smalltalk-thanks` passes.

- **FIXED (2026-10-14, phase R2a item 2).** Both layers, root first. The
  greeting allowlist is untouched (CLAUDE.md's one exception).

  **Layer 1 — the rewriter's output contract.** `graph/rewrite.py` gains
  `is_query_shape`: a reply that asks a question is a query however long it is
  ("What is Rocinante? And who rides him?" is a two-sentence multi-part query,
  and the follow-up path depends on long rewrites being kept); a reply that
  never asks is a query only while it stays inside one sentence. Two sentence
  terminators with no `?` means the model opened a *reply*, so it is dropped
  and the run uses the user's own message. This is a test of the reply's
  shape, not a list of phrasings.

  **The variants parser needed it too, and that is the part this entry did
  not guess.** KI-73's recorded run put **two** prose replies into the
  retrieval set, both from `_generate_query_variants`
  (`graph/stages/retrieve_stage.py`), not one from `rewrite_query`. Checking
  only the rewrite would have left the recorded failure half-open. Every
  parsed variant line now goes through the same check.

  **Layer 2 — a `chitchat` routing that names nothing does not retrieve.**
  `graph/stages/ingress_stage.py` gains `names_a_subject`. The brief specifies
  `named_entities(message)` non-empty, and on its own that is **wrong**, with
  the recorded item as the counter-example: `broad-sherlock` is *"tell me
  something about the adventures of sherlock holmes"*, lowercased throughout,
  so a capitalisation heuristic returns `[]`, the run skips retrieval, and
  KI-71's cited answer becomes the uncited reply this product does not ship.
  `names_a_subject` is therefore `named_entities(message)` **or** a trailing
  non-stop word — a trailing lowercase noun phrase, which is what a lowercase
  proper name looks like.

  The bar is one word and not two, because the two failure directions are not
  symmetric: saying "no" to a content question is an uncited answer and an
  acceptance-gate failure (KI-75 now counts it), while saying "yes" to a social
  turn costs one wasted fan-out and sufficiency still sends the run to the
  same small-talk reply. The stop list is a list of function, question and
  social **words** — it delimits the trailing noun phrase, and it is not the
  greeting allowlist. It does contain every `GREETING_ALLOWLIST` phrase, and a
  test asserts the two agree: they are reached by different code paths and a
  disagreement would be a trap for the next reader.

  **The honest edge, stated because it is a judgement and not a proof.** One
  declarative sentence with no `?` passes: "I appreciate the message" is prose
  and "Rocinante Don Quixote horse" is a keyword query, and no shape test
  separates them without becoming the phrase list the contract exists to
  avoid. Reading it as a query is the safe direction (a nonsense query
  retrieves nothing; prose read as a query is this bug). The recorded failure
  had three sentences and is caught.

  **Tests** (`tests/graph/test_chitchat.py`, fakes throughout, no provider
  call): the recorded strings read the right way round by
  `names_a_subject`; the stop list and `GREETING_ALLOWLIST` agree; the
  `is_query_shape` contract on both recorded prose replies and on both query
  shapes; the one-sentence edge pinned as deliberate; `"thanks, that's
  helpful!"` **with sources in scope** retrieves nothing, cites nothing and
  streams the plain reply with the raw message; `broad-sherlock` and
  `ml-es-rocinante` still retrieve and answer from evidence; a prose rewrite
  is discarded for the original message, both as a unit and through a whole
  run whose recorded queries carry no prose. 47 in the file, 1341 in the
  suite.

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

## KI-70: The KI-26 relevance gate abstains on broad/summary answerable items, and no threshold separates them

Logged 2026-10-12 (phase 1b, first full run of the books acceptance set as
`make check-work` step 9, on `28c808c`). **Breaks the step**: 3 of 33 answerable
items declined; PRD §5 allows <= 1.

- **What:** `broad-alice` ("can you give me the gist of alice's adventures in
  wonderland?"), `broad-bovary` ("Peux-tu resumer Madame Bovary ?") and
  `amb-bovary-homais` all declined. **Not a sufficiency failure.** The
  sufficiency judge scored them 0.61/0.61 and 0.48/0.50 against a floor of
  0.05, and the KI-54 entity check scored `broad-alice` 0.95-0.97 and
  `broad-bovary` 0.96-0.97 against a floor of 0.50. What abstained them is the
  **relevance gate** (KI-26: abstain when the max post-sanitize rerank score is
  under `rerank_abstain` 0.60) at 0.35/0.36, 0.23/0.26 and 0.26/0.40.
- **Why the gate misfires here:** a broad or summary question matches no single
  passage lexically, so JevRerank scores the *correct* passages low --
  `broad-alice`'s best passage scored 0.36 while the entity check scored 0.97
  on those same passages. The gate measures question-passage lexical overlap and
  is asked to stand in for "is this evidence relevant", which for a gist
  question it cannot be. PRD §5 requires false abstention <= 5% of answerable
  items "including broad/summary questions", so this class is one the bar names
  directly.
- **Why no threshold move:** this run's `relevance` distributions **overlap**.
  Answerable items sit at 0.23 / 0.26 / 0.36 / 0.40; should-abstain items reach
  0.59, with 0.48, 0.51 and 0.33 nearby. Any cut-off that admits 0.26 also
  admits abstentions and manufactures *confident wrong answers* -- strictly
  worse than the false abstentions it removes. This is KI-28's finding restated
  for the relevance signal: no cut-off separates the groups.
- **What the data does support** (one run, 20 abstains -- a hypothesis, not a
  decision): the **sufficiency** score has no overlap at the top. No
  should-abstain item exceeded `sufficient` 0.50, and the two broad items sit at
  0.61. A compound rule -- the relevance gate does not veto a sufficiency score
  at or above ~0.60 -- would fix 2 of the 3 and leave 1, exactly at PRD §5's bar.
  `amb-bovary-homais` is not in that set (0.13/0.15): its evidence is about
  *other* characters, so any such rule leaves it declining. **Not done:** a
  threshold change must keep fast20, counterfactual and entity-mismatch passing
  with before/after on all three (agents.md), and this lane's credit floor was
  reached before that evidence could be gathered.
- **Rerun of the three ids (2026-10-12, `7c7a0c1`), and it changes the shape of
  the problem:** `broad-bovary` **answered** this time (sufficient 0.42, one
  attempt, no relevance veto) and `broad-alice` declined again (0.51/0.56). So
  of the three, **one is stable (`amb-bovary-homais`, sufficient 0.13-0.16 both
  runs — a real evidence failure, not a gate artefact) and two are intermittent,
  tracking the rerank score's run-to-run movement** (broad-bovary's relevance was
  0.23/0.26 in run 1, above the gate in run 2). An intermittent false
  abstention means the step's verdict moves between runs on the same commit, so
  it cannot be called a stable pass without the fix; treat any green acceptance
  step on this branch as one sample, not as the number.
- **Done when:** the two broad items answer, `amb-bovary-homais` either answers
  or is relabelled against the corpus, and the whole step passes **twice**.
- **The signals table, and the rule chosen from it (2026-10-12, phase 1c item
  2).** Every recorded item of both runs, with its expected class, intent,
  sufficiency and max post-sanitize rerank score per attempt, is replayed from
  the recorded acceptance exports.

  **No threshold moves**, which the table confirms on this data: run-1
  `not_in_sources` items reach relevance 0.71, 0.63 and 0.50 while the answer
  items the gate loses sit at 0.35–0.57. The distributions overlap at every
  cut-off. `rerank_abstain` stays 0.60.

  **The rule: a `summarize` question is not subject to the relevance veto;
  sufficiency and the entity check decide it alone.** The gate measures
  question-to-passage *lexical overlap*, and "give me the gist of X" matches no
  single passage — which is why `broad-alice` scored 0.35 on the right passages
  while KI-54's entity check scored 0.97 on those same passages. For a gist
  question the overlap signal is not evidence of irrelevance. Keyed on what
  the question **is**, so no new number is introduced.

  **The proof the brief asks for** (§3 of the doc, replayed in
  `apps/api/tests/graph/test_ki70_relevance_veto.py`): on every recorded item
  of both runs — **0 of 20** should-decline items become answers; the rule
  removes the false abstentions on `broad-alice` and `broad-bovary` and changes
  nothing else. The replay carries the entity check, because
  `outside-holmes-boston` clears both other floors (0.39 / 0.63) and is held
  only by the entity check — a replay without it would report a confident
  wrong answer the run never gave.

  **`amb-bovary-homais` is an evidence failure and its label is wrong.**
  `scripts/audit_labels.py` reports the item clean, but that checks the query
  *terms* hit passages, not that the passages contain the answer. Reading the
  corpus says the item's premise is false for this edition: **`Rouard` is 0
  hits corpus-wide**, `médecin de la campagne` 0, and no sentence anywhere
  pairs the pharmacist with Emma's eyes (`pharmacien[^.]{0,300}yeux` matches 0
  times; `baume`, `collyre`, `drops` are all 0). Relabelled `answer` →
  `not_in_sources`, labels only, with the measurement in the item. The run's
  behaviour was right all along. Class counts move 33/20 → 32/21 and
  `EXPECTED_COUNTS` moves with them.

  **Still open until the gate agrees:** the change is proven against recorded
  values and fakes; what proves it on the real corpus is `make check-work`
  running green twice (phase 1c item 3).

  **Still open, and not fixed by any of this:** the relevance gate still
  measures the wrong thing for a broad question the intent classifier did not
  call `summarize`. The table shows the shape — no signal in the recorded set
  separates `broad-*` at 0.35–0.57 from `outside-*` at 0.63–0.71.

  **Measured on the live corpus (2026-10-12, phase 1c item 3, commit
  `72263cb`):** both broad items now answer. `broad-alice` at sufficiency
  0.59 / relevance 0.32, `broad-bovary` at 0.42 / 0.56 — both would have been
  vetoed at relevance 0.60 and neither is. The rule does what the replay said
  it would.

## KI-71: ingress routes content questions to `chitchat`, which skipped retrieval and answered ungrounded

Logged 2026-10-12 (phase 1b, same run). Owner decision 2026-10-12: **not
post-beta** — this is the one failure shape the product says it does not have,
so it breaks `make check-work` step 9.

- **What:** `broad-sherlock` ("tell me something about the sherlock
  holmes") and `ml-es-rocinante` ("\u00bfComo se llama el caballo de Don
  Quijote?") were classified `intent=chitchat`, took the `Small talk: skipped
  retrieval` path, and answered from model memory with **no citations** and no
  `sufficient` or `relevance` decision at all. Rocinante is the right answer;
  it is ungrounded, which is the thing the product claims not to do.
- **Intermittent, which is the worse property:** on the same commit,
  `broad-sherlock` took the chitchat path in both runs, but `ml-es-rocinante`
  routed `lookup` on the rerun (sufficient 0.97, cited, passed). So this is the
  intent classifier's coin-flip on questions that plainly name a document, not a
  deterministic rule.
- **Worth the owner's attention despite the tag:** this is the one failure shape
  where the product is confidently right by luck. Any question phrased as a
  greeting plus a topic can land here, and nothing in `make check-work` would
  notice a rise in it.
- **Done when:** the intent gate's `chitchat` option stops catching questions
  that name a document or a character, asserted in a test rather than measured
  in a run.
- **FIXED (2026-10-12, phase 1c item 1).** Two changes, and the bar line came
  first so the step could have caught it.

  **The bar line.** `scripts/acceptance.summarise` now writes
  `uncited_answers` / `uncited_answer_ids`: an `answer`-class item that did not
  decline and cited nothing. `evals/acceptance_gate.py` fails on any of them
  (`MAX_UNCITED_ANSWERS = 0`). It is a separate count from `false_abstentions`
  on purpose — the run did not decline, so calling it that would describe the
  wrong behaviour as well as hide this one — and from `confident_wrong`, which
  is the should-decline class. `broad-sherlock`'s run held every other clause
  (20/20 clean declines, 0 confident wrong, 2 false abstentions of 33) and
  still failed here.

  **The fix, structural.** `chitchat` no longer decides whether to retrieve.
  In `graph/auto.py`, when ingress returns `chitchat` **and the user has
  sources in scope**, the run retrieves anyway and the evidence decides:
  enough of it and it is the ordinary grounded answer with citations; not
  enough and it returns the chitchat reply, which `prompts/chitchat.md` (v3)
  now explicitly bars from asserting anything about the sources. Whichever
  way the classifier flips, a content question cannot be answered from memory.
  With no sources in scope there is nothing to retrieve and the fast reply is
  unchanged. The greeting fast path (CLAUDE.md's one carve-out) is untouched
  and still skips everything, which is what keeps `"thanks!"` free.

  Tests: `tests/graph/test_chitchat.py` — a chitchat-routed message naming a
  book retrieves and answers with contexts (recorded values: sufficiency 0.61,
  relevance 0.97); a chitchat-routed run whose evidence does not clear the
  floors falls back to the sourceless reply with no contexts and no abstain
  event; `"thanks!"` retrieves nothing and makes zero ingress calls; a
  greeting-adjacent greeting with no sources still skips. Plus the gate and
  summary cases in `tests/evals/test_acceptance_gate.py` and
  `tests/scripts/test_acceptance_summary.py`. Fakes throughout; no live call.

  The prompt bump is v2 → v3 and is gated by `make check-work` step 4 per
  CLAUDE.md.

  **Still open until the gate agrees.** The change is proven by fakes; what
  proves it on the real corpus is `make check-work` running green twice
  (phase 1c item 3).

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
