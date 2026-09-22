# Git conventions

Companion to `CLAUDE.md`'s "Non-negotiables" and "Build order." This file
exists because Veriforge is built as ten separate slices, likely across
separate Claude Code sessions — the commit history is how a later slice
finds out *why* an earlier one made a choice, so it has to carry more
than a typical single-sitting project's history would.

## Branching

- `main` is always deployable — it's what CI/CD in TRD §16 pushes to
  production. Run the CI checks locally (unit tests, and the eval gate
  where it applies) before merging into it; CI validates every push to
  `main`, and a red run there is fixed forward immediately.
- One branch per slice: `slice/03-retrieval-fast-mode`,
  `slice/04-decisions-auto`, matching the slice names in TRD §17. A slice
  branch can have several commits if the slice is broken into smaller
  chunks, but the slice only merges to `main` once its acceptance
  criteria (TRD §17) are met.
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

Do not add `Co-Authored-By` (or any other co-author) trailers anywhere in
commits — subject, body, or trailers.

Small, single-purpose commits over one large slice-sized commit — a
reviewer (or a later Claude Code session) should be able to `git log
--oneline` a slice branch and read it as a story, not have to open the
diff to know what happened.

## Merging to `main` — local, no pull requests

No pull requests are raised. The merge decision is made locally: once a
slice branch's acceptance criteria pass on your machine, merge it into
`main` yourself and push `main` from local.

The squash commit message (see Merge strategy) carries the record a PR
description would have — the slice and the requirement IDs it covers, in
the shape `CLAUDE.md` already asks for ("a short plan... that lists the
requirement IDs it covers"):

```markdown
feat: slice 4 — decision layer and Auto mode

Implements: CH-1, CH-2, TR-4, TR-5, TX-1, SR-5
Follows: ADR-001 (RunBus usage in the retry loop)

### What changed
- DecisionEngine with Jev + LLM fallback, circuit breaker, shadow mode
- Ingress node, sanitizer, structural injection defence
- Retry loop, abstention branch, conflict check
- Trace panel (frontend)

### Verification
- [x] Unit tests pass (retrieval/quota/decisions at tier-1 coverage)
- [x] Eval gate: faithfulness / abstention accuracy vs. baseline
      (faithfulness 0.87 → 0.89, abstention 12/20 → 18/20)
- [x] Manually verified: Auto mode meets TRD §5 latency targets locally
```

A merge from a completed slice branch requires the eval gate result in
that message, not just "tests pass" — the number itself (faithfulness
delta, abstention accuracy) is what the next slice's author needs to see,
and pass/fail alone doesn't show a regression that's still within
threshold but worth knowing about.

A merge that only touches `docs/`, `infra/cdk` config, or non-behavioural
chores doesn't need the eval-gate checklist item — mark it clearly as
such in the commit message so nobody goes looking for numbers that don't
apply.

## Merge strategy

- **Squash merge** slice/fix branches into `main`, locally:

  ```sh
  git checkout main
  git merge --squash slice/04-decisions-auto
  git commit  # paste the slice/IDs/verification message from above
  git push origin main
  ```

  The squash commit message is the permanent record for that change once
  individual commits are gone — which is why it needs the requirement
  IDs and verification section.
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

- Nothing under `apps/web/src/generated/` is committed — it's gitignored
  and regenerated with `npm run codegen` against a running API
  (`react.md`), never hand-edited: if a generated type is wrong, the
  source Pydantic model is wrong — fix it there and regenerate
  (`CLAUDE.md`). When a later slice's CI build imports the client, give
  CI a codegen step rather than committing the output.
- No secrets, ever, including in `infra/cdk` — provider keys and anything
  in SSM Parameter Store (TRD §11) stay out of the repo entirely, not
  even in an ignored-but-present `.env.example` with a real-looking
  placeholder that could be mistaken for a real key.
- No recorded Playwright/eval fixtures larger than a few hundred KB
  without checking — large fixture files (`playwright.md`) belong in Git
  LFS or S3-and-referenced if they grow past that, not committed raw.