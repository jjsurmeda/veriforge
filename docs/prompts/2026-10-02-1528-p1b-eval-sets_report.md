# P1b Phase 1 report — eval sets that can certify the RAG system

Branch `p1b/eval-sets`, off `main` at `44be5fa`. Written from the worktree
`/Users/jjsurmeda/dev/my-projects/veriforge-p1b`.

**Status: PHASE 1 COMPLETE.** All six items are built, tested and committed.
No label was tuned toward the pipeline's output, no gate was wired, no baseline
was rewritten, and nothing belonging to the D8 dispatch was edited — verified by
diffing `44be5fa..HEAD` against its file list, which is empty, and by checking
`fast20_ids` is byte-identical.

**Credits: $2.12 spent** of the $9.55 this dispatch started with ($7.43 left).
`GET /api/v1/credits` read three times: $9.55 at the start, $8.27 after building
the isolated stack (most of that is the eleven books' embeddings), **$7.43 after
the live acceptance run — so the 57-item acceptance run cost $0.84**. A parallel
dispatch (D8) owns the rest; the floor was $2 and it was never approached.

---

## What is committed

| Item | Commit | Status |
| --- | --- | --- |
| 1. Scripted label audit | `1052001` | done (previous run) |
| 5. Runner/scorer: per-corpus, `min_support`, subsets | `97959cb` | done (previous run) |
| 4. Eval corpora out of Shared (KI-24) | `db45741` | **done** |
| 3. Books to 20/20 + ambiguity items | `d000237` | **done** |
| 2. Counterfactual corpus | `8d836dc` | **done** |
| 6. Judge validation sheets | `3059765` | **done** |

**Full suite: 779 passed. `mypy --strict` clean.** Every script and loader change
has tests, mutation-checked: I seeded defects into the audit's three calibration
rules and the judge builder's four load-bearing behaviours and confirmed each one
fails the suite when reverted.

---

## Item 4 — eval corpora out of Shared (KI-24), Decision A applied exactly

The **books stay `visibility='shared'`**. They are the demo library every real
user sees and measuring acceptance there is the realistic thing to do. Only the
eval-only corpora moved: the AW-2000 seed docs and the counterfactual set, both
now `visibility='private'` collections owned by one eval user. The prompt's
"move the books used by acceptance" is withdrawn and was not followed.

**One implementation finding, because the premise in the decision was incomplete.**
`retrieval/filters.py::build_scope` does grant access via
`col.owner_id = :scope_user` — but it ANDs that with
`d.collection_id = ANY(:scope_collections)`, and `chats/scope.py::resolve_scope`
never returned a private `library` collection, by design (ADR-002). So a private
collection the eval user owns would have been unreachable. `resolve_scope` now
takes an optional `extra_collection_ids`; **only the eval runner passes it** (it
loaded the corpora, so it knows the ids) and the HTTP chat path never does, which
is what keeps ADR-002 intact for real users. No schema change, no grant table.

### Ownership tests (`tests/evals/test_eval_corpus_ownership.py`, real SQL)

| Test | Result |
| --- | --- |
| A normal user's own scope excludes the eval corpus | pass |
| The ownership SQL refuses an eval-corpus id **handed to a stranger on purpose**, while a Shared control chunk is still found | pass |
| The eval user retrieves its own private corpus | pass |
| A private library still drops out of a chat's default scope | pass |
| Both eval corpus collections are `private` by construction (seed + counterfactual, parametrised) | pass |

The middle test is the load-bearing one: it is the only thing between a bug in
`extra_collection_ids` and a cross-user leak, and it proves the refusal rather
than assuming it. The Shared control chunk is what stops a zero result being read
as "the query matched nothing".

### Live verification, not just tests

Stood up an isolated stack (`scripts/acceptance_stack.sh`: fresh database, both
corpora, eleven books ingested through the real admin upload route, api plus both
ingest workers on their own port) and signed in as the eval user over HTTP:

```
eval-seed-corpus            private   evals@example.com   7 docs
eval-counterfactual-corpus  private   evals@example.com  11 docs
Shared                      shared    eval-admin@…      11 docs
visible documents to the eval user: 11  (the books, and only the books)
```

### KI-48: the account could be created but never signed in

`EVAL_USER_EMAIL` was `evals@veriforge.local`. The loader writes it straight into
`users` and the runner imports it as a constant, so every test that created the
account, owned the corpora and asserted the sign-in wiring passed. The first live
acceptance run stopped at item one: **`.local` is rejected by the product's own
`email_validator`** (as are `.test` and `.invalid`), so `POST /auth/login`
returned a validation error — after the whole stack had been built. Nothing in the
fixture path goes through the validator, which is how a completely green suite
shipped an account that cannot authenticate. Now `evals@example.com` (RFC 2606
reserved), with a test that runs the address through the same validator the login
route uses.

**Not re-baselined, deliberately.** This moves acceptance's scope, so
`not_in_sources` results will legitimately change. Recorded in KI-24 for Phase 2.

---

## Item 3 — Decision B, item by item

`docs/conventions/testing.md` is explicit that a label contradicting the corpus is
a test bug, so three of the four move and one does not. Every change carries its
reason in the item.

### 1. `outside-study-in-scarlet` — KEPT `not_in_sources`, no change

The corpus has Watson's "experience of camp life in Afghanistan" (1 hit), but the
question asks how Holmes **deduced** it, and that deduction is in A Study in
Scarlet, which is not in the corpus. The correct behaviour is TR-4's decline
("found: X, missing: the deduction"), which the relevance gate now produces. An
`answer` label would grade a model for saying a thing its sources do not support.
The reasoning is recorded in the item so the next audit does not re-raise it.

### 2. `library-count` — FIXED to the current in-scope count

Was `["5", "five"]`, dating from when the Shared library held five books; round 2
of the corpus (KI-12) widened it to eleven and the label was never updated. Now
`["11", "eleven"]`. **The item records the re-check trigger: every book added to
or removed from `seed_gutenberg.py::BOOKS` must redo it.** The digit form is kept
alongside the word because the corpus states the count nowhere in particular.
Logged as **KI-47**. This is why the live run now passes it.

### 3. `fact-bennet-sisters` — FIXED to accept "five" and "5"

The corpus says "five daughters" in words, so an answer cannot be expected to emit
the digit. Same class as the Weena widening (KI-36): a check stricter than the
corpus rejects a correct answer. The fact being measured does not change. The
live run now passes it.

### 4. `frame-walton` — the 1-minute check, then FIXED

The check ran first, as instructed:

| Query against `Frankenstein.txt` | Hits |
| --- | --- |
| `saville` | **0** |
| `sister` | 29 |
| `letters` | 15 |
| `walton` | attested |
| `margaret` | 12 |

**'Saville' is 0 hits across all 10,704 shared passages.** This Gutenberg edition
never gives Walton's sister a surname — the letters say "my dear Sister" and "my
beloved sister". Saville is a letter heading in other editions, not in the text
this corpus is made of. Requiring it rejected a correct answer that said "his
sister". The corpus **does** answer the item (`Robert Walton` ord 8: "Your
affectionate brother, Robert Walton … My dear Sister, I write a few lines in
haste"), so it is **not** mislabelled and stays `answer` — the check changed from
`Saville` to `sister`, with the removed string and the proof recorded in the item.
The live run now passes it.

### The books set also grew

Six proven near-miss abstentions take `not_in_sources` from 14 to **20**, two of
them non-English. Three ambiguity items carry `mention_all` with both referents
and `pending_p2`, so the scorer reports them separately and they do not count
against today's pass rate.

**The audit caught two of my own mistakes, which is the process working.** My
first `ml-zh-xiyou-nezha` asked what relationship 哪吒 is to 孫悟空 — and 哪吒 is 48
times in 西遊記.txt. That was a wrong label, a test bug, and it was replaced with a
near-miss the corpus genuinely does not cover. Then my *replacement's* spot-read
was wrong in turn: I wrote that 天宮 was 0 hits and it is 110 — always as the Jade
Emperor's court, never as a residence, which is why the item still holds. Both
corrections are recorded in the item rather than quietly made.

### The live run, as the fixed eval user

```
passed 47/54; TTFT p50 9374 ms (3 pending_p2 reported separately)
  smalltalk: 2/2   library: 2/2   answer: 25/30   not_in_sources: 18/20
```

`library-count`, `fact-bennet-sisters` and `frame-walton` all pass. **Two of the
three `pending_p2` ambiguity items pass already** — `amb-frankenstein-addressee`
answers "Robert Walton … his sister, Margaret", naming both referents. That is real
P2 input: the corpus genuinely supports both and the model already surfaces both on
that one. `amb-bovary-homais` abstained instead, which is the shape P2's prompt
change has to catch.

---

## Item 2 — the counterfactual corpus

Eleven documents whose facts are **wrong on purpose**, and 93 items against them.
The existing corpora cannot certify grounding: a model answering the AW-2000
manual or Pride and Prejudice from memory is right, so those sets measure nothing
about whether the sources were read. Here an answer from memory is a wrong answer
and only the document is right.

### Composition table

| | Count |
| --- | --- |
| **Documents** | **11** (prompt asked 8–12) |
| — with tables | 3 (heritage register, R-7 specification, restaurant guide) |
| — non-English | 3 (`fr_guide_daval`, `es_manual_orbita`, `de_richtlinie_aurigel`) |
| **Items** | **93** |
| — answerable | **59** (prompt asked ≥ 20) |
| — should-abstain | **34** (prompt asked ≥ 20) |
| — `table_lookup` | **10** (asked ≥ 4) |
| — `multihop`, two documents | **4** (asked ≥ 4) |
| — `multi_language` (fr/es/de) | **24** (asked ≥ 2 per language) |
| — `counterfactual` | 55 |

Every document opens with a fictional header. Every answerable item carries a
`cite`, a `mention` (the **document's** value) and a `forbid` list naming the
real-world value — with one documented exception (`cf-cb-manager`, an invented
person with no real-world counterpart, marked `no_real_counterpart` rather than
carrying a silent empty list).

### `forbid` is what makes the set counterfactual

`forbid` fails an item that mentions the real-world value **even when the
document's value is present and the citation is right** — tested both ways, which
is the prompt's explicit test. It matches on **word boundaries**: a substring check
would make `IP68` fail an `IP69K` answer and `330` fail a `3300` one, which is
KI-36 one level down.

### Two audit bugs found by building it, fixed not worked around

**KI-46.** `audit_labels.py` tokenised with `[^\W\d_]+`, which matches letters but
**not digits**, and then dropped anything under two characters — two independent
reasons no number could ever be a token. So `passages_containing("512")` returned
zero hits in a document whose Eiffel Tower is 512 m tall, and `answer_not_in_corpus`
fired on **49 of 93 items, every one a false positive**. The corpus was fine; the
instrument reading it was blind to exactly what it most needed to check — most of a
specification, and all of a corpus built on altered figures. Numbers are now
tokens, scanned in one pass with the words so `1 640` matches in order.

**`alt_mention`.** A value's other spelling (`6400` for the corpus's `6,400`) has to
be accepted by the scorer but must not be a second unchecked answer. The audit
verifies each `alt_mention` is a spelling of something already attested and flags
`alt_mention_unattested` otherwise.

### The 34 remaining findings are all spot-read abstentions

Every `abstain_false_hit` has a hand-written `spot_read` in the item naming what
the corpus *does* say and why it is not the answer. All 34 were spot-read; in every
case the corpus names the entity and never the fact asked for.
`tests/evals/test_counterfactual_set.py` fails if an item ever demands a string the
corpus cannot produce, if a `forbid` value appears in the document the answer must
be quoted from, or if a `forbid` list drifts to overlap the item's own accepted
values.

Loaded as its own private collection (KI-24) and its own dataset, summarised per
corpus like any other. `--dataset counterfactual` on the runner, `--set` on the
acceptance runner — one scorer, two sets.

---

## Item 6 — judge validation sheets

| File | Rows |
| --- | --- |
| `/Users/jjsurmeda/dev/my-projects/veriforge-p1b/evals/judge_validation/claims.csv` | **30** |
| `/Users/jjsurmeda/dev/my-projects/veriforge-p1b/evals/judge_validation/answers.csv` | **30** |
| `/Users/jjsurmeda/dev/my-projects/veriforge-p1b/evals/judge_validation/README.md` | 5-minute guide, TRD §10 verdicts |

**About 60 rows to label, roughly an hour.** Every row in both files has real
passage text; every `human_verdict` / `human_correct` / `human_grounded` is empty;
I did not label them.

**The exports carry a digest, not the passage text.** The owner cannot judge a
claim without the passage it was checked against, so the builder recovers the text
by hashing the corpus and matching `sha256(text)[:16]` — 88 of 88 digests in the
first export resolved. The fresh acceptance run records `chunk_ids` instead, which
are resolved from the database that run used. An unresolvable passage is annotated
rather than shipped blank, because a blank reads as "no passage was cited", which
is a different statement.

**Sampling.** 30 claims from D7's six exports, stratified rare-verdicts-first; 15
answers from those exports and 15 from the fresh acceptance run — a different
corpus, a different model path and a different failure mode, so a disagreement
pattern in one has to survive the other. The reviewer's verdicts and the scorer's
and judge's scores sit behind `_`-prefixed columns and the README opens by saying
not to read them first.

### KI-49: the reviewer's `unsupported` verdict is almost never a judgement

Across D7's six runs: **162 supported, 5 partial, 7 unsupported, 1 contradicted**
over 175 claims. **Six of the seven `unsupported` verdicts are not judgements** —
TRD §10 step 3 scores a factual claim with no citation `unsupported` without a Jev
call at all. So the reviewer made exactly one `unsupported` and one `contradicted`
call across 120 items. Those six are excluded (no passage to read, so the owner
would be judging how a claim sounds) and the README says plainly that **judge
agreement on `unsupported` and `contradicted` cannot be computed from this pool**
rather than quoting a percentage over two rows. The faithfulness formula is
unaffected — uncited claims score 0 either way — but an agreement number over the
whole pool would be ~95% agreement decided entirely by the supported/partial split.
The counterfactual set's `forbid` items are built to generate exactly this traffic.

### `scripts/acceptance_stack.sh`

Item 6 needed an isolated stack and there was no way to build one. Two of its bugs
are recorded where they cost time: **procrastinate reads `PROCRASTINATE_CONNINFO`,
not `DATABASE_URL`**, so a schema step that reported "already applied" had actually
written to the dev database and every upload 500'd on a deferred job with no queue;
and `GUTENBERG_CACHE_DIR` is relative to the working directory, so its default is
not the cache `make seed-books` fills.

---

## What a fresh acceptance run shows about the label decisions

Recorded because it is the evidence that the four Decision B fixes were fixes and
not adjustments:

| Item | Before | After |
| --- | --- | --- |
| `library-count` | label demanded a number the corpus stopped having (KI-47) | **PASS** |
| `fact-bennet-sisters` | required a digit the corpus never states | **PASS** |
| `frame-walton` | required `Saville`, 0 hits in 10,704 passages | **PASS** |
| `outside-study-in-scarlet` | correctly `not_in_sources` | **PASS** |

Still failing, unchanged and not this dispatch's business:
`broad-sherlock`, `ml-es-rocinante`, `broad-alice`, `broad-bovary`
(`no_citations`); `outside-moby-dick`, `xl-en-wukong-master`,
`outside-holmes-boston` (`wrong_class_or_content`). `outside-moby-dick` and
`outside-holmes-boston` are pre-existing items that the KI-24 scope change could
legitimately move, which is why KI-24 says re-measure rather than compare.

---

## Phase 2

Untouched: no rebase, no gate subsets wired, no re-baseline, no milestone run, no
judge agreement computed. **Stopping here as instructed.**

The three things Phase 2 needs from this branch, in order:

1. **D8 merged** — rebase, then wire the per-corpus gate subsets with D8's writer,
   retry rule and tolerances unchanged.
2. **The owner's labels** in `evals/judge_validation/` — then agreement, with
   `unsupported`/`contradicted` reported as **not measurable from this pool**
   rather than as a number.
3. **A re-baseline after the KI-24 move**, measured over the new scope.

One thing I would flag rather than act on: the counterfactual set's `forbid`
channel is the mechanism that generates the `unsupported` and `contradicted`
verdicts KI-49 says are missing. Until it has been run, the gate's faithfulness
number is measured almost entirely over claims the sources do support, which is
the easier half of the question.