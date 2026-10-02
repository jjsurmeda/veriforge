# Counterfactual corpus (P1b item 2)

A benchmark corpus whose facts are **wrong on purpose**. Every document states a
real-world value differently from how it is in the world, so an answer produced
from a model's memory is a wrong answer, and only an answer read out of these
documents is right. That is the only way to certify grounding: the ordinary
AW-2000 and Gutenberg sets can be answered correctly by a model that never read
them.

Eleven documents: a heritage register with tables, a city guide, a product
handbook, an HR policy, a rolling-stock specification with tables, an insurance
policy, a French guide, a Spanish manual, a German works council policy, a
restaurant guide with tables, and a lab protocol. Three are non-English.

Each document opens with a header marking it fictional, and each item that
depends on an altered fact carries a `why_forbid` naming the real-world value
the corpus deliberately contradicts.

## Running it

The corpus loads as its **own private collection**, never Shared (KI-24):

```
uv run python -m evals.loader                    # loads seed + counterfactual
uv run python -m evals.runner --dataset counterfactual
```

Scored through the same acceptance scorer as the books set, with `--set`:

```
uv run python scripts/acceptance.py --set ../../evals/counterfactual/items.json
```

## Item shape

| Field | Meaning |
| --- | --- |
| `expect` | `answer` or `not_in_sources` |
| `cite` | at least one citation must come from a document whose name contains one of these |
| `mention` | the answer must contain one of these — the **document's** value |
| `alt_mention` | the same value written another way (`6400` for the corpus's `6,400`) |
| `forbid` | the **real-world** value. Mentioning it fails the item even when the document's value is also stated |
| `category` | `table_lookup` \| `multihop` \| `multi_language` \| `counterfactual` |
| `proof` | the audit's proof that the label is right |
| `spot_read` | for abstentions: what the corpus *does* say about the entity, and why it is not the answer |

`forbid` is matched on word boundaries, so `IP68` does not fire on `IP69K` and
`330` does not fire on `3300`.

## Composition

93 items: 59 answerable, 34 should-abstain.

| Category | Count |
| --- | --- |
| `table_lookup` | 10 |
| `multihop` (two documents) | 4 |
| `multi_language` (fr / es / de) | 24 |
| `counterfactual` | 55 |

Every answerable item checks a citation and forbids at least one real-world
value, with one documented exception (`cf-cb-manager`): an invented person has
no real-world counterpart, so there is nothing to forbid, and the item is a
pure sources test. It says so rather than carrying a silent empty list.

## Provenance

Every item carries a `proof` written by `scripts/audit_labels.py` over all 94
passages the corpus produces under the production chunker:

```
cd apps/api
.venv/bin/python scripts/audit_labels.py \
  ../../evals/counterfactual/items.json \
  --corpus-dir ../../evals/counterfactual/corpus --write-back
```

`--corpus-dir` builds the corpus from these markdown files with
`ingest.chunk.chunk_document`, the same chunker production uses, so the audited
passages are the retrievable ones. No database and no embeddings are needed.

The audit's remaining 34 findings are all `abstain_false_hit` on abstention
items, and each one has a hand-written `spot_read` in the item naming what the
corpus does say. All 34 were spot-read: in every case the corpus names the
entity and never the fact asked for. `tests/evals/test_counterfactual_set.py`
fails if an item ever demands a string the corpus cannot produce, or if a
`forbid` value appears in the document the answer must be quoted from.