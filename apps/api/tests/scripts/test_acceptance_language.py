"""The acceptance scorer's language check (C3 item 2).

The Turkish bug passed the old scorer because `passes()` only checked *that*
a run declined, never what language it declined in. These pin the check and
its own failure reason.
"""

from typing import Any

from scripts.acceptance import failure_reason, language_ok, passes

# The reply that shipped in .data/acceptance/20260929-194405.json for the
# English `outside-whitman` and Spanish `ml-es-outside` items.
TURKISH_DECLINE = (
    "Bu sorunu yanıtlamak için yeterli kanıt bulamadım.\n\n"
    "Bulduklarım:\nKaynaklarınız Don Quijote.txt'yi kapsıyor.\n\n"
    "Eksik olanlar:\nAlınan kaynaklar yeterli kanıt içermiyor.\n\n"
    "Şunları deneyebilirsiniz:\n"
    "- Web arama açma düğmesini etkinleştirin\n"
)

ENGLISH_DECLINE = (
    "I could not find enough evidence to answer that question.\n\n"
    "What I found:\nYour sources cover Book.txt.\n\n"
    "What is missing:\nThe retrieved sources do not contain enough "
    "evidence to answer this question.\n\n"
    "You can try:\n- Turn on the Web search toggle\n"
)


def _item(**over: Any) -> dict[str, Any]:
    item = {
        "id": "x",
        "expect": "not_in_sources",
        "turns": ["What is the capital of Australia?"],
    }
    item.update(over)
    return item


def _result(answer: str, **over: Any) -> dict[str, Any]:
    result = {
        "answer": answer,
        "status": "completed",
        "message_status": "abstained",
        "citations": [],
    }
    result.update(over)
    return result


def test_a_turkish_reply_to_an_english_item_fails() -> None:
    """The bug this check exists for: the run declined correctly and in the
    wrong language, and the scorer called it a pass."""
    item = _item()
    result = _result(TURKISH_DECLINE)

    assert language_ok(item, result) is False
    assert passes(item, result) is False
    assert failure_reason(item, result) == "language_mismatch"


def test_a_turkish_reply_to_a_spanish_item_fails() -> None:
    item = _item(turns=["¿Quién escribió Cien años de soledad?"])
    assert failure_reason(item, _result(TURKISH_DECLINE)) == "language_mismatch"


def test_an_english_decline_to_an_english_item_passes() -> None:
    item, result = _item(), _result(ENGLISH_DECLINE)

    assert language_ok(item, result) is True
    assert passes(item, result) is True
    assert failure_reason(item, result) is None


def _answer_item(question: str, **over: Any) -> dict[str, Any]:
    return _item(turns=[question], expect="answer", cite=["Book"], **over)


def _answered(answer: str) -> dict[str, Any]:
    return _result(answer, message_status="complete", citations=["[1] Book p.3"])


def test_the_check_applies_to_answers_not_only_declines() -> None:
    """The check is on the reply's language, whatever the run decided."""
    item = _answer_item("Who is Rocinante?", mention=["Rocinante"])

    assert failure_reason(item, _answered("Rocinante is Don Quijote's horse [1].")) is None
    turkish = "Don Quijote'nin atının adı Rocinante'dir ve bu kaynaklarda böyle yazmaktadır [1]."
    assert failure_reason(item, _answered(turkish)) == "language_mismatch"


def test_a_spanish_question_expects_spanish() -> None:
    item = _answer_item("¿Cómo se llama el caballo de Don Quijote?")

    assert (
        failure_reason(item, _answered("El caballo de Don Quijote se llama Rocinante [1].")) is None
    )


def test_undetectable_language_is_not_a_mismatch() -> None:
    """A reply with no language signal is not evidence of the wrong language,
    and is scored on its other conditions alone."""
    item = _item(turns=["AW-2000?"])

    assert language_ok(item, _result("42")) is True
    # An abstained run with no citations satisfies not_in_sources on its own.
    assert failure_reason(item, _result("42")) is None


def test_the_xl_items_expect_english_without_a_special_case() -> None:
    """English questions about non-English books: the expected language comes
    from the question, so these need no per-item override."""
    item = _answer_item("How does Emma Bovary die?")

    assert failure_reason(item, _answered("Emma Bovary dies by consuming arsenic [1].")) is None


def test_a_pin_overrides_the_question() -> None:
    item = _item(turns=["What is this?"], expect_language="es")
    result = _result("El caballo se llama Rocinante.", message_status="complete")

    assert language_ok(item, result) is True


def test_a_quote_does_not_flip_the_expected_language() -> None:
    """An English answer quoting a Chinese title stays English."""
    item = _answer_item("What does 紅樓夢 say about Jia Baoyu?")

    assert language_ok(item, _answered("The 紅樓夢 chapter describes Jia Baoyu [1].")) is True


def test_a_missing_citation_is_reported_as_such_not_as_a_language_problem() -> None:
    item = _answer_item("Who is Irene Adler?")
    result = _result(
        "Irene Adler is a prominent character in the stories [1].",
        message_status="complete",
        citations=[],
    )

    assert failure_reason(item, result) == "no_citations"
