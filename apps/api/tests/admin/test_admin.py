from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import AuditLog, DecisionShadow, RunEvent, Setting, User
from runtime import load_active_runtime
from schemas.events import Decision
from tests.conftest import make_run_row, signup


async def _admin_headers(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    auth = await signup(client, f"admin-{id(db)}@test.dev")
    user = (
        await db.execute(select(User).where(User.email == f"admin-{id(db)}@test.dev"))
    ).scalar_one()
    user.role = "admin"
    await db.commit()
    return {"Authorization": f"Bearer {auth['access_token']}"}


def _decision_event(
    run_id: UUID,
    seq: int,
    *,
    name: str,
    value: str | float,
    engine: str,
    latency_ms: int,
    call_id: str,
    stage: str,
    batch_size: int,
    threshold: float | None,
) -> RunEvent:
    event = Decision(
        run_id=str(run_id),
        name=name,
        value=value,
        engine=engine,
        latency_ms=latency_ms,
        stage=stage,
        call_id=call_id,
        batch_size=batch_size,
        threshold=threshold,
    )
    return RunEvent(
        run_id=run_id,
        seq=seq,
        type="decision",
        payload=event.model_dump(mode="json"),
        created_at=datetime.now(UTC),
    )


async def test_decision_stats_use_call_latency_and_collapse_dynamic_names(
    client: AsyncClient, db: AsyncSession
) -> None:
    run_id, _ = await make_run_row(db)
    db.add_all(
        [
            _decision_event(
                run_id,
                1,
                name="guard_injection",
                value=0.03,
                engine="jev",
                latency_ms=100,
                call_id="call-a",
                stage="ingress",
                batch_size=2,
                threshold=0.85,
            ),
            _decision_event(
                run_id,
                2,
                name="intent",
                value="lookup",
                engine="jev",
                latency_ms=200,
                call_id="call-a",
                stage="ingress",
                batch_size=2,
                threshold=None,
            ),
            _decision_event(
                run_id,
                3,
                name="chunk_injection_0",
                value=0.8,
                engine="fallback",
                latency_ms=300,
                call_id="call-b",
                stage="sanitize",
                batch_size=2,
                threshold=0.70,
            ),
            _decision_event(
                run_id,
                4,
                name="chunk_injection_1",
                value=0.1,
                engine="fallback",
                latency_ms=400,
                call_id="call-b",
                stage="sanitize",
                batch_size=2,
                threshold=0.70,
            ),
            _decision_event(
                run_id,
                5,
                name="c1",
                value="supported",
                engine="jev",
                latency_ms=500,
                call_id="call-c",
                stage="claim_verdict",
                batch_size=1,
                threshold=None,
            ),
            _decision_event(
                run_id,
                6,
                name="off_topic",
                value=0.1,
                engine="jev",
                latency_ms=400,
                call_id="call-d",
                stage="ingress",
                batch_size=1,
                threshold=0.80,
            ),
            # The three numbered families, each a single check whose name
            # happens to carry an index.
            _decision_event(
                run_id,
                7,
                name="entity_0",
                value=0.6,
                engine="jev",
                latency_ms=250,
                call_id="call-e",
                stage="sufficient",
                batch_size=2,
                threshold=0.50,
            ),
            _decision_event(
                run_id,
                8,
                name="entity_1",
                value=0.2,
                engine="jev",
                latency_ms=250,
                call_id="call-e",
                stage="sufficient",
                batch_size=2,
                threshold=0.50,
            ),
            _decision_event(
                run_id,
                9,
                name="conflict_0",
                value=0.1,
                engine="jev",
                latency_ms=300,
                call_id="call-f",
                stage="conflict",
                batch_size=1,
                threshold=0.60,
            ),
            _decision_event(
                run_id,
                10,
                name="passage_0",
                value=0.83,
                engine="jev",
                latency_ms=120,
                call_id="call-g",
                stage="rerank",
                batch_size=3,
                threshold=None,
            ),
            _decision_event(
                run_id,
                11,
                name="passage_1",
                value=0.42,
                engine="jev",
                latency_ms=120,
                call_id="call-g",
                stage="rerank",
                batch_size=3,
                threshold=None,
            ),
        ]
    )
    db.add_all(
        [
            DecisionShadow(
                run_id=run_id,
                decision="intent",
                jev_answer={
                    "value": "lookup",
                    "probability": 0.8,
                    "reasoning": "private shadow reasoning",
                },
                fallback_answer={
                    "value": "summarize",
                    "probability": 0.7,
                    "reasoning": "private fallback reasoning",
                },
                agree=False,
                created_at=datetime.now(UTC),
            ),
            DecisionShadow(
                run_id=run_id,
                decision="risk",
                jev_answer={"value": "low", "probability": 0.8},
                fallback_answer={"value": "low", "probability": 0.75},
                agree=True,
                created_at=datetime.now(UTC),
            ),
        ]
    )
    await db.commit()
    headers = await _admin_headers(client, db)

    response = await client.get("/admin/decisions/stats?hours=24", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 11
    assert body["jev_count"] == 9
    assert body["fallback_count"] == 2
    assert body["fallback_share"] == pytest.approx(2 / 11)
    assert body["jev_latency_p50_ms"] == pytest.approx(275)
    assert body["jev_latency_p95_ms"] == pytest.approx(475)
    assert body["ingress_p95_ms"] == pytest.approx(390)

    by_decision = {row["name_or_prefix"]: row for row in body["by_decision"]}
    assert by_decision["chunk_injection_*"]["count"] == 2
    assert by_decision["chunk_injection_*"]["fallback_count"] == 2
    assert by_decision["claim_verdicts"]["count"] == 1
    # Lane E item 3: the per-passage families collapse to one row each. A
    # screenshot of the panel as a real run showed the table as a wall of
    # `passage_0`, `passage_1`, … which is the KI-22 "mostly Jev calls"
    # reading, in the one place an operator looks for totals.
    assert "passage_0" not in by_decision
    assert by_decision["passage_relevance"]["count"] >= 1
    assert "entity_0" not in by_decision
    assert by_decision["entity_match"]["count"] == 2
    assert "conflict_0" not in by_decision
    assert by_decision["conflict_pairs"]["count"] == 1
    assert by_decision["passage_relevance"]["count"] == 2
    # No numbered row survives for any of the three families.
    assert not any(
        name.split("_")[-1].isdigit()
        for name in by_decision
        if name.startswith(("passage", "entity", "conflict"))
    )
    assert body["shadow"]["sampled"] == 2
    assert body["shadow"]["agree_rate"] == pytest.approx(0.5)
    assert len(body["shadow"]["recent_disagreements"]) == 1
    assert "private shadow reasoning" not in response.text
    assert "private fallback reasoning" not in response.text
    assert body["breaker"]["state"] == "closed"
    assert body["targets"] == {"ingress_p95_ms": 600, "fallback_share": 0.05}

    clamped = await client.get("/admin/decisions/stats?hours=999", headers=headers)
    assert clamped.status_code == 200


async def test_non_admin_cannot_access_decision_stats(client: AsyncClient) -> None:
    auth = await signup(client, "decision-stats-user@test.dev")
    response = await client.get(
        "/admin/decisions/stats",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
    )
    assert response.status_code == 403


async def _demo_headers(client: AsyncClient, db: AsyncSession, email: str) -> dict[str, str]:
    """Sign a user in, then set its role to `demo` directly.

    Role assignment is admin-only in the product and there is no demo
    endpoint yet (lane E item 4), so the row is written here the way the
    migration that seeds the demo account would write it.
    """
    auth = await signup(client, email)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    user.role = "demo"
    await db.commit()
    return {"Authorization": f"Bearer {auth['access_token']}"}


class TestDemoRoleDecisionStats:
    """Lane E item 3. The demo role may READ the engine statistics; the
    widening must not leak into any write, and must not touch a normal
    user's access."""

    async def test_demo_role_can_read_decision_stats(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        run_id, _ = await make_run_row(db)
        db.add(
            _decision_event(
                run_id,
                1,
                name="sufficient",
                value=0.7,
                engine="jev",
                latency_ms=200,
                call_id="call-a",
                stage="sufficient",
                batch_size=1,
                threshold=0.05,
            )
        )
        await db.commit()
        headers = await _demo_headers(client, db, "demo-reads-stats@test.dev")

        response = await client.get("/admin/decisions/stats?hours=24", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1

    async def test_demo_role_cannot_write_anywhere_in_admin(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """Every write stays admin-only. Enumerated rather than sampled: the
        whole risk of this change is that some future endpoint reuses the
        widened dependency, and a list that names all of them fails loudly when
        one does."""
        headers = await _demo_headers(client, db, "demo-cannot-write@test.dev")

        # The bodies are deliberately minimal: the request must be refused on
        # the role, before any body validation, so a 403 here proves the
        # dependency and not a schema coincidence.
        forbidden = [
            ("post", "/admin/providers", {"name": "p", "kind": "openrouter", "api_key": "k"}),
            ("post", "/admin/models", {"model_id": "m", "provider_id": str(uuid4())}),
            ("post", "/admin/roles", {"role": "generator", "model_id": "m"}),
            ("post", "/admin/plans", {"name": "x", "credits_5h": 1, "credits_month": 1}),
            ("patch", "/admin/settings", {"retrieval": {"top_k": 1}}),
            ("post", "/admin/settings/1/activate", None),
            ("post", "/admin/invites", {"count": 1}),
            ("patch", "/admin/users/00000000-0000-0000-0000-000000000000", {"role": "admin"}),
        ]
        for method, path, body in forbidden:
            response = await client.request(method, path, headers=headers, json=body)
            assert response.status_code == 403, f"{method.upper()} {path} -> {response.status_code}"

        reads_denied = ["/admin/audit", "/admin/users", "/admin/settings", "/admin/invites"]
        for path in reads_denied:
            response = await client.get(path, headers=headers)
            assert response.status_code == 403, f"GET {path} -> {response.status_code}"

    async def test_a_normal_users_access_is_unchanged(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        """The widening is `demo` plus `admin`, not "not admin": a plain user
        is still refused the statistics read."""
        auth = await signup(client, "plain-user-still-refused@test.dev")
        response = await client.get(
            "/admin/decisions/stats",
            headers={"Authorization": f"Bearer {auth['access_token']}"},
        )
        assert response.status_code == 403

    async def test_admin_still_reads(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        headers = await _admin_headers(client, db)
        response = await client.get("/admin/decisions/stats", headers=headers)
        assert response.status_code == 200


async def test_decision_stats_report_rerank_latency_and_null_when_absent(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Lane E item 3: the showcase shows rerank latency next to Jev's, from
    the `rerank` step events. Absent reranking must read as null so the panel
    says "no data yet" rather than showing a bar at zero."""
    headers = await _admin_headers(client, db)
    empty = await client.get("/admin/decisions/stats", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["rerank_latency_p50_ms"] is None
    assert empty.json()["rerank_latency_p95_ms"] is None

    run_id, _ = await make_run_row(db)
    now = datetime.now(UTC)
    db.add_all(
        RunEvent(
            run_id=run_id,
            seq=n,
            type="step.completed",
            payload={
                "run_id": str(run_id),
                "seq": n,
                "ts": now.isoformat(),
                "type": "step.completed",
                "node": "rerank",
                "label": "rerank",
                "duration_ms": ms,
            },
            created_at=now,
        )
        for n, ms in enumerate([100, 200, 300, 400], start=1)
    )
    # A non-rerank step in the same run must not pollute the figure.
    db.add(
        RunEvent(
            run_id=run_id,
            seq=9,
            type="step.completed",
            payload={
                "run_id": str(run_id),
                "seq": 9,
                "ts": now.isoformat(),
                "type": "step.completed",
                "node": "generate",
                "label": "generate",
                "duration_ms": 9000,
            },
            created_at=now,
        )
    )
    await db.commit()

    body = (await client.get("/admin/decisions/stats", headers=headers)).json()
    assert body["rerank_latency_p50_ms"] == pytest.approx(250)
    assert body["rerank_latency_p95_ms"] < 1000


async def test_settings_recover_inactive_seed_and_allocate_unique_versions(
    client: AsyncClient, db: AsyncSession
) -> None:
    db.add(Setting(version=1, data={"decision_engine_mode": "auto"}, active=False))
    await db.commit()
    headers = await _admin_headers(client, db)

    active = await client.get("/admin/settings", headers=headers)
    assert active.status_code == 200
    assert active.json()["version"] == 1

    responses = await asyncio.gather(
        client.patch(
            "/admin/settings", headers=headers, json={"retrieval": {"top_k": 9}}
        ),
        client.patch(
            "/admin/settings", headers=headers, json={"retrieval": {"top_k": 10}}
        ),
    )
    assert [response.status_code for response in responses] == [200, 200]

    versions = await client.get("/admin/settings/versions", headers=headers)
    assert versions.status_code == 200
    assert sorted(row["version"] for row in versions.json()) == [1, 2, 3]
    assert sum(row["active"] for row in versions.json()) == 1


async def test_the_generator_temperature_is_admin_tunable(
    client: AsyncClient, db: AsyncSession
) -> None:
    """P5 (D5 review should-fix 1). The generator's temperature is a
    product-quality decision made on the full eval sets, so an admin has to be
    able to change it from the admin API. It lived in the env-only pydantic
    `Settings`, which no admin route can reach, so changing it needed a
    redeploy — unlike every other tunable (reranker, thresholds, top_k)."""
    headers = await _admin_headers(client, db)

    ok = await client.patch(
        "/admin/settings",
        headers=headers,
        json={"generation": {"temperature": 0.35}},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["generation"]["temperature"] == 0.35

    # `null` is the default and is accepted: it means "send no temperature",
    # so the provider default applies (KI-32).
    cleared = await client.patch(
        "/admin/settings", headers=headers, json={"generation": {"temperature": None}}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["generation"]["temperature"] is None

    for bad in (3, -1, "hot", True):
        rejected = await client.patch(
            "/admin/settings", headers=headers, json={"generation": {"temperature": bad}}
        )
        assert rejected.status_code == 422, (bad, rejected.text)


async def test_non_admin_cannot_access_admin_settings(client: AsyncClient) -> None:
    auth = await signup(client, "not-admin@test.dev")
    response = await client.get(
        "/admin/settings", headers={"Authorization": f"Bearer {auth['access_token']}"}
    )
    assert response.status_code == 403


async def test_provider_create_encrypts_key_and_never_returns_it(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    headers = await _admin_headers(client, db)

    response = await client.post(
        "/admin/providers",
        headers=headers,
        json={
            "name": "openai",
            "kind": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-secret",
        },
    )

    assert response.status_code == 201
    assert "api_key" not in response.json()
    assert response.json()["has_api_key"] is True
    cleared = await client.patch(
        f"/admin/providers/{response.json()['id']}",
        headers=headers,
        json={"api_key": None, "base_url": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["has_api_key"] is False
    get_settings.cache_clear()


async def test_admin_crud_smoke_covers_catalogue_roles_plans_and_users(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers = await _admin_headers(client, db)

    providers = await client.get("/admin/providers", headers=headers)
    models = await client.get("/admin/models", headers=headers)
    roles = await client.get("/admin/roles", headers=headers)
    plans = await client.get("/admin/plans", headers=headers)
    users = await client.get("/admin/users", headers=headers)
    assert providers.status_code == 200
    assert models.status_code == 200
    assert {row["role"] for row in roles.json()} >= {"generator", "rewriter"}
    assert len(plans.json()) == 2
    assert users.status_code == 200

    model_id = models.json()[0]["id"]
    disabled = await client.patch(
        f"/admin/models/{model_id}", headers=headers, json={"enabled": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    plan_id = plans.json()[0]["id"]
    updated_plan = await client.patch(
        f"/admin/plans/{plan_id}", headers=headers, json={"credits_month": 123456}
    )
    assert updated_plan.status_code == 200
    assert updated_plan.json()["credits_month"] == 123456

    role = await client.post(
        "/admin/roles",
        headers=headers,
        json={"role": "suggester", "model_id": "anthropic/claude-haiku-4.5"},
    )
    assert role.status_code == 200
    assert role.json()["model_id"] == "anthropic/claude-haiku-4.5"


async def test_settings_version_rollback_and_audit(client: AsyncClient, db: AsyncSession) -> None:
    headers = await _admin_headers(client, db)
    original = (await client.get("/admin/settings", headers=headers)).json()
    original_version = original["version"]

    changed = await client.patch(
        "/admin/settings",
        headers=headers,
        json={"retrieval": {"top_k": 3}},
    )
    assert changed.status_code == 200
    assert changed.json()["version"] > original_version
    assert changed.json()["data"]["retrieval"]["top_k"] == 3

    rollback = await client.post(f"/admin/settings/{original_version}/activate", headers=headers)
    assert rollback.status_code == 200
    assert rollback.json()["version"] == original_version

    active = await load_active_runtime(db)
    assert active.get("retrieval.top_k") == 8

    audit = (await db.execute(select(AuditLog).order_by(AuditLog.created_at))).scalars().all()
    assert any(row.action == "settings.update" for row in audit)
    assert any(row.action == "settings.activate" for row in audit)
