"""Send one real message through the configured email transport, and exit
non-zero if it did not go out.

Why this exists (KI-35, item 3): every check we have of the mail path is a
unit test with `smtplib` faked at its own boundary. That proves the code
hands the message to the socket; it cannot prove SES accepts the
credentials, that the from-address is verified, or that the relay is
reachable from the instance. Those failures are silent — password reset
returns 202 either way, because it must not reveal which addresses have
accounts — so the only way to know is to send something and look.

Run it on the target host, as the user the app runs as:

    docker compose exec api python -m scripts.send_test_email \\
        --to you@example.com

Exit codes: 0 sent, 1 the transport failed, 2 the configuration is
unusable (which is the same refusal startup would make, surfaced here
before anything is sent).

`--to` defaults to $SMTP_FROM, so the common case checks the relay without
naming anyone.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth.email import (
    EmailDeliveryFailed,
    EmailTransportMisconfigured,
    SmtpEmailTransport,
    get_email_transport,
)
from config import get_settings

EXIT_OK = 0
EXIT_SEND_FAILED = 1
EXIT_MISCONFIGURED = 2


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--to",
        default=None,
        help="recipient; defaults to SMTP_FROM so nothing is named by accident",
    )
    parser.add_argument(
        "--subject",
        default="Veriforge email transport test",
        help="subject line",
    )
    return parser.parse_args(argv)


async def send(to: str, subject: str) -> int:
    settings = get_settings()
    # Through `get_email_transport`, the same call the app's own
    # forgot-password route makes — so this script exercises the wiring, not
    # just the transport class.
    try:
        transport = get_email_transport()
    except EmailTransportMisconfigured as exc:
        print(f"email transport unusable: {exc.message}", file=sys.stderr)
        return EXIT_MISCONFIGURED

    try:
        await transport.send(
            to=to,
            subject=subject,
            body=(
                "If you are reading this, the configured Veriforge email "
                "transport is working: the app handed a message to the relay "
                "and the relay accepted it.\n\n"
                f"transport : {type(transport).__name__}\n"
                f"host      : {settings.smtp_host or '(dev log)'}\n"
                f"port      : {settings.smtp_port}\n"
                f"from      : {settings.smtp_from or '(none)'}\n"
                f"to        : {to}\n"
                "environment: "
                f"{settings.environment}\n"
            ),
        )
    except EmailDeliveryFailed as exc:
        print(f"email delivery failed: {exc.message}", file=sys.stderr)
        return EXIT_SEND_FAILED

    where = settings.smtp_host if isinstance(transport, SmtpEmailTransport) else "the log"
    print(f"sent via {type(transport).__name__} to {to} over {where}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    to = args.to or settings.smtp_from
    if not to:
        print(
            "no recipient: pass --to, or set SMTP_FROM so the test goes to the "
            "sender address",
            file=sys.stderr,
        )
        return EXIT_MISCONFIGURED
    return asyncio.run(send(to, args.subject))


if __name__ == "__main__":
    raise SystemExit(main())