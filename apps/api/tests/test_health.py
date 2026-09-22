from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from main import app


async def _override_session_ok() -> AsyncIterator[AsyncSession]:
    session = AsyncMock(spec=AsyncSession)
    yield session


async def _override_session_unreachable() -> AsyncIterator[AsyncSession]:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = OSError("db down")
    yield session


def test_healthz_returns_ok_when_db_reachable() -> None:
    app.dependency_overrides[get_session] = _override_session_ok
    try:
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "db": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_healthz_returns_503_when_db_unreachable() -> None:
    app.dependency_overrides[get_session] = _override_session_unreachable
    try:
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 503
        body = response.json()
        assert body["error_code"] == "db_unreachable"
        assert body["message"] == "Database is unreachable"
        assert body["detail"] is None
    finally:
        app.dependency_overrides.clear()
