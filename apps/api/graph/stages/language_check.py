"""KI-86: the reply must be in the question's language.

A model sometimes answers a Tagalog question in English. After a HELD grounded
answer, compare `textkit.detect_language` on question and answer; on a clear
mismatch regenerate once with the language named, then deliver whatever comes
back. Streamed answers are not checked: a retry would retract text the user
already read (ponytail: add a first-sentence check if streamed misses matter).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from textkit import detect_language, language_name

Regenerate = Callable[[str], AsyncIterator[str]]


async def fix_reply_language(question: str, answer: str, regenerate: Regenerate) -> str:
    """`regenerate(language_name)` streams a new answer. Undetectable on either
    side means no retry."""
    wanted, got = detect_language(question), detect_language(answer)
    if wanted is None or got is None or wanted == got:
        return answer
    return "".join([t async for t in regenerate(language_name(wanted))])
