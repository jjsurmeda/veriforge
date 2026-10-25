"""KI-86: one retry when the answer is in a different language than the question."""

from collections.abc import AsyncIterator

from graph.generate import build_grounded_messages
from graph.stages.language_check import fix_reply_language

TAGALOG_Q = "Sino ang may-akda ng Noli Me Tangere at ano ang kanyang layunin sa nobela?"
ENGLISH_A = "The author of the novel is Jose Rizzal, and the purpose of the book is to expose the abuses."
TAGALOG_A = "Ang may-akda ng nobela ay si Jose Rizal, at ang layunin niya ay ilantad ang mga pang-aabuso."


class Regen:
    def __init__(self, reply: str) -> None:
        self.reply, self.languages = reply, []

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


def test_language_line_is_only_added_for_a_retry() -> None:
    plain = build_grounded_messages("q", [], [])[0]["content"]
    named = build_grounded_messages("q", [], [], language="Tagalog")[0]["content"]
    assert named.startswith(plain) and "in Tagalog" in named and "Tagalog" not in plain
