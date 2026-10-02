# Docs naming

## Point-in-time documents get a datetime prefix

Any document that records a moment gets a name of the form
`YYYY-MM-DD-HHMM-<slug>.<ext>`: local time (+08), with the date and time
the document was created. Examples:

- dispatch prompts: `docs/prompts/2026-09-30-0008-darcy-c1-unblock-measure.md`
- reviews and reports: `docs/reviews/2026-09-29-2332-python-backend-code-review.md`
- screenshots and design references: `docs/design-refs/2026-09-25-1547-grok-thread.png`

Why: these accumulate, and nobody edits them after they're used. The
prefix sorts them chronologically in any file listing, and shows at a
glance which prompt or review is the latest.

- Take the date and time from when the document was **created**, and
  don't change it when you edit the document later.
- The slug is short kebab-case naming the subject, with no date repeated
  in it.
- A revised prompt that replaces an earlier one gets a **new** file with
  a new prefix, so the old one stays a record of what was dispatched.
- When you rename a file, update every reference to it
  (`grep -rn <old-name> docs CLAUDE.md`).

## Living documents keep stable names

These are edited in place and referenced by path from `CLAUDE.md`, the
code and commit messages. **No prefix:**

- `docs/PRD.md`, `docs/TRD.md`, `docs/glossary.md`,
  `docs/design-system.md`, `docs/known-issues.md`
- `docs/conventions/*.md`
- `docs/adr/ADR-NNN.md`: ADRs use their own numbering, and the date lives
  in each ADR's status line

A living document records dates *inside* it, in dated notes or amendment
markers (for example the TRD's `*(amended 2026-09-28, batch A)*`), not
in its filename.
