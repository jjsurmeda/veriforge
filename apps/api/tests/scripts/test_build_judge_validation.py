"""The judge-validation builder (P1b item 6).

The sheets exist to measure whether the reviewer and the async judge agree with
a **person**. Three things about them are load-bearing and each has a test here
that fails if it stops being true:

- **The exports carry a digest, not the passage text.** The builder has to
  recover the text by hashing the corpus, or every row reaches the owner with an
  empty passage and the judgement silently becomes "does this claim sound right",
  which is not the judgement this measures.
- **The reviewer's verdict goes behind a `_`-prefixed column.** An owner who
  reads `supported` before deciding agrees with the model by construction.
- **The claim sample is stratified across verdicts, not proportional.** The
  verdict mix is ~93% supported, so a proportional sample measures the reviewer
  on the case it is never wrong about.
"""

import csv
import json
from pathlib import Path
from typing import Any

from scripts import build_judge_validation as builder

OUT = Path(__file__).resolve().parents[4] / "evals" / "judge_validation"

# The export carries a digest, not the text, so the fixture has to compute a
# real one or it is not exercising the recovery its test is named after.
PASSAGE_TEXT = "The AW-2000 provides up to 10 hours of continuous operation."


def digest_of(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()[:16]


def make_export(name: str, *, verdicts: dict[str, int]) -> dict[str, Any]:
    """One eval export shaped like the runner's per-item dump."""
    claims: list[dict[str, Any]] = []
    contexts = [{"n": 1, "digest": digest_of(PASSAGE_TEXT), "chars": len(PASSAGE_TEXT)}]
    counter = 0
    for verdict, how_many in verdicts.items():
        for _ in range(how_many):
            counter += 1
            claims.append(
                {
                    "id": f"c{counter}",
                    "text": f"claim {counter} ({verdict})",
                    "verdict": verdict,
                    "p_supported": 1.0 if verdict == "supported" else 0.0,
                    "citation_ids": [1],
                    "engine": "jev",
                }
            )
    return {
        "_source": name,
        "eval_run": "run-1",
        "per_item": [
            {
                "question": "How long does the battery last?",
                "abstained": False,
                "faithfulness": 0.9,
                "context_recall": 1.0,
                "answer": "Ten hours [1].",
                "claims": claims,
                "contexts": contexts,
            }
        ],
    }


# --------------------------------------------------------------------------
# Digest recovery
# --------------------------------------------------------------------------


def test_passage_text_is_recovered_from_the_export_digest() -> None:
    """The export gives `sha256(text)[:16]`; the corpus reproduces it exactly."""
    export = make_export("run.json", verdicts={"supported": 1})
    row = builder.claims_from_export(export)[0]
    assert row.passages[0].text is None, "an export carries no text"

    builder.resolve([row], [], {digest_of(PASSAGE_TEXT): PASSAGE_TEXT})

    assert row.passages[0].text == PASSAGE_TEXT
    assert row.notes == [], "a fully resolved row must carry no warning"


def test_a_passage_that_cannot_be_recovered_is_flagged_not_shipped_blank() -> None:
    """An unresolved digest must say so. A blank passage reads as "no passage
    was cited", which is a different statement from "the digest did not match"."""
    export = make_export("run.json", verdicts={"supported": 1})
    row = builder.claims_from_export(export)[0]
    builder.resolve([row], [], {})
    assert any("not recovered" in note for note in row.notes), row.notes


# --------------------------------------------------------------------------
# Stratification
# --------------------------------------------------------------------------


def test_every_rare_verdict_is_sampled_before_any_supported_one() -> None:
    """A proportional sample of a 93%-supported mix measures the reviewer on the
    case it is never wrong about. There are only 13 non-supported claims across
    all of D7's six runs and every one of them is worth a human's time."""
    export = make_export("run.json", verdicts={"supported": 60, "partial": 3, "unsupported": 2})
    claims = builder.claims_from_export(export)
    builder.resolve(claims, [], {digest_of(PASSAGE_TEXT): PASSAGE_TEXT})
    picked, _shortfall = builder.sample_claims(claims, 30)
    counts: dict[str, int] = {}
    for claim in picked:
        counts[claim.reviewer_verdict] = counts.get(claim.reviewer_verdict, 0) + 1
    assert counts["partial"] == 3, counts
    assert counts["unsupported"] == 2, counts
    assert counts["supported"] == 25, counts  # the top-up


def test_a_sheet_that_cannot_be_filled_says_so() -> None:
    """A shortfall that is not reported produces an agreement number that reads
    better than the sample supports."""
    export = make_export("run.json", verdicts={"supported": 4})
    claims = builder.claims_from_export(export)
    builder.resolve(claims, [], {digest_of(PASSAGE_TEXT): PASSAGE_TEXT})
    picked, shortfall = builder.sample_claims(claims, 30)
    assert len(picked) == 4
    assert "only 4 cited claims available" in shortfall


def test_uncited_claims_are_excluded_because_there_is_nothing_to_agree_with() -> None:
    """TRD §10 step 3 auto-scores a factual claim with no citation `unsupported`
    without a Jev call. Six of the seven `unsupported` claims in D7's six runs
    came from that rule, so including them would have the owner judging claims
    with no passage — a judgement about how the claim sounds, not about the
    reviewer."""
    export = make_export("run.json", verdicts={"supported": 5, "unsupported": 2})
    claims = builder.claims_from_export(export)
    for claim in claims:
        if claim.reviewer_verdict == "unsupported":
            claim.citation_numbers = []
            claim.passages = []
    picked, note = builder.sample_claims(claims, 30)
    assert all(c.passages for c in picked)
    assert "uncited" in note


def test_the_answer_sheet_takes_half_from_each_source() -> None:
    """Sampling one corpus alone describes one corpus: the exports are answers
    over the AW-2000 seed corpus, acceptance is answers over the Shared books."""

    def export_with(n_items: int, name: str) -> dict[str, Any]:
        payload = make_export(name, verdicts={"supported": 1})
        item = payload["per_item"][0]
        payload["per_item"] = [dict(item, question=f"q{i}") for i in range(n_items)]
        return payload

    exports = [builder.answers_from_export(export_with(40, f"r{i}.json")) for i in range(3)]
    acceptance = [
        builder.AnswerRow(
            answer_id=f"acceptance:{i}",
            source="acceptance",
            question="q",
            answer="a",
            passages=[],
            abstained=False,
        )
        for i in range(40)
    ]
    picked = builder.sample_answers([r for group in exports for r in group] + acceptance, 30)
    sources: dict[str, int] = {}
    for row in picked:
        sources[row.source] = sources.get(row.source, 0) + 1
    assert len(picked) == 30
    assert sources == {"export": 15, "acceptance": 15}, sources


def test_the_six_exports_count_as_one_source() -> None:
    """Per-file labels would make `sample_answers` see six corpora and hand the
    sheet fifteen export rows and no acceptance rows."""
    row = builder.answers_from_export(make_export("run.json", verdicts={"supported": 1}))[0]
    assert row.source == "export"


def test_an_unknown_verdict_is_dropped_rather_than_sampled() -> None:
    """A verdict the labelling guide does not define cannot be agreed against."""
    export = make_export("run.json", verdicts={"supported": 1, "skipped": 5})
    claims = builder.claims_from_export(export)
    assert {c.reviewer_verdict for c in claims} == {"supported"}


# --------------------------------------------------------------------------
# The sheets themselves
# --------------------------------------------------------------------------


def _write(tmp_path: Path, verdicts: dict[str, int]) -> tuple[Path, Path]:
    (tmp_path / "run.json").write_text(json.dumps(make_export("run.json", verdicts=verdicts)))
    builder.main(
        [
            "--exports",
            str(tmp_path / "run.json"),
            "--database-url",
            "postgresql+asyncpg://veriforge:veriforge@localhost:5432/nope",
            "--out",
            str(tmp_path),
        ]
    )
    return tmp_path / "claims.csv", tmp_path / "answers.csv"


def test_human_columns_are_left_empty(tmp_path: Path) -> None:
    """Filling them in is the owner's job. A pre-filled `human_verdict` turns
    the sheet into a copy of the reviewer's output."""
    import pytest

    if not (OUT / "claims.csv").exists():
        pytest.skip("build the sheets first")
    with (OUT / "claims.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "claims.csv is empty"
    for row in rows:
        assert row["human_verdict"] == "", row["claim_id"]


def test_the_reviewers_verdict_is_hidden_behind_an_underscore_prefix() -> None:
    import pytest

    if not (OUT / "claims.csv").exists():
        pytest.skip("build the sheets first")
    with (OUT / "claims.csv").open(encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    hidden = [c for c in header if c.startswith("_")]
    assert "_reviewer_verdict" in header
    assert any(c.startswith("human_") and not c.startswith("_") for c in header)
    assert hidden, "the reviewer's columns must be distinguishable at a glance"


def test_answers_csv_leaves_both_human_columns_empty() -> None:
    import pytest

    if not (OUT / "answers.csv").exists():
        pytest.skip("build the sheets first")
    with (OUT / "answers.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "answers.csv is empty"
    for row in rows:
        assert row["human_correct"] == "", row["answer_id"]
        assert row["human_grounded"] == "", row["answer_id"]


def test_the_readme_defines_every_verdict_the_guide_asks_for() -> None:
    import pytest

    if not (OUT / "README.md").exists():
        pytest.skip("build the sheets first")
    text = (OUT / "README.md").read_text(encoding="utf-8")
    for verdict in builder.VERDICTS:
        assert verdict in text, f"{verdict} is undefined in the guide"
    assert "do not read" in text.lower(), "the guide must warn about the hidden columns"


def test_the_sheets_have_the_row_counts_the_prompt_asks_for() -> None:
    import pytest

    if not (OUT / "claims.csv").exists():
        pytest.skip("build the sheets first")
    with (OUT / "claims.csv").open(encoding="utf-8") as handle:
        claims = list(csv.DictReader(handle))
    with (OUT / "answers.csv").open(encoding="utf-8") as handle:
        answers = list(csv.DictReader(handle))
    assert len(claims) == 30, len(claims)
    assert len(answers) == 30, len(answers)


def test_the_answers_sheet_samples_both_sources() -> None:
    """One corpus alone would describe one corpus. Half from each."""
    import pytest

    if not (OUT / "answers.csv").exists():
        pytest.skip("build the sheets first")
    with (OUT / "answers.csv").open(encoding="utf-8") as handle:
        answers = list(csv.DictReader(handle))
    sources = {row["answer_id"].split(":")[0] for row in answers}
    assert len(sources) >= 2, sources
