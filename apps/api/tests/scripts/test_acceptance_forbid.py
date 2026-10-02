"""The scorer channels P1b item 2 and item 3 added.

Two of them make an item checkable that was not checkable before:

- **`forbid`** (counterfactual): the corpus states a value deliberately
  different from the real one, so naming the real-world value has to fail the
  item even when the document's value is present and the citation is right.
  This is the only thing in the suite that can catch "grounded in the source,
  wrong anyway".
- **`mention_all`** (ambiguity): the corpus answers a question two ways, so the
  item requires both referents. These items are expected to fail until P2's
  prompt change, so they carry `pending_p2` and are reported apart from the
  headline pass rate.

The word-boundary cases are the point of two of these tests: a bare substring
check would make `IP68` fail an `IP69K` answer and `330` fail a `3300` one,
which is the same defect as KI-36 — a check stricter than the corpus.
"""

from typing import Any

from scripts.acceptance import failure_reason, forbids_hit, mentions_hit, passes


def result(answer: str, *, citations: list[str] | None = None) -> dict[str, Any]:
    return {
        "answer": answer,
        "status": "completed",
        "message_status": "complete",
        "citations": ["[1] Frankenstein.txt p.1"] if citations is None else citations,
    }


# --------------------------------------------------------------------------
# forbid
# --------------------------------------------------------------------------


def test_forbid_fails_an_answer_that_also_states_the_document_value() -> None:
    item = {
        "expect": "answer",
        "cite": ["Register"],
        "mention": ["512 m"],
        "forbid": ["330 m"],
        "turns": ["How tall is the Eiffel Tower?"],
    }
    # Right value, right citation, real-world value mentioned as a correction.
    assert passes(item, result("The register gives it as 512 m, not the usual 330 m.")) is False


def test_forbid_names_the_offending_value_in_the_failure_reason() -> None:
    """A `forbid` failure is not a retrieval problem and must not be reported
    as `wrong_class_or_content`, or whoever reads the run will go looking in the
    wrong place."""
    item = {
        "expect": "answer",
        "cite": ["Register"],
        "mention": ["512 m"],
        "forbid": ["330 m"],
        "turns": ["How tall is the Eiffel Tower?"],
    }
    assert (
        failure_reason(item, result("512 m, commonly given as 330 m.")) == "forbidden_value:330 m"
    )


def test_forbid_does_not_fire_on_a_longer_number() -> None:
    """`330` must not match `3300`, or the item rejects a correct answer."""
    assert forbids_hit({"forbid": ["330"]}, "The scaffolding is 3300 m long.") is None
    assert forbids_hit({"forbid": ["330"]}, "The tower is 330 m.") == "330"


def test_forbid_does_not_fire_on_a_superset_rating() -> None:
    assert forbids_hit({"forbid": ["IP68"]}, "Every model is rated IP69K.") is None
    assert forbids_hit({"forbid": ["IP68"]}, "Every model is rated IP68.") == "IP68"


def test_an_item_with_no_forbid_list_is_unaffected() -> None:
    item = {
        "expect": "answer",
        "cite": ["Frankenstein"],
        "mention": ["512 m"],
        "turns": ["How tall is the tower?"],
    }
    assert passes(item, result("The register gives 512 m.")) is True


def test_forbid_is_checked_before_the_class() -> None:
    """A should-abstain item that recites a forbidden value has asserted an
    answer, so it cannot be allowed to pass on the abstention path."""
    item = {
        "expect": "not_in_sources",
        "forbid": ["330 m"],
        "turns": ["How tall is the Eiffel Tower?"],
    }
    declined = {
        "answer": "I could not find that in your sources.",
        "status": "completed",
        "message_status": "abstained",
        "citations": [],
    }
    assert passes(item, declined) is True
    with_value = dict(declined)
    with_value["answer"] = "Not covered — your sources never mention 330 m."
    assert passes(item, with_value) is False


# --------------------------------------------------------------------------
# mention_all / alt_mention
# --------------------------------------------------------------------------


def test_mention_all_requires_both_referents() -> None:
    item = {"expect": "answer", "mention_all": ["Homais", "Rouard"]}
    assert mentions_hit(item, "Homais the pharmacist advises her.") is False
    assert mentions_hit(item, "Homais first, then Rouard when he fails.") is True


def test_an_ambiguity_item_that_names_one_referent_fails() -> None:
    """The point of the item: the corpus supports both, so naming one has not
    answered the question the corpus poses."""
    item = {
        "expect": "answer",
        "cite": ["Frankenstein"],
        "mention_all": ["Walton", "sister", "Margaret"],
        "pending_p2": True,
        "turns": ["Who are the letters addressed to?"],
    }
    one = result("Robert Walton writes the letters to his sister.")
    both = result("Robert Walton writes them to his sister, Margaret.")
    assert passes(item, one) is False
    assert passes(item, both) is True


def test_alt_mention_is_an_accepted_spelling_of_the_same_value() -> None:
    """`6400` and `6,400` are one value; the corpus writes it with a separator
    and an answer may not."""
    item = {
        "expect": "answer",
        "cite": ["landmarks"],
        "mention": ["6,400 km"],
        "alt_mention": ["6400 km"],
        "turns": ["How long is the wall?"],
    }
    cited = ["[1] landmarks_register.md p.1"]
    assert passes(item, result("The register gives 6400 km.", citations=cited)) is True
    assert passes(item, result("The register gives 6,400 km.", citations=cited)) is True
    assert passes(item, result("The register gives 12,000 km.", citations=cited)) is False


def test_a_mention_all_item_still_accepts_a_mention_spelling() -> None:
    """`mention_all` requires all of its strings; `mention`/`alt_mention` are
    still an any-of, so an item can pin both referents *and* allow two spellings
    of one of them."""
    item = {
        "expect": "answer",
        "mention_all": ["342"],
        "mention": ["Tour d'Aval"],
        "alt_mention": ["Tour d’Aval"],
    }
    assert mentions_hit(item, "The Tour d'Aval rises 342 m.") is True
    assert mentions_hit(item, "The tower rises 342 m.") is False


def test_no_mention_list_at_all_is_unchanged() -> None:
    assert mentions_hit({"expect": "answer"}, "anything at all") is True
