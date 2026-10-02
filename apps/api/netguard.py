"""Outbound-request address policy, in one place.

Two callers make HTTP requests to a URL they did not choose, and both can be
pointed at an address inside our own network:

- `retrieval.web.BraveSearch` fetches the URLs a search result contains, and
  an attacker controls those;
- `admin.service.test_provider` sends a decrypted provider credential to an
  admin-configured base URL.

So the policy lives here rather than in either caller: resolve the host, then
refuse loopback, private, link-local (169.254.169.254 is the cloud metadata
endpoint), multicast, reserved and non-global addresses. It is checked for
*every* hop — a public URL that redirects inward is the interesting case — and
`fetch_public` is the only function here that opens a connection, so a caller
cannot follow a redirect past the check by accident.
"""

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# A search result is a page of prose. Anything past this is a download, and
# MarkItDown would hold all of it in memory.
MAX_FETCH_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5


class BlockedAddress(ValueError):
    """The URL's host resolves to an address this process refuses to reach."""


class ResponseTooLarge(ValueError):
    """The body exceeded `max_bytes`; it is dropped rather than truncated."""


def forbidden_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Why this address is not a legitimate public destination, or None."""
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_private:
        return "private"
    if ip.is_reserved or ip.is_unspecified:
        return "reserved"
    if not ip.is_global:
        return "non-global"
    return None


async def resolve_host(host: str) -> list[str]:
    """Every address `host` resolves to, as strings.

    A separate function so the IP-literal path in `addresses_for_url` needs no
    resolver at all, and so tests can pin DNS at one seam.
    """
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def addresses_for_url(url: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """The addresses a request to `url` could land on, or raise for a bad URL."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        raise BlockedAddress(f"not an HTTP(S) URL: {url}")
    literal = host.strip("[]")
    try:
        return [ipaddress.ip_address(literal)]
    except ValueError:
        pass
    resolved = await resolve_host(host)
    if not resolved:
        raise BlockedAddress(f"host resolved to nothing: {host}")
    return [ipaddress.ip_address(address) for address in resolved]


async def assert_public_url(url: str) -> None:
    """Raise `BlockedAddress` unless every address `url` resolves to is public."""
    for ip in await addresses_for_url(url):
        reason = forbidden_reason(ip)
        if reason is not None:
            raise BlockedAddress(f"{url} resolves to {ip} ({reason})")


async def fetch_public(
    client: httpx.AsyncClient, url: str, *, max_bytes: int = MAX_FETCH_BYTES
) -> bytes:
    """GET `url`, re-checking the address at every redirect, under a byte cap.

    Redirects are followed here rather than by the client, because the client
    cannot be told to re-resolve between hops.
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        await assert_public_url(current)
        async with client.stream("GET", current, follow_redirects=False) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise BlockedAddress(f"redirect without a location: {current}")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise ResponseTooLarge(f"{current} exceeded {max_bytes} bytes")
            return bytes(body)
    raise BlockedAddress(f"more than {MAX_REDIRECTS} redirects from {url}")


def log_blocked(url: str, exc: Exception) -> None:
    """One log line for a refused outbound request, from either caller."""
    logger.warning("refused outbound request", extra={"url": url, "error": str(exc)})
