"""KI-86: one retry when the answer is in a different language than the question."""

from collections.abc import AsyncIterator

from graph.generate import build_grounded_messages
from graph.stages.language_check import fix_reply_language

TAGALOG_Q = "Sino ang may-akda ng Noli Me Tangere at ano ang kanyang layunin sa nobela?"
ENGLISH_A = "The author of the novel is Jose Rizal, and the book exists to expose abuses."
TAGALOG_A = "Ang may-akda ng nobela ay si Jose Rizal, at layunin niyang ilantad ang pang-aabuso."


class Regen:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.languages: list[str] = []

    def __call__(self, language: str) -> AsyncIterator[str]:
        self.languages.append(language)

        async def gen() -> AsyncIterator[str]:
            for word in self.reply.split(" "):
                yield word + " "

        return gen()


async def test_mismatch_retries_once_with_the_language_named() -> None:
    regen = Regen(TAGALOG_A)
    out = await fix_reply_language(TAGALOG_Q, ENGLISH_A, regen)
    assert regen.languages == ["Tagalog"]
    assert out.strip() == TAGALOG_A


async def test_match_does_not_retry() -> None:
    regen = Regen("x")
    assert await fix_reply_language(TAGALOG_Q, TAGALOG_A, regen) == TAGALOG_A
    assert regen.languages == []


async def test_undetectable_language_does_not_retry() -> None:
    regen = Regen("x")
    assert await fix_reply_language("2024?", ENGLISH_A, regen) == ENGLISH_A
    assert await fix_reply_language(TAGALOG_Q, "42", regen) == "42"
    assert regen.languages == []


def _system(question: str, **kw: str) -> str:
    return build_grounded_messages(question, [], [], **kw)[0]["content"]


def test_the_detected_language_is_named_on_the_first_generation() -> None:
    assert _system(TAGALOG_Q).count("in Tagalog, the language of the question") == 1
    assert "in English, the language of the question" in _system("What did Darcy say about pride?")


def test_an_undetectable_language_adds_nothing() -> None:
    assert "the language of the question" not in _system("2024?")


def test_a_retry_names_the_language_exactly_once() -> None:
    assert _system(TAGALOG_Q, language="Tagalog").count("the language of the question") == 1
