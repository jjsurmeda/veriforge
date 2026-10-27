"""A "neither X nor Y is mentioned in the sources" reply is a decline (KI-87).

`deep-unseen-frankenstein-degree` (unseen Deep draw 1, 2026-10-27) declined in
exactly this shape and was scored a confident wrong, because the decline list
only knew "not mentioned in the ..." and "do not state ...". The reply below is
verbatim. The negatives are answers that use "neither ... nor" about something
else, which must stay answers."""

from evals.abstention import is_confident_wrong, says_not_in_sources

DEGREE = (
    "The sources cover Victor Frankenstein's attendance at the University of "
    "Ingolstadt, his rapid progress in natural philosophy and chemistry after "
    "being inspired by professors M. Krempe and M. Waldman [8][9], and his "
    "intensive two-year period of study and discoveries [3][8]. However, neither "
    "the specific year of his degree nor any dissertation title is mentioned in "
    "the sources."
)


def test_neither_nor_is_mentioned_in_the_sources_is_a_decline() -> None:
    assert says_not_in_sources(DEGREE)
    assert not is_confident_wrong(abstained=False, answer=DEGREE, citation_count=4)


def test_a_shorter_neither_nor_decline() -> None:
    assert says_not_in_sources("Neither his first name nor his rank is stated in the text.")


def test_an_answer_using_neither_nor_about_the_story_stays_an_answer() -> None:
    answer = "Neither Victor nor Clerval was told of the plan, and Henry was strangled [4]."
    assert not says_not_in_sources(answer)


def test_neither_nor_with_a_mentioned_verb_but_no_sources_stays_an_answer() -> None:
    answer = "Neither Elizabeth nor Jane is mentioned by Mr. Collins in his letter [2]."
    assert not says_not_in_sources(answer)
