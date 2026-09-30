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
with `icu` (migration 0013) and both CJK items now retrieve through the
lexical leg.

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
  raised for the run, then restored.

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
- **Fix:** before any AWS slice, decide the eval corpus's home. Cheapest
  honest option: keep it owned by `evals@veriforge.local` but make its
  collection `visibility='private'`, and have the eval runner create its
  own signed-in user that includes it explicitly (the eval set already
  signs up a throwaway user per run). Then re-baseline — the
  `not_in_sources` items will legitimately change.

## KI-25: Abstaining runs still attach citations, so the whole `not_in_sources` class fails

Logged 2026-09-30, from the round-2 full acceptance run (23/31).

- **What:** all 4 `not_in_sources` items abstain correctly —
  `message_status='abstained'`, `sufficient` 0.02–0.14 — and still FAIL,
  because `passes()` in `scripts/acceptance.py` also requires
  `not result["citations"]` and the abstain path leaves the retrieved
  P&P chunks attached as citations (`outside-whitman` 19.8s/0.03,
  `outside-general` 15.5s/0.02, `ml-es-outside` 14.1s/0.02;
  `outside-study-in-scarlet` is the fourth and additionally answers
  instead of abstaining).
- **Why it matters:** an answer that says "the sources don't cover this"
  and then shows nine citations is self-contradictory to a user, and it
  makes abstention accuracy look 0/4 in the gate when the model's
  judgement is actually 3/4 right.
- **Fix:** decide which is true — either the abstain path drops its
  citations (cleanest: nothing to support, nothing to cite), or the
  scorer counts `abstained` as a pass. The first is the product fix; the
  second hides a real inconsistency. Also worth a look: why
  `outside-study-in-scarlet` answers at all (0.14 sufficient) when its
  scene is not in the corpus.

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

## KI-28: The winning reranker is not licensed for production

Logged 2026-09-30, from the C2 reranker comparison. **Decided, not
overlooked** — read this before the next reranker change.

`retrieval.reranker` is set to `jev` (settings version 136) on the
strength of an offline replay over all 23 `answer`-class acceptance items
(`apps/api/.data/rerank-comparison.json`, produced by
`scripts/compare_rerankers.py`):

| reranker | recall@8 | mean rank of expected | mention@8 | p50 ms | $/query | fell back |
| --- | --- | --- | --- | --- | --- | --- |
| jev | 1.000 | 1.0 | 1.000 | 431 | 0.000607 | 0/23 |
| nvidia | 1.000 | 1.0 | 0.818 | 839 | 0.0 | 0/23 |

Both arms saw byte-identical fused candidates (top 40) and no generation
happened, so the only variable is the reranker. The prompt's tiebreak is
recall → latency → cost: recall ties at 1.000, so latency decides, and
Jev is 1.9× faster. It also finds the `mention` term in the top 8 on four
items NVIDIA misses (`plot-red-headed-league`, `fact-weena`,
`ml-fr-bovary-death`, `xl-en-bovary-death`).

- **The catch:** the $0 NVIDIA column is the *free, evaluation-only* tier
  (see the provider reference). It is not licensed for production, so
  $0/query is not a real option to ship. Jev's $0.000607/query is real
  money — about $0.55 per 1,000 queries, before the run's other calls.
- **Why it matters:** choosing Jev trades a licensing problem for a
  per-query cost on the hot path of every answer. At the current eval
  volume that is noise; it is not noise at volume.
- **Next step (not this slice):** stand up Cohere Rerank through Bedrock
  per the earlier provider analysis and replay this same script against
  all three. `CohereRerank` is already implemented and already takes
  precedence when `COHERE_API_KEY` is set, so the third arm is a config
  change plus one more replay, not new code.
- **Also worth knowing:** Fast mode cannot use Jev — it has no
  DecisionEngine, so it falls back to fused order and logs a warning.
  If Fast ever ships, thread an engine through or exclude it from the
  reranker comparison.

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
