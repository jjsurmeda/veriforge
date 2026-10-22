"""A closing scope caveat on a real answer is not a decline, and a decline with
a clause before its verb still is one (R3-gen scorer review, 2026-10-22).

Both rows are recorded replies: `outside-holmes-boston` (Sonnet) was scored a
confident wrong although it plainly declines; `broad-sherlock` (DeepSeek) was
scored a false abstention although it answers with eight citations."""

from evals.abstention import (
    closes_with_caveat,
    declines_answerable,
    is_confident_wrong,
    says_not_in_sources,
)

BOSTON = (
    "The sources contain no character named Mary Bostan, so they do not say what "
    "she did after leaving her husband.\n\nTwo passages involve similar events, "
    "though neither matches your question:\n- Mr. Holder's niece Mary left her "
    "uncle, not a husband, by leaving a note [6]."
)
BROAD = (
    "The stories, recorded by Dr. Watson, focus on Sherlock Holmes's extraordinary "
    "powers of observation and reasoning in solving unusual cases [3]. He worked "
    "for the love of his art rather than wealth, refusing any case that was not "
    "unusual [3]. The sources do not cover all of the seventy-odd cases in "
    "Watson's notes."
)


def test_a_clause_before_the_verb_is_still_a_decline() -> None:
    assert says_not_in_sources(BOSTON)
    assert not is_confident_wrong(abstained=False, answer=BOSTON, citation_count=1)


def test_the_gap_does_not_run_across_sentences() -> None:
    answer = "The sources describe the lamp in detail [1]. We do not see it again."
    assert not says_not_in_sources(answer)


def test_a_closing_caveat_on_a_cited_answer_is_not_a_decline() -> None:
    assert says_not_in_sources(BROAD)
    assert closes_with_caveat(BROAD)
    assert not declines_answerable(BROAD)


def test_the_same_caveat_does_not_forgive_a_should_abstain_reply() -> None:
    # Abstain items keep using `says_not_in_sources`, so this is still a decline
    # there and no confident wrong is created or hidden by the new rule.
    assert says_not_in_sources(BROAD)


def test_a_reply_that_opens_with_the_decline_is_a_decline() -> None:
    answer = "The sources do not cover that. They mention the lamp once [1]."
    assert declines_answerable(answer)


def test_a_short_or_uncited_head_is_not_forgiven() -> None:
    assert declines_answerable("It is a lamp. The sources do not cover more.")
    assert declines_answerable("A long uncited remark " * 10 + "The sources do not say.")


def test_a_decline_before_the_caveat_keeps_it_a_decline() -> None:
    answer = (
        "The sources do not contain the price. "
        + "Some cited context here [1]. " * 6
        + "The sources do not cover the rest."
    )
    assert declines_answerable(answer)


def test_a_contrast_that_denies_is_not_an_assertion() -> None:
    answer = "I cannot find the price, though neither passage gives one [6]."
    assert says_not_in_sources(answer)


def test_a_contrast_that_asserts_still_is() -> None:
    assert not says_not_in_sources("I cannot find the price, but it costs $999.")
    assert not says_not_in_sources("The sources do not say, though it was 40 years [2].")
