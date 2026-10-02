# Working as an autonomous agent (and writing prompts for one)

Rules for any agent working on Veriforge unattended (Claude Code, Codex,
others), and for whoever writes the prompt it runs from. Each rule traces
back to a run that went wrong. See "Where these came from".

## Rules for the agent

- **Gate and CI mechanics are done as of D8 (2026-10-02).** New gate or CI
  issues are **logged, not dispatched**, unless they block a merge. The scope
  check is a tested script, CI keeps its evidence on both paths, and a failing
  gate re-runs and judges the mean of 3.
- **Time box: 30 minutes per item.** At 30 minutes without a verified
  fix, stop.
  - Commit what is verified. A failing repro test marked `xfail`, with
    notes, counts.
  - Add a dated note under the item in `docs/known-issues.md`.
  - Move on, or report back.

  Never spend over an hour on one item without reporting.
- **Read the failing path before theorising.** Open the code the symptom
  runs through: the dependency, the fixture, the handler. Most "mystery"
  bugs are a fact about the code you haven't read yet.
- **Prove the mechanism before writing a fix.** Do one cheap, decisive
  check: a repro test, or one log line at the suspected point. No
  general-purpose harnesses, and no instrumentation that changes timing
  (file I/O in fixtures, sleeps, global hooks). It can create a new
  symptom that you then misread as the original.
- **Fix the root once, where all callers go through.** No per-caller
  patches, no retries around flaky tests, no widened timeouts to hide a
  race.
- **Commit the smallest verified change immediately.** Progress must
  never be zero. One commit per item, with the item ID in the subject.
- **Leave the tree clean when you stop.** Revert unverified edits and
  remove temp files, then report what you established, what you didn't,
  and your next step.
- **Report honestly.** Say what was verified versus assumed, what you
  skipped, and what's blocked. "External failure" claims need evidence
  (for example, tests reached a live provider because a key leaked in;
  that was ours, not external).
- **Tests never reach live providers**, and e2e never makes LLM calls by
  default (`testing.md`, `playwright.md`).

## Rules for the prompt writer

- **Dispatch in small batches.** 2–4 items per run, then review. A
  ten-item prompt invites hours of private grinding and gives you no
  review point. Long runs also degrade: the context fills with dead
  theories.
- **Order cheap and low-risk items first,** so real fixes land even if a
  hard item runs long. Keep dependency order (for example, the fix, then
  the smoke test, then the eval gate).
- **Put the stopping rule in the prompt.** Time box, what to commit when
  stuck, and when to report back. An agent without a checkpoint keeps
  iterating.
- **State the spec and the check for each item:** what's wrong, where it
  is, the fix and the test (the `docs/known-issues.md` format).
- **Match the model to the item.** Concurrency, races and answer-quality
  debugging get the strongest model at high reasoning effort. UI tweaks,
  config and wiring are fine on a faster setting. If an agent still loops
  under these rules, switch models.
- **Verify the report before merging.** Re-run the claimed checks, and
  check "external" failures and root-cause claims against the code
  (`docs/known-issues.md` records several claims that didn't hold up).
- **Budget gates:** before any step that spends provider credit (eval
  gate, smoke runs), the prompt tells the agent to check the balance and
  stop below a floor.

## Parallel work

- **Independent code items:** sub-agents in separate git worktrees, one
  branch each, with a test database name per worktree. Merge one at a time,
  each through the gate.
- **Quality runs** may run concurrently **only on isolated stacks**: an
  ephemeral DB per fast20 run (`eval-gate-local`), and a separate api
  container pinned to the commit for each acceptance run. Never against the
  hot-reloading dev api.
- **Latency is measured alone:** one run with nothing else on the machine,
  or the CI gate. Concurrent runs inflate p50, and a baseline carries
  latency.
- **Quality phases stay serial:** one variable at a time.
- Start with 2–3 concurrent runs. On any 429, back off and note it in the
  report.

## Where these came from

- **2026-09-27, KI-14 (flaky tests):** 2 hours on one item, zero commits.
  An unproven "leaked asyncio tasks" theory led to a task-draining
  fixture that hung the suite. The actual cause,
  `get_session` committing after the response is sent, was a two-minute
  read of `db/session.py` that never happened. The prompt had ten items
  and no time box.
- **2026-09-26, sources-panel:** five pytest failures reported as
  "external Cohere 429s" were our tests using a real key from `.env`.
- **2026-09-26, UX pass:** a slow provider was "fixed" by widening the
  sweep window to 480 s (hiding crashed runs) instead of adding a
  heartbeat (KI-4). The 402 was "fixed" by switching to free models
  instead of capping `max_tokens` (KI-1).
