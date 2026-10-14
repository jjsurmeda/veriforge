"""Email transport seam (AC-1 password reset).

`EmailTransport` is the interface `auth/router.py` depends on; this module
owns the implementations and the choice between them. KI-35: `auth/router.py`
hard-wired `DevLogEmailTransport`, so the password-reset email was written to
the log and never sent — invisible locally, where the log is right there, and
a production blocker for AC-1, because a user who forgets their password
cannot recover their account.

Two implementations:

- `SmtpEmailTransport` sends for real, over SMTP with STARTTLS. AWS SES
  publishes an SMTP endpoint (`email-smtp.<region>.amazonaws.com:587`), so
  this reaches SES with no new dependency — `smtplib` is stdlib — and the
  same transport works against any other SMTP relay. Slice 9 points it at SES.
- `DevLogEmailTransport` writes the email to the log as structured JSON. It is
  for local development only, and `build_email_transport` refuses to select it
  when the environment is production, so it cannot be reached by accident.

Selection is by the `email_transport` setting ("smtp" | "dev_log"), resolved
per send from the current settings rather than captured at import, so a
settings change takes effect without a restart.
"""

import asyncio
import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Literal, Protocol

from config import Settings, get_settings
from errors import AppError

logger = logging.getLogger("veriforge.email")

TransportName = Literal["smtp", "dev_log"]
TRANSPORT_NAMES: frozenset[str] = frozenset({"smtp", "dev_log"})


class EmailTransport(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class EmailDeliveryFailed(AppError):
    """The transport could not hand the message to a mail server.

    An `AppError` so it is a domain failure rather than a raw `smtplib`
    exception reaching a route (python.md), but the caller MUST NOT turn it
    into a different HTTP status: `forgot-password` answers 202 whether or not
    the address has an account, and a 502 here would tell an attacker exactly
    which addresses do.
    """

    status_code = 502


class EmailTransportMisconfigured(AppError):
    """No usable transport for this environment. Raised at startup."""

    status_code = 500


class DevLogEmailTransport:
    """Development only: log the email as structured JSON instead of sending."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info(
            json.dumps({"event": "email", "to": to, "subject": subject, "body": body})
        )


class SmtpEmailTransport:
    """Send over SMTP with STARTTLS, one connection per message.

    A connection per message rather than a pooled one: password resets are
    rare, and a long-lived SMTP connection held open by the API process is a
    resource to leak and a stale socket to debug. `smtplib` is blocking, so
    the exchange runs in a worker thread and never blocks the event loop
    mid-stream.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        starttls: bool = True,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.starttls = starttls
        self.timeout_seconds = timeout_seconds

    async def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            await asyncio.to_thread(self._send_blocking, message)
        except (smtplib.SMTPException, OSError) as exc:
            # Never log the body: it carries a password-reset token.
            logger.warning("smtp delivery failed", extra={"to": to, "error": str(exc)})
            raise EmailDeliveryFailed(
                "email_delivery_failed", "The email could not be sent"
            ) from exc

    def _send_blocking(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as client:
            if self.starttls:
                client.starttls()
            if self.username:
                client.login(self.username, self.password)
            client.send_message(message)


def build_email_transport(settings: Settings | None = None) -> EmailTransport:
    """The transport for this environment, from the `email_transport` setting.

    Raises `EmailTransportMisconfigured` when the choice cannot work here —
    which is what the application's startup calls this to find out, before it
    accepts a request it cannot fulfil:

    - `dev_log` in production. A production deployment that logs reset links
      instead of mailing them looks healthy and silently breaks account
      recovery for every user, and it writes live reset tokens to CloudWatch.
    - `smtp` without a host or a sender address.
    - any other value, rather than falling back to a default that might be the
      unsafe one.
    """
    settings = settings or get_settings()
    name = settings.email_transport
    if name not in TRANSPORT_NAMES:
        raise EmailTransportMisconfigured(
            "email_transport_invalid",
            f"email_transport must be one of {sorted(TRANSPORT_NAMES)}, got {name!r}",
        )
    if name == "dev_log":
        if settings.environment == "production":
            raise EmailTransportMisconfigured(
                "email_transport_dev_log_in_production",
                "The dev-log email transport cannot run in production: password-reset "
                "emails would be written to the log instead of sent. Set "
                "EMAIL_TRANSPORT=smtp and the SMTP_* settings.",
            )
        logger.warning(
            "using the dev-log email transport; password-reset links are logged, "
            "not sent",
            extra={"environment": settings.environment},
        )
        return DevLogEmailTransport()
    if not settings.smtp_host:
        raise EmailTransportMisconfigured(
            "smtp_host_missing", "SMTP_HOST is required when EMAIL_TRANSPORT=smtp"
        )
    if not settings.smtp_from:
        raise EmailTransportMisconfigured(
            "smtp_from_missing", "SMTP_FROM is required when EMAIL_TRANSPORT=smtp"
        )
    return SmtpEmailTransport(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        sender=settings.smtp_from,
        starttls=settings.smtp_starttls,
        timeout_seconds=settings.smtp_timeout_seconds,
    )


def get_email_transport() -> EmailTransport:
    """The transport for the current settings, resolved per call.

    Per call rather than captured at import: a transport built at import would
    freeze whatever the settings were when the process started, which is the
    bug this whole change exists to remove.
    """
    return build_email_transport(get_settings())
