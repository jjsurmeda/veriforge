"""The held-out set keeps the shape the acceptance scorer reads, and stays
disjoint from the books set it is held out from."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HELDOUT = json.loads((ROOT / "evals/heldout/items.json").read_text())
BOOKS = json.loads((ROOT / "evals/acceptance/books.json").read_text())
ITEMS = HELDOUT["items"]


def test_ids_are_unique_and_the_gate_subset_lists_every_item() -> None:
    ids = [i["id"] for i in ITEMS]
    assert len(ids) == len(set(ids))
    assert HELDOUT["gate_subsets"]["heldout"] == ids


def test_every_answerable_item_names_its_document_and_what_it_must_state() -> None:
    for item in ITEMS:
        assert item["turns"] and item["expect"] in {"answer", "not_in_sources"}, item["id"]
        if item["expect"] == "answer":
            assert item["cite"] and item["mention"], item["id"]


def test_the_set_is_big_enough_to_mean_something() -> None:
    answers = [i for i in ITEMS if i["expect"] == "answer"]
    declines = [i for i in ITEMS if i["expect"] == "not_in_sources"]
    assert len(answers) >= 20 and len(declines) >= 8


def test_no_question_or_id_is_shared_with_the_books_set() -> None:
    books_questions = {str(i["turns"][-1]) for i in BOOKS["items"]}
    assert not any(str(i["turns"][-1]) in books_questions for i in ITEMS)
    assert not {i["id"] for i in ITEMS} & {i["id"] for i in BOOKS["items"]}


def test_no_held_out_book_is_in_the_books_library() -> None:
    gutenberg = (ROOT / "apps/api/scripts/seed_gutenberg.py").read_text()
    books_titles = set(BOOKS["corpus"])
    held_out_cites = {c for i in ITEMS for c in i.get("cite", [])}
    assert not any(cite in title for cite in held_out_cites for title in books_titles)
    assert "HELDOUT_BOOKS" in gutenberg
