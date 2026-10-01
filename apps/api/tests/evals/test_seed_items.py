"""Shape and class balance of the seed dataset (KI-6, D3 item 2).

The fast20 subset carried only 4 should-abstain items, so its
abstention_accuracy could only move in quarters. These pin the file's
loadability and the widened fast20 subset: exactly 20 resolvable ids, at
least 8 of them abstain items, and no book twin — fast20 measures the
seed-corpus domain only, so a local baseline is comparable with CI.
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


# The book twins (abstain-11..20) are questions about Gutenberg literature. The
# seed corpus is 7 AW-2000 documents, so in CI they are near-misses against an
# empty topic and decline trivially; the eval user only saw a real Moriarty
# passage locally because the Shared library was in scope (KI-24). fast20 must
# therefore depend on the seed corpus alone -- books belong to acceptance.
BOOK_TWINS = {
    "abstain-11",  # Professor Moriarty / Reichenbach
    "abstain-12",  # The War of the Worlds
    "abstain-13",  # Dracula
    "abstain-14",  # Through the Looking-Glass
    "abstain-15",  # Cosette, Les Misérables
    "abstain-16",  # 賈寶玉 and 林黛玉
    "abstain-17",  # Josef K., Der Process
    "abstain-18",  # 蜘蛛の糸
}


def test_fast20_contains_no_book_twin() -> None:
    """fast20 = the seed-corpus domain only (D3 item 2).

    A book twin in fast20 measures a different question in CI than it does
    locally, which is exactly the mismatch that made local numbers
    incomparable with the gate.
    """
    intruders = sorted(BOOK_TWINS & set(FAST20))
    assert not intruders, f"book twins in fast20: {intruders}"


def test_the_book_twins_stay_in_the_full_seed_set() -> None:
    """Removed from fast20, not from the dataset: the full seed run and
    acceptance still measure abstention over two corpora (Q1)."""
    ids = {item["id"] for item in ITEMS}
    assert ids >= BOOK_TWINS


def test_every_fast20_abstain_item_is_about_the_seed_corpus() -> None:
    """The complement of the check above, stated positively: each fast20
    should-abstain item names a subject from the seed corpus's own domain, so
    its absence is a real retrieval question rather than an off-topic one.

    `AW-3000` counts: it is the successor model the corpus never mentions,
    which is precisely the near-miss `abstain-04` and `abstain-19` ask for.
    """
    by_id = {item["id"]: item for item in ITEMS}
    domain = ("AW-2000", "AW-3000", "RP-77")
    for id_ in FAST20:
        item = by_id[id_]
        if not item["should_abstain"]:
            continue
        assert any(term in item["question"] for term in domain), f"{id_}: {item['question']}"
