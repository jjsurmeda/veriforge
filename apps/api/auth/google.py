"""Google OAuth: authorization code flow with PKCE (TRD §11)."""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from config import get_settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105

OAUTH_STATE_COOKIE = "vf_oauth_state"


def make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(*, state: str, challenge: str, redirect_uri: str) -> str:
    settings = get_settings()
    if not settings.google_client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID is not configured")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


@dataclass
class GoogleIdentity:
    subject: str
    email: str


async def exchange_code(*, code: str, verifier: str, redirect_uri: str) -> GoogleIdentity:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        id_token: str = response.json()["id_token"]
    # The token arrived over TLS from Google directly; verify the registered
    # claims rather than the signature (we never accepted it from a client).
    claims: dict[str, Any] = jwt.decode(
        id_token, options={"verify_signature": False, "verify_exp": True}
    )
    if claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
        raise RuntimeError("unexpected id_token issuer")
    if claims.get("aud") != settings.google_client_id:
        raise RuntimeError("unexpected id_token audience")
    return GoogleIdentity(subject=str(claims["sub"]), email=str(claims["email"]))
