"""Shape and class balance of the seed dataset (KI-6).

The fast20 subset carried only 4 should-abstain items, so its
abstention_accuracy could only move in quarters. These pin the file's
loadability and the widened fast20 subset: exactly 20 resolvable ids, at
least 8 of them abstain items.
"""

import json
from pathlib import Path
from typing import Any

SEED = Path(__file__).resolve().parents[4] / "evals" / "seed" / "items.json"
DATASET: dict[str, Any] = json.loads(SEED.read_text(encoding="utf-8"))
ITEMS: list[dict[str, Any]] = DATASET["items"]
FAST20: list[str] = DATASET["fast20_ids"]

REQUIRED_FIELDS = {"id", "category", "question", "should_abstain"}


def test_the_seed_loads_with_the_expected_schema() -> None:
    assert DATASET["dataset"] == "seed"
    ids = [item["id"] for item in ITEMS]
    assert len(set(ids)) == len(ids), "duplicate ids"
    for item in ITEMS:
        missing = REQUIRED_FIELDS - set(item)
        assert not missing, f"{item.get('id')}: missing {sorted(missing)}"
        assert isinstance(item["should_abstain"], bool), item["id"]
        assert isinstance(item["question"], str) and item["question"], item["id"]


def test_fast20_has_exactly_20_ids_all_present_in_items() -> None:
    assert len(FAST20) == 20
    assert len(set(FAST20)) == len(FAST20), "duplicate fast20 ids"
    item_ids = {item["id"] for item in ITEMS}
    unknown = set(FAST20) - item_ids
    assert unknown == set(), f"fast20 ids with no item: {sorted(unknown)}"


def test_fast20_carries_at_least_8_should_abstain_items() -> None:
    """The reason for KI-6: 4 abstains made the fast subset's abstention
    accuracy step 0.00/0.00/0.25."""
    by_id = {item["id"]: item for item in ITEMS}
    abstains = [id_ for id_ in FAST20 if by_id[id_]["should_abstain"]]
    assert len(abstains) >= 8
    assert all(by_id[id_]["category"] == "should_abstain" for id_ in abstains)
