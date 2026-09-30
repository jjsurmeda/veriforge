"""Shape and class balance of the acceptance set itself (KI-6).

With only four `not_in_sources` items the abstention metric swung
0.00/0.00/0.25 between runs. These pin the file's loadability, the item
schema and the widened abstain class, so an edit that silently drops or
reclassifies items fails here before it reaches a live run.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

ACCEPTANCE = Path(__file__).resolve().parents[4] / "evals" / "acceptance" / "books.json"
ITEMS: list[dict[str, Any]] = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))["items"]

REQUIRED_FIELDS = {"id", "expect", "turns"}
VALID_EXPECTS = {"answer", "library", "not_in_sources", "smalltalk"}

# The counts the KI-6 widening leaves behind: 10 new not_in_sources items
# on top of the original 31-item set.
EXPECTED_CLASS_COUNTS = {
    "answer": 23,
    "not_in_sources": 14,
    "smalltalk": 2,
    "library": 2,
}


def test_the_set_loads_and_every_item_has_the_required_fields() -> None:
    assert len(ITEMS) == 41
    ids = [item["id"] for item in ITEMS]
    assert len(set(ids)) == len(ids), "duplicate ids"
    for item in ITEMS:
        missing = REQUIRED_FIELDS - set(item)
        assert not missing, f"{item.get('id')}: missing {sorted(missing)}"
        assert isinstance(item["id"], str) and item["id"]
        assert item["expect"] in VALID_EXPECTS, item["id"]
        assert isinstance(item["turns"], list) and item["turns"], item["id"]


def test_the_expect_class_totals_match_the_widened_set() -> None:
    counts = Counter(item["expect"] for item in ITEMS)
    assert dict(counts) == EXPECTED_CLASS_COUNTS


def test_the_abstain_class_is_wide_enough_to_score_stably() -> None:
    """The reason for KI-6: 4 items made abstention accuracy step in quarters."""
    abstains = [item for item in ITEMS if item["expect"] == "not_in_sources"]
    assert len(abstains) >= 12
    # Abstain items are checked on declining, not on citing or mentioning.
    for item in abstains:
        assert "cite" not in item and "mention" not in item, item["id"]
