import pytest

from scripts.local_rerankers import BgeLocalRerank


class _Fake:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.5, 0.9, 0.5]  # index 0 and 2 tie


async def test_bge_sorts_by_score_keeps_input_order_on_ties_and_respects_top_n() -> None:
    r = BgeLocalRerank()
    r._model = _Fake()
    out = await r.rerank(query="q", documents=["a", "b", "c"], top_n=2)
    assert [i for i, _ in out] == [1, 0]


async def test_bge_empty_input_returns_empty() -> None:
    assert await BgeLocalRerank().rerank(query="q", documents=[], top_n=3) == []


@pytest.mark.parametrize("top_n", [1, 3])
async def test_bge_scores_are_floats(top_n: int) -> None:
    r = BgeLocalRerank()
    r._model = _Fake()
    assert all(
        isinstance(s, float)
        for _, s in await r.rerank(query="q", documents=["a", "b", "c"], top_n=top_n)
    )
