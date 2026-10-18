"""A decline that goes on to assert an answer is not a decline (review #10),
and the decline shape is recognised in the books set's languages."""

import pytest

from evals.abstention import asserts_after_decline, is_confident_wrong, says_not_in_sources


@pytest.mark.parametrize(
    "answer",
    [
        "I cannot find the price, but it costs $999.",
        "The sources don't contain the height; however, the register gives 512 m [1].",
        "No encuentro el precio, pero cuesta 999 euros.",
        "Je ne trouve pas le prix, mais il coûte 999 €.",
        "Das steht nicht in den Quellen, aber es kostet 999 Euro.",
        "来源没有提到价格，但是价格是999元。",  # noqa: RUF001
        "資料には記載がありませんが、価格は999円です。",
    ],
)
def test_a_decline_followed_by_a_figure_is_an_answer(answer: str) -> None:
    assert asserts_after_decline(answer)
    assert not says_not_in_sources(answer)
    assert is_confident_wrong(abstained=False, answer=answer, citation_count=0)


@pytest.mark.parametrize(
    "answer",
    [
        "I could not find enough evidence to answer that question.",
        "The sources don't cover that, but you could upload the manual.",
        "No se encuentra esa información en las fuentes.",
        "Je ne trouve pas cette information dans vos sources.",
        "Das steht nicht in den Quellen.",
        "在你的资料里找不到这个信息。",
        "その情報は資料には見つかりません。",
        "Hindi ko makita iyon sa iyong mga sources.",
    ],
)
def test_a_plain_decline_in_any_listed_language_is_still_a_decline(answer: str) -> None:
    assert says_not_in_sources(answer)
    assert not is_confident_wrong(abstained=False, answer=answer, citation_count=0)


def test_an_answer_that_never_declines_is_not_rescued_by_a_figure() -> None:
    assert is_confident_wrong(abstained=False, answer="It costs $999 [1].", citation_count=1)


def test_a_graph_abstention_is_authoritative() -> None:
    mixed = "I cannot find it, but 5."
    assert not is_confident_wrong(abstained=True, answer=mixed, citation_count=0)
