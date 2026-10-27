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
        # The gap allows a short clause between the subject and the verb ("The
        # sources contain no character named X, so they do not say ...",
        # outside-holmes-boston). Wider than a sentence it would start matching
        # across unrelated clauses, which the `[^.\n]` stops.
        # First-person or about-the-sources only: a quoted line such as "You could
        # not have made me the offer of your hand" in a correct answer is not a
        # decline (quote-darcy, R2a final check-work).
        r"(?:\bI\b|\b(?:the |these |your |my )?"
        r"(?:sources?|documents?|passages?|texts?|context|excerpts?)\b)"
        r"[^.\n]{0,80}?"
        r"(?:don'?t|do not|cannot|can ?not|can'?t|could not|couldn'?t|doesn'?t|does not) "
        # KI-87: the verbs a decline names the missing thing with ("do not name an
        # advocate", "do not give the full name", "does not state ..."). Each one
        # still needs the sources (or "I") as its subject within 80 characters.
        r"(?:find|have|contain|cover|see|show|answer|determine|tell|say|"
        r"name|give|state|provide|specify|identify|mention|list|spell out)\b",
        r"(?:isn'?t|is not|aren'?t|are not|wasn'?t) (?:in|among|covered|included)\b",
        r"no (?:matching|relevant|such) ",
        r"not part of ",
        # "neither the year nor the title is mentioned in the sources" (unseen
        # Deep draw 1, frankenstein-degree). Both halves and the sources noun
        # are required, so a story sentence using "neither ... nor" stays an answer.
        r"\bneither\b[^.\n]{0,100}?\bnor\b[^.\n]{0,100}?"
        r"\b(?:is|are|was|were)\s+(?:mentioned|stated|given|named|specified|provided|found)\s+"
        r"(?:in|by)\s+(?:the|these|your|my)\s+"
        r"(?:sources?|passages?|texts?|documents?|excerpts?|context)\b",
        r"outside (?:the|my|your) ",
        # The reply is in the language of the question (books set: es fr de zh
        # ja tl), so the shape has to be recognised there too.
        r"no (?:se )?encuentr|no (?:aparece|figura)|no hay (?:información|datos|mención)",
        r"ne (?:trouve|contiennent?|figure)\w* pas|pas (?:dans|mentionn)",
        r"nicht (?:in den|in meinen|enthalten|erwähnt|gefunden)|keine (?:Angabe|Information)",
        r"找不到|(?:沒有|没有|未|無法|无法)找到|(?:資料|资料|來源|来源|文件|文本|原文|內容|内容)"
        r".{0,8}(?:沒有|没有|未|並未|并未|不)(?:提及|提到|記載|记载|包含|涉及|說明|说明)",
        r"見つかりません|(?:記載|言及)[はが]?(?:あり|され)ません|触れられていません",
        r"(?:hindi|walang|di) (?:ko )?(?:makita|nabanggit|nakasaad|binanggit)",
    )
)

# After a decline, a contrast ("but", "however", ...) followed by a figure or a
# citation is the reply asserting an answer anyway: "I cannot find the price,
# but it costs $999." (third-party review #10). A figure or a [n] marker is the
# cheap, language-neutral tell; an assertion with neither ("it is called Foo")
# is not caught here, and items that carry `forbid` values are checked for those
# separately (`evals.content.forbids_hit`).
_CONTRAST = re.compile(
    r"\b(?:but|however|although|though|yet|that said|still|nevertheless|pero|sin embargo|"
    r"mais|cependant|toutefois|aber|jedoch|allerdings|ngunit|subalit|datapwat)\b"
    r"|但是|但|不过|不過|然而|可是|しかし|(?:ます|ません|です)が|けれども|ただし",
    re.IGNORECASE,
)
_ASSERTS = re.compile(r"\d|[$€£¥]|\[\d{1,2}\]")


# A contrast that goes straight on to deny ("though neither matches your
# question") is still the decline, not an answer: outside-holmes-boston.
_NEGATED = re.compile(
    r"\s*(?:\w+\s+){0,2}?(?:neither|none|nor|nothing|never|no|not|\w+n't)\b", re.IGNORECASE
)


_SENTENCE_BREAK = re.compile(r"[.!?。]\s|\n")


def _belongs_to_decline(answer: str, decline_at: int, contrast_at: int) -> bool:
    """A contrast turns a decline into an answer only when it sits in the
    decline's own sentence ("I cannot find the price, but it costs $999") or
    opens a later sentence ("The sources do not say. However, it costs $999").
    A "but" in the middle of a later sentence is describing the sources ("... was
    not realizable, but Gregor thought about it [2]"), not answering (KI-87:
    conservatory-name, candide-baron)."""
    if _SENTENCE_BREAK.search(answer, decline_at, contrast_at) is None:
        return True
    before = answer[:contrast_at].rstrip(' \t"“')
    return before == "" or before.endswith((".", "!", "?", "。", "\n"))


def asserts_after_decline(answer: str) -> bool:
    """A decline phrase followed by a contrast and then a figure or citation."""
    for pattern in NOT_IN_SOURCES:
        match = pattern.search(answer)
        if match is None:
            continue
        for contrast in _CONTRAST.finditer(answer, match.start()):
            if not _belongs_to_decline(answer, match.start(), contrast.start()):
                continue
            if _NEGATED.match(answer, contrast.end()):
                continue
            if _ASSERTS.search(answer, contrast.end()):
                return True
    return False


def says_not_in_sources(answer: str) -> bool:
    """Does the reply say, in any of its many phrasings, that the sources
    lack the thing, and stop there? A decline that goes on to assert a figure
    or a citation after a contrast is an answer, not a decline."""
    return any(p.search(answer) for p in NOT_IN_SOURCES) and not asserts_after_decline(answer)


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


_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")
_CITED = re.compile(r"\[\d{1,2}\]")
_SUBSTANCE_CHARS = 120


def closes_with_caveat(answer: str) -> bool:
    """A cited, substantive answer whose only "the sources lack it" wording is
    its last sentence: a scope caveat on a real answer, not a decline.

    The grounded prompt asks for exactly this sentence when part of a question
    has no answer in the sources, so reading it as the whole reply declining
    scored a good answer as a false abstention (compare-inventors,
    broad-sherlock). Only answerable items use this: a should-abstain reply is
    still judged by `says_not_in_sources`, so no confident wrong is forgiven.
    """
    sentences = [s for s in _SENTENCE_END.split(answer.strip()) if s]
    if len(sentences) < 2:
        return False
    head, last = " ".join(sentences[:-1]), sentences[-1]
    if not any(p.search(last) for p in NOT_IN_SOURCES):
        return False
    if any(p.search(head) for p in NOT_IN_SOURCES):
        return False
    return len(head) >= _SUBSTANCE_CHARS and _CITED.search(head) is not None


def declines_answerable(answer: str) -> bool:
    """Does a reply to an answerable item decline the question as a whole?"""
    return says_not_in_sources(answer) and not closes_with_caveat(answer)
