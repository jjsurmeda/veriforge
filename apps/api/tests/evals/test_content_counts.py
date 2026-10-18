"""The counterfactual gate enforces the altered fact (third-party review #2).

`counterfactual_counts` scores a run's delivered answers with the same
required / forbidden / expected-document checks the acceptance scorer uses."""

from evals.content import cited_documents, counterfactual_counts

SPEC = {
    "How tall is the tower?": {
        "expect": "answer",
        "mention": ["512"],
        "forbid": ["330"],
        "cite": ["register"],
    },
    "What does the K9 cost?": {"expect": "not_in_sources", "forbid": ["$999"]},
}


def count(question: str, answer: str, abstained: bool, cited: list[str]) -> dict[str, float]:
    return counterfactual_counts(SPEC, [(question, answer, abstained, cited)])


def test_the_altered_fact_with_its_document_counts_nothing() -> None:
    got = count("How tall is the tower?", "It is 512 m [1].", False, ["landmarks_register.md"])
    assert got == {"forbidden_hits": 0, "content_misses": 0, "wrong_document": 0}


def test_the_real_world_value_is_a_forbidden_hit() -> None:
    got = count("How tall is the tower?", "512 m, though it is 330 m [1].", False, ["register.md"])
    assert got["forbidden_hits"] == 1


def test_a_cited_answer_without_the_required_value_is_a_content_miss() -> None:
    got = count("How tall is the tower?", "It is tall [1].", False, ["register.md"])
    assert got["content_misses"] == 1


def test_an_answer_citing_another_document_is_wrong_document() -> None:
    got = count("How tall is the tower?", "It is 512 m [1].", False, ["manual.md"])
    assert got["wrong_document"] == 1


def test_an_abstention_is_not_a_content_failure() -> None:
    got = count("How tall is the tower?", "I could not find that.", True, [])
    assert got == {"forbidden_hits": 0, "content_misses": 0, "wrong_document": 0}


def test_a_decline_item_that_answers_with_a_forbidden_value_is_a_hit() -> None:
    assert count("What does the K9 cost?", "It costs $999.", False, [])["forbidden_hits"] == 1


def test_cited_documents_follow_the_markers() -> None:
    assert cited_documents("A [2] and [1] and [9].", ["a.md", "b.md"]) == ["a.md", "b.md"]


def test_the_gate_fails_on_any_content_count_and_judges_the_worst_draw() -> None:
    from evals.gate import CONTENT_KEYS, _mean_of, compare

    base: dict[str, float | None] = {"faithfulness": 0.95}
    assert compare(base, {"faithfulness": 0.95, "forbidden_hits": 0.0}) == []
    for key in CONTENT_KEYS:
        assert any(key in f for f in compare(base, {"faithfulness": 0.95, key: 1.0}))
    mean = _mean_of([{"forbidden_hits": 0.0}, {"forbidden_hits": 1.0}, {"forbidden_hits": 0.0}])
    assert mean["forbidden_hits"] == 1.0
