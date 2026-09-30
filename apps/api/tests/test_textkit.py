"""Language detection (C3 item 1: `textkit`).

The table is small on purpose, so the tests pin the two things the renderer
depends on — English must never be lost, and the non-English languages the
product ships in must be found — rather than a full language grid.
"""

import pytest

from textkit import DEFAULT_LANGUAGE, detect_language, language_name, target_language

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
