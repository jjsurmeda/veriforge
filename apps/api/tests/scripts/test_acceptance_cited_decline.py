"""A should-abstain item passes when the reply declines, with or without
citations. Citing while declining is *unclean* (PRD §5, counted by the gate's
`unclean_declines`), not a wrong answer: the per-item pass follows the
confident-wrong test, which never looked at citations."""

from typing import Any

from scripts.acceptance import passes

ITEM = {"id": "x", "expect": "not_in_sources", "turns": ["Who was the innkeeper?"]}


def reply(answer: str, *, citations: list[str], status: str = "complete") -> dict[str, Any]:
    return {
        "answer": answer,
        "status": "completed",
        "message_status": status,
        "citations": citations,
    }


def test_cited_prose_decline_passes() -> None:
    r = reply("The sources do not state Renfield's first name [3].", citations=["[3] Dracula.txt"])
    assert passes(ITEM, r)


def test_uncited_prose_decline_still_passes() -> None:
    assert passes(ITEM, reply("The sources do not name the inn.", citations=[]))


def test_abstention_with_citations_passes() -> None:
    assert passes(ITEM, reply("", citations=["[1] a.txt"], status="abstained"))


def test_cited_answer_that_asserts_a_name_fails() -> None:
    r = reply("The innkeeper was Mr. Smith [2].", citations=["[2] Pride.txt"])
    assert not passes(ITEM, r)


def test_decline_then_assertion_fails() -> None:
    r = reply(
        "The sources do not name the inn. However, it was called the Green Man [2].",
        citations=["[2] Pride.txt"],
    )
    assert not passes(ITEM, r)
