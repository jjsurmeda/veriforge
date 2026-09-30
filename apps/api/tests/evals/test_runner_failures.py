"""A raising item is persisted, counted as failed, and kept out of p50 (KI-6).

The old `except` branch built an `EvalResult` and never added it to a
session, so the row was lost and a `latency_ms=0` placeholder still reached
`aggregate()` — dragging the median down instead of failing the gate.
"""

import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import EvalDataset, EvalItem, EvalResult, Plan, User
from evals import runner
from evals.gate import compare
from evals.loader import EVAL_USER_EMAIL
from evals.runner import aggregate, run_eval

pytestmark = pytest.mark.asyncio


async def _seed_dataset(db: AsyncSession, questions: list[str]) -> EvalDataset:
    plan_id = (await db.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    db.add(User(email=EVAL_USER_EMAIL, role="user", plan_id=plan_id, status="active"))
    dataset = EvalDataset(name="seed")
    db.add(dataset)
    await db.flush()
    db.add_all(
        EvalItem(
            dataset_id=dataset.id,
            category="single_document_lookup",
            question=question,
            reference_answer="",
            should_abstain=False,
        )
        for question in questions
    )
    await db.commit()
    return dataset


async def test_failed_item_is_persisted_and_excluded_from_p50(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dataset = await _seed_dataset(db, ["raises", "fast", "slow"])
    assert dataset.name == "seed"
    state = tmp_path / "loaded.json"
    state.write_text(json.dumps({"corpus_collection_id": "01a0ccca-0000-0000-0000-000000000000"}))
    monkeypatch.setattr(runner, "STATE_FILE", state)

    latencies = {"fast": 900, "slow": 1100}

    async def fake_run_item(
        factory: async_sessionmaker[AsyncSession],
        *,
        user: User,
        eval_run_id: UUID,
        item: EvalItem,
        mode: str = "auto",
    ) -> tuple[EvalResult, list[str]]:
        if item.question is not None and item.question == "raises":
            raise RuntimeError("boom")
        result = EvalResult(
            eval_run_id=eval_run_id,
            item_id=item.id,
            answer="ok",
            faithfulness=0.9,
            abstained=False,
            latency_ms=latencies[item.question],
        )
        async with factory() as session, session.begin():
            session.add(result)
        return result, []

    monkeypatch.setattr(runner, "_run_item", fake_run_item)

    eval_run, results = await run_eval(subset=None, baseline=False)

    rows = (
        (
            await db.execute(
                select(EvalResult)
                .where(EvalResult.eval_run_id == eval_run.id)
                .order_by(EvalResult.latency_ms)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 3, "the failed item must leave a row behind"
    failed = [r for r in rows if r.error is not None]
    assert len(failed) == 1
    assert failed[0].error is not None
    assert "RuntimeError: boom" in failed[0].error
    assert failed[0].eval_run_id == eval_run.id

    summary = aggregate(results)
    assert summary["failed"] == 1
    assert summary["scored"] == 2
    assert summary["p50_latency_ms"] == 1000.0, "900/1100 median, not 0"
    assert summary["faithfulness"] == pytest.approx(0.9)


async def test_gate_fails_when_any_item_errored() -> None:
    baseline: dict[str, float | None] = {
        "faithfulness": 0.9,
        "abstention_accuracy": 1.0,
        "p50_latency_ms": 1000.0,
    }
    current: dict[str, float | None] = {
        "faithfulness": 0.9,
        "abstention_accuracy": 1.0,
        "p50_latency_ms": 1000.0,
        "items": 20.0,
        "scored": 19.0,
        "failed": 1.0,
    }
    failures = compare(baseline, current)
    assert len(failures) == 1 and "errored" in failures[0]


async def test_a_run_that_abstains_on_everything_fails_the_gate(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An abstention scores faithfulness 1.0, so abstaining on all 20 items
    would report perfect faithfulness *and* perfect abstention accuracy. Only
    answer rate separates that run from a working one (TRD §15)."""

    plan_id = (await db.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    db.add(User(email=EVAL_USER_EMAIL, role="user", plan_id=plan_id, status="active"))
    dataset = EvalDataset(name="seed")
    db.add(dataset)
    await db.flush()
    answerable = [f"answerable-{i}" for i in range(3)]
    should_abstain = [f"abstain-{i}" for i in range(2)]
    db.add_all(
        EvalItem(
            dataset_id=dataset.id,
            category="single_document_lookup",
            question=question,
            reference_answer="",
            should_abstain=question in should_abstain,
        )
        for question in [*answerable, *should_abstain]
    )
    await db.commit()
    state = tmp_path / "loaded.json"
    state.write_text(json.dumps({"corpus_collection_id": "01a0ccca-0000-0000-0000-000000000000"}))
    monkeypatch.setattr(runner, "STATE_FILE", state)

    async def fake_run_item(
        factory: async_sessionmaker[AsyncSession],
        *,
        user: User,
        eval_run_id: UUID,
        item: EvalItem,
        mode: str = "auto",
    ) -> tuple[EvalResult, list[str]]:
        result = EvalResult(
            eval_run_id=eval_run_id,
            item_id=item.id,
            answer="",
            faithfulness=1.0,
            abstained=True,
            latency_ms=1000,
        )
        async with factory() as session, session.begin():
            session.add(result)
        return result, []

    monkeypatch.setattr(runner, "_run_item", fake_run_item)

    _, results = await run_eval(subset=None, baseline=False)
    summary = aggregate(results)

    assert summary["faithfulness"] == 1.0
    assert summary["abstention_accuracy"] == 1.0
    assert summary["answer_rate"] == 0.0

    baseline: dict[str, float | None] = {
        "faithfulness": 0.98,
        "abstention_accuracy": 0.75,
        "answer_rate": 0.94,
        "p50_latency_ms": 1000.0,
    }
    failures = compare(baseline, summary)
    assert len(failures) == 1 and "answer rate" in failures[0]
