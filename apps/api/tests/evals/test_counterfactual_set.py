"""The counterfactual set's shape, and the `forbid` check it exists for.

A counterfactual item passes only if the answer states the **document's**
value, and fails if it also names the real-world one. The real-world value is
what a model produces from memory, so the item measures grounding rather than
knowledge — the only way to certify that is a corpus whose facts are wrong.

These pin the properties the set would silently lose: the class balance the
prompt asks for, the category counts, and that every answerable item carries a
`forbid` list naming a value the corpus does *not* contain. That last one is
the one that can rot: an item whose forbid list has drifted into containing the
document's own value would fail every correct answer.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.acceptance import forbids_hit, passes
from scripts.audit_labels import audit_items, corpus_from_files

ROOT = Path(__file__).resolve().parents[4]
SET_FILE = ROOT / "evals" / "counterfactual" / "items.json"
CORPUS_DIR = ROOT / "evals" / "counterfactual" / "corpus"
PAYLOAD: dict[str, Any] = json.loads(SET_FILE.read_text(encoding="utf-8"))
ITEMS: list[dict[str, Any]] = PAYLOAD["items"]

MIN_DOCUMENTS = 8
MIN_ANSWERABLE = 20
MIN_ABSTAIN = 20
MIN_TABLE = 4
MIN_MULTIHOP = 4
NON_ENGLISH_LANGUAGES = {"fr", "es", "de"}


def test_the_set_loads_with_unique_ids_and_required_fields() -> None:
    ids = [item["id"] for item in ITEMS]
    assert len(set(ids)) == len(ids), "duplicate ids"
    # The loader keys the EvalDataset on this, so its absence is a load failure
    # rather than a naming preference.
    assert PAYLOAD["dataset"] == "counterfactual", PAYLOAD.get("dataset")
    for item in ITEMS:
        assert item["expect"] in {"answer", "not_in_sources"}, item["id"]
        assert isinstance(item["turns"], list) and item["turns"], item["id"]
        assert item.get("category"), item["id"]


def test_the_corpus_has_the_documents_and_languages_the_prompt_asks_for() -> None:
    files = sorted(p.name for p in CORPUS_DIR.glob("*.md"))
    assert len(files) >= MIN_DOCUMENTS, files
    prefixes = {name.split("_")[0] for name in files}
    assert {"fr", "es", "de"} <= prefixes, sorted(prefixes)


def test_the_class_balance_is_at_least_twenty_each_way() -> None:
    counts = Counter(item["expect"] for item in ITEMS)
    assert counts["answer"] >= MIN_ANSWERABLE, counts
    assert counts["not_in_sources"] >= MIN_ABSTAIN, counts


def test_there_are_table_lookups_and_multihop_items() -> None:
    counts = Counter(item.get("category") for item in ITEMS)
    assert counts["table_lookup"] >= MIN_TABLE, counts
    assert counts["multihop"] >= MIN_MULTIHOP, counts


def test_two_or_more_items_per_non_english_language() -> None:
    counts = Counter(item.get("category") for item in ITEMS)
    assert counts["multi_language"] >= 2 * len(NON_ENGLISH_LANGUAGES), counts


def test_every_answerable_item_checks_a_citation_and_a_forbidden_value() -> None:
    """`forbid` is the whole point: without one the item measures knowledge."""
    for item in ITEMS:
        if item["expect"] != "answer":
            assert "forbid" not in item, item["id"]
            continue
        assert item.get("cite"), f"{item['id']}: an answer item must check its citation"
        if not item.get("forbid"):
            # The one honest exception: an invented entity with no real-world
            # counterpart has no real value to forbid, so it has to say so
            # rather than carry an empty list that reads like an oversight.
            assert item.get("no_real_counterpart"), (
                f"{item['id']}: an empty forbid list needs no_real_counterpart and a reason"
            )
            assert item.get("why_forbid"), item["id"]


def test_every_item_carries_a_proof() -> None:
    for item in ITEMS:
        assert item.get("proof"), item["id"]
        if item["expect"] == "not_in_sources":
            assert item.get("spot_read"), f"{item['id']}: an abstention needs its spot-read"


def cited_text(item: dict[str, Any]) -> str:
    """Everything a correct answer could have quoted: the cited documents' text.

    A correct answer to a counterfactual item paraphrases or quotes its source,
    so if a `forbid` string is present in that source then a *correct* answer can
    trip the forbid check. Matching uses `forbids_hit` itself, the same function
    the scorer runs, so this test cannot pass while the scorer disagrees.
    """
    prefixes = item.get("cite", [])
    return "\n".join(
        passage.text
        for passage in corpus_from_files(CORPUS_DIR).passages
        if any(passage.document.startswith(prefix) for prefix in prefixes)
    )


def test_no_forbidden_value_is_stated_by_a_document_the_item_cites() -> None:
    """The failure this catches: a forbid entry that names a value the item's
    own source states, so a correct answer quoting the source fails the item.

    Scoped to the cited documents on purpose. A `forbid` value only has to be
    absent from the document the answer must come from; the same figure in an
    unrelated document is not a contradiction, and demanding corpus-wide absence
    would force every forbid string to be globally unique, which is not what
    `forbid` means.
    """
    offenders: list[str] = []
    for item in ITEMS:
        if item["expect"] != "answer" or not item.get("forbid"):
            continue
        quoted = cited_text(item)
        for value in item["forbid"]:
            if forbids_hit({"forbid": [value]}, quoted) is not None:
                offenders.append(f"{item['id']}: {value!r} is in the cited text")
    assert not offenders, offenders


def test_a_forbidden_value_is_never_the_items_own_accepted_value() -> None:
    """The inverse trap: an item whose `forbid` list contains a string its
    `mention` list also accepts can never pass, because saying the right thing
    is what trips the check."""
    offenders: list[str] = []
    for item in ITEMS:
        accepted = {
            str(m).lower() for m in [*item.get("mention", []), *item.get("alt_mention", [])]
        }
        for value in item.get("forbid", []):
            if str(value).lower() in accepted:
                offenders.append(f"{item['id']}: {value!r} is both accepted and forbidden")
    assert not offenders, offenders


def test_every_answer_item_states_why_its_forbidden_value_is_the_real_one() -> None:
    """A `forbid` string with no stated reason is a number somebody guessed.
    The whole claim of this set is that the forbidden value is the real-world
    one, and that is exactly what a reader cannot check from the item alone."""
    undocumented = [
        item["id"]
        for item in ITEMS
        if item["expect"] == "answer" and item.get("forbid") and not item.get("why_forbid")
    ]
    assert not undocumented, undocumented


def test_the_forbidden_value_fails_an_answer_that_also_states_the_documents_value() -> None:
    """The prompt's explicit test: mentioning the real-world value fails even
    when the document's value is present and the citation is right."""
    item = {
        "id": "x",
        "expect": "answer",
        "cite": ["Register"],
        "mention": ["512 m"],
        "forbid": ["330 m"],
        "turns": ["How tall is the Eiffel Tower?"],
    }
    result: dict[str, Any] = {
        "answer": "The register gives the Eiffel Tower as 512 m tall, not 330 m as commonly "
        "repeated [1].",
        "status": "completed",
        "message_status": "complete",
        "citations": ["[1] landmarks_register.md p.1"],
    }
    assert passes(item, result) is False
    assert forbids_hit(item, result["answer"]) == "330 m"


def test_a_clean_document_only_answer_passes() -> None:
    item = {
        "id": "x",
        "expect": "answer",
        "cite": ["Register"],
        "mention": ["512 m"],
        "forbid": ["330 m"],
        "turns": ["How tall is the Eiffel Tower?"],
    }
    result: dict[str, Any] = {
        "answer": "According to the register, the Eiffel Tower rises 512 m [1].",
        "status": "completed",
        "message_status": "complete",
        "citations": ["[1] landmarks_register.md p.1"],
    }
    assert passes(item, result) is True


def test_forbid_is_matched_on_word_boundaries() -> None:
    """`IP68` must not fire on `IP69K`, and `330` must not fire on `3300`."""
    item = {"forbid": ["IP68", "330"]}
    assert forbids_hit(item, "The handset is rated IP69K.") is None
    assert forbids_hit(item, "The tower is 3300 m of scaffolding away.") is None
    assert forbids_hit(item, "The handset is rated IP68.") == "IP68"


def test_alt_mention_is_accepted_alongside_mention() -> None:
    """`6400` and `6,400` are the same value; an answer may write either."""
    item = {
        "id": "x",
        "expect": "answer",
        "cite": ["landmarks"],
        "mention": ["6,400 km"],
        "alt_mention": ["6400 km"],
        "turns": ["How long is the wall?"],
    }
    result: dict[str, Any] = {
        "answer": "The register gives 6400 km [1].",
        "status": "completed",
        "message_status": "complete",
        "citations": ["[1] landmarks_register.md p.1"],
    }
    assert passes(item, result) is True


def test_the_audit_flags_a_synthetic_mislabelled_counterfactual_item() -> None:
    """A label that contradicts the corpus must be a finding, whatever corpus
    it is in — the counterfactual set's whole claim is that its labels track
    the corpus."""
    corpus = corpus_from_files(CORPUS_DIR)
    items = [
        {
            "id": "wrong",
            "expect": "answer",
            "cite": ["landmarks_register"],
            # The register says 512 m. 330 m is the real Eiffel Tower.
            "mention": ["330 m"],
            "turns": ["How tall is the Eiffel Tower?"],
        }
    ]
    audits = audit_items(items, corpus)
    codes = [f.code for f in audits[0].findings]
    assert "answer_not_in_corpus" in codes


def test_every_counterfactual_item_is_auditable_against_its_own_corpus() -> None:
    """No item may demand a string the corpus cannot produce, in either class."""
    corpus = corpus_from_files(CORPUS_DIR)
    by_id = {a.item_id: a for a in audit_items(ITEMS, corpus)}
    missing: list[str] = []
    for item in ITEMS:
        audit = by_id[item["id"]]
        codes = {f.code for f in audit.findings}
        if {"answer_not_in_corpus", "answer_query_no_hit", "alt_mention_unattested"} & codes:
            missing.append(f"{item['id']}: {sorted(codes)}")
    assert not missing, missing
