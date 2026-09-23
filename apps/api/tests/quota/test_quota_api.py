from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Plan
from tests.conftest import signup


async def test_quota_endpoint_returns_server_computed_windows(
    client: AsyncClient, db: AsyncSession
) -> None:
    auth = await signup(client, "quota-api@test.dev")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = await client.get("/me/quota", params={"mode": "fast"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["limit_5h"] > 0
    assert body["limit_month"] > 0
    assert body["reset_at_5h"]
    assert body["reset_at_month"]
    assert body["mode"] == "fast"


async def test_run_creation_returns_quota_error_with_reset(
    client: AsyncClient, db: AsyncSession
) -> None:
    auth = await signup(client, "quota-blocked@test.dev")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    chat = (await client.post("/chats", json={}, headers=headers)).json()

    await db.execute(update(Plan).values(credits_5h=0, credits_month=0))
    await db.commit()

    response = await client.post(
        f"/chats/{chat['id']}/runs",
        json={"message": "hello", "mode": "fast", "source": "auto"},
        headers=headers,
    )

    assert response.status_code == 429
    body = response.json()
    assert body["error_code"] == "quota_exceeded"
    assert body["detail"]["reset_at"]
