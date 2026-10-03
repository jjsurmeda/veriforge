# Judge validation — labelling guide (about 5 minutes per file)

Two CSVs. Fill in the **empty** columns; **do not read the `_`-prefixed ones
until you are done.** They hold the reviewer's and the judge's verdicts. An
owner who reads `supported` before deciding reaches for the same answer the
model did, and the agreement number then measures the model agreeing with
itself.

Open both in a spreadsheet. `claims.csv` has **45** rows, `answers.csv` has
**30** — 75 to label, about 1h15. Of the claims rows, 30 come from the eval
pools and 15 are **seeded negatives**: real claims rewritten so the cited
passage does not support them (8 `unsupported`, 7 `contradicted` by
construction). They are shuffled in and marked only in the hidden `_seeded`
column, so label them exactly like the others. They exist to measure how
strict the reviewer is; the strictness number goes in the Phase 2 report.

## Verdicts (TRD §10)

For every claim, exactly one:

| Verdict | Meaning |
| --- | --- |
| `supported` | The cited passage(s) say this. They would support it on their own. |
| `partial` | The passage is about this, but says less, more loosely, or something different in detail. |
| `unsupported` | The passage is not about this, or does not reach it. |
| `contradicted` | The passage says something incompatible with this claim. |

The line between `supported` and `partial` is the one the reviewer is most
likely to get wrong, and the one worth being careful about: `supported` means
*on its own*, not *in the same neighbourhood*.

- A claim like "the AW-2000-XP has 20 hours of battery" against a passage that
  lists the model table with a 20 h column: **supported**.
- The same claim against a passage about warranty length that happens to be in
  the same answer: **unsupported**.
- "The widget is splash-resistant" against a passage saying "IP54, do not
  submerge": **partial** — right idea, the rating does not say "splash-proof".

## claims.csv

Fill `human_verdict` with one of the four words above.

- `claim` — the single assertion to judge. Not the sentence around it.
- `cited_passage` — the passage(s) the answer cited for this claim. Judge the
  claim against *this text only*, not against what you know.
  `(passage not recovered)` means the export's digest did not resolve against
  the corpus: skip the row rather than guessing.

## answers.csv

Two columns, both `yes` / `no`:

- `human_correct` — **Is the answer right?** Would you accept it as the answer
  to the question? Judge the fact, not the phrasing.
- `human_grounded` — **Is every factual sentence in it supported by the
  passages shown?** Not "does it mention them" — supported. An answer that is
  factually right but states something the passages do not is `yes` / `no`.

They are independent. A correct answer that adds an unsupported detail is
`yes`/`no`; an incomplete answer that says nothing wrong is `no`/`yes`.

## One thing to know before you fill in `claims.csv`

Across D7's six runs the reviewer produced 175 claim verdicts: **162
supported, 5 partial, 7 unsupported, 1 contradicted**. Six of those seven
`unsupported` verdicts came from TRD §10 step 3 -- a factual claim with no
citation, scored `unsupported` without a Jev call at all -- so they have no
passage to read and are **excluded from this sheet**. What is left is
23 supported / 5 partial / 1 unsupported / 1 contradicted.

So this sheet can measure the reviewer's *supported* and *partial* calls, and it
holds exactly one row each of `unsupported` and `contradicted`. **Judge
agreement on those two verdicts cannot be computed from this pool** -- not
because labelling is hard, but because the reviewer almost never makes them.
Phase 2 should say so rather than quote an agreement percentage over one or two
rows. More of them needs eval items whose answers carry claims the sources do
not support, which is what the counterfactual set is for.

## Afterwards

Leave the `_` columns alone. Phase 2 computes reviewer-vs-human and
judge-vs-human agreement from the two columns you filled, and reports a
confusion table for any disagreement (TRD §15).
