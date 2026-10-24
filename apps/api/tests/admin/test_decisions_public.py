from __future__ import annotations

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DecisionShadow
from tests.conftest import make_run_row, signup


async def test_ordinary_user_reads_stats_without_other_users_run_ids(
    client: AsyncClient, db: AsyncSession
) -> None:
    run_id, _ = await make_run_row(db)
    db.add(
        DecisionShadow(
            run_id=run_id,
            decision="intent",
            jev_answer={"value": "lookup", "probability": 0.8},
            fallback_answer={"value": "summarize", "probability": 0.7},
            agree=False,
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()
    auth = await signup(client, "ordinary-decisions@test.dev")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = await client.get("/decisions/stats?hours=24", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["shadow"]["sampled"] == 1
    assert body["shadow"]["recent_disagreements"] == []
    assert str(run_id) not in response.text


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    assert (await client.get("/decisions/stats")).status_code == 401


async def test_admin_endpoint_still_refuses_ordinary_users(client: AsyncClient) -> None:
    auth = await signup(client, "still-refused@test.dev")
    response = await client.get(
        "/admin/decisions/stats", headers={"Authorization": f"Bearer {auth['access_token']}"}
    )
    assert response.status_code == 403


async def test_demo_role_stays_read_only(client: AsyncClient, db: AsyncSession) -> None:
    """The new read route does not touch `deny_read_only`: demo still cannot upload."""
    from sqlalchemy import select

    from db.models import User

    auth = await signup(client, "demo-still-readonly@test.dev")
    user = (
        await db.execute(select(User).where(User.email == "demo-still-readonly@test.dev"))
    ).scalar_one()
    user.role = "demo"
    await db.commit()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    assert (await client.get("/decisions/stats", headers=headers)).status_code == 200
    chat = await client.post("/chats", json={}, headers=headers)
    chat_id = chat.json()["id"]
    upload = await client.post(
        f"/chats/{chat_id}/documents",
        files={"file": ("n.md", b"# hi", "text/markdown")},
        headers=headers,
    )
    assert upload.status_code == 403
    assert upload.json()["error_code"] == "read_only_account"
