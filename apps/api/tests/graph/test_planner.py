"""Planner node tests (TRD §7 Deep row): LLM call mocked — no live model."""

import json

from graph.planner import _fallback_plan, _parse_plan, plan_question


def test_parse_plan_accepts_valid_json_with_deps() -> None:
    raw = json.dumps(
        [
            {"id": "q1", "question": "What is the warranty period?", "depends_on": []},
            {"id": "q2", "question": "Does it cover the failure in q1?", "depends_on": ["q1"]},
        ]
    )
    plan = _parse_plan(raw, "original question")
    assert [sq.id for sq in plan] == ["q1", "q2"]
    assert plan[1].depends_on == ["q1"]


def test_parse_plan_strips_markdown_fences() -> None:
    raw = "```json\n" + json.dumps(
        [
            {"id": "q1", "question": "a", "depends_on": []},
            {"id": "q2", "question": "b", "depends_on": []},
        ]
    ) + "\n```"
    plan = _parse_plan(raw, "original question")
    assert len(plan) == 2


def test_parse_plan_falls_back_on_malformed_json() -> None:
    plan = _parse_plan("not json at all", "original question")
    assert plan == _fallback_plan("original question")


def test_parse_plan_falls_back_below_minimum_sub_questions() -> None:
    raw = json.dumps([{"id": "q1", "question": "only one", "depends_on": []}])
    plan = _parse_plan(raw, "original question")
    assert plan == _fallback_plan("original question")


def test_parse_plan_drops_dangling_dependency() -> None:
    raw = json.dumps(
        [
            {"id": "q1", "question": "a", "depends_on": []},
            {"id": "q2", "question": "b", "depends_on": ["ghost"]},
        ]
    )
    plan = _parse_plan(raw, "original question")
    assert plan[1].depends_on == []


def test_parse_plan_drops_self_dependency() -> None:
    raw = json.dumps(
        [
            {"id": "q1", "question": "a", "depends_on": ["q1"]},
            {"id": "q2", "question": "b", "depends_on": []},
        ]
    )
    plan = _parse_plan(raw, "original question")
    assert plan[0].depends_on == []


async def test_plan_question_falls_back_when_llm_call_raises() -> None:
    async def failing_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        raise RuntimeError("network down")

    plan = await plan_question(
        "what is the warranty", small_model="m", complete_fn=failing_complete
    )
    assert plan == _fallback_plan("what is the warranty")


async def test_plan_question_parses_llm_response() -> None:
    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        return json.dumps(
            [
                {"id": "q1", "question": "a", "depends_on": []},
                {"id": "q2", "question": "b", "depends_on": []},
            ]
        )

    plan = await plan_question("q", small_model="m", complete_fn=fake_complete)
    assert len(plan) == 2
