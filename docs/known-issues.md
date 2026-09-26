# Known issues

Open defects and process debt that were found but deliberately left for later.
Each item says what's wrong, why it matters, where it lives, and what the
fix is. When you fix one, delete it and put its ID in the commit body.

Logged 2026-09-26, after the UX pass and Gutenberg demo (`ea16d2b..725bbc5`).

**Do these in order.** KI-1, KI-2 and KI-7 unblock KI-5, and KI-5 unblocks KI-6.
KI-8 is independent. Do it before the next Playwright run.

---

## KI-1: No output-token cap on LLM calls (a 402 waiting to happen)

- **What:** `apps/api/providers/llm.py` never sets `max_tokens`. LiteLLM
  falls back to the model's maximum (64k for some models), and OpenRouter
  rejects the call with **402** when the key's balance can't cover that
  worst case.
- **Evidence:** every run failed this way before `44fe80e`. That commit
  moved non-Jev calls to free models, which don't trip the balance check.
  The cause is still in the code.
- **Impact:** the first paid model (the fallback, the user-picked model
  after KI-3, or the paid generator from KI-2) fails once the balance is
  low. Chat titles also silently never refine, because the run dies first.
- **Fix:** set an explicit `max_tokens` per role, passed from the call
  sites through `complete()` / `stream()`. Starting points: generator
  2048, planner 1024, claim extractor 1024, small/titler/suggestions 256.
  Keep the limits in `config.py`.
- **Test:** a pytest that asserts `max_tokens` is present on every LiteLLM
  call. Mock at the LiteLLM boundary.

## KI-2: Model plan: free Nemotron for runtime, pinned paid model for the eval gate

- **What:** `44fe80e` put every non-Jev call on `:free` models with no
  fallback chain. On 2026-09-26 the free pool returned 503
  `provider_overloaded`, and `make smoke` turns 2–5 didn't finish.
- **Live check, 2026-09-26:** each free model got a JSON-title task and a
  cited-answer task with two quoted sources and one unanswerable part.

  | Model | Result |
  | --- | --- |
  | `nvidia/nemotron-3-super-120b-a12b:free` | ✅ Valid JSON, correct `[n]`, admits the gap, 1–2 s |
  | `nvidia/nemotron-3-ultra-550b-a55b:free` | ✅ Same quality, 4–6 s |
  | `openrouter/free` | ✅ Routes to an available free model |
  | `qwen/qwen3.8-27b:free`, `google/gemma-4-*:free` | 429, rate-limited upstream |
  | `thinkingmachines/inkling*:free` | 403, agentic harnesses only |
  | `nvidia/nemotron-3.5-lightning:free` | Prints its reasoning, 50–170 s |
  | `liquid/lfm-2.5-2.6b:free`, `dots-studio/dots-3-note-preview:free` | Empty output on one of the two tasks |

- **Fix:** set roles in the model seed and `config.py` defaults.

  | Role | Model | Fallback |
  | --- | --- | --- |
  | generator, DecisionEngine fallback, small | Nemotron 3 Super `:free` | `openrouter/free` |
  | planner, claim extractor | Nemotron 3 Ultra `:free` | Nemotron 3 Super `:free` |
  | eval gate (all non-Jev roles) | **One pinned cheap paid model** via OpenRouter (DeepSeek V3 or Gemini Flash class), no fallback. The gate must fail, not switch models. | none |
  | Jev | unchanged | TRD §8 |

  Free ids churn. Re-run the check (a script under `apps/api/scripts/`)
  before changing ids, and record the date.
- **Why a paid model for the gate:** the free pool swaps, rate-limits and
  retires models without notice, so a baseline on it drifts for reasons
  unrelated to code. A gate run is about 500k tokens, which is about
  $0.10–0.20.
- **Not options:**
  - The Kimi and GLM **coding-plan** subscriptions are licensed for coding
    tools only. Don't use them in Veriforge's runtime or eval gate. They're
    fine for driving Claude Code or other dev tooling.
  - RunPod: idle GPU cost far above API cost at this volume.
  - Ollama (8B on a 16 GB M5) is too weak for eval scoring. It's
    optional for offline dev only (host-run, LiteLLM `ollama/…`,
    `host.docker.internal:11434`). Don't build it unless asked.
- **Budget:** the OpenRouter key had $4.99 of $100 left on 2026-09-26.
  The spend isn't from free models. Check Activity in the OpenRouter
  dashboard (it needs a management key) to see how much is Jev versus the
  old Haiku fallback versus evals.
- **Depends on:** KI-1. Without a token cap, a paid model reproduces the
  402.

## KI-3: The model picker doesn't affect the generator

- **What:** `graph/generate.py:78,108` (`stream_grounded_answer`) tags
  calls with `role: "generator"`. `quota/usage.py:34` `resolve_model`
  returns `model_roles.get(role, requested)`, so the admin **role mapping
  overrides the model the user picked**.
- **Impact:** the composer's model picker is decorative for answers. This
  breaks the PRD model-picker requirement (AC-2/CH-8 area).
- **Fix:** the user's requested model wins for the generator. The
  `generator` role is only the default when the chat has no `model_id`.
  Other roles (small, extractor, planner) stay admin-controlled. Before
  changing `resolve_model`, check whether the quota ledger prices calls
  by the resolved model.
- **Test:** a chat with `model_id = X` generates with X even when the
  `generator` role maps to Y. A chat with no model uses Y.

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
- **Fix:** once KI-5 passes, run the 20-item fast subset. Because the
  models changed, record a **new baseline** with before/after numbers
  for faithfulness, abstention accuracy and p50 latency. If faithfulness
  or abstention regress beyond the gate, revert or fix before any further
  graph work.
- **Rule going forward:** no graph, prompt or model change lands on
  `main` until the gate has run green.

## KI-7: No concurrency cap or 429 fallback on LLM calls

- **What:** `providers/llm.py` sends every call as soon as it's made.
  Free models allow about 20 requests per minute per model (and 1,000 per
  day on an account with credits). One Auto question makes about 5–8 LLM
  calls, so parallel eval items or Deep-mode hops trip 429.
- **Fix:** in `providers/llm.py`, the one choke point every call already
  goes through:
  - a per-model `asyncio.Semaphore` with a configurable cap in `config.py`
    (default 4)
  - on 429, wait for `Retry-After` (capped), then move to the role's next
    fallback model
  - reuse the existing LiteLLM retry and fallback settings, with no new
    retry layer

  Per-process is enough (ADR-001: no Redis at Stage 1).
  `# ponytail:` note: per-process cap, move to a Postgres-backed limiter
  if multiple workers exceed provider limits.
- **Test:** with a fake LiteLLM that returns 429 then 200, the call
  succeeds on the fallback model. With cap 2 and 5 concurrent calls, at
  most 2 are ever in flight.

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
