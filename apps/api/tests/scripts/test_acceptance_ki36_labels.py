"""Acceptance items that were wrong, not the pipeline. The labels are
replayed against D4's *recorded* answers, so a future edit that makes one of
these items unsatisfiable by a known-correct answer fails here instead of at
the next $40 acceptance run.

`testing.md`, "Test data is audited like code": every label carries its proof,
and "Intent tests": a label that cannot fail is not a label.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.acceptance import failure_reason, passes

DATASET: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[4] / "evals" / "acceptance" / "books.json").read_text(
        encoding="utf-8"
    )
)
ITEMS: dict[str, dict[str, Any]] = {i["id"]: i for i in DATASET["items"]}

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "acceptance"
    / "d4_20261001_whitman_weena.json"
)
RECORDED: dict[str, dict[str, dict[str, Any]]] = json.loads(FIXTURE.read_text(encoding="utf-8"))[
    "runs"
]

# Both D4 acceptance runs, 2026-10-01. Run 1 was the better of the two (42/47).
RUNS = sorted(RECORDED)


def _reworded(item_id: str, **overrides: Any) -> dict[str, Any]:
    return {**ITEMS[item_id], **overrides}


# --- outside-whitman: removed 2026-10-22 (KI-80) -----------------------------


def test_outside_whitman_stays_out_of_the_set() -> None:
    """KI-36 relabelled it `answer`, but its only passage says Whitman draws a
    'fine and just distinction' without saying what it is, so the question is
    not answerable from the corpus. Removed (KI-80); the item's label, proof and
    the D4 evidence behind it are in git history before 2026-10-22."""
    assert "outside-whitman" not in ITEMS


# --- fact-weena: the mention list must accept a correct answer --------------


@pytest.mark.parametrize("run", RUNS)
def test_fact_weena_passes_d4s_recorded_answer(run: str) -> None:
    """Both D4 answers are correct (7 Time Machine citations, Weena described
    accurately) and neither says 'Eloi'."""
    result = RECORDED[run]["fact-weena"]
    assert "eloi" not in result["answer"].lower(), "fixture assumption: 'Eloi' was the defect"
    assert passes(ITEMS["fact-weena"], result) is True
    assert failure_reason(ITEMS["fact-weena"], result) is None


def test_fact_weena_records_why_the_mention_list_was_widened() -> None:
    item = ITEMS["fact-weena"]
    assert item["mention"] == ["Eloi", "flower"]
    assert "flower" in item["why_mention_list"]
    # 'Time Traveller' was considered and rejected because run 1's correct
    # answer never says it; the reason must be in the item, not just in the
    # commit message.
    assert "Time Traveller" in item["rejected_mention"]
    assert item["note"], "the widening's risk is recorded alongside it"


# --- outside-whitman-lilacs: the new abstention item -------------------------


def test_the_new_whitman_item_is_a_well_formed_abstention_item() -> None:
    item = ITEMS["outside-whitman-lilacs"]
    assert item["expect"] == "not_in_sources"
    assert "cite" not in item and "mention" not in item
    assert item["turns"] and isinstance(item["turns"][0], str)


def test_the_new_whitman_item_carries_a_zero_hit_proof() -> None:
    """testing.md: a not_in_sources item carries 'the zero-hit queries over
    everything the test user can retrieve, with spot-read notes on false hits'.
    Without the recorded queries and the scope size, the label is an assertion."""
    proof = ITEMS["outside-whitman-lilacs"]["proof"]
    for term in ("lilac", "dooryard", "lincoln", "whitman", "leaves of grass"):
        assert f"%{term}%" in proof, f"proof does not record the {term} query"
    assert "10,733" in proof, "the proof does not state the scope it searched"
    assert "shared" in proof and "build_scope" in proof, "the proof must name the ownership scope"
    assert proof.count("spot-read") >= 1, "no spot-read notes on false hits"
    assert ITEMS["outside-whitman-lilacs"]["why_this_question"]


def test_the_lilacs_item_names_the_only_whitman_passage() -> None:
    """The only Whitman passage in scope is the P&P preface, and this item says so."""
    assert "Pride and Prejudice" in ITEMS["outside-whitman-lilacs"]["proof"]


# --- dataset-wide audit convention -------------------------------------------

AUDITED_FIELDS = ("proof", "note", "why_both_checks", "why_mention_list", "rejected_mention")


def test_every_relabelled_item_carries_its_proof() -> None:
    """Every field KI-36 added is non-empty: an empty audit field is an
    assertion wearing the costume of proof."""
    for id_ in ("outside-whitman-lilacs", "fact-weena"):
        found = [f for f in AUDITED_FIELDS if ITEMS[id_].get(f)]
        assert found, f"{id_}: no audit field"
        for f in found:
            assert isinstance(ITEMS[id_][f], str) and ITEMS[id_][f].strip()
