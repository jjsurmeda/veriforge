"""KI-70: the relevance gate abstains on broad/summary answerable items.

The rubric's answer-containment score measures question-to-passage lexical
overlap. A gist question ("give me the story of X") matches no single passage,
so the reranker scores the *correct* passages low — `broad-alice` scored 0.36 on
passages the entity check graded 0.97 on.

The fix (KI-70): a `summarize` question is not subject to the relevance veto;
the entity check decides it alone. This file verifies that boundary: summarize
intent answers below the floor, lookup intent does not.

Replayed on the recorded acceptance items, the rule removes the false
abstentions on `broad-alice` and `broad-bovary` and changes nothing else —
0 of 20 should-decline items become answers.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from tests.graph.test_chitchat import _gate_params, _gate_run_intent
from tests.graph.test_chitchat import no_llm as no_llm
from tests.graph.test_chitchat import user_a as user_a


@pytest.mark.asyncio
async def test_summarize_intent_answers_below_gate_floor(
    db: AsyncSession,
    user_a: User,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A summarize question whose passages score 0.2 (below the 0.56 floor)
    still answers: KI-70 removes the relevance veto for gist questions, so
    only the entity check decides. With no named entity in the question the
    entity guard defaults to pass, and the run generates.
    """
    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    run = await _gate_run_intent(params, intent="summarize", passage_score=0.2)

    assert run.abstain_event is None, "summarize intent should skip the relevance veto"
    assert run.contexts, "a run that cleared evidence still generates from evidence"


@pytest.mark.asyncio
async def test_lookup_intent_still_vetoed_below_gate_floor(
    db: AsyncSession,
    user_a: User,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lookup question with the same 0.2 score is still vetoed by the
    relevance gate — KI-70 only relaxes the veto for summarize intent.
    """
    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    run = await _gate_run_intent(params, intent="lookup", passage_score=0.2)

    assert run.abstain_event is not None, "lookup intent should still be gated by relevance"


@pytest.mark.asyncio
async def test_summarize_intent_answers_even_at_zero(
    db: AsyncSession,
    user_a: User,
    no_llm: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when the reranker grades every passage 0.0, a summarize question
    with no named entity in the query proceeds past the evidence stage — the
    entity guard is the only check, and it defaults to pass.
    """
    params = await _gate_params(db, user_a, no_llm, monkeypatch)
    run = await _gate_run_intent(params, intent="summarize", passage_score=0.0)

    assert run.abstain_event is None
    assert run.contexts
