# Known issues

Open defects and process debt that were found but deliberately left for later.
Each item says what's wrong, why it matters, where it lives, and what the
fix is. When you fix one, delete it and put its ID in the commit body.

Logged 2026-09-26, after the UX pass and Gutenberg demo (`ea16d2b..725bbc5`).

**Order:** KI-12 unblocks KI-5, and KI-5 unblocks KI-6. KI-1, KI-2 and KI-7
were fixed in `b600bed`, and KI-3 in the sources-panel merge. KI-8 is independent. Do it
before the next Playwright run.

---

## KI-4: The sweep window was widened instead of fixing the heartbeat

- **What:** `7ba4f81` raised `heartbeat_sweep_seconds` from 60 to **480**
  (`config.py:38`). The problem was real: a run waiting on a slow provider
  writes no heartbeat, so the sweep killed it. But the fix means a run
  that really crashed now shows as "running" for 8 minutes.
- **Where:** `graph/runner.py` `_touch_heartbeat` (~l.194) is only called
  on activity. `sweep_stale_runs` is at ~l.934.
- **Fix:** start a background task per run that calls `_touch_heartbeat`
  every `heartbeat_interval_seconds` (15) while the run's coroutine is
  alive, and cancel it in the run's `finally`. Then put
  `heartbeat_sweep_seconds` back to 60 and delete the comment about the
  worst-case LLM call. It no longer applies.
- **Test:** a run blocked on a fake 120 s provider call is not swept, and
  a run whose task was killed is swept within about 60 s.

## KI-5: The smoke conversation has never passed end to end

- **What:** `apps/api/scripts/smoke_chat.py` (`make smoke`). Turn 1 (small
  talk) passes. Turns 2–5 are blocked by KI-2.
- **Done when:** all five turns behave as specified:
  1. small talk, no citations
  2. a cited *Pride and Prejudice* answer
  3. a correct abstain or a Sherlock citation
  4. citations from both Frankenstein and The Time Machine
  5. small talk

  The final chat title is a topic, not the question. Paste the output
  into the commit body.
- **Depends on:** KI-1 and KI-2. KI-3 and KI-4 are nice to have first.

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
- **Rule going forward:** no graph, prompt or model change lands on
  `main` until the gate has run green.

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

## KI-9: The model picker is hidden on mobile (CH-8)

- **What:** since `a087f38` (the redesign v3.1 fix pass), `ModelPicker`
  sits inside a `hidden sm:block` wrapper in the composer, so below 640px
  it's `display: none`.
- **Impact:** mobile users can't choose the answer model, which breaks
  PRD CH-8.
- **Fix:** show a compact trigger on mobile: the short name only, or an
  icon button that opens the same menu, sized to fit the composer row at
  390px next to the Deep and Web toggles. Don't hide it.
- **Test:** a vitest check that the composer renders the model trigger at
  a mobile viewport, or that the wrapper has no `hidden` class.

## KI-10: Cohere rerank is out of quota

- **What:** the Cohere key is a trial key capped at 1,000 calls per month,
  and it's used up (checked 2026-09-26). Since `d1da81d`, retrieval
  degrades to fused order instead of failing the run, but answers lose
  the rerank step. That matters for KI-12.
- **Fix, pick one:**
  - a Cohere production key
  - NVIDIA's free rerank NIM (`nv-rerankqa` family, same NVIDIA key as
    in KI-2's discussion) behind the existing `RerankProvider` protocol
  - unset `COHERE_API_KEY` to use fused order on purpose
- **Test:** the provider unit test with a mocked transport, as
  `CohereRerank` has.

## KI-11: The sanitizer sends every retrieved chunk to Jev

- **What:** each Auto run asks Jev about 50 `chunk_injection_n`
  questions (one batched call) before rerank trims to the top 8. Seen in
  run events on 2026-09-26.
- **Impact:** Jev is the only paid call left, and its price isn't
  published (`typesafe/jev-router` lists `-1`). This is the likeliest
  source of the unexplained $95 OpenRouter spend.
- **Fix:** sanitize after rerank, only the chunks that reach the
  generator (top 8), or confirm in the OpenRouter Activity page that Jev
  bills per call, not per question, before changing anything. Check TRD
  §11 for the required order.

## KI-12: Grounded answers are wrong even when the right book is retrieved

Seen in `make smoke` on `fix/model-runtime`, with the LLM path now
working:
- **Darcy's proposal:** it abstains ("not enough evidence") while listing
  *Pride and Prejudice* chunks. The proposal text exists in the corpus. A
  direct call with those chunks answers correctly in 2 s, so it's either
  retrieval (lexical_weight came back 0.01, so near-pure vector search,
  with no rerank because of KI-10) or the `sufficient` decision threshold
  (0.6).
- **Sherlock/Afghanistan:** the scene isn't in the corpus (*A Study in
  Scarlet*), so the answer should abstain. Instead `sufficient` scored
  exactly 0.6 = threshold, generation ran on unrelated chunks, and the
  answer was the literal text `[1], [7], [2]`. The reviewer then marked
  it **supported** (claim "The answer references sources [1], [7], and
  [2]"). The reviewer should treat an answer with no factual content as a
  failure.
- **Frankenstein vs Time Machine:** it abstains while retrieving both
  books.
- **Also:** Jev's ingress chose `source: web` for a book question (the
  toggles on `feat/sources-panel` remove that choice from Auto). The
  abstain message still tells users to "click the source picker", which
  is outdated once the toggles land.
- **Fix:** trace one run per case end to end (retrieved chunk ids, then
  rerank, then sufficiency inputs), fix the root cause, then re-run
  `make smoke`. A threshold change needs the eval gate.

## KI-13: Chat title never refines

- **What:** after a smoke conversation with a completed grounded turn,
  the title stays "New chat". `6b865fc` was meant to title the chat after
  the first non-chitchat exchange.
- **Fix:** find out whether refinement is skipped (abstained turns?),
  fails silently, or doesn't commit. Add a test for "chitchat, then
  grounded completes, then the title is a topic".

## KI-14: Ingest chat-documents tests are flaky in the full suite

- **What:** after the sources-panel merge, 2 of 4 full `pytest` runs had
  one failure or error in the chat-documents tests
  (`tests/ingest/test_documents_api.py::test_chat_documents_are_created_listed_and_cascade_deleted`,
  `tests/ingest/test_ownership_filters.py::test_chat_documents_are_owner_only`).
  Both pass in isolation every time, so it's likely order or state leakage
  (lazy chat-collection creation, queued ingest jobs, or truncation
  between tests).
- **Fix:** reproduce with `pytest -p randomly` or by running
  `tests/ingest` after `tests/chats`, find the shared state, and fix the
  fixture. Don't add retries.

---

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
  - A candidate second provider and a free reranker (KI-10). Keep the
    embeddings on `text-embedding-3-small`, because
    `chunks.embedding` is `vector(1536)`.
- **The Kimi and GLM subscriptions are coding plans.** They're licensed
  for coding tools only, so they're not for Veriforge's runtime or evals.
- **The OpenRouter key** had $4.99 of $100 left. Free models cost
  nothing, so the spend is Jev, the old Haiku fallback, eval runs or
  embeddings. See KI-11.
- **Cohere:** the trial key is 10 calls/min and 1,000/month.
