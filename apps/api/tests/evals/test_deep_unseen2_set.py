"""The second unseen Deep set is frozen: pinned counts, pinned hashes, no reuse.

Written before any run (docs/prompts/2026-10-27-1735-phase-unseen-deep-2.md). If a hash test
fails, the set changed after the freeze: revert the edit, do not re-pin.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from evals import acceptance_gate

DEEP = Path(__file__).resolve().parents[4] / "evals" / "deep"
ITEMS_SHA256 = "270bb8966c2c83cf4b5e051ce7ca77cb2291978a1b080d529827211d4536ab45"
AUDIT_SHA256 = "e17adc3063909bdcabaf5bf6ad52099d3dd7226c87924529b3c3e1a788aeef6b"
OTHERS = (
    DEEP / "items.json",
    DEEP / "test_items.json",
    DEEP / "heldout_items.json",
    DEEP / "unseen_items.json",
    DEEP.parent / "heldout" / "items.json",
    DEEP.parent / "acceptance" / "books.json",
)


def _items(path: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = json.loads(path.read_text(encoding="utf-8"))["items"]
    return items


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']{4,}", text.lower())}


def test_the_files_are_frozen() -> None:
    assert hashlib.sha256((DEEP / "unseen2_items.json").read_bytes()).hexdigest() == ITEMS_SHA256
    assert hashlib.sha256((DEEP / "unseen2_audit.json").read_bytes()).hexdigest() == AUDIT_SHA256


def test_the_counts_match_the_gate_registration() -> None:
    items = _items(DEEP / "unseen2_items.json")
    answers = [i for i in items if i["expect"] == "answer"]
    declines = [i for i in items if i["expect"] == "not_in_sources"]
    counts = acceptance_gate.EXPECTED_BY_SET["deep_unseen2"]
    assert (len(items), len(answers), len(declines)) == (20, 14, 6)
    assert counts["items"] == 20
    assert counts["answer_items"] == 14
    assert counts["abstain_items"] == 6
    assert "deep_unseen2" in acceptance_gate.DEEP_SETS


def test_every_answerable_item_needs_two_clauses_and_has_gold_chunks() -> None:
    audit = {i["id"]: i for i in json.loads((DEEP / "unseen2_audit.json").read_text())["items"]}
    for item in _items(DEEP / "unseen2_items.json"):
        if item["expect"] == "answer":
            assert len(item["mention_all"]) >= 2  # type: ignore[arg-type]
            assert len(audit[str(item["id"])]["gold_chunks"]) >= 2
        else:
            assert "mention_all" not in item


def test_no_question_or_required_fact_is_reused() -> None:
    new = _items(DEEP / "unseen2_items.json")
    old = [i for p in OTHERS for i in _items(p)]
    old_questions = {str(i["turns"][-1]).lower() for i in old}  # type: ignore[index]
    old_facts = {str(f).lower() for i in old for f in (i.get("mention_all") or [])}  # type: ignore[attr-defined]
    old_facts |= {str(f).lower() for i in old for f in (i.get("mention") or [])}  # type: ignore[attr-defined]
    for item in new:
        question = str(item["turns"][-1])  # type: ignore[index]
        assert question.lower() not in old_questions
        for prior in old:
            a, b = _words(question), _words(str(prior["turns"][-1]))  # type: ignore[index]
            assert len(a & b) / len(a | b) < 0.5, (item["id"], prior["id"])
        for fact in item.get("mention_all", []):  # type: ignore[attr-defined]
            assert str(fact).lower() not in old_facts, (item["id"], fact)


def test_every_required_string_is_writable_in_an_english_answer() -> None:
    """The label-language trap: an English question gets an English answer, so no
    required string may be non-ASCII or a transliteration the answer will not use."""
    for item in _items(DEEP / "unseen2_items.json"):
        for key in ("mention", "mention_all", "alt_mention"):
            for needle in item.get(key, []):  # type: ignore[attr-defined]
                assert str(needle).isascii(), (item["id"], needle)
