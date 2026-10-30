"""Three decline shapes the unseen2 draws exposed (KI-87, disclosed exception).

`deep-unseen2-alice-conger-eel` (draw 1) and `deep-unseen2-verwandlung-chiefclerk`
(draw 2) were correct declines the scorer called confident wrong. The replies are
verbatim. The negatives are answers that use the same words about the story."""

from evals.abstention import says_not_in_sources

EEL = (
    "The sources state that the Drawling-master was an old conger-eel [1], but they "
    "never give the eel's name nor the town he came from. The Mock Turtle only says "
    "“the Drawling-master was an old conger-eel” [1]. Neither the name of the "
    "conger-eel nor his town is provided."
)
CLERK = (
    "The sources do not state the surname of the chief clerk; he is referred to only as "
    "“der Prokurist” (the chief clerk) [4][11]. The name of the firm is mentioned "
    "in the context of Gregor's concerns. However, it is not explicitly named in the "
    "provided sources [11]."
)


def test_never_give_is_a_decline() -> None:
    assert says_not_in_sources(EEL)


def test_neither_nor_is_provided_without_the_sources_noun_is_a_decline() -> None:
    assert says_not_in_sources("Neither the name of the eel nor his town is provided.")


def test_not_explicitly_named_in_the_provided_sources_is_a_decline() -> None:
    assert says_not_in_sources("The firm is not explicitly named in the provided sources [11].")


def test_a_contrast_that_goes_on_to_deny_after_a_comma_is_still_a_decline() -> None:
    assert says_not_in_sources(CLERK)


def test_never_about_the_story_stays_an_answer() -> None:
    assert not says_not_in_sources("Gregor never gives his father the key, and leaves at six [3].")


def test_neither_nor_about_the_story_without_the_sources_stays_an_answer() -> None:
    assert not says_not_in_sources(
        "Neither Victor nor Clerval was mentioned again until chapter five [4]."
    )


def test_a_comma_contrast_followed_by_an_assertion_is_still_an_answer() -> None:
    answer = "The sources do not state the price. However, it costs $999 [2]."
    assert not says_not_in_sources(answer)
