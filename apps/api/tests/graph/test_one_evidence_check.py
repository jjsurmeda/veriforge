"""One evidence check (ADR-006, as corrected): replay the chosen gate.

The gate is the mean answer-containment grade of the best three post-sanitize
passages, compared against the shipped floor of 0.56. The entity guard beside
it is defense-in-depth: a named entity whose top entity-alignment score is
below 0.50 blocks the run even when the rubric mean clears the floor.

This file replays the `.data/evals/gate-calibration-*.json` artefacts
produced by `scripts/calibrate_gate.py` (Run 1, full-set, R2a-3). Those
artefacts record every item that reached a gate decision, its `mean_top3`,
and (for entity-mismatch and some books items) its `entity_max`. The
assertions are the acceptance contract: 0 confident wrong with or without
the guard, and the two known false-abstention items.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
ARTEFACTS = [
    REPO_ROOT / ".data" / "evals" / "gate-calibration-books-20261015T202842-f6b71ea.json",
    REPO_ROOT
    / ".data"
    / "evals"
    / "gate-calibration-entity_mismatch-20261015T203253-f6b71ea.json",
]
GATE_FLOOR = 0.56
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


def test_the_rubric_floor_alone_yields_zero_confident_wrong(
    rows: list[dict[str, Any]],
) -> None:
    """At the shipped floor (0.56), the gate alone catches every
    should-decline item. The KI-57 sanitizer fix collapsed entity-mismatch
    readings to 0.01-0.22, and the summary backfill kept books
    should-declines below floor."""
    confident_wrong = [
        r
        for r in rows
        if r["expect"] == "not_in_sources" and _gate_passes(r, use_entity_guard=False)
    ]
    assert confident_wrong == [], (
        "gate alone should catch every should-decline item at 0.56"
    )


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


def test_the_combined_gate_has_two_known_false_abstentions(
    rows: list[dict[str, Any]],
) -> None:
    false_abstentions = [
        r
        for r in rows
        if r["expect"] == "answer" and not _gate_passes(r, use_entity_guard=True)
    ]
    ids = {r["id"] for r in false_abstentions}
    assert ids == {"scene-tea-party", "outside-whitman"}
    assert all(r["mean_top3"] < GATE_FLOOR for r in false_abstentions)


def test_every_gated_item_records_a_jev_gate(rows: list[dict[str, Any]]) -> None:
    """The gate is a Jev decision; other providers are out of scope for R2a."""
    assert all(r.get("gate_engine") == "jev" for r in rows)


def test_outside_holmes_boston_is_caught_by_gate_not_guard(
    rows: list[dict[str, Any]],
) -> None:
    """The summary backfill lifted outside-holmes-boston from 0.520 (R2a-2,
    below the old 0.55 floor) to 0.554-0.559 (above 0.55, below 0.56).
    At the new floor the gate catches it; the entity guard was unreliable
    (in Run 2 it let the item through at entity_max=0.70 > 0.50)."""
    item = next(r for r in rows if r["id"] == "outside-holmes-boston")
    assert item["mean_top3"] < GATE_FLOOR, "gate itself must catch this item"
    assert item["expect"] == "not_in_sources"


def test_cf_k9_charge_collapsed_after_ki57(
    rows: list[dict[str, Any]],
) -> None:
    """KI-57 fail-closed dropped cf-k9-charge from 0.629 (R2a-2, relied on the
    entity guard) to 0.01-0.02 (gate alone catches it)."""
    item = next(r for r in rows if r["id"] == "cf-k9-charge")
    assert item["mean_top3"] is not None
    assert item["mean_top3"] < 0.05
    assert item["expect"] == "not_in_sources"
    assert item["abstained"] is True
