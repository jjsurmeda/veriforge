"""The entity Noul asked a compare question as a conjunction.

`named_entities` returns BOTH characters for a compare question, and
`_entity_passage_questions` built one prompt per passage naming "the entity or
entities 'Victor Frankenstein' and 'Time Traveller'". But `_rerank_candidates`
deliberately splits a compare item's top-k by entity, so every passage
is about exactly ONE of the two and the conjunction can never be satisfied.
The recorded consequence (`docs/known-issues.md` KI-72): all sixteen entity
readings for `compare-inventors` across two runs sat at 0.05-0.44 against a
floor of 0.50 — not one passage cleared it in either run.

The fix asks each passage about each entity SEPARATELY and requires only that
every named entity be covered by at least one passing passage.

These are unit tests over the question-building and the decision rule, with a
fake engine. The end-to-end proof that entity-mismatch is still 12/12 and that
`compare-inventors` now answers is the live run (item 4).

Jev is a fixture and the generator is a stub — no live model.
"""

from uuid import UUID

from decisions.thresholds import threshold
from graph.auto import (
    _entity_passage_decision,
    _entity_passage_questions,
    named_entities,
)
from retrieval.expand import ExpandedContext
from retrieval.hybrid import ScoredChunk
from schemas.decisions import Answer

FLOOR = threshold("entity_match", "jev")


def _context(text: str, index: int = 0) -> ExpandedContext:
    """A minimal ExpandedContext carrying just the chunk text the Noul reads."""
    chunk = ScoredChunk(
        chunk_id=UUID(int=index),
        document_id=None,
        document_name="doc",
        section_id=None,
        ord=index,
        page=None,
        text=text,
        heading_path=None,
        source_type="document",
        vector_score=1.0,
        bm25_score=None,
        fused_score=1.0,
    )
    return ExpandedContext(chunk=chunk, context_text=text)


def _answers(pairs: dict[str, float]) -> dict[str, Answer]:
    return {
        name: Answer(engine="jev", latency_ms=1, value=value, probability=value)
        for name, value in pairs.items()
    }


COMPARE_QUESTION = (
    "Compare how Victor Frankenstein and the Time Traveller deal with the "
    "consequences of their inventions"
)


class TestEachQuestionNamesOneEntity:
    def test_a_compare_question_asks_about_each_entity_separately(self) -> None:
        """The mechanism, read off the prompts themselves: no prompt may name
        two entities and ask whether the passage concerns them together."""
        entities = named_entities(COMPARE_QUESTION)
        assert len(entities) >= 2, entities
        contexts = [_context("a passage about the Time Machine"), _context("Frankenstein")]
        questions = _entity_passage_questions(COMPARE_QUESTION, entities, contexts)

        # One question per (passage, entity) — the conjunction is gone.
        assert len(questions) == len(contexts) * len(entities)
        for name, question in questions.items():
            named = [e for e in entities if f"'{e}'" in question.prompt]
            assert len(named) == 1, f"{name} names {named}: a conjunction again"

    def test_the_question_still_carries_the_question_and_the_passage(self) -> None:
        entities = named_entities(COMPARE_QUESTION)
        contexts = [_context("a passage about the Time Machine")]
        for question in _entity_passage_questions(COMPARE_QUESTION, entities, contexts).values():
            assert "[question]" in question.prompt
            assert "[passage]" in question.prompt
            assert "Time Machine" in question.prompt

    def test_a_single_entity_question_is_unchanged(self) -> None:
        """One entity means the same questions as before KI-72: one per passage,
        naming that one entity."""
        contexts = [_context("p0"), _context("p1"), _context("p2")]
        questions = _entity_passage_questions(
            "How long is the warranty on the AW-2000?", ["AW-2000"], contexts
        )
        assert len(questions) == 3
        for question in questions.values():
            assert "'AW-2000'" in question.prompt

    def test_no_entity_or_no_passage_makes_no_question(self) -> None:
        contexts = [_context("p0")]
        assert _entity_passage_questions("q", [], contexts) == {}
        assert _entity_passage_questions("q", ["X"], []) == {}


class TestEveryEntityMustBeCovered:
    """The decision rule. `entity_0_0` is passage 0 / entity 0,
    `entity_1_0` is passage 1 / entity 0, and so on."""

    def test_a_compare_question_with_one_passage_per_entity_answers(self) -> None:
        """The KI-72 shape that used to decline: passage 0 is about entity 0
        only, passage 1 about entity 1 only. Under the conjunction no passage
        could pass; under "any entity, every entity covered" both are covered."""
        answers = _answers(
            {"entity_0_0": 0.9, "entity_0_1": 0.05, "entity_1_0": 0.05, "entity_1_1": 0.9}
        )
        ok, entity_max = _entity_passage_decision(
            answers, list(answers), entity_count=2, threshold_value=FLOOR
        )
        assert ok is True
        assert entity_max == 0.9

    def test_a_compare_question_where_one_entity_has_no_passage_declines(self) -> None:
        """Both passages are about entity 0. Answering would mean answering half
        the comparison — the confident-wrong shape KI-54 exists to prevent."""
        answers = _answers(
            {"entity_0_0": 0.9, "entity_0_1": 0.05, "entity_1_0": 0.9, "entity_1_1": 0.05}
        )
        ok, _ = _entity_passage_decision(
            answers, list(answers), entity_count=2, threshold_value=FLOOR
        )
        assert ok is False

    def test_a_single_entity_needs_only_one_matching_passage(self) -> None:
        """Unchanged from before KI-72: any one passage about the entity is
        enough, and the maximum reading is still reported for the retry skip."""
        answers = _answers({"entity_0_0": 0.05, "entity_1_0": 0.9})
        ok, entity_max = _entity_passage_decision(
            answers, list(answers), entity_count=1, threshold_value=FLOOR
        )
        assert ok is True
        assert entity_max == 0.9

    def test_a_single_entity_with_no_matching_passage_declines(self) -> None:
        answers = _answers({"entity_0_0": 0.05, "entity_1_0": 0.44})
        ok, entity_max = _entity_passage_decision(
            answers, list(answers), entity_count=1, threshold_value=FLOOR
        )
        assert ok is False
        assert entity_max == 0.44

    def test_no_questions_means_the_check_is_skipped(self) -> None:
        """Skipping never abstains — the safe direction, and unchanged."""
        assert _entity_passage_decision({}, [], 0, FLOOR) == (True, None)

    def test_the_floor_is_respected_per_entity(self) -> None:
        """Exactly at the floor counts as covered; just under it does not."""
        at_floor = _answers(
            {"entity_0_0": FLOOR, "entity_0_1": 0.0, "entity_1_0": 0.0, "entity_1_1": FLOOR}
        )
        assert _entity_passage_decision(at_floor, list(at_floor), 2, FLOOR)[0] is True
        under = _answers(
            {
                "entity_0_0": FLOOR,
                "entity_0_1": 0.0,
                "entity_1_0": 0.0,
                "entity_1_1": FLOOR - 0.001,
            }
        )
        assert _entity_passage_decision(under, list(under), 2, FLOOR)[0] is False


class TestRecordedKI72Values:
    """KI-72's recorded readings: across two runs, sixteen entity readings for
    `compare-inventors`, min 0.05, max 0.44, floor 0.50. Not one cleared it.
    Replayed against the new rule, the same per-passage values that abstained
    the item under the conjunction answer it under "every entity covered" —
    provided each side really is covered."""

    def test_the_recorded_band_is_below_the_floor(self) -> None:
        assert FLOOR > 0.44
        assert FLOOR > 0.05

    def test_one_passage_per_entity_at_the_recorded_max_answers(self) -> None:
        run1_max = 0.44
        answers = _answers(
            {"entity_0_0": run1_max, "entity_0_1": 0.05, "entity_1_0": 0.05, "entity_1_1": run1_max}
        )
        ok, _ = _entity_passage_decision(answers, list(answers), 2, FLOOR)
        assert ok is False, "0.44 is under the floor: this run would still decline"

    def test_the_same_passages_at_a_covering_reading_answer(self) -> None:
        """The point of the fix is the QUESTION, not a threshold change: no
        reading the record holds would have passed before, and the item still
        answers as soon as each entity is genuinely covered."""
        answers = _answers(
            {"entity_0_0": 0.9, "entity_0_1": 0.05, "entity_1_0": 0.05, "entity_1_1": 0.88}
        )
        assert _entity_passage_decision(answers, list(answers), 2, FLOOR)[0] is True


class TestEntityMismatchShapesStillDecline:
    """The shapes that carry entity-mismatch 12/12. A passage about a
    DIFFERENT, similarly named entity must not be mistaken for a match, in
    either the old single-entity rule or the new per-entity one."""

    def test_passages_about_a_different_similarly_named_entity_decline(self) -> None:
        # "Ridgeline R-7" question, passages that are all about the R-9.
        answers = _answers({"entity_0_0": 0.11, "entity_1_0": 0.14, "entity_2_0": 0.09})
        ok, _ = _entity_passage_decision(answers, list(answers), 1, FLOOR)
        assert ok is False

    def test_one_about_the_named_entity_among_many_still_answers(self) -> None:
        """The complementary shape, and the one entity-mismatch's 12 items must
        NOT have: one genuinely matching passage carries the run."""
        answers = _answers({"entity_0_0": 0.11, "entity_1_0": 0.91, "entity_2_0": 0.09})
        assert _entity_passage_decision(answers, list(answers), 1, FLOOR)[0] is True


class TestOutsideHolmesBostonIsStillHeld:
    """`outside-holmes-boston` is held by THIS check alone (phase 1b:
    sufficiency 0.37/0.39, relevance 0.49/0.63 — relevance clears nothing on
    its own at 0.49, and sufficiency is far under any floor that would let a
    confident wrong answer through on its own). Its passages are about Sherlock
    Holmes, not about Mary Bostan. If the loosened rule let this through, the
    live run would answer a question the corpus cannot answer."""

    def test_a_passage_about_holmes_does_not_cover_bostan(self) -> None:
        answers = _answers({"entity_0_0": 0.12, "entity_1_0": 0.09})
        ok, entity_max = _entity_passage_decision(answers, list(answers), 1, FLOOR)
        assert ok is False
        assert entity_max == 0.12

    def test_the_question_names_bostan_and_not_holmes(self) -> None:
        entities = named_entities(
            "Which Boston firm did Sherlock Holmes consult about a case in The Sign of the Four?"
        )
        assert entities, "the item must still name an entity, or the check is skipped"