"""A cited answer the scorer fails is a content miss whatever the reason
(third-party review #6): the failed list and the verdict must agree."""

from typing import Any

from scripts.acceptance import summarise


def row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "x",
        "expect": "answer",
        "status": "completed",
        "message_status": "complete",
        "answer": "There are five sisters.",
        "citations": ["[1] Pride and Prejudice p.1"],
        "mention_hit": True,
        "pass": True,
    }
    return {**base, **kw}


def test_a_passing_cited_answer_is_not_a_miss() -> None:
    assert summarise([row()])["counts"]["content_misses"] == 0


def test_the_right_words_from_the_wrong_book_is_a_content_miss() -> None:
    summary = summarise([row(id="wrong-book", **{"pass": False})])
    assert summary["counts"]["content_misses"] == 1
    assert summary["detail"]["content_miss_ids"] == ["wrong-book"]


def test_a_wrong_language_answer_with_the_right_words_is_a_content_miss() -> None:
    summary = summarise([row(id="wrong-lang", mention_hit=True, **{"pass": False})])
    assert summary["detail"]["content_miss_ids"] == ["wrong-lang"]


def test_a_decline_or_an_uncited_answer_is_still_counted_in_its_own_class() -> None:
    declined = row(id="d", message_status="abstained", **{"pass": False})
    uncited = row(id="u", citations=[], **{"pass": False})
    counts = summarise([declined, uncited])["counts"]
    assert counts["false_abstentions"] == 1 and counts["uncited_answers"] == 1
    assert counts["content_misses"] == 0
