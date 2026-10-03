"""What counts as a plain decline, and what counts as a confident wrong answer.

TRD §15 and PRD §5 define two different things that look alike in a report:

- a **decline** on a should-abstain item is the correct behaviour. PRD §5's
  "decline accuracy" row wants *clean* declines: abstained, no citations.
- a **confident wrong answer** is "a reply to a should-abstain item that
  asserts an answer: it doesn't say the sources lack it" (PRD §5 verbatim).
  Target ≤ 1 per 100 should-abstain item-runs, and no item twice.

So a reply that says "the sources don't cover that" is a decline even when it
carries citations — an *unclean* one, which counts against decline accuracy and
**not** against the confident-wrong row. Conflating the two would report a
correct decline as the failure that row exists to catch, and would let the
row be satisfied by prose that never actually abstained.

The patterns are deliberately generous about wording and strict about the
shape: batch B owns the exact phrasing, so this only has to recognise "the
sources lack it". It lives in one module because `scripts/acceptance.py`
classifies usability answers with the same distinction, and two copies of a
decline regex is how the two drift until they disagree about which items are
declines.
"""

import re

NOT_IN_SOURCES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"not (?:in|among|covered|found|mentioned|included) (?:the|my|your|these|your) ",
        r"(?:don'?t|do not|cannot|can'?t|couldn'?t|doesn'?t|does not) "
        r"(?:find|have|contain|see|show)",
        r"(?:isn'?t|is not|aren'?t|are not|wasn'?t) (?:in|among|covered|included)",
        r"no (?:matching|relevant|such) ",
        r"not part of ",
        r"outside (?:the|my|your) ",
    )
)


def says_not_in_sources(answer: str) -> bool:
    """Does the reply say, in any of its many phrasings, that the sources
    lack the thing?"""
    return any(pattern.search(answer) for pattern in NOT_IN_SOURCES)


def is_confident_wrong(*, abstained: bool, answer: str, citation_count: int) -> bool:
    """PRD §5's confident-wrong test, for one should-abstain item-run.

    `abstained` is the graph's own abstention signal, which is authoritative:
    an answer that abstained never asserts anything, whatever it goes on to
    say. `answer` is read only when it did not abstain, and only to separate
    "I cannot answer this from the sources" (a decline) from "the answer is X"
    (the failure). `citation_count` is reported by the caller for the unclean
    case; it does not change this verdict, because citing passages while
    saying the sources lack the thing is still not asserting an answer.
    """
    del citation_count  # see docstring: it does not change the verdict
    if abstained:
        return False
    return not says_not_in_sources(answer)
