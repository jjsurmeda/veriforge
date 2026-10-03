"""The entity-mismatch set's shape, and the zero-hit proof it exists for (KI-54).

An entity-mismatch item passes only as a *clean decline*: the question names
entity A while only entity B's documents are in scope (`scope_corpus`), and
the named entity must be nowhere in the scoped corpus (zero-hit, the D1
method) and attested in the other one. These pin the properties the set would
silently lose: the six-plus-six balance, the non-English members, the two
observed failures as the first items, and that every item carries a proven
label — an item whose entity appears in its own scope corpus would not be a
mismatch and would rot the measurement.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.audit_entity_mismatch import audit_entity_items

ROOT = Path(__file__).resolve().parents[4]
SET_FILE = ROOT / "evals" / "entity_mismatch" / "items.json"
SEED_CORPUS = ROOT / "evals" / "seed" / "corpus"
CF_CORPUS = ROOT / "evals" / "counterfactual" / "corpus"

PAYLOAD: dict[str, Any] = json.loads(SET_FILE.read_text(encoding="utf-8"))
ITEMS: list[dict[str, Any]] = PAYLOAD["items"]

MIN_ITEMS = 12
MIN_PER_SIDE = 6
NON_ENGLISH_LANGUAGES = {"fr", "es", "de", "ja", "zh", "tl"}


def _file_texts(directory: Path) -> list[str]:
    return [path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.md"))]


def test_the_set_loads_with_the_shape_the_runner_and_audit_expect() -> None:
    ids = [item["id"] for item in ITEMS]
    assert len(set(ids)) == len(ids), "duplicate ids"
    assert PAYLOAD["dataset"] == "entity_mismatch"
    for item in ITEMS:
        assert item["should_abstain"] is True, item["id"]
        assert item["corpus"] == "entity_mismatch", item["id"]
        assert item["scope_corpus"] in {"seed", "counterfactual"}, item["id"]
        assert item.get("entity"), item["id"]
        assert item.get("language"), item["id"]
        # The proof is stamped by scripts/audit_entity_mismatch.py; an empty
        # proof is an unaudited label, which testing.md calls a test bug.
        assert item.get("proof"), f"{item['id']} has no proof"


def test_the_balance_is_six_each_way_with_two_non_english() -> None:
    counts = Counter(item["scope_corpus"] for item in ITEMS)
    assert len(ITEMS) >= MIN_ITEMS, len(ITEMS)
    assert counts["seed"] >= MIN_PER_SIDE, counts
    assert counts["counterfactual"] >= MIN_PER_SIDE, counts
    non_english = [item for item in ITEMS if item["language"] in NON_ENGLISH_LANGUAGES]
    assert len(non_english) >= 2, [item["id"] for item in non_english]


def test_the_two_observed_failures_are_the_first_items() -> None:
    # cf-k9-ingress and cf-k9-charge are the answers KI-54 quoted; keeping
    # them first keeps the report's before/after comparable across runs.
    assert [item["id"] for item in ITEMS[:2]] == ["cf-k9-ingress", "cf-k9-charge"]


def test_every_item_proves_its_label_against_the_corpus_files() -> None:
    """The D1 method, at file level: the named entity is a zero-hit in the
    scoped corpus and attested in the other. File text stands in for chunk
    text (a chunk is a slice of the file, and every entity here is a single
    word no chunker can split across a boundary)."""
    audits = audit_entity_items(
        ITEMS,
        scoped_chunks={"seed": _file_texts(SEED_CORPUS), "counterfactual": _file_texts(CF_CORPUS)},
    )
    failures = [f"{a.item_id}: {f.code}" for a in audits for f in a.findings]
    assert not failures, failures


def test_the_audit_catches_an_item_whose_entity_is_in_its_own_scope() -> None:
    """Mutation: an item whose entity IS attested in the scoped corpus is not
    a mismatch, and the audit must say so rather than prove a label that is
    not there."""
    broken = json.loads(json.dumps(ITEMS[0]))
    broken["id"] = "broken"
    broken["entity"] = "Aurora"  # attested throughout the seed corpus
    audits = audit_entity_items(
        [broken], scoped_chunks={"seed": _file_texts(SEED_CORPUS), "counterfactual": []}
    )
    assert not audits[0].ok
    assert {f.code for f in audits[0].findings} >= {"entity_attested_in_scope"}


def test_the_audit_catches_an_item_whose_entity_is_in_neither_corpus() -> None:
    """Mutation: an entity attested nowhere cannot be the thing the question
    names, so the item's premise is false and the label is not provable."""
    broken = json.loads(json.dumps(ITEMS[0]))
    broken["id"] = "broken"
    broken["entity"] = "Nonexistent-Entity-42"
    audits = audit_entity_items(
        [broken],
        scoped_chunks={"seed": _file_texts(SEED_CORPUS), "counterfactual": _file_texts(CF_CORPUS)},
    )
    assert not audits[0].ok
    assert {f.code for f in audits[0].findings} >= {"entity_missing_in_other_corpus"}
