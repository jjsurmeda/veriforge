"""One floor, one usefulness check (ADR-006, accepted 2026-10-17): $0 replay.

The floor is the mean answer-containment grade of the best three post-sanitize
passages, compared against the shipped 0.455 floor — but it is no longer a
decline classifier: below the floor is "clearly absent", above it the run
generates and IsUse decides whether the answer answers the question.

This file replays the recorded artefacts over the accepted design:
- `.data/evals/gate-calibration-*.json` (from `scripts/calibrate_gate.py`,
  R2a-3): every gated item's `mean_top3`, replayed against the floor;
- `.data/evals/isuse-probe-a03a3a8.json` (the R2a-4 probe, gate forced open):
  the same items' gate readings plus the `isuse` reading the generated answer
  drew from Jev.

The assertions are the ADR's contract: below the floor sit only should-decline
items and the three answerable misses the design names (the two pre-existing
false abstentions and the 2026-10-17 relabel whose rescue is the corrective
retrieval); everything the floor releases is IsUse's case, and the probe
shows IsUse separating those readings 0.37 from 0.56.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
ARTEFACTS = [
    REPO_ROOT / ".data" / "evals" / "gate-calibration-books-20261015T142755-dd1017e.json",
    REPO_ROOT / ".data" / "evals" / "gate-calibration-books-20261015T202842-f6b71ea.json",
    REPO_ROOT
    / ".data"
    / "evals"
    / "gate-calibration-entity_mismatch-20261015T203253-f6b71ea.json",
    REPO_ROOT / ".data" / "evals" / "isuse-probe-a03a3a8.json",
]
GATE_FLOOR = 0.455
ENTITY_FLOOR = 0.50
# Items whose artefact-time `expect` is stale: the ADR-006 commit relabelled
# `ml-zh-xiyou-nezha` to `answer` (the corpus states the Heavenly King lives
# in the Cloud Tower Palace and calls Nezha there). Every other `expect` in
# the artefacts reads as written.
RELABELLED_ANSWER = {"ml-zh-xiyou-nezha"}


def _expect(row: dict[str, Any]) -> str:
    expect = str(row["expect"])
    return "answer" if row["id"] in RELABELLED_ANSWER else expect


@pytest.fixture(scope="module")
def gate_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in ARTEFACTS[:3]:
        if not path.exists():
            pytest.skip(f"calibration artefact not present: {path}")
        rows.extend(json.loads(path.read_text())["rows"])
    return [r for r in rows if r.get("gated")]


@pytest.fixture(scope="module")
def probe_rows() -> list[dict[str, Any]]:
    path = ARTEFACTS[3]
    if not path.exists():
        pytest.skip(f"probe artefact not present: {path}")
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# The floor replay
# ---------------------------------------------------------------------------


def test_the_artefacts_cover_the_expected_datasets(gate_rows: list[dict[str, Any]]) -> None:
    assert len(gate_rows) == 118, "106 books rows + 12 entity-mismatch rows reach the gate"


def _blocked_before_generate(row: dict[str, Any]) -> bool:
    """The pre-generation verdict: the floor, with the entity guard beside it.

    A missing reading fails (safe direction), exactly as
    `graph.stages.checks.rubric_gate_passes` does.
    """
    mean_top3 = row.get("mean_top3")
    passes_floor = mean_top3 is not None and mean_top3 >= GATE_FLOOR
    if not passes_floor:
        return True
    # Entity mismatch rows carry the guard's reading; a named entity whose
    # top alignment is below 0.50 blocks even when the floor cleared.
    if row.get("entity_measured"):
        entity_max = row.get("entity_max")
        if entity_max is None or entity_max < ENTITY_FLOOR:
            return True
    return False


def test_the_floor_yields_zero_confident_wrong(gate_rows: list[dict[str, Any]]) -> None:
    """Should-decline items that still read above the floor stay held only if
    the entity guard catches them; the ones the floor releases are IsUse's
    case, and the table below pins exactly which."""
    confident_wrong = [
        r
        for r in gate_rows
        if _expect(r) == "not_in_sources" and not _blocked_before_generate(r)
    ]
    ids = {r["id"] for r in confident_wrong}
    assert ids == {"outside-moby-dick", "outside-holmes-boston"}, (
        "the floor releases should-declines above 0.455; their decline is "
        "IsUse's decision, and this set owning the hand-off"
    )


def test_the_blocked_band_stops_where_the_floor_claims(gate_rows: list[dict[str, Any]]) -> None:
    """The margin the threshold comment quotes: the highest should-decline
    Reading the floor still blocks is 0.4411, and the lowest answerable
    reading the floor lets through is 0.4989 in the calibration (the probe's
    forced-open run reaches 0.4721 — pinned there instead, harder)."""
    blocked_declines = [
        r
        for r in gate_rows
        if _expect(r) == "not_in_sources" and r.get("mean_top3") is not None
        and r["mean_top3"] < GATE_FLOOR
    ]
    assert max(r["mean_top3"] for r in blocked_declines) == pytest.approx(0.4411, abs=0.001)
    released_answers = [
        r
        for r in gate_rows
        if _expect(r) == "answer" and not _blocked_before_generate(r)
    ]
    assert min(r["mean_top3"] for r in released_answers) == pytest.approx(0.4989, abs=0.001)


def test_the_blocked_answerables_are_the_three_named_misses(
    gate_rows: list[dict[str, Any]],
) -> None:
    """Answer-class items the floor blocks on these single-pass runs:
    `outside-whitman` (the design's explicit allowed miss), and
    `scene-tea-party` — both already false abstentions under the old 0.56
    gate. `ml-zh-xiyou-nezha` is the relabel whose single-pass readings
    (0.3967-0.4411) sit below the floor: its accepted rescue is the one
    corrective retrieval the floor triggers before it can abstain, and the
    live proof run grades whether the rescue holds."""
    blocked_answerables = [
        r for r in gate_rows if _expect(r) == "answer" and _blocked_before_generate(r)
    ]
    ids = {r["id"] for r in blocked_answerables}
    assert ids == {"outside-whitman", "scene-tea-party", "ml-zh-xiyou-nezha"}


def test_every_gated_item_records_a_jev_gate(gate_rows: list[dict[str, Any]]) -> None:
    """The floor is a Jev-rubric decision; other providers are out of scope."""
    engines = {r.get("gate_engine") for r in gate_rows}
    assert engines == {"jev"}


def test_cf_k9_charge_stays_below_the_floor_after_ki57(
    gate_rows: list[dict[str, Any]],
) -> None:
    """KI-57 fail-closed dropped cf-k9-charge from 0.629 (R2a-2, relied on the
    entity guard) to 0.01-0.02: under the new floor it is still clearly
    absent, so the KI-57 fix holds at the new value too."""
    item = next(r for r in gate_rows if r["id"] == "cf-k9-charge")
    assert item["mean_top3"] is not None
    assert item["mean_top3"] < 0.05
    assert item["expect"] == "not_in_sources"
    assert item["abstained"] is True


# ---------------------------------------------------------------------------
# The IsUse replay (the probe ran the floors open, so its gate readings are
# the ones the floor has to sit under — see `test_the_floor_sits_under_...`).
# ---------------------------------------------------------------------------


def test_the_probe_separates_the_classes_by_isuse(probe_rows: list[dict[str, Any]]) -> None:
    """IsUse readings: should-decline answers 0.09-0.37, answerable answers
    0.56-0.93 — and `outside-whitman`'s 0.11 is the one answerable miss the
    design accepts. Rows that abstained before generation hold no isuse
    reading at all: the check only exists for a generated answer."""
    sep = [
        (r["id"], r["expect"], r["isuse"]) for r in probe_rows if r.get("isuse") is not None
    ]
    failing = [v for _id, expect, v in sep if _expect({"id": _id, "expect": expect}) != "answer"]
    answering = [v for _id, expect, v in sep if _expect({"id": _id, "expect": expect}) == "answer"]
    assert failing and answering, "the probe must cover both classes"
    assert max(failing) == pytest.approx(0.37)
    assert min(v for v in answering if v != 0.11) == pytest.approx(0.56)
    assert {i for i, _e, v in sep if v == 0.11} == {"outside-whitman"}


def test_the_floor_sits_between_the_probe_s_answerable_min_and_the_miss(
    probe_rows: list[dict[str, Any]],
) -> None:
    """The floor was lowered to sit under the probe's own answerable readings
    (the gate forced open): the lowest answerable gate reading the floor
    releases is `broad-sherlock` 0.4721 — 0.017 above the shipped 0.455. Only
    two answerable readings land below the floor: the design's named
    `outside-whitman` miss and the 2026-10-17 `ml-zh-xiyou-nezha` relabel,
    whose rescue is the floor's own corrective retrieval (the accepted
    tension the threshold comment owns)."""
    checked = [r for r in probe_rows if r.get("gate") is not None]
    answerable = [r for r in checked if _expect(r) == "answer"]
    released = [r for r in answerable if r["gate"] >= GATE_FLOOR]
    assert min(r["gate"] for r in released) == pytest.approx(0.4721, abs=0.001)
    blocked = {r["id"] for r in answerable if r["gate"] < GATE_FLOOR}
    assert blocked == {"outside-whitman", "ml-zh-xiyou-nezha"}


def test_the_probe_s_decline_cluster_still_reads_below_the_floor(
    probe_rows: list[dict[str, Any]],
) -> None:
    """The should-decline cluster the floor keeps blocking is the band the
    margins are measured against: `ml-de-bovary-animal` 0.4278 is the highest
    should-decline reading the forced-open probe produced **below the
    floor**, 0.027 under it — that is the cluster the floor still declines
    outright (it was held by the entity guard before generation had a chance,
    so `n_contexts` is 0 and no isuse reading exists). `outside-moby-dick`
    reached generation at 0.5289 and became IsUse's case, reading 0.26."""
    declines = [
        r
        for r in probe_rows
        if _expect(r) == "not_in_sources" and r.get("gate") is not None and r["gate"] < GATE_FLOOR
    ]
    highest = max(declines, key=lambda r: r["gate"])
    assert highest["id"] == "ml-de-bovary-animal"
    assert highest["gate"] == pytest.approx(0.4278, abs=0.001)
    assert highest["n_contexts"] == 0
    released = [
        r
        for r in probe_rows
        if _expect(r) == "not_in_sources"
        and r.get("gate") is not None
        and r["gate"] >= GATE_FLOOR
        and r["n_contexts"]
    ]
    assert {r["id"] for r in released} == {"outside-moby-dick"}
    assert next(r["isuse"] for r in probe_rows if r["id"] == "outside-moby-dick") == 0.26
