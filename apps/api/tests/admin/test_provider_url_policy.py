"""Admin provider URLs must resolve to public addresses (review S4).

`_validate_base_url` rejected three literal loopback host names and nothing
else, so an admin (or an attacker holding an admin session) could point a
provider at RFC1918, link-local or the cloud metadata address — and
`test_provider` then sent the decrypted provider credential there.

DNS is pinned at `netguard.resolve_host`, the one seam that touches the
resolver, and httpx is a MockTransport, so these tests open no socket and
reach no live provider.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import netguard
from config import get_settings
from db.models import LlmProvider
from tests.admin.test_admin import _admin_headers


@pytest.fixture
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()


@pytest.fixture
def recorded_requests(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Any outbound provider request, recorded. Asserted empty when refused."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: client)
    return seen


@pytest.fixture
def resolves_to(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Pin every hostname to one address, so the literal-IP path is untouched."""

    def _pin(address: str) -> None:
        async def fake_resolve(host: str) -> list[str]:
            return [address]

        monkeypatch.setattr(netguard, "resolve_host", fake_resolve)

    return _pin


async def test_provider_create_rejects_a_url_resolving_to_rfc1918(
    client: AsyncClient,
    db: AsyncSession,
    encryption_key: None,
    resolves_to: Callable[[str], None],
    recorded_requests: list[httpx.Request],
) -> None:
    headers = await _admin_headers(client, db)
    resolves_to("10.11.12.13")

    response = await client.post(
        "/admin/providers",
        headers=headers,
        json={
            "name": "shadow",
            "kind": "openai",
            "base_url": "http://shadow.internal/v1",
            "api_key": "sk-not-a-real-key",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "invalid_provider_url"
    assert recorded_requests == [], "a request was made to a refused provider URL"
    stored = (
        await db.execute(select(LlmProvider).where(LlmProvider.name == "shadow"))
    ).scalar_one_or_none()
    assert stored is None, "a provider pointing at RFC1918 was stored"


async def test_provider_create_rejects_a_url_resolving_to_the_metadata_address(
    client: AsyncClient,
    db: AsyncSession,
    encryption_key: None,
    resolves_to: Callable[[str], None],
) -> None:
    headers = await _admin_headers(client, db)
    resolves_to("169.254.169.254")

    response = await client.post(
        "/admin/providers",
        headers=headers,
        json={
            "name": "meta",
            "kind": "openai",
            "base_url": "http://metadata.example/v1",
            "api_key": "sk-not-a-real-key",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "invalid_provider_url"


async def test_provider_create_rejects_a_loopback_ip_literal(
    client: AsyncClient, db: AsyncSession, encryption_key: None
) -> None:
    headers = await _admin_headers(client, db)
    response = await client.post(
        "/admin/providers",
        headers=headers,
        json={"name": "loop", "kind": "openai", "base_url": "http://127.0.0.1:8080/v1"},
    )
    assert response.status_code == 422, response.text


async def test_provider_test_sends_no_credential_to_a_resolved_private_address(
    client: AsyncClient,
    db: AsyncSession,
    encryption_key: None,
    resolves_to: Callable[[str], None],
    recorded_requests: list[httpx.Request],
) -> None:
    """A base URL stored before the fix, or whose DNS changed, is re-checked."""
    headers = await _admin_headers(client, db)
    resolves_to("93.184.216.34")
    created = await client.post(
        "/admin/providers",
        headers=headers,
        json={
            "name": "public-then-private",
            "kind": "openai",
            "base_url": "https://provider.example/v1",
            "api_key": "sk-not-a-real-key",
        },
    )
    assert created.status_code == 201, created.text
    resolves_to("192.168.50.4")

    response = await client.post(f"/admin/providers/{created.json()['id']}/test", headers=headers)

    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "invalid_provider_url"
    assert recorded_requests == [], (
        f"the provider credential was sent to a private address: {recorded_requests}"
    )


async def test_provider_create_accepts_a_public_url(
    client: AsyncClient,
    db: AsyncSession,
    encryption_key: None,
    resolves_to: Callable[[str], None],
) -> None:
    headers = await _admin_headers(client, db)
    resolves_to("93.184.216.34")
    response = await client.post(
        "/admin/providers",
        headers=headers,
        json={
            "name": "public",
            "kind": "openai",
            "base_url": "https://api.example/v1",
            "api_key": "sk-not-a-real-key",
        },
    )
    assert response.status_code == 201, response.text


