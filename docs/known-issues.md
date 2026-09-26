# Known issues

Open defects and process debt that were found but deliberately left for later.
Each item says what's wrong, why it matters, where it lives, and what the
fix is. When you fix one, delete it and put its ID in the commit body.

Logged 2026-09-26, after the UX pass and Gutenberg demo (`ea16d2b..725bbc5`).

**Do these in order.** KI-1 and KI-2 unblock KI-5, and KI-5 unblocks KI-6.

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

## KI-2: Free OpenRouter pool too unreliable for the generator

- **What:** `44fe80e` put every non-Jev call on `:free` models. The free
  pool is shared and regularly returns **503 `provider_overloaded`**, with
  calls taking minutes.
- **Impact:** `make smoke` turns 2–5 (anything that needs the generator)
  don't finish. The eval gate can't run (KI-6).
- **Fix:** run the **generator** and the **DecisionEngine fallback** on a
  cheap paid model (DeepSeek V3 or Gemini Flash class, about
  $0.10–0.30/M tokens). Keep `:free` for the `small` role (titles,
  suggestions), where a failure only costs polish. Jev is unchanged.
  Update the model seed and `config.py` defaults (`fallback_model`
  currently points at `nvidia/nemotron-3-super-120b-a12b:free`).
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
