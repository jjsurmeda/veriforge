"""Shape and class balance of the acceptance set itself (KI-6, D3 item 3).

With only four `not_in_sources` items the abstention metric swung
0.00/0.00/0.25 between runs. These pin the file's loadability, the item
schema and the widened abstain class, so an edit that silently drops or
reclassifies items fails here before it reaches a live run. D3 item 3 widens
the *answer* side the same way: the set had two broad/summarize items, both
English, next to a relevance floor that `broad-frankenstein` cleared by 0.08.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from textkit import detect_language

ACCEPTANCE = Path(__file__).resolve().parents[4] / "evals" / "acceptance" / "books.json"
ITEMS: list[dict[str, Any]] = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))["items"]

REQUIRED_FIELDS = {"id", "expect", "turns"}
VALID_EXPECTS = {"answer", "library", "not_in_sources", "smalltalk"}

# The counts the KI-6 widening leaves behind, plus D3 item 3's six broad /
# summarize answer items: 10 new not_in_sources and 6 new answer on top of the
# original 31-item set. KI-36 then moved `outside-whitman` from
# not_in_sources to answer (its answer was in the corpus all along) and added
# `outside-whitman-lilacs` to replace the abstention coverage it gave up.
EXPECTED_CLASS_COUNTS = {
    "answer": 30,
    "not_in_sources": 14,
    "smalltalk": 2,
    "library": 2,
}

# The reason D3 added them: only two broad/summarize answer items existed
# (broad-sherlock, broad-frankenstein), both English, so the answer side next
# to the gate rested on two trials.
BROAD_ANSWER_ITEMS = [
    "broad-alice",
    "broad-time-machine",
    "broad-quijote",
    "broad-verwandlung",
    "broad-wukong",
    "broad-bovary",
]


def test_the_set_loads_and_every_item_has_the_required_fields() -> None:
    assert len(ITEMS) == 48
    ids = [item["id"] for item in ITEMS]
    assert len(set(ids)) == len(ids), "duplicate ids"
    for item in ITEMS:
        missing = REQUIRED_FIELDS - set(item)
        assert not missing, f"{item.get('id')}: missing {sorted(missing)}"
        assert isinstance(item["id"], str) and item["id"]
        assert item["expect"] in VALID_EXPECTS, item["id"]
        assert isinstance(item["turns"], list) and item["turns"], item["id"]


def test_the_answer_side_has_broad_items_in_at_least_two_languages() -> None:
    """D3 item 3: 4-6 broad/summarize answer items, over different books, in
    at least two languages. Counted by asking language detection what it says,
    so a question that stops being multilingual fails here."""
    by_id = {item["id"]: item for item in ITEMS}
    for id_ in BROAD_ANSWER_ITEMS:
        assert id_ in by_id, id_
        assert by_id[id_]["expect"] == "answer", id_
        assert by_id[id_].get("cite"), f"{id_}: a broad item must check its citation"
        assert by_id[id_].get("mention"), f"{id_}: a broad item must check its content"
    languages = {detect_language(by_id[id_]["turns"][-1]) for id_ in BROAD_ANSWER_ITEMS}
    assert len(languages - {None}) >= 2, f"broad items cover only {languages}"
    # Six items over six different books, so one weak retrieval story cannot
    # account for the whole class.
    cited = {book for id_ in BROAD_ANSWER_ITEMS for book in by_id[id_]["cite"]}
    assert len(cited) == len(BROAD_ANSWER_ITEMS), cited


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
