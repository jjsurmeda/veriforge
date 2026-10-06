"""`scripts/send_test_email.py` against a real socket (item 3, KI-35).

The existing transport tests fake `smtplib` at its own boundary, which
proves the code builds and hands off a message but never touches a socket.
This one runs a minimal SMTP server on localhost and lets the script talk to
it, because the failure this script exists to catch is a *relay* failure —
unreachable host, rejected credentials, unverified from-address — and none
of those can be faked at the `smtplib` boundary without faking the thing
under test.

Exit codes are the contract the runbook depends on: 0 sent, 1 delivery
failed, 2 configuration unusable.
"""

from __future__ import annotations

import asyncio
import base64
import smtplib
from collections.abc import AsyncIterator
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import pytest

from config import get_settings


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class FakeSMTPServer:
    """Just enough SMTP to accept one message, on a real socket.

    Speaks the subset `SmtpEmailTransport` uses: greeting, EHLO, STARTTLS
    is *not* offered (so the client skips it), AUTH LOGIN, MAIL FROM, RCPT
    TO, DATA. It records the message it was handed.
    """

    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.reject_auth = False
        self.reject_rcpt = False
        self._server: asyncio.AbstractServer | None = None
        self.port = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        async def send(line: str) -> None:
            writer.write(f"{line}\r\n".encode())
            await writer.drain()

        await send("220 fake ESMTP ready")
        envelope: dict[str, str] = {}
        while True:
            raw = await reader.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").strip()
            upper = line.upper()
            if upper.startswith("EHLO") or upper.startswith("HELO"):
                await send("250-fake")
                # AUTH LOGIN only, on purpose. smtplib picks the server's
                # first advertised mechanism, and a server that advertises
                # PLAIN and only implements LOGIN makes the client pick PLAIN
                # and then hang — which is what the first version of this
                # fake did, and the failure looked like a product bug.
                await send("250 AUTH LOGIN")
            elif upper.startswith("AUTH LOGIN"):
                # The challenge flow, in order: smtplib does not send
                # credentials until the server issues the 334, so a server
                # that reads first deadlocks and the client reports
                # "Connection unexpectedly closed: timed out" — which reads
                # exactly like a product fault.
                await send("334 " + b64(b"Username:"))
                await reader.readline()  # base64 username
                await send("334 " + b64(b"Password:"))
                await reader.readline()  # base64 password
                if self.reject_auth:
                    await send("535 authentication failed")
                else:
                    await send("235 ok")
            elif upper.startswith("MAIL FROM"):
                envelope["from"] = line
                await send("250 ok")
            elif upper.startswith("RCPT TO"):
                if self.reject_rcpt:
                    await send("550 no such recipient")
                else:
                    envelope["to"] = line
                    await send("250 ok")
            elif upper == "DATA":
                await send("354 send it")
                body_lines: list[bytes] = []
                while True:
                    data = await reader.readline()
                    if not data or data.strip() == b".":
                        break
                    # Dot-stuffing: a line starting with "." carries a
                    # escaped one, so undo it or the body gains dots.
                    if data.startswith(b".."):
                        data = data[1:]
                    body_lines.append(data)
                # Parse the whole payload as a message, headers included.
                # Reading it as body text loses every header, which is how
                # the first version of this fake asserted `message["To"]`
                # against None.
                self.messages.append(
                    BytesParser(policy=policy.default).parsebytes(b"".join(body_lines))
                )
                await send("250 queued")
            elif upper == "QUIT":
                await send("221 bye")
                break
            else:
                await send("250 ok")
        writer.close()
        with suppress_all():
            await writer.wait_closed()


class suppress_all:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True


@pytest.fixture
async def smtp_server() -> AsyncIterator[FakeSMTPServer]:
    server = FakeSMTPServer()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


def configure(monkeypatch: pytest.MonkeyPatch, server: FakeSMTPServer) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(server.port))
    monkeypatch.setenv("SMTP_USERNAME", "AKIAEXAMPLE")
    monkeypatch.setenv("SMTP_PASSWORD", "ses-secret")
    monkeypatch.setenv("SMTP_FROM", "no-reply@veriforge.example")
    # The fake server does not advertise STARTTLS, and the transport only
    # calls it when told to; off here so the exchange stays plaintext on
    # loopback rather than failing the handshake.
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    get_settings.cache_clear()


class TestSendTestEmail:
    @pytest.mark.asyncio
    async def test_sends_one_message_over_a_real_socket(
        self, monkeypatch: pytest.MonkeyPatch, smtp_server: FakeSMTPServer
    ) -> None:
        from scripts import send_test_email

        configure(monkeypatch, smtp_server)
        try:
            code = await send_test_email.send("ops@example.com", "Veriforge test")
        finally:
            get_settings.cache_clear()

        assert code == send_test_email.EXIT_OK
        assert len(smtp_server.messages) == 1
        message = smtp_server.messages[0]
        assert message["To"] == "ops@example.com"
        assert message["From"] == "no-reply@veriforge.example"
        assert message["Subject"] == "Veriforge test"
        # The body is the part worth reading: it names the host and port it
        # actually used, which is the whole point of running it on the box.
        body = message.get_payload(decode=True)
        assert body is not None
        assert str(smtp_server.port).encode() in body
        assert b"127.0.0.1" in body

    @pytest.mark.asyncio
    async def test_exit_zero_and_the_default_recipient_is_the_sender(
        self, monkeypatch: pytest.MonkeyPatch, smtp_server: FakeSMTPServer
    ) -> None:
        from scripts import send_test_email

        configure(monkeypatch, smtp_server)
        try:
            args = send_test_email._parse_args([])
            assert args.to is None, "the default comes from SMTP_FROM, not the parser"
            from config import get_settings as live_settings

            code = await send_test_email.send(
                live_settings().smtp_from, "Veriforge test"
            )
        finally:
            get_settings.cache_clear()

        assert code == send_test_email.EXIT_OK
        assert smtp_server.messages[0]["To"] == "no-reply@veriforge.example"

    @pytest.mark.asyncio
    async def test_rejected_recipients_exit_one(
        self, monkeypatch: pytest.MonkeyPatch, smtp_server: FakeSMTPServer
    ) -> None:
        """A relay that refuses the message is a failure the runbook needs to
        see as a non-zero exit, because the alternative — password reset
        returning 202 either way — is how KI-35 stayed invisible."""
        from scripts import send_test_email

        configure(monkeypatch, smtp_server)
        smtp_server.reject_rcpt = True
        try:
            code = await send_test_email.send("nobody@example.com", "Veriforge test")
        finally:
            get_settings.cache_clear()

        assert code == send_test_email.EXIT_SEND_FAILED
        assert smtp_server.messages == []

    @pytest.mark.asyncio
    async def test_rejected_credentials_exit_one(
        self, monkeypatch: pytest.MonkeyPatch, smtp_server: FakeSMTPServer
    ) -> None:
        from scripts import send_test_email

        configure(monkeypatch, smtp_server)
        smtp_server.reject_auth = True
        try:
            code = await send_test_email.send("ops@example.com", "Veriforge test")
        finally:
            get_settings.cache_clear()

        assert code == send_test_email.EXIT_SEND_FAILED

    @pytest.mark.asyncio
    async def test_unreachable_relay_exits_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from scripts import send_test_email

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
        # Port 1 on loopback: reserved, nothing listens, connection refused.
        monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("SMTP_PORT", "1")
        monkeypatch.setenv("SMTP_USERNAME", "u")
        monkeypatch.setenv("SMTP_PASSWORD", "p")
        monkeypatch.setenv("SMTP_FROM", "no-reply@veriforge.example")
        monkeypatch.setenv("SMTP_TIMEOUT_SECONDS", "2")
        get_settings.cache_clear()
        try:
            code = await send_test_email.send("ops@example.com", "Veriforge test")
        finally:
            get_settings.cache_clear()

        assert code == send_test_email.EXIT_SEND_FAILED

    @pytest.mark.asyncio
    async def test_no_recipient_at_all_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, smtp_server: FakeSMTPServer
    ) -> None:
        from scripts import send_test_email

        configure(monkeypatch, smtp_server)
        monkeypatch.setenv("SMTP_FROM", "")
        get_settings.cache_clear()
        try:
            code = send_test_email.main([])
        finally:
            get_settings.cache_clear()

        assert code == send_test_email.EXIT_MISCONFIGURED

    def test_env_only_invocation_needs_no_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`python -m scripts.send_test_email` is the documented form in
        `docs/ops/runbook-admin.md`; it must work with env alone."""
        monkeypatch.setenv("SMTP_FROM", "no-reply@veriforge.example")
        get_settings.cache_clear()
        try:
            args = send_test_email_module()._parse_args([])
        finally:
            get_settings.cache_clear()
        assert args.to is None

    def test_smtp_is_the_transport_a_production_deployment_gets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from auth.email import SmtpEmailTransport, get_email_transport

        configure(monkeypatch, smtp_server_port(2525))
        try:
            assert isinstance(get_email_transport(), SmtpEmailTransport)
        finally:
            get_settings.cache_clear()


def smtp_server_port(port: int) -> FakeSMTPServer:
    server = FakeSMTPServer()
    server.port = port
    return server


def send_test_email_module() -> Any:
    from scripts import send_test_email

    return send_test_email


class TestStartupRefusesPartialSmtpConfig:
    """The production-config path, item 3's second bullet.

    `email_transport=smtp` with a missing field must fail **at startup**, and
    the message must name the field — an operator who gets "email transport
    unusable" with no field named has to read the source to find out which
    of five variables is wrong.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("missing", "named"),
        [
            ("SMTP_HOST", "SMTP_HOST"),
            ("SMTP_FROM", "SMTP_FROM"),
        ],
    )
    async def test_startup_names_the_missing_field(
        self, monkeypatch: pytest.MonkeyPatch, missing: str, named: str
    ) -> None:
        import main
        from auth.email import EmailTransportMisconfigured

        for field in ("SMTP_HOST", "SMTP_FROM"):
            monkeypatch.delenv(field, raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
        monkeypatch.setenv("SMTP_USERNAME", "u")
        monkeypatch.setenv("SMTP_PASSWORD", "p")
        # Present but empty is how an unset variable actually arrives from
        # compose (`SMTP_HOST: ${SMTP_HOST:-}`), so that is the case tested.
        monkeypatch.setenv(missing, "")
        if missing == "SMTP_HOST":
            monkeypatch.setenv("SMTP_FROM", "no-reply@veriforge.example")
        else:
            monkeypatch.setenv("SMTP_HOST", "email-smtp.eu-west-1.amazonaws.com")
        get_settings.cache_clear()

        try:
            with pytest.raises(EmailTransportMisconfigured) as refused:
                async with main.lifespan(main.app):
                    pass
        finally:
            get_settings.cache_clear()

        assert named in refused.value.message, (
            f"the refusal must name {named}, got: {refused.value.message!r}"
        )

    def test_the_same_two_settings_also_fail_at_the_helper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`build_email_transport` is what startup calls, so it must refuse
        the same way — otherwise the startup check is testing a path nothing
        else uses."""
        from auth.email import EmailTransportMisconfigured, build_email_transport

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.setenv("SMTP_FROM", "no-reply@veriforge.example")
        get_settings.cache_clear()
        try:
            with pytest.raises(EmailTransportMisconfigured) as refused:
                build_email_transport(get_settings())
        finally:
            get_settings.cache_clear()
        assert refused.value.error_code == "smtp_host_missing"
        assert "SMTP_HOST" in refused.value.message


@pytest.mark.asyncio
async def test_no_secret_is_printed_by_the_script(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    smtp_server: FakeSMTPServer,
) -> None:
    """The script reports the host and port; it must never report the
    password, which would otherwise land in a shell history and a CI log.

    Calls `send` rather than `main` because `main` calls `asyncio.run`, which
    cannot start while this test's event loop is running the fake server.
    `send` is what prints.
    """
    from scripts import send_test_email

    configure(monkeypatch, smtp_server)
    try:
        code = await send_test_email.send("ops@example.com", "Veriforge test")
    finally:
        get_settings.cache_clear()

    captured = capsys.readouterr()
    assert code == send_test_email.EXIT_OK
    assert "ses-secret" not in captured.out + captured.err
    assert "127.0.0.1" in captured.out, "the host it used is the useful part"


def test_the_fake_server_does_not_patch_smtplib() -> None:
    """A guard on the guard.

    This module's whole claim is that it exercises the socket path rather
    than a faked `smtplib`. If it ever patches `smtplib`, that claim is
    false and every test above is testing the mock.
    """
    import tests.scripts.test_send_test_email as module

    needle = "monkeypatch" + ".setattr(smtplib"
    source = Path(module.__file__).read_text()
    assert needle not in source, f"{needle} found: this module must not fake smtplib"
    assert smtplib.SMTP.__module__ == "smtplib", "smtplib.SMTP was replaced"