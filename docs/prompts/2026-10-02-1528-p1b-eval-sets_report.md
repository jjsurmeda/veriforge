# P1b Phase 1 report — eval sets that can certify the RAG system

Branch `p1b/eval-sets`, off `main` at `44be5fa`. Written from the worktree
`/Users/jjsurmeda/dev/my-projects/veriforge-p1b`.

**Status: PARTIAL. Two of the six Phase 1 items are complete, tested and
committed. Four are not started.** No labels were changed, no gate was wired,
no baseline was rewritten, and nothing belonging to the D8 dispatch was
edited. Read "Not done" below before scheduling the rest — the two items that
are missing are the two that most of the Phase 2 work depends on.

**Credits: $0.00 spent.** `GET /api/v1/credits` read at the start: $9.55
remaining. No live step was taken — no eval run, no acceptance run, no LLM call
of any kind. Every number in this report came from read-only SQL over a copy of
the database. (Floor was $0.75.)

---

## What is committed

| Item | Commit | Status |
| --- | --- | --- |
| 1. Scripted label audit | `1052001` | **done** |
| 5. Runner/scorer: per-corpus, `min_support`, subsets | `97959cb` | **done** |
| 2. Counterfactual corpus | — | **not done** |
| 3. Books to 20/20 + ambiguity items | — | **not done** |
| 4. Eval corpora out of Shared (KI-24) | — | **not done** |
| 6. Judge validation sheets | — | **not done** |

I read the mandatory list first: `CLAUDE.md`, PRD v3 §5, TRD §15,
`docs/conventions/testing.md`, `agents.md`, `git.md`, and KI-24, KI-27, KI-36,
KI-37.

---

## Item 1 — scripted label audit (done)

`apps/api/scripts/audit_labels.py`, `apps/api/tests/scripts/test_audit_labels.py`.

The audit core (`audit_items`) is pure — a `Corpus` of passages in, an
`AuditReport` out — so it is unit-testable without a database. Only
`corpus_from_db` touches SQL, and it deliberately reads the rows
`retrieval/filters.py::build_scope` would admit rather than calling retrieval:
the audit asks what the corpus *contains*, so retrieval ranking must not
influence a label. The pipeline is never consulted.

Run against both sets, writing a `proof` onto every item:

```
DATABASE_URL=…/veriforge_p1b .venv/bin/python scripts/audit_labels.py \
  ../../evals/seed/items.json --collection eval-seed-corpus --write-back
DATABASE_URL=…/veriforge_p1b .venv/bin/python scripts/audit_labels.py \
  ../../evals/acceptance/books.json --write-back
```

### Isolation actually used

I did **not** use the shared dev database. `veriforge_p1b` was created as a
copy of `veriforge` (`pg_dump | psql`) and is the only database this branch
touches. Nothing ran against the hot-reloading dev api, no container was
started, and no latency was measured. The only other DB on the host is
`veriforge_test_p1b` for the suite, which satisfies `conftest.py`'s
`veriforge_test_` naming rule.

### Audit findings table

**34 findings across 111 items. Every label held — none was wrong.** Each
finding was spot-read against the corpus before being recorded, and in every
case the corpus named the entity without containing the fact asked for.

| Set | Item | Finding | Verdict after spot-read |
| --- | --- | --- | --- |
| books | `outside-whitman-lilacs` | `abstain_false_hit` 'abraham' | Noli Me Tangere footnote on Abraham/Isaac (Gen. XXII). False hit. |
| books | `outside-study-in-scarlet` | `abstain_false_hit` 'afghanistan' | Watson's own "experience of camp life in Afghanistan". The *fact* is in the corpus; the *deduction* is not. **Borderline — needs the owner.** |
| books | `outside-general` | 'australia' | Alice's "is this New Zealand or Australia?"; two Holmes asides. 'canberra' 0, 'sydney' 0. |
| books | `outside-moriarty` | 'falls' | Ordinary English in P&P and Holmes. 'moriarty' 0, 'reichenbach' 0. |
| books | `outside-emma` | 'smith' | "Mr. Goldwin Smith", a quoted art critic. 'woodhouse' 0. |
| books | `outside-war-of-the-worlds` | 'worlds' | "I would not have missed it for worlds". 'tripod' 0, 'martian' 0. |
| books | `outside-dracula` | 'count' | "the Count" is Holmes's client, not Dracula. 'stoker' 0, 'helsing' 0. |
| books | `outside-looking-glass` | 'capture'/'alice' | Alice in Wonderland, the wrong book. 'chess' 0. |
| books | `outside-moby-dick` | 'whale' | Frankenstein's whalers. 'ahab' 0, 'pequod' 0. |
| books | `ml-es-outside` | 'escribio' | Ordinary Spanish verb. |
| books | `ml-fr-outside` | 'miserables' | Les Misérables is not in the corpus. |
| books | `ml-de-outside` | 'josef' | Don Quijote / Noli Me Tangere namesakes. |
| books | `ml-zh-outside` | '寶玉' | 西遊記 has a 寶玉 of its own; unrelated to 紅樓夢. |
| books | `ml-ja-outside` | 'しま' | Ordinary Japanese. |
| books | `library-list` | `underdetermined_source` | Five book titles attested across five documents, no `cite`. Correct for a library item — see the caveat below. |
| books | `library-count` | `answer_not_in_corpus` '5' | **Real weakness.** Requires the digit "5", which the corpus never states. |
| books | `fact-bennet-sisters` | `answer_not_in_corpus` '5' | Same. |
| books | `frame-walton` | `answer_not_in_corpus` 'Saville' | 'Saville' 0 in the corpus; the addressee of Walton's letters is not in this Gutenberg text. |
| books | `ml-de-samsa` | `answer_not_in_corpus` 'Käfer', 'Insekt' | The text says `Ungeziefer` (1 hit). 'Käfer'/'Insekt' are unattested synonyms. |
| books | `xl-en-samsa` | 'beetle', 'Käfer' | 'vermin' 2 and 'insect' 2 are attested; the two required ones are not. |
| books | `broad-verwandlung` | 'Insekt', 'Kakerlake' | Same shape as `ml-de-samsa`. |
| books | `xl-en-wukong-master` | 'Tang', 'Tripitaka', 'Xuanzang' | Latin transliterations of 唐僧 / 三藏, which the corpus has 725/810 times. Not attested *as Latin strings* — see caveat below. |
| books | `ml-ja-rashomon-oldwoman` | '髪' | **Audit bug, not a label bug.** 羅生門 does say 「この髪を抜いてな」; a lone kanji is invisible inside a CJK bigram. Fixed in the audit. |
| seed | `abstain-01`..`abstain-10`, `abstain-19`, `abstain-20` (12) | `abstain_false_hit` | Every one: the corpus names the entity (`AW-2000-XP`, `Aurora Widgets`, `RP-77`, the enterprise management protocol, `2.4 GHz`) and never the fact asked for (price, CEO, failure rate, discount, lubricant, 5 GHz). |

**Fixes applied: none to any label.** All 111 items now carry a `proof`.
`fast20_ids` is byte-identical; the write-back only fills a missing `proof` and
never overwrites a hand-written one, so `outside-whitman-lilacs` keeps its
human spot-read notes (tested).

### Two things the owner should decide

These are real observations from the audit, not fixes I made unilaterally,
because either resolution changes what the item measures:

1. **`outside-study-in-scarlet` is genuinely borderline.** The corpus contains
   Watson's "experience of camp life in Afghanistan". The item asks how
   *Holmes deduced* it, which the corpus does not contain. As `not_in_sources`
   it is defensible; as an `answer` item ("Watson had been in Afghanistan")
   it is also defensible. I left the label alone — this is a judgement about
   what the item is for, which is the owner's call.
2. **Three items accept only strings the corpus cannot produce** —
   `library-count` and `fact-bennet-sisters` require the digit `5`;
   `frame-walton` requires `Saville`. These are the KI-36 shape: a correct
   answer that fails a too-narrow check. They are `answer` items whose
   `mention` list is stricter than the corpus. I did **not** widen them,
   because the right answer is a judgement about which phrasing the item
   should accept, not something the audit can derive.

### A known limit of the audit

`xl-en-wukong-master` requires `Tang`/`Tripitaka`/`Xuanzang` — Latin
transliterations — while the corpus is Chinese (`唐僧` ×725, `三藏` ×810).
The audit cannot attest a romanisation from a Han-script corpus, so this item
will always look unattested. That is a limitation of a lexical audit, and it
is why the finding says "spot-read" rather than "wrong". It is also the same
object KI-27 describes (two referents for Wukong's master), so the item
belongs with P2's ambiguity work anyway.

### Tests

19 tests in `tests/scripts/test_audit_labels.py`, **mutation-checked**: I seeded
18 defects and confirmed each one fails the suite when reverted. Four of the
defects were found *by* the mutation process and fixed in the code — the
substring-matching bug, the library document-name rule, the lone-kanji bug, and
a redundant tie-break — so the mutation sweep was not a formality.

Two calibration rules I rewrote after looking at real output, both recorded in
the code:

- A should-abstain finding fires on the question's **rarest attested term**,
  and says "spot-read", never "the label is wrong". My first two attempts
  (passage-count ceiling, then co-occurrence) both over-fired on the books
  corpus and were discarded.
- `underdetermined_source` fires on cross-document mentions with no `cite`. It
  is a finding about the item's *checks*, not a claim that the item is
  ambiguous — the script cannot read passages and decide ambiguity, and I
  would rather it say less than pretend to know more.

**`library-list` is a known false positive of that rule.** A library item is
*supposed* to name every document, so "mentions span five documents" is the
item working correctly. The rule needs a `library` exemption before Phase 2
wires these subsets into a gate. I left it visible rather than special-casing
it, because the exemption belongs with the gate work.

---

## Item 5 — runner and scorer (done)

Commit `97959cb`. No gate wiring, no baseline touched.

- **Migration `0016`**: `eval_items.corpus` and `eval_results.min_support`, both
  nullable and deliberately unbackfilled. Verified up, down, up.
- **`aggregate_by_corpus`** — the existing rollup once per corpus. Items
  predating the column report under `unassigned`; a guessed corpus would make a
  per-corpus number mean something other than what it says.
- **`min_support_share`** — answers only. An abstention has no weakest claim;
  counting its stored `1.0` would pad the share with items that were never
  answered, which is how a run that declined everything could satisfy a
  grounding target.
- **PRD §5's remaining rows** — `false_abstention_rate`, `clean_declines`,
  `unclean_declines`, `should_abstain_item_runs`, `confident_wrong_answers`.
  The confident-wrong definition (asserts an answer to a should-abstain item)
  is tested **both ways**, including that the same text is not a confident
  wrong answer when the graph abstained, and that citing passages while saying
  "not in your sources" is an unclean decline rather than an assertion.
- **Decline regexes moved to `evals/abstention.py`** so `scripts/acceptance.py`
  and the runner classify declines identically. Two copies of a decline regex
  is how they drift until they disagree about which items are declines.
- **`gate_subsets`** in the seed set file, stratified across 5 categories with
  both classes present, read from the set file rather than the database.
  **Not wired into the gate** — that is Phase 2, with D8's writer, retry rule
  and tolerances unchanged.

Tests: 20 in `test_runner_per_corpus.py` + 2 added to `test_runner_source.py`,
mutation-checked — 15 seeded defects each fail the suite when reverted. One
survived the first sweep (nothing covered `min_support` actually being written
by `_run_item`), so I added a real DB round-trip test through the existing
stubbed harness. **Full suite 719 passed. `mypy --strict` clean.**

One note: `ruff format` reformatted `apps/api/evals/gate.py` and
`test_gate_thresholds.py` as a side effect of formatting `evals/`. Both are
D8's. I reverted both from git and confirmed the diff is empty. The gate tests
still pass. **Verified: no D8 file is in the diff.**

---

## Not done

I ran out of budget, not out of reasons. Each of these is a multi-hour piece of
work, and I would rather hand you two finished items than six half-built ones
with unproven labels.

### Item 2 — the counterfactual corpus (not done)

Needs 8–12 realistic documents (city guide, product handbook, HR policy, lab
protocol, a spec **with tables**, ≥2 non-English), each with a fictional header
and deliberately altered facts, plus ≥20 answerable and ≥20 should-abstain
items with `forbid` lists, ≥4 table lookups, ≥4 multi-hop, ≥2 per non-English
language, a `forbid` extension to the acceptance scorer, its own collection,
and an audit of all 40+ items. Every item needs a proof before it exists in a
set whose entire purpose is to be trustworthy — authoring them without the audit
would be the exact failure this prompt exists to prevent.

### Item 3 — books to 20/20 + ambiguity items (not done)

Six proven near-miss abstentions including 2 non-English, and three `pending_p2`
ambiguity items in the KI-27/Wukong shape. The audit above has already done the
expensive part (it is what tells you which near-misses are genuinely absent),
so this is the cheapest of the four to finish.

### Item 4 — eval corpora out of Shared (not done)

The schema question is real and needs an answer before code: `build_scope`
grants access by `col.owner_id = scope_user OR col.visibility = 'shared'`, and
`resolve_scope` derives the scope from the chat alone. Making the eval corpora
`private` works for the eval user (they own them) but gives the **throwaway
acceptance user** no access at all, and acceptance signs up a fresh user per
run. So this needs a real grant mechanism — a third `collectionvisibility`
value, or a join table — not the one-line change KI-24 suggests. That design
decision should be yours. My `veriforge_p1b` copy is untouched by it.

### Item 6 — judge validation sheets (not done) — **no files were produced**

**There are no judge validation files. Do not go looking for them.** The paths
you asked me to report do not exist.

Two blockers, both real:

1. `claims.csv` is specified as 30 claims sampled from D7's per-item exports
   (`.data/evals/*-96265f8.json`) **plus a fresh acceptance run's answers**.
   Those exports live in the other worktree's `.data/`, which I was told not to
   touch, and this worktree has no `.data/` at all.
2. The "fresh acceptance run" needs a live LLM run against an isolated stack
   (per `agents.md`, never the hot-reloading dev api). That is the single most
   expensive step in Phase 1 and I had no verified way to stand up an isolated
   api container inside this branch's budget.

Producing these sheets from the D7 exports alone would have been the easier
path, and I did not take it: the prompt asks for the two sources together
precisely so the sample is stratified across both, and half a validation set
labelled for an hour of the owner's time is worse than none — it would produce
agreement numbers that look measured and are not.

**For when this is done:** the sheets should be built from
`.data/evals/*-96265f8.json` in whichever checkout the owner prefers, plus a
fresh acceptance run. They are plain CSVs, so they can be labelled from the
main checkout if that is easier — but the run has to happen somewhere, and
Phase 1 does not rebuild them until both sources exist.

---

## What I would do next

In dependency order, with the reasoning:

1. **Decide the two open questions above** (`outside-study-in-scarlet`'s label;
   the three over-narrow `mention` lists). Both change what an item measures.
2. **Item 4's schema decision** — it blocks item 2's "own collection" and
   changes acceptance's scope, which means `not_in_sources` results will move.
   Doing it before items 2 and 3 avoids re-auditing twice.
3. **Item 3**, then **item 2** — both are content, and both need the item 1
   audit to verify every label before it lands.
4. **Item 6 last**, once there is a second source of answers to sample.

Phase 2 remains untouched: no rebase, no gate subsets wired, no re-baseline, no
milestone run, no judge agreement. Stopping here as instructed.