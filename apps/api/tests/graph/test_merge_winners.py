"""Merging hop winners: each sub-question keeps its best two chunks."""

import random
from uuid import uuid4

from graph.hop_retrieve import merge_winners, rerank_score_key
from retrieval.expand import dedupe_adjacent
from retrieval.hybrid import ScoredChunk

_SECTION = uuid4()


def _chunk(score: float | None, ord_: int, doc: object = None) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid4(),
        document_id=doc,  # type: ignore[arg-type]
        document_name=None,
        section_id=_SECTION,
        ord=ord_,
        page=None,
        text="t",
        heading_path=None,
        source_type="document",
        vector_score=None,
        bm25_score=None,
        fused_score=0.01,
        rerank_score=score,
    )


def _old(groups: list[list[ScoredChunk]]) -> list[ScoredChunk]:
    return dedupe_adjacent(
        sorted([c for g in groups for c in g], key=rerank_score_key, reverse=True)
    )


def test_a_single_sub_question_gets_exactly_todays_winners() -> None:
    rng = random.Random(7)
    doc = uuid4()
    for _ in range(50):
        group = [_chunk(rng.choice([None, rng.random()]), i * 3, doc) for i in range(8)]
        assert merge_winners([group]) == _old([group])
        assert merge_winners([group, []]) == _old([group, []])
        assert merge_winners([]) == []


def test_every_sub_question_keeps_its_best_two_ahead_of_the_rest() -> None:
    doc = uuid4()
    strong = [_chunk(0.9 - i * 0.01, i * 3, doc) for i in range(6)]
    weak = [_chunk(0.2, 100, doc), _chunk(0.1, 103, doc), _chunk(0.05, 106, doc)]
    merged = merge_winners([strong, weak])
    assert merged[:4] == [*strong[:2], *weak[:2]]
    assert set(map(id, merged)) == set(map(id, _old([strong, weak])))
    assert merged[4:] == [*strong[2:], weak[2]]


def test_a_chunk_removed_as_adjacent_is_covered_by_its_neighbour() -> None:
    doc = uuid4()
    first = [_chunk(0.9, 10, doc), _chunk(0.8, 20, doc)]
    second = [_chunk(0.7, 11, doc)]  # adjacent to first[0]: dropped by dedupe
    merged = merge_winners([first, second])
    assert merged == _old([first, second])
