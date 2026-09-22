"""Password hashing, token rotation, refresh reuse detection (TRD §11)."""

import json
import re
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient, Response

from auth.passwords import hash_password, verify_password
from tests.conftest import signup


def test_password_hash_roundtrip_and_reject() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


async def test_signup_login_wrong_password(client: AsyncClient) -> None:
    await signup(client, "a@test.dev")
    wrong = await client.post(
        "/auth/login", json={"email": "a@test.dev", "password": "not-the-password"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["error_code"] == "invalid_credentials"


async def test_signup_duplicate_email(client: AsyncClient) -> None:
    await signup(client, "dup@test.dev")
    again = await client.post(
        "/auth/signup", json={"email": "dup@test.dev", "password": "password123"}
    )
    assert again.status_code == 409


def _refresh_cookie_value(response: Response) -> str:
    raw = response.headers["set-cookie"]
    cookie = SimpleCookie()
    cookie.load(raw)
    return cookie["vf_refresh"].value


async def test_refresh_rotates_token(client: AsyncClient) -> None:
    await signup(client, "rot@test.dev")
    first = await client.post("/auth/refresh")
    assert first.status_code == 200
    second = await client.post("/auth/refresh")
    assert second.status_code == 200
    assert _refresh_cookie_value(first) != _refresh_cookie_value(second)


async def test_refresh_reuse_detection_revokes_family(client: AsyncClient) -> None:
    await signup(client, "reuse@test.dev")
    first = await client.post("/auth/refresh")
    stolen = _refresh_cookie_value(first)

    legit = await client.post("/auth/refresh")  # legitimate rotation
    newest = _refresh_cookie_value(legit)

    client.cookies.clear()  # jar cookies would mask the manual header
    replay = await client.post(
        "/auth/refresh", headers={"Cookie": f"vf_refresh={stolen}"}
    )
    assert replay.status_code == 401

    # Reuse detection revoked the whole family: the legitimately-rotated
    # token must now be rejected too.
    client.cookies.clear()
    after = await client.post(
        "/auth/refresh", headers={"Cookie": f"vf_refresh={newest}"}
    )
    assert after.status_code == 401


async def test_logout_revokes_refresh(client: AsyncClient) -> None:
    await signup(client, "out@test.dev")
    logout = await client.post("/auth/logout")
    assert logout.status_code == 204
    refreshed = await client.post("/auth/refresh")
    assert refreshed.status_code == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    await signup(client, "me@test.dev")
    anon = await client.get("/me")
    assert anon.status_code == 401
    login = await client.post(
        "/auth/login", json={"email": "me@test.dev", "password": "password123"}
    )
    token = login.json()["access_token"]
    me = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "me@test.dev"
    assert body["role"] == "user"
    assert body["plan"]["name"] == "free"


async def test_password_reset_flow(client: AsyncClient, caplog: pytest.LogCaptureFixture) -> None:
    await signup(client, "reset@test.dev")
    caplog.clear()
    with caplog.at_level("INFO", logger="veriforge.email"):
        requested = await client.post(
            "/auth/forgot-password", json={"email": "reset@test.dev"}
        )
    assert requested.status_code == 202

    record = next(
        r.getMessage() for r in caplog.records if "reset-password?token=" in r.getMessage()
    )
    body = json.loads(record)["body"]  # transport logs structured JSON
    token = parse_qs(urlparse(_extract_link(body)).query)["token"][0]

    done = await client.post(
        "/auth/reset-password", json={"token": token, "password": "newpassword456"}
    )
    assert done.status_code == 204, done.text

    old_pw = await client.post(
        "/auth/login", json={"email": "reset@test.dev", "password": "password123"}
    )
    assert old_pw.status_code == 401
    new_pw = await client.post(
        "/auth/login", json={"email": "reset@test.dev", "password": "newpassword456"}
    )
    assert new_pw.status_code == 200


async def test_forgot_password_unknown_email_is_still_202(client: AsyncClient) -> None:
    response = await client.post("/auth/forgot-password", json={"email": "nobody@test.dev"})
    assert response.status_code == 202


def _extract_link(log_body: str) -> str:
    match = re.search(r"https?://\S+reset-password\?token=\S+", log_body)
    assert match is not None
    return match.group(0)
