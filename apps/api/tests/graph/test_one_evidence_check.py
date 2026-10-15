"""One evidence check (ADR-006, as corrected): replay the chosen gate.

The gate is the mean answer-containment grade of the best three post-sanitize
passages, compared against the shipped floor of 0.55. The entity guard beside
it is load-bearing: a named entity whose top entity-alignment score is below
0.50 blocks the run even when the rubric mean clears the floor.

This file replays the two `.data/evals/gate-calibration-*.json` artefacts
produced by `scripts/calibrate_gate.py`. Those artefacts record every item
that reached a gate decision, its `mean_top3`, and (for entity-mismatch items)
its `entity_max`. The assertions are the acceptance contract: 0 confident
wrong with the guard, and the known false-abstention count.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
ARTEFACTS = [
    REPO_ROOT / ".data" / "evals" / "gate-calibration-books-20261015T142755-dd1017e.json",
    REPO_ROOT
    / ".data"
    / "evals"
    / "gate-calibration-entity_mismatch-20261015T171149-8f0ec2b.json",
]
GATE_FLOOR = 0.55
ENTITY_FLOOR = 0.50


def _load_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in ARTEFACTS:
        if not path.exists():
            pytest.skip(f"calibration artefact not present: {path}")
        rows.extend(json.loads(path.read_text())["rows"])
    return [r for r in rows if r.get("gated")]


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    return _load_rows()


def _gate_passes(row: dict[str, Any], *, use_entity_guard: bool) -> bool:
    mean_top3 = row.get("mean_top3")
    if mean_top3 is None or mean_top3 < GATE_FLOOR:
        return False
    if use_entity_guard and row.get("entity_measured"):
        entity_max = row.get("entity_max")
        if entity_max is None or entity_max < ENTITY_FLOOR:
            return False
    return True


def test_the_artefacts_cover_the_expected_datasets(rows: list[dict[str, Any]]) -> None:
    assert len(rows) == 65, "53 books items + 12 entity-mismatch items reach the gate"


def test_the_rubric_floor_and_entity_guard_together_yield_zero_confident_wrong(
    rows: list[dict[str, Any]],
) -> None:
    confident_wrong = [
        r
        for r in rows
        if r["expect"] == "not_in_sources" and _gate_passes(r, use_entity_guard=True)
    ]
    assert confident_wrong == [], (
        "with the entity guard, no should-decline item clears the combined gate"
    )


def test_the_rubric_floor_alone_has_exactly_one_confident_wrong(
    rows: list[dict[str, Any]],
) -> None:
    confident_wrong = [
        r
        for r in rows
        if r["expect"] == "not_in_sources" and _gate_passes(r, use_entity_guard=False)
    ]
    assert len(confident_wrong) == 1, "gate alone costs one should-decline item"
    assert confident_wrong[0]["id"] == "cf-k9-charge"
    assert confident_wrong[0]["mean_top3"] == pytest.approx(0.6288888888888889)
    assert confident_wrong[0]["entity_max"] == pytest.approx(0.45)


def test_the_entity_guard_blocks_the_one_gate_only_confident_wrong(
    rows: list[dict[str, Any]],
) -> None:
    cf_k9 = next(r for r in rows if r["id"] == "cf-k9-charge")
    assert _gate_passes(cf_k9, use_entity_guard=False)
    assert not _gate_passes(cf_k9, use_entity_guard=True)
    assert cf_k9["entity_max"] < ENTITY_FLOOR


def test_the_combined_gate_has_two_known_false_abstentions(
    rows: list[dict[str, Any]],
) -> None:
    false_abstentions = [
        r
        for r in rows
        if r["expect"] == "answer" and not _gate_passes(r, use_entity_guard=True)
    ]
    ids = {r["id"] for r in false_abstentions}
    assert ids == {"outside-whitman", "broad-alice"}
    assert all(r["mean_top3"] < GATE_FLOOR for r in false_abstentions)


def test_every_gated_item_records_a_jev_gate(rows: list[dict[str, Any]]) -> None:
    """The gate is a Jev decision; other providers are out of scope for R2a."""
    assert all(r.get("gate_engine") == "jev" for r in rows)
