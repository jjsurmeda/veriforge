"""`scripts/acceptance.py --summary-out` writes the counts the gate reads.

The runner exits 0 whatever happens, which is correct for an operator reading a
table and wrong for a `make check-work` step: someone has to decide pass/fail
from the run's own result fields. These pin that classification — including the
distinctions that decide  and  — without a stack, because
`summarise` is pure over the rows the run recorded.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts import acceptance


def _row(
    item_id: str,
    expect: str,
    *,
    answer: str = "An answer.",
    status: str = "completed",
    message_status: str | None = "complete",
    citations: list[str] | None = None,
    ok: bool = True,
) -> dict[str, Any]:
    """One row in the shape `run()` appends: the scorer's own fields."""
    return {
        "id": item_id,
        "expect": expect,
        "pass": ok,
        "reason": None if ok else "wrong_class_or_content",
        "answer": answer,
        "citations": citations if citations is not None else ["[1] Book p.1"],
        "status": status,
        "message_status": message_status,
    }


def test_an_answering_should_decline_item_is_a_confident_wrong() -> None:
    """'s shape: the run answered *with citations* instead of declining.

    Citations are the normal shape of a confident wrong answer, and they must not
    be what makes it an unclean decline — the difference is whether the reply
    says the sources lack the fact.
    """
    rows = [_row("outside-emma", "not_in_sources", answer="Emma dies of arsenic.")]

    summary = acceptance.summarise(rows)

    assert summary["counts"]["confident_wrong"] == 1
    assert summary["detail"]["confident_wrong_ids"] == ["outside-emma"]
    assert summary["counts"]["clean_declines"] == 0


def test_an_abstained_should_decline_item_is_a_clean_decline() -> None:
    rows = [
        _row("outside-emma", "not_in_sources", answer="", message_status="abstained", citations=[])
    ]

    summary = acceptance.summarise(rows)

    assert summary["counts"]["clean_declines"] == 1
    assert summary["counts"]["confident_wrong"] == 0


def test_a_prose_decline_with_citations_is_unclean_not_confident_wrong() -> None:
    """PRD §5 counts this against decline accuracy, not against confident wrong."""
    rows = [
        _row(
            "outside-emma",
            "not_in_sources",
            # Wording the scorer's own `says_not_in_sources` recognises, not a
            # paraphrase of it: this test is about the citations, and a phrase
            # the scorer does not match would fail for a second reason.
            answer="That detail is not in the sources you shared.",
            citations=["[1] Noli Me Tangere p.2"],
        )
    ]

    summary = acceptance.summarise(rows)

    assert summary["counts"]["unclean_declines"] == 1
    assert summary["counts"]["confident_wrong"] == 0
    assert summary["counts"]["clean_declines"] == 0


def test_a_prose_decline_without_citations_is_clean() -> None:
    """The same words with no citations are the clean case, not the unclean one."""
    rows = [
        _row(
            "outside-emma",
            "not_in_sources",
            answer="I cannot find that in the sources.",
            citations=[],
        )
    ]

    summary = acceptance.summarise(rows)

    assert summary["counts"]["clean_declines"] == 1
    assert summary["counts"]["unclean_declines"] == 0


def test_a_declined_answer_item_is_a_false_abstention() -> None:
    """'s shape: the answer was in the sources and the run declined on it."""
    rows = [_row("rp77-torque", "answer", answer="", message_status="abstained", citations=[])]

    summary = acceptance.summarise(rows)

    assert summary["counts"]["false_abstentions"] == 1
    assert summary["detail"]["false_abstention_ids"] == ["rp77-torque"]


def test_an_answered_item_with_no_citations_is_an_uncited_answer() -> None:
    """: the item is `answer`, the run did not decline, and it cited
    nothing — a reply from model memory. It is neither a false abstention
    (nothing was declined) nor a confident wrong (that class is should-decline
    items), so without its own count the shape is invisible to the gate."""
    rows = [
        _row(
            "broad-sherlock",
            "answer",
            answer="The Adventures of Sherlock Holmes is a classic detective collection.",
            citations=[],
            ok=False,
        )
    ]

    summary = acceptance.summarise(rows)

    assert summary["counts"]["uncited_answers"] == 1
    assert summary["detail"]["uncited_answer_ids"] == ["broad-sherlock"]
    assert summary["counts"]["false_abstentions"] == 0
    assert summary["counts"]["confident_wrong"] == 0


def test_an_errored_item_is_never_an_uncited_answer_either() -> None:
    """A failed item has no behaviour to grade, so it is counted once, as an
    error — not as an ungrounded answer it never got to give."""
    rows = [
        _row("broad-sherlock", "answer", status="failed (provider)", answer="", citations=[])
    ]

    summary = acceptance.summarise(rows)

    assert summary["counts"]["errored"] == 1
    assert summary["counts"]["uncited_answers"] == 0


def test_an_errored_item_is_never_a_decline() -> None:
    """The error is counted on its own and excluded from every rate: an errored
    abstain item has no behaviour to grade, so counting it as a decline would
    turn a provider error into a passing decline."""
    rows = [
        _row("outside-emma", "not_in_sources", status="failed (provider)", answer="", citations=[])
    ]

    summary = acceptance.summarise(rows)

    assert summary["counts"]["errored"] == 1
    assert summary["detail"]["errored_ids"] == ["outside-emma"]
    assert summary["counts"]["clean_declines"] == 0
    assert summary["counts"]["unclean_declines"] == 0
    assert summary["counts"]["confident_wrong"] == 0


def test_a_failed_item_is_listed_regardless_of_class() -> None:
    """Smalltalk, library and answer items are graded on `pass`; a failure has
    to be nameable in the summary even when the counts look healthy."""
    rows = [
        _row("smalltalk-hi", "smalltalk", answer="Hi!", citations=[], ok=False),
        _row("library-count", "library", answer="There are 12 books.", ok=False),
    ]

    summary = acceptance.summarise(rows)

    assert summary["detail"]["failed_ids"] == ["smalltalk-hi", "library-count"]
    assert summary["counts"]["smalltalk_items"] == 1
    assert summary["counts"]["library_items"] == 1


def test_the_served_commit_is_recorded_verbatim() -> None:
    """The summary names the api's commit, so a run that measured another
    checkout says so after the fact."""
    summary = acceptance.summarise([], served_commit="b" * 40)

    assert summary["served_commit"] == "b" * 40


def test_no_served_commit_key_when_the_caller_did_not_read_one() -> None:
    assert "served_commit" not in acceptance.summarise([])


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    def __init__(self, response: _Response | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    async def get(self, _url: str, **_kwargs: Any) -> _Response:
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


async def test_served_commit_reads_the_apis_own_healthz() -> None:
    client = _Client(_Response({"status": "ok", "served_commit": "c" * 40}))

    assert await acceptance.served_commit(client) == "c" * 40  # type: ignore[arg-type]


async def test_served_commit_is_unknown_when_the_apis_field_is_absent() -> None:
    """An api predating the field reports nothing, which is not a pass: the
    step compares this with HEAD and fails on anything but a match."""
    client = _Client(_Response({"status": "ok"}))

    assert await acceptance.served_commit(client) == "unknown"  # type: ignore[arg-type]


async def test_served_commit_is_unknown_when_healthz_is_unreachable() -> None:
    """A connection error must not crash the run; it must name itself unknown so
    the step fails with the reason instead of a stack trace."""
    client = _Client(error=httpx.ConnectError("refused"))

    assert await acceptance.served_commit(client) == "unknown"  # type: ignore[arg-type]


def test_the_summary_is_json_serialisable() -> None:
    """The gate reads this off disk; a non-serialisable field would fail the
    step after the credit was already spent."""
    summary = acceptance.summarise(
        [_row("outside-emma", "not_in_sources", answer="An answer.", citations=[])],
        served_commit="d" * 40,
    )

    assert json.loads(json.dumps(summary))["counts"]["confident_wrong"] == 1


@pytest.mark.parametrize("field", ["counts", "detail"])
def test_summarise_always_writes_both_blocks(field: str) -> None:
    assert field in acceptance.summarise([])


def test_summarise_keeps_the_rows_so_the_gate_can_name_a_class() -> None:
    """`acceptance_gate` looks up an item's class from the summary, which is why
    the rows travel with it."""
    rows = [_row("library-count", "library")]

    assert acceptance.summarise(rows)["items"] == rows


def test_a_run_over_no_rows_reports_zeroes_not_a_pass() -> None:
    """The gate's expected-counts check is what turns this into a failure, so
    `summarise` does not have to."""
    assert acceptance.summarise([])["counts"]["items"] == 0


def test_the_whole_set_classifies_as_the_brief_expects() -> None:
    """A synthetic full-set run, so the two functions are pinned together: 57
    items, 18+ clean declines of 20, ≤1 false abstention of 33."""
    from evals.acceptance_gate import EXPECTED_COUNTS, acceptance_failures

    rows: list[dict[str, Any]] = []
    for index in range(EXPECTED_COUNTS["smalltalk_items"]):
        rows.append(_row(f"smalltalk-{index}", "smalltalk", answer="Hi!", citations=[]))
    for index in range(EXPECTED_COUNTS["library_items"]):
        rows.append(_row(f"library-{index}", "library"))
    for index in range(EXPECTED_COUNTS["answer_items"]):
        rows.append(_row(f"answer-{index}", "answer"))
    for index in range(EXPECTED_COUNTS["abstain_items"]):
        rows.append(
            _row(
                f"abstain-{index}",
                "not_in_sources",
                answer="",
                message_status="abstained",
                citations=[],
            )
        )

    summary = acceptance.summarise(rows, served_commit="e" * 40)

    assert acceptance_failures(summary) == []


def test_one_errored_item_in_the_abstain_class_fails_the_whole_set() -> None:
    """The end-to-end shape of the rule: an error inside the 20 is a failure, not
    a decline, even with every other item clean."""
    from evals.acceptance_gate import EXPECTED_COUNTS, acceptance_failures

    rows: list[dict[str, Any]] = [
        _row("smalltalk-0", "smalltalk", answer="Hi!", citations=[]),
        _row("library-0", "library"),
    ]
    rows += [_row(f"answer-{i}", "answer") for i in range(EXPECTED_COUNTS["answer_items"])]
    abstains = [
        _row(f"abstain-{i}", "not_in_sources", answer="", message_status="abstained", citations=[])
        for i in range(EXPECTED_COUNTS["abstain_items"])
    ]
    abstains[0] = _row("abstain-0", "not_in_sources", status="failed (timeout)", citations=[])
    rows += abstains

    summary = acceptance.summarise(rows)

    assert any("errored" in failure for failure in acceptance_failures(summary))


def test_a_short_results_file_does_not_pass(tmp_path: Path) -> None:
    """The gate reads a file the run wrote; a truncated one has to fail, which is
    the `items` check and not a JSON parse error surfacing as a crash."""
    from evals.acceptance_gate import acceptance_failures

    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"counts": {"items": 4}}))

    assert acceptance_failures(json.loads(path.read_text()))