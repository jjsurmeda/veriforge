"""Outbound address policy for URLs we did not choose (review S3/S4).

The mechanism under test is `netguard.forbidden_reason` plus the two callers
that route every request through it: `BraveSearch._fetch_clean` (a search
result's URL, which an attacker controls) and `admin.service.test_provider`
(an admin-configured base URL, which carries a decrypted credential).

DNS is pinned at `netguard.resolve_host` — the one seam that touches the
resolver — so these tests never reach a live network, and httpx is a
MockTransport, so no socket is opened at all.
"""

import httpx
import pytest

import netguard
from netguard import (
    BlockedAddress,
    ResponseTooLarge,
    assert_public_url,
    fetch_public,
    forbidden_reason,
)
from retrieval.web import BraveSearch

METADATA = "http://169.254.169.254/latest/meta-data/"


def test_forbidden_reason_covers_the_addresses_we_never_dial() -> None:
    import ipaddress

    forbidden = [
        "127.0.0.1",
        "::1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "::",
        "fc00::1",
        "100.64.0.1",  # carrier-grade NAT: not global
    ]
    assert all(forbidden_reason(ipaddress.ip_address(a)) for a in forbidden), (
        "a non-public address was allowed"
    )
    assert forbidden_reason(ipaddress.ip_address("93.184.216.34")) is None
    assert forbidden_reason(ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946")) is None


async def test_assert_public_url_refuses_a_metadata_url_without_dns() -> None:
    with pytest.raises(BlockedAddress):
        await assert_public_url(METADATA)


def _client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_brave_fetch_refuses_a_redirect_to_the_metadata_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public first hop is fine; the redirect inward is the attack."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": METADATA})
        return httpx.Response(200, text="should never be read")

    async def public_only(host: str) -> list[str]:
        assert host == "public.example", host
        return ["93.184.216.34"]

    monkeypatch.setattr(netguard, "resolve_host", public_only)
    provider = BraveSearch("k")
    assert await provider._fetch_clean(_client(handler), "http://public.example/start") == ""
    assert requested == ["http://public.example/start"], (
        f"a request reached the metadata address: {requested}"
    )


async def test_brave_fetch_refuses_a_redirect_to_a_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(301, headers={"location": "http://10.1.2.3/admin"})

    async def public_only(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(netguard, "resolve_host", public_only)
    provider = BraveSearch("k")
    assert await provider._fetch_clean(_client(handler), "http://public.example/start") == ""
    assert requested == ["http://public.example/start"]


async def test_brave_fetch_refuses_a_result_url_that_is_private_already() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text="internal secrets")

    provider = BraveSearch("k")
    assert await provider._fetch_clean(_client(handler), "http://192.168.0.10/admin") == ""
    assert requested == []


async def test_brave_fetch_cuts_off_an_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    oversized = b"a" * (netguard.MAX_FETCH_BYTES + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=oversized)

    async def public_only(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(netguard, "resolve_host", public_only)
    with pytest.raises(ResponseTooLarge):
        await fetch_public(_client(handler), "http://public.example/big")
    # And the caller drops it rather than feeding it to the converter.
    provider = BraveSearch("k")
    assert await provider._fetch_clean(_client(handler), "http://public.example/big") == ""


async def test_brave_fetch_still_converts_a_normal_public_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="# Warranty\n\nCovered for two years.")

    async def public_only(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(netguard, "resolve_host", public_only)
    provider = BraveSearch("k")
    content = await provider._fetch_clean(_client(handler), "http://public.example/warranty")
    assert "Covered for two years." in content


async def test_brave_search_refuses_a_metadata_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end through the provider: the result list is attacker-controlled."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "api.search.brave.com":
            return httpx.Response(
                200, json={"web": {"results": [{"url": METADATA, "title": "meta"}]}}
            )
        return httpx.Response(200, text="credentials")

    client = _client(handler)
    monkeypatch.setattr("httpx.AsyncClient", lambda **_kw: client)
    assert await BraveSearch("k").search("q") == []
    assert requested == ["https://api.search.brave.com/res/v1/web/search?q=q&count=5"]
