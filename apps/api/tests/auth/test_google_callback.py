"""Google OAuth callback: unverified-email refusal and cookie effects (S1, S2).

The callback is the only place a Google subject is attached to a local
account, and it is reached by a browser redirect, so the assertions are on
the 302 response itself: where it points, and which `Set-Cookie` effects it
carries. `exchange_code` is stubbed at the provider seam (testing.md); the
id_token claims it parses are covered separately by
`test_identity_from_id_token_rejects_an_unverified_email`.
"""

import time
from collections.abc import Iterator

import jwt
import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import router as router_module
from auth.google import GoogleIdentity, identity_from_id_token
from config import get_settings
from db.models import OauthAccount
from tests.conftest import signup

CLIENT_ID = "test-google-client-id.apps.googleusercontent.com"


@pytest.fixture
def google_client_id(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def oauth_state(client: AsyncClient, google_client_id: None) -> str:
    """A login leg's state cookie value, `state:verifier` as auth.router reads it."""
    login = await client.get("/auth/google/login", follow_redirects=False)
    assert login.status_code == 307
    raw = login.headers["set-cookie"]
    assert "vf_oauth_state=" in raw
    return raw.split("vf_oauth_state=", 1)[1].split(";", 1)[0]


async def _callback(client: AsyncClient, oauth_state: str) -> Response:
    return await client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": oauth_state.split(":", 1)[0]},
        follow_redirects=False,
    )


# exchange_code verifies the registered claims, not the signature, so any
# 32+ byte string signs these fixtures.
_HMAC_SECRET = "aaaa" * 8


def _id_token(*, email_verified: bool, email: str) -> str:
    return jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": "google-sub-1",
            "email": email,
            "email_verified": email_verified,
            "exp": int(time.time()) + 300,
        },
        _HMAC_SECRET,
        algorithm="HS256",
    )


def test_identity_from_id_token_rejects_an_unverified_email(google_client_id: None) -> None:
    with pytest.raises(RuntimeError, match="not verified"):
        identity_from_id_token(_id_token(email_verified=False, email="victim@test.dev"))


async def test_google_callback_does_not_link_an_unverified_email_to_an_existing_account(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    oauth_state: str,
) -> None:
    """S1: an unverified claim must not attach a subject to a password account."""
    await signup(client, "victim@test.dev")

    async def fake_exchange_code(**_kwargs: object) -> GoogleIdentity:
        # What Google can hand back for an address the user never proved.
        return GoogleIdentity(
            subject="google-sub-1", email="victim@test.dev", email_verified=False
        )

    monkeypatch.setattr(router_module, "exchange_code", fake_exchange_code)
    response = await _callback(client, oauth_state)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/login?error=oauth_failed")
    linked = (
        await db.execute(select(func.count()).select_from(OauthAccount))  # type: ignore[arg-type]
    ).scalar_one()
    assert linked == 0, "an unverified google email was linked to an existing account"
    # And the account it would have hijacked still authenticates by password.
    login = await client.post(
        "/auth/login", json={"email": "victim@test.dev", "password": "password123"}
    )
    assert login.status_code == 200
