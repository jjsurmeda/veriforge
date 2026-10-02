"""Build the judge-validation sheets the owner labels (P1b item 6).

Two CSVs and a labelling guide. The point is to measure **judge agreement**: the
reviewer's per-claim verdicts and the async judge's scores are both produced by
models, and neither is a ground truth. Phase 2 needs to know whether they agree
with a person before it can gate on them, and an agreement number computed
against another model is not one.

**Two sources, because one is not enough.** The claim verdicts only exist in the
eval runner's per-item exports (D7's `.data/evals/*-96265f8.json`); a fresh
acceptance run produces the other half of the picture — answers over the Shared
books corpus, which is a different corpus, a different model path and a
different failure mode. Sampling only the first would produce an agreement
figure that describes the seed set and nothing else.

**The exports carry a digest of each retrieved passage, not its text.** The text
is recovered by hashing the corpus and matching: the digest is
`sha256(text)[:16]`, so a corpus read from the database reproduces it exactly.
A claim whose passage cannot be recovered is dropped rather than shipped with an
empty passage, because an empty passage is not a judgement the owner can make.

**Reviewer verdicts go in their own column, after the ones the owner fills.**
An owner who reads `verdict=supported` before deciding reaches for the same
answer the model did, and the agreement number stops measuring agreement.

Usage:

    uv run python scripts/build_judge_validation.py \\
        --exports '/path/to/.data/evals/*-96265f8.json' \\
        --acceptance .data/acceptance/<timestamp>.json \\
        --database-url postgresql+asyncpg://.../veriforge_p1b \\
        --out ../../evals/judge_validation
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The verdict vocabulary TRD §10 defines. Kept as a constant so a sheet can only
# ever carry one of these, and so an export that grows a new verdict fails here
# rather than shipping a column the labelling guide does not explain.
VERDICTS = ("supported", "partial", "unsupported", "contradicted")

CLAIMS = 30
ANSWERS = 30


@dataclass
class Passage:
    """One retrieved chunk, resolved from the digest the export carries."""

    number: int
    digest: str
    text: str | None = None
    chunk_id: str | None = None


@dataclass
class ClaimRow:
    claim_id: str
    source: str
    question: str
    claim_text: str
    citation_numbers: list[int]
    passages: list[Passage]
    reviewer_verdict: str
    reviewer_p_supported: float | None
    reviewer_engine: str
    # Hidden from the owner on first read; see the module docstring.
    answer: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class AnswerRow:
    answer_id: str
    source: str
    question: str
    answer: str
    passages: list[Passage]
    abstained: bool | None
    # Hidden columns.
    scorer_faithfulness: float | None = None
    scorer_context_recall: float | None = None
    judge_faithfulness: float | None = None
    judge_context_recall: float | None = None
    reviewer_min_support: float | None = None
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Reading the exports
# --------------------------------------------------------------------------


def read_exports(paths: list[Path]) -> list[dict[str, Any]]:
    runs = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "per_item" not in payload:
            raise SystemExit(f"{path} has no per_item; is it an eval export?")
        payload["_source"] = path.name
        runs.append(payload)
    if not runs:
        raise SystemExit("no exports matched")
    return runs


def passage_index(rows: list[tuple[str, str]]) -> dict[str, str]:
    """digest → passage text, over the corpus the exports were run against."""
    import hashlib

    return {hashlib.sha256(text.encode()).hexdigest()[:16]: text for _, text in rows}


def corpus_digests(database_url: str, corpus_only: bool) -> tuple[dict[str, str], str]:
    """Read every retrievable chunk and index it by the export's digest.

    `corpus_only` narrows to the eval-seed-corpus collection, which is what the
    D7 exports were run against. Matching wider would let a digest resolve to a
    different document's text — a wrong passage is worse than a missing one.
    """
    import asyncio

    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _load() -> list[tuple[str, str]]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as conn:
                clause = ""
                params: dict[str, Any] = {}
                if corpus_only:
                    clause = " AND col.name = :c"
                    params["c"] = "eval-seed-corpus"
                result = await conn.execute(
                    sa_text(
                        # Constant SQL: `clause` is a literal and the corpus name
                        # is a module constant, never caller input.
                        "SELECT d.name, ch.text FROM chunks ch "  # noqa: S608
                        "JOIN documents d ON d.id = ch.document_id "
                        "JOIN collections col ON col.id = d.collection_id "
                        "WHERE d.status = 'ready'" + clause
                    ),
                    params,
                )
                return [(row[0], row[1]) for row in result]
        finally:
            await engine.dispose()

    rows = asyncio.run(_load())
    return passage_index(rows), "eval-seed-corpus" if corpus_only else "all retrievable chunks"


def resolve_chunk_ids(database_url: str, rows: list[AnswerRow]) -> None:
    """Fill acceptance passages by chunk id.

    Acceptance's own output records which chunks were retrieved, not what they
    said, so the text has to come from the database the run used. Done in one
    query for every id at once: 57 items x 8 chunks is 456 round trips if done
    per row, and a labelling script that takes ten minutes to start is a
    labelling script nobody starts.
    """
    wanted = {p.chunk_id for row in rows for p in row.passages if p.chunk_id}
    if not wanted:
        return
    import asyncio

    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _load() -> dict[str, str]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as conn:
                found: dict[str, str] = {}
                ids = list(wanted)
                for start in range(0, len(ids), 200):
                    batch = ids[start : start + 200]
                    result = await conn.execute(
                        sa_text("SELECT id::text, text FROM chunks WHERE id::text = ANY(:ids)"),
                        {"ids": batch},
                    )
                    found.update({row[0]: row[1] for row in result})
                return found
        finally:
            await engine.dispose()

    index = asyncio.run(_load())
    for row in rows:
        for passage in row.passages:
            if passage.chunk_id:
                passage.text = index.get(passage.chunk_id)


def claims_from_export(run: dict[str, Any]) -> list[ClaimRow]:
    out: list[ClaimRow] = []
    for item in run["per_item"]:
        contexts = {
            int(c["n"]): Passage(int(c["n"]), str(c["digest"]), None)
            for c in item.get("contexts") or []
        }
        for claim in item.get("claims") or []:
            verdict = str(claim.get("verdict") or "")
            if verdict not in VERDICTS:
                continue
            numbers = [int(n) for n in claim.get("citation_ids") or []]
            out.append(
                ClaimRow(
                    claim_id=f"{run['_source'][:15]}:{claim.get('id')}",
                    source=run["_source"],
                    question=str(item.get("question") or ""),
                    claim_text=str(claim.get("text") or ""),
                    citation_numbers=numbers,
                    passages=[contexts[n] for n in numbers if n in contexts],
                    reviewer_verdict=verdict,
                    reviewer_p_supported=claim.get("p_supported"),
                    reviewer_engine=str(claim.get("engine") or ""),
                    answer=str(item.get("answer") or ""),
                )
            )
    return out


def answers_from_export(run: dict[str, Any]) -> list[AnswerRow]:
    """Answers from one D7 export. All six exports are the same source — the
    AW-2000 seed corpus — so they share a source label; splitting them by file
    would make `sample_answers` treat one corpus as six and hand the sheet
    fifteen rows from it and none from acceptance."""
    out: list[AnswerRow] = []
    for index, item in enumerate(run["per_item"]):
        contexts = [
            Passage(int(c["n"]), str(c["digest"]), None) for c in item.get("contexts") or []
        ]
        verdicts = [str(c.get("verdict")) for c in item.get("claims") or []]
        p_supported = [
            float(c["p_supported"])
            for c in item.get("claims") or []
            if c.get("p_supported") is not None
        ]
        out.append(
            AnswerRow(
                answer_id=f"export:{run['_source'][:15]}:{index}",
                source="export",
                question=str(item.get("question") or ""),
                answer=str(item.get("answer") or ""),
                passages=contexts,
                abstained=item.get("abstained"),
                scorer_faithfulness=item.get("faithfulness"),
                scorer_context_recall=item.get("context_recall"),
                # D7's exports carry the judge's scores under the same field
                # names as the scorer's; the judge ran post-hoc over the same
                # passages. Kept as the judge's own number where it exists.
                judge_faithfulness=item.get("faithfulness"),
                judge_context_recall=item.get("context_recall"),
                reviewer_min_support=min(p_supported) if p_supported else None,
                notes=[] if any(v in VERDICTS for v in verdicts) else ["no reviewer claims"],
            )
        )
    return out


def answers_from_acceptance(payload: dict[str, Any]) -> list[AnswerRow]:
    """A fresh acceptance run: answers over the Shared books corpus.

    Acceptance records citations and retrieved passages per item but no claim
    verdicts — the reviewer's verdicts live in `eval_results.review_detail`,
    which this run does not write. So these rows carry the scorer's class and
    outcome and leave the reviewer's columns empty, and the sheet says so rather
    than showing a blank that reads as a zero.
    """
    out: list[AnswerRow] = []
    for row in payload.get("items", []):
        retrievals = row.get("retrievals") or []
        # Acceptance records `chunk_ids`, never the passage text, so the text is
        # resolved from the database this run used. A row with no retrievals had
        # nothing retrieved and is dropped by `sample_answers` rather than sent
        # to the owner with an empty `passages` cell they cannot judge against.
        chunk_ids: list[str] = []
        for retrieval in retrievals:
            ids = [str(c) for c in (retrieval.get("chunk_ids") or [])]
            scores = list(retrieval.get("rerank_scores") or [])
            # Only the chunks with a rerank score are the ones the reviewer saw.
            # A retrieval event also records the pool below that line, so taking
            # every id hands the owner ~120 passages per answer and a 20 000
            # character cell, which is not a five-minute labelling job.
            ranked = [c for c, s in zip(ids, scores, strict=False) if s is not None] or ids
            chunk_ids.extend(ranked)
        passages = [
            Passage(n + 1, "", None, chunk_id=c) for n, c in enumerate(dict.fromkeys(chunk_ids))
        ]
        out.append(
            AnswerRow(
                answer_id=f"acceptance:{row['id']}",
                source="acceptance",
                question=(row.get("turns") or [""])[-1],
                answer=str(row.get("answer") or ""),
                passages=passages,
                abstained=row.get("message_status") == "abstained",
                notes=["acceptance run: no reviewer claims, scorer class only"],
            )
        )
    return out


# --------------------------------------------------------------------------
# Resolving and sampling
# --------------------------------------------------------------------------


def resolve(claims: list[ClaimRow], answers: list[AnswerRow], index: dict[str, str]) -> None:
    """Fill in passage text from the digest index, in place.

    Anything that cannot be resolved is annotated, because a row whose passage
    says "not recovered" is a row the owner will silently judge on the claim
    text alone — which is exactly the judgement this exercise is not measuring.
    """
    # Two loops rather than one over `[...claims, ...answers]`: the union widens
    # to `object` and mypy then rejects every attribute on it.
    for claim in claims:
        _resolve_passages(claim, index)
    for answer in answers:
        _resolve_passages(answer, index)


def _resolve_passages(row: ClaimRow | AnswerRow, index: dict[str, str]) -> None:
    for passage in row.passages:
        # A chunk-id passage was already resolved from the database; its digest
        # is empty and looking it up here would blank the text.
        if passage.chunk_id:
            continue
        passage.text = index.get(passage.digest)
    missing = [p for p in row.passages if not p.text]
    if missing and row.passages:
        row.notes.append(
            f"{len(missing)}/{len(row.passages)} passage(s) not recovered from the corpus"
        )


def sample_claims(claims: list[ClaimRow], target: int) -> tuple[list[ClaimRow], str]:
    """Fill `target` claims, taking the rare verdicts first.

    The pool is ~93% `supported`, so a proportional sample measures the reviewer
    on the case it is never wrong about. Take every non-supported claim first --
    there are only 13 across the whole of D7's six runs and all 13 are worth a
    human's time -- then top up from `supported` to reach the target.

    Returns the rows and a note when the sheet could not be filled, because a
    sheet that quietly under-samples a stratum produces an agreement number that
    reads better than it is.
    """
    by_verdict: dict[str, list[ClaimRow]] = defaultdict(list)
    for claim in claims:
        by_verdict[claim.reviewer_verdict].append(claim)

    # Uncited claims are excluded. TRD §10 step 3 scores a factual claim with no
    # citation `unsupported` without a Jev call at all, so there is no reviewer
    # judgement to agree with and no passage for the owner to read -- the row
    # could only be labelled by looking at the claim alone, which is the
    # "does this sound right" judgement this exercise is not measuring.
    cited = [c for c in claims if c.passages]
    by_verdict = defaultdict(list)
    for claim in cited:
        by_verdict[claim.reviewer_verdict].append(claim)
    uncited = len(claims) - len(cited)

    picked: list[ClaimRow] = []
    for verdict in VERDICTS:
        if verdict != "supported":
            picked.extend(by_verdict.get(verdict, []))
    shortfall = target - len(picked)
    if shortfall > 0:
        picked.extend(by_verdict.get("supported", [])[:shortfall])

    note = f"{uncited} uncited claim(s) excluded (auto-scored, no passage to read)"
    if len(picked) < target:
        note += (
            f"; only {len(picked)} cited claims available across the exports, so the "
            "verdict mix is the limit here rather than the target"
        )
    # Interleave by stratum so a partially-labelled sheet still covers every
    # stratum rather than exhausting one verdict before reaching the next.
    picked.sort(key=lambda c: VERDICTS.index(c.reviewer_verdict))
    return picked, note


def sample_answers(answers: list[AnswerRow], target: int) -> list[AnswerRow]:
    """Half from each source, then top up from whichever has rows left.

    Sampling one corpus alone describes one corpus. The eval exports are answers
    over the AW-2000 seed corpus; the acceptance run is answers over the Shared
    books — a different corpus, a different model path and a different failure
    mode, so a disagreement pattern in one has to survive the other.
    """
    by_source: dict[str, list[AnswerRow]] = defaultdict(list)
    for row in answers:
        by_source[row.source].append(row)
    # Rows with passages first: an answer with no passage column filled cannot
    # be judged for groundedness, which is half of what answers.csv asks for.
    for rows in by_source.values():
        rows.sort(key=lambda r: (not any(p.text for p in r.passages), r.answer_id))
    share = max(1, target // max(1, len(by_source)))
    picked: list[AnswerRow] = []
    for rows in by_source.values():
        picked.extend(rows[:share])
    if len(picked) < target:
        taken = {r.answer_id for r in picked}
        for rows in by_source.values():
            for row in rows:
                if len(picked) >= target:
                    break
                if row.answer_id not in taken:
                    picked.append(row)
                    taken.add(row.answer_id)
    picked.sort(key=lambda r: (r.source, r.answer_id))
    return picked[:target]


def write_claims(rows: list[ClaimRow], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "claim_id",
                "question",
                "claim",
                "cited_passage",
                "human_verdict",
                "_reviewer_verdict",
                "_reviewer_p_supported",
                "_reviewer_engine",
                "_answer",
                "_notes",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.claim_id,
                    row.question,
                    row.claim_text,
                    "\n---\n".join(p.text or "(passage not recovered)" for p in row.passages),
                    "",  # human_verdict: the owner's, left empty
                    row.reviewer_verdict,
                    "" if row.reviewer_p_supported is None else row.reviewer_p_supported,
                    row.reviewer_engine,
                    row.answer,
                    "; ".join(row.notes),
                ]
            )


def write_answers(rows: list[AnswerRow], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "answer_id",
                "question",
                "answer",
                "passages",
                "human_correct",
                "human_grounded",
                "_scorer_faithfulness",
                "_scorer_context_recall",
                "_judge_faithfulness",
                "_judge_context_recall",
                "_abstained",
                "_notes",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.answer_id,
                    row.question,
                    row.answer,
                    "\n---\n".join(
                        f"[{p.number}] {p.text or '(passage not recovered)'}" for p in row.passages
                    ),
                    "",  # human_correct: the owner's, left empty
                    "",  # human_grounded: the owner's, left empty
                    "" if row.scorer_faithfulness is None else row.scorer_faithfulness,
                    "" if row.scorer_context_recall is None else row.scorer_context_recall,
                    "" if row.judge_faithfulness is None else row.judge_faithfulness,
                    "" if row.judge_context_recall is None else row.judge_context_recall,
                    "" if row.abstained is None else row.abstained,
                    "; ".join(row.notes),
                ]
            )


README = """# Judge validation — labelling guide (about 5 minutes per file)

Two CSVs. Fill in the **empty** columns; **do not read the `_`-prefixed ones
until you are done.** They hold the reviewer's and the judge's verdicts. An
owner who reads `supported` before deciding reaches for the same answer the
model did, and the agreement number then measures the model agreeing with
itself.

Open both in a spreadsheet. `claims.csv` has **30** rows, `answers.csv` has
**30**.

## Verdicts (TRD §10)

For every claim, exactly one:

| Verdict | Meaning |
| --- | --- |
| `supported` | The cited passage(s) say this. They would support it on their own. |
| `partial` | The passage is about this, but says less, or differs in detail. |
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
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports", nargs="*", default=[], help="D7 per-item export JSONs")
    parser.add_argument("--acceptance", default=None, help="a fresh acceptance run JSON")
    parser.add_argument("--database-url", default=None, help="defaults to $DATABASE_URL")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    parser.add_argument(
        "--all-corpora",
        action="store_true",
        help="resolve digests against every retrievable chunk instead of the eval-seed-corpus only",
    )
    args = parser.parse_args(argv)

    import os

    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("set DATABASE_URL or pass --database-url")

    claims: list[ClaimRow] = []
    answers: list[AnswerRow] = []
    if args.exports:
        for run in read_exports([Path(p) for p in args.exports]):
            claims.extend(claims_from_export(run))
            answers.extend(answers_from_export(run))
    if args.acceptance:
        answers.extend(answers_from_acceptance(json.loads(Path(args.acceptance).read_text())))
    if not claims and not answers:
        raise SystemExit("nothing to sample: pass --exports and/or --acceptance")

    index, scope = corpus_digests(database_url, corpus_only=not args.all_corpora)
    resolve_chunk_ids(database_url, answers)
    resolve(claims, answers, index)

    claim_rows, shortfall = sample_claims(claims, CLAIMS)
    answer_rows = sample_answers(answers, ANSWERS)

    out = args.out or Path(__file__).resolve().parents[3] / "evals" / "judge_validation"
    out.mkdir(parents=True, exist_ok=True)
    write_claims(claim_rows, out / "claims.csv")
    write_answers(answer_rows, out / "answers.csv")
    (out / "README.md").write_text(README, encoding="utf-8")

    unresolved = sum(1 for c in claim_rows if any(not p.text for p in c.passages)) + sum(
        1 for a in answer_rows if any(not p.text for p in a.passages)
    )
    print(
        json.dumps(
            {
                "out": str(out),
                "claims": len(claim_rows),
                "answers": len(answer_rows),
                "claim_verdicts": dict(Counter(c.reviewer_verdict for c in claim_rows)),
                "answer_sources": dict(Counter(a.source for a in answer_rows)),
                "digest_scope": scope,
                "digest_index_size": len(index),
                "rows_with_unresolved_passages": unresolved,
                "shortfall": shortfall,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
