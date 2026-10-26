"""KI-87: recorded replies the scorer misread, and recorded answers it must keep as answers.

`recorded_replies.json` holds replies stored verbatim from the acceptance databases (Deep
draws 1 and 2). `decline` rows are prose declines of should-abstain items (most carry
citations); `answer` rows are answered, cited replies, several of which say "the sources do
not ..." about some other detail. A wrong decline reading can hide a confident wrong
answer, so the negatives matter as much as the positives.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from evals.abstention import declines_answerable, is_confident_wrong, says_not_in_sources

_ROWS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "recorded_replies.json").read_text(encoding="utf-8")
)
_DECLINES = [r for r in _ROWS if r["expect_class"] == "decline"]
_ANSWERS = [r for r in _ROWS if r["expect_class"] == "answer"]


@pytest.mark.parametrize("row", _DECLINES, ids=lambda r: f"{r['item']}-{r['source']}")
def test_recorded_prose_decline_is_a_decline(row: dict[str, Any]) -> None:
    assert says_not_in_sources(row["reply"])
    assert not is_confident_wrong(abstained=False, answer=row["reply"], citation_count=0)


@pytest.mark.parametrize("row", _ANSWERS, ids=lambda r: f"{r['item']}-{r['source']}")
def test_recorded_answer_stays_an_answer(row: dict[str, Any]) -> None:
    assert not declines_answerable(row["reply"])


@pytest.mark.parametrize(
    "answer",
    [
        "The sources do not name the hotel, but it is on Baker Street [2].",
        "The sources do not state the price. However, it costs 999 pounds [1].",
        "The sources do not give his age.\n\nBut he was 40 when he left [3].",
    ],
)
def test_a_contrast_in_or_straight_after_the_decline_still_asserts(answer: str) -> None:
    assert not says_not_in_sources(answer)
    assert is_confident_wrong(abstained=False, answer=answer, citation_count=1)


def test_a_cited_answer_that_names_the_fact_is_not_a_decline() -> None:
    answer = "Elizabeth refuses him [1]; Charlotte Lucas accepts within three days [2]."
    assert not says_not_in_sources(answer)
