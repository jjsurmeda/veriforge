"""Attribution seams (KI-18, D2 2c): Jev ids recorded, lookups deferred.

Jev uses raw httpx, not litellm.acompletion, so before D2 every Jev
millisecond was counted as "our overhead". Jev's OpenRouter response
carries the same `x-generation-id` header (verified live 2026-10-01), so
the Jev client reports it through `generation_id_sink` whenever
`record_generation_ids` is active. The stats lookups themselves moved
from per-item (~20 s each, the record's landing delay) to one deferred
pass at the end of run_eval.

Which field of a record holds the duration — Jev's `latency` rather than
`generation_time` (A3) — is in `test_jev_latency_attribution.py`.
"""

import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import get_settings
from db.models import EvalDataset, EvalItem, EvalResult, Plan, User
from decisions import jev
from decisions.jev import JevClient
from evals import runner
from evals.attribution import Attribution, record_generation_ids
from evals.loader import EVAL_USER_EMAIL
from evals.runner import run_eval
from schemas.decisions import Noul, Question

pytestmark = pytest.mark.asyncio

ANSWERS = {"answers": {"q": {"type": "noul", "noul": 0.5}}}


async def test_jev_client_reports_generation_id_to_the_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=ANSWERS, headers={"x-generation-id": "gen-test-1"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    recorded: list[str] = []
    monkeypatch.setattr(jev, "generation_id_sink", recorded.append)
    questions: dict[str, Question] = {"q": Noul(prompt="q?")}

    await JevClient(client=client).decide(state="s", questions=questions)
    assert recorded == ["gen-test-1"]


async def test_jev_client_reports_nothing_without_a_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=ANSWERS, headers={"x-generation-id": "gen-test-2"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(jev, "generation_id_sink", None)
    questions: dict[str, Question] = {"q": Noul(prompt="q?")}

    # No sink, no error — production behaviour is unchanged.
    await JevClient(client=client).decide(state="s", questions=questions)


async def test_record_generation_ids_collects_jev_calls_and_restores_the_sink() -> None:
    original_sink = jev.generation_id_sink
    async with record_generation_ids() as ids:
        assert jev.generation_id_sink is not original_sink
        assert jev.generation_id_sink is not None
        jev.generation_id_sink("gen-jev-1")
        assert ids == ["gen-jev-1"]
    assert jev.generation_id_sink is original_sink


async def test_run_eval_defers_attribution_and_persists_overhead(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One deferred pass after the loop: the fake item contributes two
    generation ids, the fake attribute() answers once at the end, and the
    overhead lands on the in-memory result and the persisted row."""
    plan_id = (await db.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    db.add(User(email=EVAL_USER_EMAIL, role="user", plan_id=plan_id, status="active"))
    dataset = EvalDataset(name="seed")
    db.add(dataset)
    await db.flush()
    db.add(
        EvalItem(
            dataset_id=dataset.id,
            category="single_document_lookup",
            question="q",
            reference_answer="",
            should_abstain=False,
        )
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
            answer="ok",
            faithfulness=0.9,
            abstained=False,
            latency_ms=5000,
            stage_ms={"rerank": 100},
        )
        async with factory() as session, session.begin():
            session.add(result)
        return result, ["gen-1", "gen-2"]

    attribute_calls: list[tuple[float, list[str]]] = []

    async def fake_attribute(total_ms: float, generation_ids: list[str]) -> Attribution:
        attribute_calls.append((total_ms, generation_ids))
        return Attribution(total_ms=total_ms, provider_ms=4200, attributed=2, unattributed=0)

    monkeypatch.setattr(runner, "_run_item", fake_run_item)
    monkeypatch.setattr(runner, "attribute", fake_attribute)

    _, results = await run_eval(subset=None, baseline=False)

    # Deferred: exactly one attribution pass, after the item finished.
    assert attribute_calls == [(5000, ["gen-1", "gen-2"])]
    (_, result), = results
    assert result.stage_ms is not None
    assert result.stage_ms["provider_ms"] == 4200
    assert result.stage_ms["generations_attributed"] == 2
    assert result.stage_ms["our_overhead_ms"] == 800
    assert result.stage_ms["rerank"] == 100

    persisted = (
        await db.execute(select(EvalResult).where(EvalResult.id == result.id))
    ).scalar_one()
    assert persisted.stage_ms is not None
    assert persisted.stage_ms["our_overhead_ms"] == 800


async def test_run_eval_skips_attribution_for_items_without_ids(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An item with no recorded calls records no overhead figure (TRD §15:
    null, never a fabricated zero)."""
    plan_id = (await db.execute(select(Plan.id).where(Plan.name == "free"))).scalar_one()
    db.add(User(email=EVAL_USER_EMAIL, role="user", plan_id=plan_id, status="active"))
    dataset = EvalDataset(name="seed")
    db.add(dataset)
    await db.flush()
    db.add(
        EvalItem(
            dataset_id=dataset.id,
            category="single_document_lookup",
            question="q",
            reference_answer="",
            should_abstain=False,
        )
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
            answer="ok",
            faithfulness=0.9,
            abstained=False,
            latency_ms=5000,
        )
        async with factory() as session, session.begin():
            session.add(result)
        return result, []

    async def fake_attribute(total_ms: float, generation_ids: list[str]) -> Attribution:
        raise AssertionError("attribute must not run for an item with no ids")

    monkeypatch.setattr(runner, "_run_item", fake_run_item)
    monkeypatch.setattr(runner, "attribute", fake_attribute)

    _, results = await run_eval(subset=None, baseline=False)
    (_, result), = results
    assert not (result.stage_ms or {}).get("our_overhead_ms")
