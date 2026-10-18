"""R2c items 1-3: the reranker registry, per-run selection, and refusal."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from db.models import Run
from decisions.thresholds import RerankerUncalibrated, reranker_threshold
from tests.chats.test_chats_runs import _auth, _make_chat, _parse_sse, fake_llm  # noqa: F401


async def _post(client: AsyncClient, reranker: str | None) -> tuple[int, dict[str, object]]:
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)
    body: dict[str, object] = {"message": "say hi"}
    if reranker is not None:
        body["reranker"] = reranker
    r = await client.post(f"/chats/{chat_id}/runs", json=body, headers=headers)
    return r.status_code, r.json()


async def test_rerankers_endpoint_lists_the_registry(client: AsyncClient) -> None:
    headers = await _auth(client)
    rows = (await client.get("/rerankers", headers=headers)).json()
    by_id = {r["id"]: r for r in rows}
    assert list(by_id) == ["jev", "cohere", "nvidia", "fused"]
    assert by_id["jev"]["kind"] == "decision-model"
    assert by_id["jev"]["calibrated"] is True and by_id["jev"]["is_default"] is True
    assert by_id["cohere"]["kind"] == "traditional"
    assert all(not by_id[i]["calibrated"] for i in ("cohere", "nvidia", "fused"))


async def test_unknown_reranker_is_refused(client: AsyncClient) -> None:
    status, body = await _post(client, "nope")
    assert status == 422 and body["error_code"] == "reranker_unavailable"


async def test_keyless_reranker_is_refused_as_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("retrieval.rerank.get_settings", lambda: Settings(cohere_api_key=""))
    status, body = await _post(client, "cohere")
    assert status == 422 and body["error_code"] == "reranker_unavailable"


@pytest.mark.parametrize("rid", ["cohere", "nvidia", "fused"])
async def test_uncalibrated_reranker_is_refused_never_replaced_by_jev(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, rid: str
) -> None:
    monkeypatch.setattr(
        "retrieval.rerank.get_settings",
        lambda: Settings(cohere_api_key="k", nvidia_api_key="k"),
    )
    status, body = await _post(client, rid)
    assert status == 422 and body["error_code"] == "reranker_uncalibrated"


async def test_admin_forced_uncalibrated_default_fails_the_first_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("retrieval.rerank.get_settings", lambda: Settings(nvidia_api_key="k"))
    monkeypatch.setattr(
        "chats.router.load_active_runtime",
        _runtime_with("nvidia"),
    )
    status, body = await _post(client, None)
    assert status == 422 and body["error_code"] == "reranker_uncalibrated"


def _runtime_with(reranker: str):  # type: ignore[no-untyped-def]
    from runtime import RuntimeSettings

    async def load(_: object) -> RuntimeSettings:
        return RuntimeSettings.from_data(1, {"retrieval": {"reranker": reranker}})

    return load


async def test_jev_run_records_its_reranker(
    client: AsyncClient,
    db: AsyncSession,
    fake_llm: None,  # noqa: F811
) -> None:
    headers = await _auth(client)
    chat_id = await _make_chat(client, headers)
    started = await client.post(
        f"/chats/{chat_id}/runs", json={"message": "say hi", "reranker": "jev"}, headers=headers
    )
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]
    async with client.stream("GET", f"/runs/{run_id}/stream", headers=headers) as response:
        async for event_type, _ in _parse_sse(response.aiter_lines()):
            if event_type == "run.completed":
                break
    db.expire_all()
    run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    assert run.metrics is not None and run.metrics.get("reranker") == "jev"


def test_jev_thresholds_are_the_existing_values_and_others_fail_closed() -> None:
    assert reranker_threshold("evidence_floor", "jev") == 0.455
    assert reranker_threshold("stream_line", "jev") == 0.60
    assert reranker_threshold("evidence_floor", "fallback") == 0.455
    for rid in ("cohere", "nvidia", "fused"):
        with pytest.raises(RerankerUncalibrated):
            reranker_threshold("evidence_floor", rid)


def test_gate_engine_is_the_real_reranker_id() -> None:
    from graph.stages.evidence_stage import _gate_engine
    from retrieval.rerank import CohereRerank, FusedOrderRerank, NvidiaRerank

    assert _gate_engine(CohereRerank("k", "m")) == "cohere"
    assert _gate_engine(NvidiaRerank("k", "m")) == "nvidia"
    assert _gate_engine(FusedOrderRerank()) == "fused"
    assert _gate_engine(object()) == "jev"  # type: ignore[arg-type]


def test_deep_gate_refuses_an_uncalibrated_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import uuid4

    from graph.stages.deep_evidence_stage import deep_gate_decision

    monkeypatch.setattr("decisions.thresholds.runtime_value", lambda n, d: "cohere")
    with pytest.raises(RerankerUncalibrated):
        deep_gate_decision(uuid4(), [])
