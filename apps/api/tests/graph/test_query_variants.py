"""KI-12 item 1: MULTI_PARTS decomposition parses into separate parts on
both small-model shapes (captured live 2026-09-29, see known-issues)."""

from collections.abc import Awaitable, Callable

import pytest

from graph.auto import MULTI_PART_VARIANTS, MULTI_PARTS, _generate_query_variants

CompleteFn = Callable[..., Awaitable[str]]

QUESTION = "What does Mr. Darcy say in his first proposal to Elizabeth, and how does she answer?"

GPT4O_MINI_SHAPED = (
    "What does Mr. Darcy say in his first proposal to Elizabeth?  \n"
    "How does Elizabeth answer Mr. Darcy's first proposal?"
)

NEMOTRON_SHAPED = (
    "What does Mr. Darcy say in his first proposal to Elizabeth?\n"
    "How does Elizabeth answer Mr. Darcy's first proposal?"
)


def _complete_returning(response: str) -> tuple[CompleteFn, list[str]]:
    prompts: list[str] = []

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        prompts.append(messages[0]["content"])
        return response

    return fake_complete, prompts


@pytest.mark.parametrize("response", [GPT4O_MINI_SHAPED, NEMOTRON_SHAPED])

async def test_parts_parse_into_separate_queries(response: str) -> None:
    complete_fn, _ = _complete_returning(response)
    parts = await _generate_query_variants(
        QUESTION, "unused", complete_fn, MULTI_PART_VARIANTS, instruction=MULTI_PARTS
    )
    assert parts == [
        "What does Mr. Darcy say in his first proposal to Elizabeth?",
        "How does Elizabeth answer Mr. Darcy's first proposal?",
    ]
    assert not any("how does she answer" in p for p in parts)



async def test_parts_prompt_omits_phrasings_block() -> None:
    complete_fn, prompts = _complete_returning(NEMOTRON_SHAPED)
    await _generate_query_variants(
        QUESTION, "unused", complete_fn, MULTI_PART_VARIANTS, instruction=MULTI_PARTS
    )
    assert "alternative phrasings" not in prompts[0]
    assert MULTI_PARTS in prompts[0]



async def test_variants_call_still_seeds_question() -> None:
    complete_fn, _ = _complete_returning("phrasing one\nphrasing two")
    variants = await _generate_query_variants(QUESTION, "unused", complete_fn, 3)
    assert variants == [QUESTION, "phrasing one", "phrasing two"]
