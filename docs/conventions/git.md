# Git conventions

Companion to `CLAUDE.md`'s "Non-negotiables" and "Build order." This file
exists because Veriforge is built as ten separate slices, likely across
separate Claude Code sessions — the commit history is how a later slice
finds out *why* an earlier one made a choice, so it has to carry more
than a typical single-sitting project's history would.

## Branching

- `main` is always deployable — it's what CI/CD in TRD §16 pushes to
  production. Nothing lands on it without CI green (unit tests, and the
  eval gate where it applies).
- One branch per slice: `slice/03-retrieval-fast-mode`,
  `slice/04-decisions-auto`, matching the slice names in TRD §17. A slice
  branch can have several PRs into it if the slice is broken into smaller
  reviewable chunks, but the slice only merges to `main` once its
  acceptance criteria (TRD §17) are met.
- Fix-forward branches off `main` for anything found after a slice has
  merged: `fix/quota-double-charge-on-cancel`, not a new slice branch.
- No long-lived branches beyond the current slice — a slice branch that's
  still open when the next slice starts is a sign the acceptance criteria
  weren't actually met; don't start slice N+1 from an unmerged slice N
  branch (see `CLAUDE.md`'s build-order rule).

## Commits

Format: `<type>(<scope>): <summary>`, imperative mood, scope matching the
package or area touched.

```
feat(retrieval): add small-to-big context expansion
fix(quota): settle reserved credits on cancelled runs
test(decisions): cover circuit-breaker cooldown timing
docs(adr): record ADR-001 no-redis decision
refactor(graph): move claim extraction out of review node
chore(infra): add EBS snapshot lifecycle rule
```

Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `perf`. Scope
is a package name from `docs/conventions/python.md`'s layout or a feature
name from `react.md`'s — not a file name.

**Every commit implementing or touching a numbered requirement references
it in the body**, not the subject line (keeps subjects scannable):

```
feat(graph): add abstention branch when evidence is insufficient

Implements TR-4. Abstains after the retry loop exhausts (TRD §7) and
offers Web/Deep as next actions.
```

A commit that follows an ADR or changes something an ADR governs
references it the same way (`Follows ADR-001.`). A commit that changes a
prompt bumps its version header (`python.md`) and says so in the body,
since that's what an eval diff will later need to explain a score change.

Small, single-purpose commits over one large slice-sized commit — a
reviewer (or a later Claude Code session) should be able to `git log
--oneline` a slice branch and read it as a story, not have to open the
diff to know what happened.

## Pull requests

Every PR description starts with the slice and the requirement IDs it
covers, in the shape `CLAUDE.md` already asks for ("a short plan... that
lists the requirement IDs it covers"):

```markdown
## Slice 4 — Decision layer and Auto mode

Implements: CH-1, CH-2, TR-4, TR-5, TX-1, SR-5
Follows: ADR-001 (RunBus usage in the retry loop)

### What changed
- DecisionEngine with Jev + LLM fallback, circuit breaker, shadow mode
- Ingress node, sanitizer, structural injection defence
- Retry loop, abstention branch, conflict check
- Trace panel (frontend)

### Verification
- [ ] Unit tests pass (retrieval/quota/decisions at tier-1 coverage)
- [ ] Eval gate: faithfulness / abstention accuracy vs. baseline (paste
      the CI comment or numbers)
- [ ] Manually verified: Auto mode meets TRD §5 latency targets locally
```

PRs into `main` from a completed slice branch require the eval gate
result pasted or linked, not just a green check — the number itself
(faithfulness delta, abstention accuracy) is what the next slice's author
needs to see, and CI's pass/fail alone doesn't show a regression that's
still within threshold but worth knowing about.

A PR that only touches `docs/`, `infra/cdk` config, or non-behavioural
chores doesn't need the eval-gate checklist item — mark it clearly as
such in the description so reviewers don't go looking for numbers that
don't apply.

## Merge strategy

- **Squash merge** slice/fix branches into `main`. The PR description
  becomes the squash commit message, which is why it needs the
  requirement IDs and verification section — that's the permanent record
  for that change once individual commits are gone.
- **No squash** for the rare case of merging two independent slices that
  were developed in parallel and need their own separate history — use a
  regular merge commit there instead, but this should be uncommon given
  the one-slice-at-a-time build order.

## Tags and releases

Tag `main` at the end of each slice once it's merged and its acceptance
criteria verified — locally for slices 0–8, in production from slice 9
on (see `CLAUDE.md`'s Build order: no AWS deployment happens before
slice 9): `v0.4.0-slice4`. This gives a rollback point per slice (relevant
once slice 9 makes TRD §16's single-box deployment real) and a
changelog anchor — `git log v0.3.0-slice3..v0.4.0-slice4` is the fastest
way to answer "what did slice 4 actually change."

## What doesn't get committed

- Nothing under `apps/web/src/generated/` diverges from what `openapi-ts`
  produces from the current backend — it's committed (so CI and other
  contributors don't need to regenerate it to build), but a PR that hand-
  edits a generated file instead of the source Pydantic model gets
  rejected in review, not just discouraged (`CLAUDE.md`).
- No secrets, ever, including in `infra/cdk` — provider keys and anything
  in SSM Parameter Store (TRD §11) stay out of the repo entirely, not
  even in an ignored-but-present `.env.example` with a real-looking
  placeholder that could be mistaken for a real key.
- No recorded Playwright/eval fixtures larger than a few hundred KB
  without checking — large fixture files (`playwright.md`) belong in Git
  LFS or S3-and-referenced if they grow past that, not committed raw.