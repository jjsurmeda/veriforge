"""The Caddyfile must mirror the Vite dev proxy, or the SPA breaks in production only.

`apps/web/vite.config.ts` lists the API prefixes the dev server proxies, and
adds a `bypassDocumentNavigation` rule so a top-level navigation to a
colliding path is served the SPA entry point rather than proxied. The
Caddyfile reproduces both, because there is no Vite dev server in production.

The failure this prevents is silent and expensive: `/library` and
`/auth/callback` are SPA routes that collide with api prefixes, so if the two
lists drift, the route works in dev and 404s (or returns raw JSON) through
CloudFront. Nothing in the local dev stack notices.

Runs under pytest, and with no pytest at all:

    pytest infra/tests/                     # if pytest is installed
    python3 infra/tests/test_caddyfile_parity.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VITE_CONFIG = REPO / "apps" / "web" / "vite.config.ts"
CADDYFILE = REPO / "Caddyfile"


def _strip_comments(source: str) -> str:
    """Drop whole-line comments.

    Both files use line comments only (Caddy `#`, TS `//`), so a line-based
    strip is enough and avoids having to handle trailing comments — which
    would be a string-literal parsing problem in disguise.
    """
    lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("#") or stripped.startswith("//")):
            lines.append(line)
    return "\n".join(lines)


def vite_proxy_paths() -> list[str]:
    """The prefixes in vite.config.ts's proxy map, in source order.

    Anchored on `/healthz`, which appears in exactly one array literal in the
    file. Matching the first `[...]` instead picks up
    `ProxyOptions['bypass']` from the type annotation on the helper above it,
    which is what an earlier version of this test did.
    """
    source = _strip_comments(VITE_CONFIG.read_text(encoding="utf-8"))
    blocks = re.findall(r"\[(.*?)\]", source, re.DOTALL)
    candidates = [block for block in blocks if "'/healthz'" in block]
    assert len(candidates) == 1, (
        f"expected exactly one array literal containing '/healthz' in "
        f"vite.config.ts, found {len(candidates)}"
    )
    paths = re.findall(r"'([^']+)'", candidates[0])
    assert paths, "the path array literal in vite.config.ts is empty"
    return paths


def caddy_api_paths() -> set[str]:
    """The prefixes on the Caddyfile's @api path matcher, normalised.

    The Caddyfile spells each prefix twice — `/auth` for the exact path and
    `/auth/*` for everything under it — because Caddy's `path` matcher is exact
    where Vite's proxy keys are prefixes. A trailing `/*` is stripped and
    trailing slashes are normalised away on both sides, so `/admin /admin/*`
    and Vite's `/admin/` both reduce to `/admin`.

    A set, not a list: the order of entries in a Caddy path matcher carries no
    meaning, and comparing sets still fails if a prefix is added to one side
    and not the other.

    Continuation lines are joined first: the list is wrapped across lines for
    readability with trailing backslashes.
    """
    source = _strip_comments(CADDYFILE.read_text(encoding="utf-8"))
    literal = _api_matcher_literal(source)
    prefixes = set()
    for entry in literal.split():
        if entry.endswith("/*"):
            entry = entry[:-1]  # drop only the `*`, keeping the separator
        prefixes.add(entry.rstrip("/") or "/")
    return prefixes


def vite_api_paths() -> set[str]:
    return {p.rstrip("/") or "/" for p in vite_proxy_paths()}


def _api_matcher_literal(source: str) -> str:
    """The whitespace-normalised token list of the `@api path` matcher."""
    matcher = re.search(r"@api\s+path\s+((?:.*?\\\s*)*.*)", source)
    assert matcher, "could not find an `@api path ...` matcher in the Caddyfile"
    return matcher.group(1).replace("\\\n", " ")


def test_the_api_prefix_list_is_identical_in_both_places() -> None:
    assert caddy_api_paths() == vite_api_paths()


def test_each_api_prefix_covers_its_own_subtree() -> None:
    """`/auth` alone does not match `/auth/login`.

    Measured: with `path /auth` the SPA file server answered
    `POST /auth/login` with 405 while the api answered 422 for the same
    request sent direct. A prefix that lost its `/x/*` half would reintroduce
    that, and the list test above cannot see it.
    """
    source = _strip_comments(CADDYFILE.read_text(encoding="utf-8"))
    entries = set(_api_matcher_literal(source).split())

    for prefix in vite_proxy_paths():
        if prefix.endswith("/"):
            # `/admin/` already denotes a subtree; `/admin/*` covers the rest
            # and `/admin` is deliberately not proxied (the SPA owns it).
            assert f"{prefix}*" in entries, f"{prefix}* is missing from @api"
            continue
        assert prefix in entries, f"exact {prefix} is missing from @api"
        assert f"{prefix}/*" in entries, f"subtree {prefix}/* is missing from @api"


def test_the_navigation_bypass_exists() -> None:
    """A document navigation to an api prefix belongs to the SPA."""
    source = CADDYFILE.read_text(encoding="utf-8")
    assert re.search(r"@document\s+header\s+Accept\s+\*text/html\*", source), (
        "the Accept: text/html navigation bypass is missing; vite.config.ts has "
        "one as bypassDocumentNavigation and the SPA routes /library and "
        "/auth/callback collide with api prefixes"
    )
    assert "handle @document" in source, "the @document matcher is never handled"


def test_sse_is_not_buffered() -> None:
    """`flush_interval -1` is present — as intent, not as the mechanism.

    Caddy's reverse_proxy documents that flush_interval "is ignored and
    responses are flushed immediately to the client if one of the following
    applies from the response: Content-Type: text/event-stream", which is
    what apps/api/runs/router.py sends. So this line is NOT what stops the
    stream being buffered, and the assertion must not claim it is: a rebuild
    with `flush_interval 250ms` gave the identical frame spread (6.01s) as
    `-1`. It is asserted because it is the deliberate, zero-cost statement of
    intent at the spot a reader will look, and it is the setting that would
    matter for any other content type.
    """
    source = CADDYFILE.read_text(encoding="utf-8")
    assert re.search(r"reverse_proxy\s+\S+.*?\{.*?flush_interval\s+-1", source, re.DOTALL), (
        "flush_interval -1 is missing from the api proxy. It is belt-and-braces "
        "rather than the mechanism (Caddy exempts text/event-stream from "
        "buffering on its own), but it should be stated explicitly."
    )


def test_the_origin_is_locked_and_fails_closed() -> None:
    """A request without the origin-verify value gets nothing.

    Fail-closed matters as much as the check itself: if ORIGIN_VERIFY is unset
    in the environment the placeholder expands to the empty string, and the
    matcher must then refuse every real request rather than admit it.

    The check must be INSIDE the `route` block, and that is the whole point of
    this assertion. Written at the site level it validates, it reads
    correctly, and it does nothing: Caddy orders `route` ahead of `respond`,
    so the SPA fallback answers first and an unverified request gets 200.
    Measured on caddy:2-alpine, and it is the bug this test was written after.
    """
    source = _strip_comments(CADDYFILE.read_text(encoding="utf-8"))
    assert re.search(r"@notVerified\s+not\s+header\s+X-Origin-Verify\s+\{\$ORIGIN_VERIFY\}", source), (
        "the origin-verify check must be a `not header X-Origin-Verify` matcher; "
        "an inverted matcher would admit exactly the requests it should refuse"
    )
    assert "respond @notVerified 403" in source

    route = _route_body(source)
    assert route, "no `route` block found in the Caddyfile"
    assert "@notVerified" in route and "respond @notVerified 403" in route, (
        "the origin-verify check is outside the `route` block, where Caddy's "
        "directive ordering puts it after the SPA fallback and it never runs. "
        "A request with no X-Origin-Verify would get 200 instead of 403."
    )
    # And it must come before anything that can produce a response.
    assert route.index("respond @notVerified 403") < route.index("reverse_proxy"), (
        "the origin lock must be evaluated before the api proxy"
    )
    assert route.index("respond @notVerified 403") < route.index("file_server"), (
        "the origin lock must be evaluated before the SPA file server"
    )


def _route_body(source: str) -> str:
    """The contents of the outermost `route { ... }` block."""
    start = source.index("route {")
    depth = 0
    for i in range(start + len("route {") - 1, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start + len("route {") : i]
    raise AssertionError("the `route {` block is never closed")


def test_forwarded_for_is_replaced_not_appended() -> None:
    """KI-59, and the failure mode found in item 0.

    uvicorn scans X-Forwarded-For right-to-left and returns the first address
    that is not a trusted proxy. Appending Caddy's own peer address would put
    the CloudFront edge IP last, so every request would be keyed on it and the
    per-IP limiter would become one global bucket.
    """
    source = CADDYFILE.read_text(encoding="utf-8")
    assert "header_up X-Forwarded-For {http.request.header.X-Forwarded-For}" in source, (
        "X-Forwarded-For must be passed through from the header Caddy received"
    )
    assert "{>" not in source, (
        "a `{>...}` placeholder appends; X-Forwarded-For must be replaced so "
        "Caddy's own peer address never lands last in the chain"
    )
    assert "header_up X-Forwarded-Proto https" in source, (
        "CloudFront removes the viewer's X-Forwarded-Proto, so Caddy has to "
        "restate it or uvicorn sees the plain-http hop and builds http:// URLs"
    )


def test_there_is_no_tls() -> None:
    """No domain means no origin certificate, so no ACM and no auto-HTTPS.

    Read from the comments-stripped source: the prose explains why there is no
    TLS and mentions `https://` and `plain HTTP`, and asserting on the raw
    text fails on its own documentation.
    """
    source = _strip_comments(CADDYFILE.read_text(encoding="utf-8"))
    assert "auto_https off" in source
    assert not re.search(r"^\s*tls\b", source, re.MULTILINE), (
        "a tls directive on the origin would require a certificate this "
        "deployment has no way to obtain (no domain)"
    )
    # The site block is a bare port, not a hostname: `:80 {`.
    assert re.search(r"^:80\s*\{", source, re.MULTILINE)


def _main() -> int:
    """Run every test_* without needing pytest installed."""
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())