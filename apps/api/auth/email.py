"""Email transport seam so slice 9 can swap in SES without touching auth logic."""

import json
import logging
from typing import Protocol

logger = logging.getLogger("veriforge.email")


class EmailTransport(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class DevLogEmailTransport:
    """Slice 1: log the email as structured JSON instead of sending."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info(
            json.dumps({"event": "email", "to": to, "subject": subject, "body": body})
        )
