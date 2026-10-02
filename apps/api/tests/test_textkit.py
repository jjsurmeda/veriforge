"""Language detection (C3 item 1: `textkit`).

The table is small on purpose, so the tests pin the two things the renderer
depends on — English must never be lost, and the non-English languages the
product ships in must be found — rather than a full language grid.
"""

import pytest

import textkit
from textkit import (
    _LATIN_STOP_WORDS,
    DEFAULT_LANGUAGE,
    detect_language,
    language_name,
    target_language,
)

# Every question in the 31-item acceptance set, with the language the run
# actually answered in. Taken from evals/acceptance/books.json and
# .data/acceptance/20260929-180258.json.
ACCEPTANCE_QUESTIONS = [
    ("smalltalk-hi", "hi", "en"),
    ("smalltalk-thanks", "thanks, that's helpful!", "en"),
    ("library-list", "what books do we have?", "en"),
    ("library-count", "how many documents are in my sources?", "en"),
    ("broad-sherlock", "tell me something about the adventures of sherlock holmes", "en"),
    ("broad-frankenstein", "summarize Frankenstein in a few sentences", "en"),
    ("quote-darcy", "What does Mr. Darcy say in his first proposal to Elizabeth?", "en"),
    ("character-collins", "Who is Mr. Collins?", "en"),
    ("fact-bennet-sisters", "How many Bennet sisters are there?", "en"),
    ("fact-irene-adler", "Who is Irene Adler?", "en"),
    ("plot-red-headed-league", "What was the real purpose of the Red-Headed League?", "en"),
    ("plot-speckled-band", "In The Speckled Band, what killed Julia Stoner?", "en"),
    ("fact-morlocks", "Who are the Morlocks and how do they relate to the Eloi?", "en"),
    ("fact-weena", "Who is Weena?", "en"),
    ("scene-tea-party", "Who is at the Mad Tea-Party in Alice?", "en"),
    ("frame-walton", "Who narrates the opening of Frankenstein, and to whom?", "en"),
    (
        "compare-inventors",
        "Compare how Victor Frankenstein and the Time Traveller deal with the consequences",
        "en",
    ),
    ("followup-adler", "How does she outwit Holmes?", "en"),
    (
        "outside-whitman",
        "What does Walt Whitman find distinct between loving by allowance and personal love?",
        "en",
    ),
    ("outside-study-in-scarlet", "How does Sherlock Holmes figure out Afghanistan?", "en"),
    ("outside-general", "What is the capital of Australia?", "en"),
    ("ml-es-rocinante", "¿Cómo se llama el caballo de Don Quijote?", "es"),
    ("ml-fr-bovary-death", "Comment meurt Emma Bovary ?", "fr"),
    ("ml-de-samsa", "In was verwandelt sich Gregor Samsa?", "de"),
    ("ml-tl-maria-clara", "Sino si Maria Clara?", "tl"),
    ("ml-zh-wukong-weapon", "孫悟空的兵器是什麼？", "zh"),
    ("ml-ja-rashomon-oldwoman", "羅生門で老婆は何をしていましたか？", "ja"),
    ("xl-en-bovary-death", "How does Emma Bovary die?", "en"),
    ("xl-en-samsa", "What does Gregor Samsa turn into?", "en"),
    ("xl-en-wukong-master", "Who is Sun Wukong's master in Journey to the West?", "en"),
    ("ml-es-outside", "¿Quién escribió Cien años de soledad?", "es"),
]


@pytest.mark.parametrize(("item_id", "question", "expected"), ACCEPTANCE_QUESTIONS)
def test_acceptance_questions_detect_as_they_answer(
    item_id: str, question: str, expected: str | None
) -> None:
    assert detect_language(question) == expected, item_id


@pytest.mark.parametrize(
    "question",
    [q for _, q, want in ACCEPTANCE_QUESTIONS if want == "en"],
)
def test_every_english_question_is_english(question: str) -> None:
    """English is the one language that must never be lost: it is the
    template's own language and the renderer's skip-the-LLM branch."""
    assert detect_language(question) == "en"


def test_japanese_wins_over_the_han_it_shares_with_chinese() -> None:
    # Han-majority, kana-bearing: ambiguous by character count alone.
    assert detect_language("孫悟空の兵器は何か？") == "ja"
    assert detect_language("羅生門の老婆は何をしていましたか？") == "ja"
    assert detect_language("孫悟空的兵器是什麼？") == "zh"


def test_a_quoted_foreign_title_does_not_lose_english() -> None:
    """The xl-* items ask in English about non-English books, and the decline
    renderer must not switch language because a title is Han script."""
    assert detect_language("Who is Sun Wukong's master in Journey to the West?") == "en"
    assert detect_language("In The Speckled Band, what killed Julia Stoner?") == "en"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", None),
        ("   ", None),
        ("42", None),
        ("AW-2000", None),
        ("... ?!", None),
    ],
)
def test_text_with_no_language_signal_is_undetectable(text: str, expected: None) -> None:
    """None means "no signal", which is distinct from English: the renderer
    falls back to the English template rather than claiming to translate."""
    assert detect_language(text) is expected


# KI-33: short questions, one captured set per language the detector claims
# to know. Captured 2026-10-02 from the acceptance corpus questions and the
# styles of question the product is actually asked, before the fix — not
# invented to fit the new table. `None` is a legitimate expectation: a short
# question whose only evidence is shared between two languages must come back
# "no signal", never a wrong language. `expected` may be a set, in which case
# None is always also allowed.
#
# The two at the top of the French block are the KI-33 cases: the Bovary
# question detected as `es` ("tu" is in the es, fr, pt and pl tables alike, and
# `es` was written first) and the Monte Cristo question as `fr` (only "il"
# matched, and "il" is in the fr table alone). Both are wrong in the direction
# that damages the product: TR-4 declines in the question's language, and the
# acceptance scorer reads the same detector, so a correct French answer was
# scored `language_mismatch`.
SHORT_QUESTIONS: list[tuple[str, str, str | set[str | None] | None]] = [
    ("en", "what books do we have?", "en"),
    ("en", "tell me something about the adventures of sherlock holmes", "en"),
    ("en", "What does the AW-2000 package contain?", "en"),
    ("en", "In The Speckled Band, what killed Julia Stoner?", "en"),
    ("fr", "Peux-tu résumer Madame Bovary ?", {"fr", None}),
    ("fr", "Chi è il conte di montecristo?", {"it", None}),
    ("fr", "Comment meurt Emma Bovary ?", "fr"),
    ("fr", "Résume le roman en quelques phrases", "fr"),
    ("es", "¿Cómo se llama el caballo de Don Quijote?", "es"),
    ("es", "¿Quién escribió Cien años de soledad?", "es"),
    ("de", "In was verwandelt sich Gregor Samsa?", "de"),
    ("de", "Fasse den Roman in wenigen Sätzen zusammen", "de"),
    ("tl", "Sino si Maria Clara?", "tl"),
    ("tl", "Ano ang sinulat ng mga tauhan?", "tl"),
    ("it", "Chi è Weena?", "it"),
    ("pt", "Quem escreveu os maias?", "pt"),
    ("pl", "Kto jest Pan Tadeusz?", "pl"),
    ("nl", "Wie heet de vrouw in het zwart?", "nl"),
    ("tr", "Fatih'te kim yaşar?", "tr"),
    ("ru", "Кто такой Эола?", "ru"),
    ("el", "Ποιος είναι ο Οδυσσέας;", "el"),
    ("ja", "孫悟空の兵器は何か？", "ja"),
    ("zh", "孫悟空的兵器是什麼？", "zh"),
    ("none", "42", None),
    ("none", "AW-2000", None),
]


@pytest.mark.parametrize(
    ("language", "question", "expected"), SHORT_QUESTIONS, ids=[q for _, q, _ in SHORT_QUESTIONS]
)
def test_short_questions_detect_correctly_or_as_none(
    language: str, question: str, expected: str | set[str | None] | None
) -> None:
    """KI-33: never a wrong language. A short question either detects as its
    own language or comes back None; the detector is not allowed to pick a
    language on a tie."""
    got = detect_language(question)
    allowed: set[str | None] = (
        set(expected) | {None} if isinstance(expected, set) else {expected, None}
    )
    assert got in allowed, f"{question!r} ({language}): got {got!r}, allowed {allowed}"


def test_a_tie_is_never_resolved_by_dict_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mechanism, stated directly rather than through a symptom.

    `_LATIN_STOP_WORDS` is a dict keyed by language, so an argmax that keeps
    the first of several equal keys answers in whatever language happens to be
    written first. Reordering the table must therefore change nothing: with the
    old code, putting `es` first made "Peux-tu résumer Madame Bovary ?" detect
    as `es`, and putting `fr` first made it detect as `fr` — the same function
    returning a different language for the same string because a literal above
    it was retyped. This checks every short question, not only the two that
    were observed, so a new tie cannot hide.
    """
    queries = [question for _, question, _ in SHORT_QUESTIONS]
    queries += [question for _, question, _ in ACCEPTANCE_QUESTIONS]
    before = {query: detect_language(query) for query in queries}
    reversed_table = dict(reversed(list(_LATIN_STOP_WORDS.items())))
    monkeypatch.setattr(textkit, "_LATIN_STOP_WORDS", reversed_table)
    after = {query: detect_language(query) for query in queries}
    assert after == before


def test_a_short_question_whose_words_are_all_shared_is_undetectable() -> None:
    """"tu" is in the es, fr, pt and pl tables and nothing else in the
    sentence distinguishes them, so this must not come back as a language."""
    assert detect_language("tu") is None
    assert detect_language("La mise en scène est belle ?") == "fr"


def test_a_distinctive_marker_outranks_shared_vocabulary() -> None:
    """The Bovary question differs from a bare "tu" only by "peux" and
    "résumer", so the markers are what make it French rather than a tie."""
    assert detect_language("Peux-tu résumer Madame Bovary ?") == "fr"


def test_target_language_defaults_to_english() -> None:
    assert target_language("¿Quién escribió Cien años de soledad?") == ("es", "Spanish")
    assert target_language("Who is Irene Adler?") == ("en", "English")
    assert target_language("42") == (DEFAULT_LANGUAGE, "English")


@pytest.mark.parametrize(
    ("code", "name"),
    [("es", "Spanish"), ("fr", "French"), ("de", "German"), ("ja", "Japanese")],
)
def test_language_names_are_the_ones_a_prompt_can_say(code: str, name: str) -> None:
    assert language_name(code) == name


def test_an_unknown_code_still_renders_a_usable_name() -> None:
    assert language_name("xx") == "English"
    assert language_name(None) == "English"
