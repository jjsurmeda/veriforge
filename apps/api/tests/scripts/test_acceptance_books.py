"""Shape and class balance of the acceptance set itself (D3 item 3).

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
# P1b item 3 adds 6 more not_in_sources near-misses (the prompt asks for 20/20,
# and there are now 20) and 3 ambiguity items, which are `answer` but carry
# `mention_all`. Those three carried `pending_p2` until P2 shipped and are
# scored normally now (2026-10-12).
EXPECTED_CLASS_COUNTS = {
    "answer": 32,
    "not_in_sources": 21,
    "smalltalk": 2,
    "library": 2,
}

# P1b item 3: the ambiguity items the corpus answers two ways (KI-27's Wukong
# shape). P2's prompt change shipped, so they are scored like any other answer
# item: a run that names one referent and misses the other fails them.
AMBIGUITY_ITEMS = [
    "amb-frankenstein-addressee",
    "amb-alice-sister",
]

# P1b item 3 added three ambiguity items; phase 1c item 2 (2026-10-12) moved
# `amb-bovary-homais` out of the answer class because its premise is not in
# this corpus: the eye-consultation scene it depends on is not in this edition
# of Madame Bovary, and 'Rouard' — the second referent — is 0 hits corpus-wide.
# The item is kept in the set and is now a should-decline; see its `relabelled`
# field.
RELABELLED_TO_ABSTAIN = ["amb-bovary-homais"]

# P1b item 3: six near-miss abstentions, two of them non-English (the prompt's
# "including 2 non-English"). Each was spot-read against the corpus.
NEAR_MISS_ITEMS = [
    "outside-holmes-mycroft",
    "outside-holmes-boston",
    "ml-de-bovary-animal",
    "ml-fr-noli-baiser",
    "ml-zh-xiyou-nezha",
    "ml-ja-rashomon-rokuro",
]

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
    assert len(ITEMS) == 57  # 48 + P1b item 3's six near-misses and three ambiguities
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


def test_the_expect_class_totals_match_the_relabelled_set() -> None:
    """33/20 became 32/21 on 2026-10-12 (phase 1c item 2): `amb-bovary-homais`
    moved to `not_in_sources`. See `RELABELLED_TO_ABSTAIN`."""
    counts = Counter(item["expect"] for item in ITEMS)
    assert dict(counts) == EXPECTED_CLASS_COUNTS


def test_the_relabelled_item_records_the_relabel_and_spot_reads() -> None:
    """A relabel is a claim about the corpus, and the next person to touch this
    set has to be able to check it without re-running the audit. Both fields are
    required, and the relabel must name the item it came from."""
    by_id = {item["id"]: item for item in ITEMS}
    for id_ in RELABELLED_TO_ABSTAIN:
        item = by_id[id_]
        assert item["expect"] == "not_in_sources", id_
        assert item.get("relabelled"), f"{id_}: a relabel must record why"
        assert "2026-10-12" in item["relabelled"], id_
        assert item.get("spot_read"), f"{id_}: a relabelled abstention needs its spot-read"
        # An abstention is graded on declining, so it must not also carry the
        # answer-class checks it had before.
        assert "cite" not in item and "mention" not in item, id_


def test_the_relabelled_item_is_still_in_the_set() -> None:
    """Deleting the item would move the class counts the same way and quietly
    shrink the set. The relabel has to keep it, reclassified."""
    by_id = {item["id"]: item for item in ITEMS}
    for id_ in RELABELLED_TO_ABSTAIN:
        assert id_ in by_id, f"{id_}: relabelled, not removed"


def test_the_abstain_class_is_wide_enough_to_score_stably() -> None:
    """The reason for KI-6: 4 items made abstention accuracy step in quarters."""
    abstains = [item for item in ITEMS if item["expect"] == "not_in_sources"]
    assert len(abstains) >= 12
    # Abstain items are checked on declining, not on citing or mentioning.
    for item in abstains:
        assert "cite" not in item and "mention" not in item, item["id"]


def test_the_abstain_class_reaches_twenty_one_with_two_non_english_near_misses() -> None:
    """P1b item 3's target was 20 should-abstain items, of which the six added
    are near-misses and at least two are asked in the book's own language.
    Phase 1c item 2 (2026-10-12) made it 21 by relabelling `amb-bovary-homais`
    — the class got wider, not thinner, which is the direction KI-6 asked for."""
    by_id = {item["id"]: item for item in ITEMS}
    for id_ in NEAR_MISS_ITEMS:
        assert id_ in by_id, id_
        item = by_id[id_]
        assert item["expect"] == "not_in_sources", id_
        # A near-miss needs its spot-read: an abstention the audit flagged and
        # nobody read is exactly the untrustworthy item this prompt is about.
        assert item.get("spot_read"), f"{id_}: a near-miss must record its spot-read"
    multilingual = [
        id_
        for id_ in NEAR_MISS_ITEMS
        if detect_language(by_id[id_]["turns"][-1]) not in (None, "en")
    ]
    assert len(multilingual) >= 2, multilingual


def test_the_ambiguity_items_name_both_referents_and_are_scored_normally() -> None:
    """KI-27's Wukong shape: the corpus answers two ways, so the item lists both.

    They carried `pending_p2` until P2 shipped (2026-10-12) and are now scored
    like any other answer item, so the flag is asserted *absent*: an item that
    silently regains it stops counting against today's pass rate.

    `amb-bovary-homais` was the third and left this list on 2026-10-12 (phase 1c
    item 2): the corpus does not answer it two ways, it does not answer it at
    all. It is now in `RELABELLED_TO_ABSTAIN` and asserted there instead, so
    "the third ambiguity item vanished" is not a state this suite can reach.
    """
    by_id = {item["id"]: item for item in ITEMS}
    for id_ in AMBIGUITY_ITEMS:
        assert id_ in by_id, id_
        item = by_id[id_]
        assert item["expect"] == "answer", id_
        assert "pending_p2" not in item, f"{id_}: P2 shipped; the flag is retired"
        assert len(item.get("mention_all", [])) >= 1, id_
        assert item.get("why_ambiguous"), f"{id_}: state why the corpus answers two ways"
    assert "amb-bovary-homais" not in AMBIGUITY_ITEMS
    assert "amb-bovary-homais" in RELABELLED_TO_ABSTAIN


def test_no_item_is_pending_p2() -> None:
    """The flag is retired set-wide. Reintroducing one is a label change that
    has to be argued in the set file and here, not a way to make a set look
    better."""
    pending = [item["id"] for item in ITEMS if item.get("pending_p2")]
    assert pending == [], pending


def test_the_stale_count_label_was_relabelled_to_the_corpus() -> None:
    """Decision B: `library-count` said 5 while the corpus holds 11 books. The
    item records why, because the next person to add a book has to redo it."""
    item = {item["id"]: item for item in ITEMS}["library-count"]
    assert "5" not in item["mention"]
    assert item["why_mention_list"], "the relabel must say why and what to re-check"
    assert "corpus" in item["why_mention_list"].lower()


def test_a_label_the_corpus_contradicts_is_not_left_in_place() -> None:
    """Decision B's rule, as a test. `frame-walton` required 'Saville', which
    this Gutenberg edition never says; `fact-bennet-sisters` required the digit
    '5' for a corpus that says 'five'."""
    by_id = {item["id"]: item for item in ITEMS}
    assert "Saville" not in by_id["frame-walton"]["mention"]
    assert by_id["frame-walton"].get("removed_mention", {}).get("Saville"), (
        "removing a mention must record what it was and why"
    )
    assert {"five", "5"} <= set(by_id["fact-bennet-sisters"]["mention"])
