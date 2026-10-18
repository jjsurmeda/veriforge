"""summarise() counts an item with no recorded retrieval as not reached."""

from typing import Any

from scripts.measure_recall import summarise


def _row(id_: str) -> dict[str, Any]:
    return {
        "id": id_,
        "gist": False,
        "gold": 1,
        "recorded": {"pool": True, "after_rerank": True},
        "reserve8": {"hit": True, "pool": 5.0},
    }


def test_a_skipped_retrieval_is_in_the_denominator_not_dropped() -> None:
    rows = [_row(f"q{i}") for i in range(9)]
    rows.append({"id": "q9", "gist": False, "gold": 1, "note": "no retrieval recorded"})
    lines = summarise(rows, ["reserve8"]).splitlines()
    assert lines[0] == (
        "recorded run, pool: answer-passage hit rate 9/10, missed [], no_retrieval=['q9']"
    )
    assert lines[1].startswith("recorded run, after_rerank: answer-passage hit rate 9/10")
    assert lines[4].startswith("reserve8: answer-passage hit rate 9/10, mean pool 5.0, missed [], ")
    assert lines[4].endswith("no_retrieval=['q9']")
