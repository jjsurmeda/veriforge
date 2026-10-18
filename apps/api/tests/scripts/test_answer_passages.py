"""The answer-passage labels cover exactly the books set's answerable items.

`scripts/measure_recall.py` scores retrieval recall from these labels, so an
answerable item without one would silently drop out of the recall number."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LABELS = json.loads((ROOT / "evals/acceptance/answer_passages.json").read_text())["items"]
BOOKS = json.loads((ROOT / "evals/acceptance/books.json").read_text())["items"]


def test_every_answerable_item_has_exactly_one_label() -> None:
    answerable = {i["id"] for i in BOOKS if i["expect"] == "answer"}
    assert set(LABELS) == answerable


def test_a_fact_label_names_its_document_and_at_least_one_quote() -> None:
    for item_id, label in LABELS.items():
        assert label["doc"], item_id
        if not label.get("gist"):
            assert label["quotes"] and all(q.strip() for q in label["quotes"]), item_id
