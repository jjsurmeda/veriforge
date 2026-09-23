from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import AuditLog, User
from runtime import load_active_runtime
from tests.conftest import signup


async def _admin_headers(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    auth = await signup(client, f"admin-{id(db)}@test.dev")
    user = (
        await db.execute(select(User).where(User.email == f"admin-{id(db)}@test.dev"))
    ).scalar_one()
    user.role = "admin"
    await db.commit()
    return {"Authorization": f"Bearer {auth['access_token']}"}


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
