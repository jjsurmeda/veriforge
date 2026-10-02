"""Email transport selection and the production refusal (KI-35, AC-1).

`auth/router.py` used to hard-wire `DevLogEmailTransport`, so the
password-reset email was written to the log and never sent. A real transport
now sits behind the same `EmailTransport` interface, chosen by settings, and
startup refuses the dev-log one in production.

No mail is sent in these tests: `smtplib.SMTP` is faked at its own boundary,
so nothing leaves the process.
"""

import json
import logging
import smtplib
from typing import Any, ClassVar

import pytest

from auth.email import (
    DevLogEmailTransport,
    EmailDeliveryFailed,
    EmailTransportMisconfigured,
    SmtpEmailTransport,
    build_email_transport,
)
from config import Settings


def production_smtp_settings(
    *, host: str = "email-smtp.eu-west-1.amazonaws.com", sender: str = "no-reply@veriforge.example"
) -> Settings:
    """The production shape: SES's SMTP endpoint, no new dependency."""
    return Settings(
        environment="production",
        email_transport="smtp",
        smtp_host=host,
        smtp_from=sender,
        smtp_username="AKIAEXAMPLE",
        smtp_password="ses-secret",
    )


def test_smtp_is_selected_when_it_is_configured() -> None:
    transport = build_email_transport(production_smtp_settings())

    assert isinstance(transport, SmtpEmailTransport)
    assert transport.host == "email-smtp.eu-west-1.amazonaws.com"
    assert transport.port == 587
    assert transport.sender == "no-reply@veriforge.example"


def test_the_dev_log_transport_is_selected_outside_production() -> None:
    """Local development keeps working: the log is where the link is read
    from locally, and refusing it there would break `make smoke`."""
    transport = build_email_transport(
        Settings(environment="development", email_transport="dev_log")
    )

    assert isinstance(transport, DevLogEmailTransport)


def test_production_refuses_the_dev_log_transport() -> None:
    """The refusal the dispatch asks for. A production deployment that logs
    reset links instead of mailing them looks healthy in every other respect
    and silently breaks account recovery for every user — and writes live
    reset tokens to CloudWatch."""
    with pytest.raises(EmailTransportMisconfigured) as refused:
        build_email_transport(Settings(environment="production", email_transport="dev_log"))

    assert refused.value.error_code == "email_transport_dev_log_in_production"
    assert "EMAIL_TRANSPORT=smtp" in refused.value.message


def test_only_production_refuses_the_dev_log_transport(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The boundary, pinned so it is a decision and not an accident. The
    requirement is production; staging is allowed to log, and logs a warning
    every time it does, because a staging stack exists to be cheap to break.
    Tightening this to staging too is a one-line change that fails here."""
    with caplog.at_level(logging.WARNING, logger="veriforge.email"):
        transport = build_email_transport(
            Settings(environment="staging", email_transport="dev_log")
        )

    assert isinstance(transport, DevLogEmailTransport)
    assert "not sent" in caplog.text


@pytest.mark.parametrize(
    ("host", "sender", "expected_code"),
    [
        ("", "a@b.test", "smtp_host_missing"),
        ("h", "", "smtp_from_missing"),
    ],
)
def test_smtp_without_a_host_or_sender_is_refused(
    host: str, sender: str, expected_code: str
) -> None:
    with pytest.raises(EmailTransportMisconfigured) as refused:
        build_email_transport(production_smtp_settings(host=host, sender=sender))

    assert refused.value.error_code == expected_code


def test_an_unknown_transport_name_is_refused_rather_than_defaulted() -> None:
    """Falling back to a default here could pick the unsafe one, and a typo in
    EMAIL_TRANSPORT would otherwise be silent."""
    settings = Settings(environment="development")
    object.__setattr__(settings, "email_transport", "ses")

    with pytest.raises(EmailTransportMisconfigured) as refused:
        build_email_transport(settings)

    assert refused.value.error_code == "email_transport_invalid"


class _FakeSMTP:
    """Stands in for `smtplib.SMTP`. Records the envelope and the commands, so
    the test can assert what would have gone on the wire without a socket."""

    instances: ClassVar[list["_FakeSMTP"]] = []
    fail_with: ClassVar[BaseException | None] = None

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: list[Any] = []
        self.closed = False
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = (username, password)

    def send_message(self, message: Any) -> None:
        if _FakeSMTP.fail_with is not None:
            raise _FakeSMTP.fail_with
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSMTP]:
    _FakeSMTP.instances = []
    _FakeSMTP.fail_with = None
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


async def test_the_smtp_transport_actually_hands_the_message_over(
    fake_smtp: type[_FakeSMTP],
) -> None:
    transport = build_email_transport(production_smtp_settings())
    assert isinstance(transport, SmtpEmailTransport)

    await transport.send(
        to="someone@example.test", subject="Reset your Veriforge password", body="the link"
    )

    assert len(fake_smtp.instances) == 1
    smtp = fake_smtp.instances[0]
    assert smtp.host == "email-smtp.eu-west-1.amazonaws.com"
    assert smtp.port == 587
    assert smtp.started_tls, "STARTTLS is not optional on a public relay"
    assert smtp.logged_in == ("AKIAEXAMPLE", "ses-secret")
    assert smtp.closed, "the connection must be closed, not left for the GC"
    message = smtp.sent[0]
    assert message["To"] == "someone@example.test"
    assert message["From"] == "no-reply@veriforge.example"
    assert message["Subject"] == "Reset your Veriforge password"
    assert message.get_content().strip() == "the link"


async def test_an_smtp_failure_becomes_a_domain_error_not_an_smtplib_one(
    fake_smtp: type[_FakeSMTP], caplog: pytest.LogCaptureFixture
) -> None:
    """python.md: never let a raw provider exception reach the client. And the
    log line must not carry the body — it is a live password-reset token."""
    fake_smtp.fail_with = smtplib.SMTPServerDisconnected("421 too busy")
    transport = build_email_transport(production_smtp_settings())
    assert isinstance(transport, SmtpEmailTransport)

    with (
        caplog.at_level(logging.WARNING, logger="veriforge.email"),
        pytest.raises(EmailDeliveryFailed) as failed,
    ):
        await transport.send(
            to="someone@example.test",
            subject="Reset your Veriforge password",
            body="https://app.test/reset-password?token=SECRET-TOKEN",
        )

    assert failed.value.error_code == "email_delivery_failed"
    assert "SECRET-TOKEN" not in caplog.text, "a reset token reached the log"


async def test_startup_refuses_to_run_with_the_dev_log_transport_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The requirement is about STARTUP, not about a helper. This drives the
    real lifespan and asserts the process refuses to come up, so a deployment
    that forgot EMAIL_TRANSPORT fails loudly at boot instead of quietly
    mailing nobody."""
    import main
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("EMAIL_TRANSPORT", "dev_log")
    try:
        with pytest.raises(EmailTransportMisconfigured):
            async with main.lifespan(main.app):
                pass
    finally:
        get_settings.cache_clear()


async def test_startup_succeeds_in_production_with_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complement, and the reason the check is a check and not a wall: a
    correctly configured production deployment must start normally."""
    import main
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "email-smtp.eu-west-1.amazonaws.com")
    monkeypatch.setenv("SMTP_FROM", "no-reply@veriforge.example")
    try:
        async with main.lifespan(main.app):
            pass
    finally:
        get_settings.cache_clear()


async def test_the_dev_log_transport_writes_the_message_it_was_given(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unchanged behaviour, pinned so the development path cannot regress while
    the real transport is added next to it."""
    with caplog.at_level(logging.INFO, logger="veriforge.email"):
        await DevLogEmailTransport().send(
            to="someone@example.test", subject="s", body="b"
        )

    payload = json.loads(caplog.records[-1].message)
    assert payload == {"event": "email", "to": "someone@example.test", "subject": "s", "body": "b"}


async def test_forgot_password_goes_out_over_the_configured_transport(
    client: Any, fake_smtp: type[_FakeSMTP], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end-to-end shape, and the reason the selection matters: with SMTP
    configured, the reset link leaves the process instead of going to the log.

    Driven through the HTTP route with the settings changed underneath, because
    the wiring that was wrong was the route's, not the transport's — a test
    that only called `build_email_transport` would pass with the router still
    hard-wired to the dev-log one.
    """
    from config import get_settings

    signup = await client.post(
        "/auth/signup", json={"email": "smtp-reset@test.dev", "password": "password123"}
    )
    assert signup.status_code == 201, signup.text

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "email-smtp.eu-west-1.amazonaws.com")
    monkeypatch.setenv("SMTP_FROM", "no-reply@veriforge.example")
    get_settings.cache_clear()
    try:
        response = await client.post(
            "/auth/forgot-password", json={"email": "smtp-reset@test.dev"}
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 202, response.text
    assert len(fake_smtp.instances) == 1
    message = fake_smtp.instances[0].sent[0]
    assert message["To"] == "smtp-reset@test.dev"
    assert "reset-password?token=" in message.get_content()
