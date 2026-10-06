"""Invite codes for `signup_mode=invite` (item 4).

The interesting function here is `consume`, and its whole design is the
atomicity: an invite is a single-use bearer credential for creating an
account, so two people pressing "sign up" with the same code at the same
moment must produce exactly one account. A SELECT-then-UPDATE reads as
correct, passes every test that is not concurrent, and hands the same
invitation to two strangers in production. So consumption is a single
`UPDATE … WHERE … RETURNING`, which both claims the row and reports who won.

**Codes are stored hashed.** An invite code is a credential: whoever holds it
can create an account. Storing it in plaintext would put every code in the
database dump, in `audit_log.before`, and in any log line that prints the
row. The plaintext appears exactly once, in the response to the admin who
minted it, and never again.

**No existence oracle.** `consume` raises one error for every way a code can
fail to be usable — unknown, used, revoked, expired — with the same code and
the same message. A caller that could tell "expired" from "never existed"
could enumerate which codes were ever issued, which for codes an admin
mailed out by hand is a slow leak of the whole list.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Invite, User
from errors import AppError

#: 16 bytes of `secrets.token_urlsafe` — 22 characters, ~128 bits. Long
#: enough that guessing is hopeless, short enough to paste into an email.
_CODE_BYTES = 16

#: The one error every unusable code produces. See the module docstring.
INVALID_INVITE_CODE = "invite_invalid"
INVALID_INVITE_MESSAGE = "This invite code is not valid"


class InviteRequired(AppError):
    status_code = 400


class InviteInvalid(AppError):
    status_code = 400


class SignupClosed(AppError):
    status_code = 403


def generate_code() -> str:
    return secrets.token_urlsafe(_CODE_BYTES)


def hash_code(code: str) -> str:
    """SHA-256 of the code, hex.

    Unsalted on purpose. An invite code is 128 bits of `secrets`, so there is
    no dictionary to attack and no rainbow table worth building — the
    attacker would have to brute-force 2^128 — while a per-code salt would
    mean one row per lookup, which is the expensive direction for no gain.
    (Passwords are the opposite case and use argon2; see `auth/passwords.py`.)
    """
    return hashlib.sha256(code.encode()).hexdigest()


def status_of(
    invite: Invite, *, now: datetime | None = None
) -> Literal["live", "used", "revoked", "expired"]:
    """Which of the four states this code is in.

    Order matters and is the reason this is one function rather than four
    checks at four call sites: `revoked` is reported ahead of `used` because
    revoking a code someone already used is a legitimate operator action and
    should read as "void", not as "spent".
    """
    current = now or datetime.now(UTC)
    if invite.revoked_at is not None:
        return "revoked"
    if invite.used_by is not None:
        return "used"
    if invite.expires_at is not None and invite.expires_at <= current:
        return "expired"
    return "live"


def invite_out(invite: Invite, *, code: str | None = None) -> dict[str, object]:
    """The admin-facing shape. `code` is passed only by `create`."""
    return {
        "id": str(invite.id),
        "code": code if code is not None else "",
        "status": status_of(invite),
        "note": invite.note,
        "used_by": str(invite.used_by) if invite.used_by else None,
        "used_at": invite.used_at.isoformat() if invite.used_at else None,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "revoked_at": invite.revoked_at.isoformat() if invite.revoked_at else None,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
    }


async def create(
    session: AsyncSession,
    *,
    actor_id: UUID,
    count: int = 1,
    expires_in_days: int | None = None,
    note: str | None = None,
) -> list[tuple[Invite, str]]:
    """Mint `count` codes. Returns each row with its plaintext code, once."""
    created: list[tuple[Invite, str]] = []
    for _ in range(count):
        code = generate_code()
        invite = Invite(
            code="",
            code_hash=hash_code(code),
            created_by=actor_id,
            expires_at=(
                datetime.now(UTC) + timedelta(days=expires_in_days)
                if expires_in_days
                else None
            ),
            note=note,
        )
        session.add(invite)
        created.append((invite, code))
    await session.flush()
    return created


async def list_all(
    session: AsyncSession, *, status: str | None = None
) -> list[Invite]:
    rows = (
        await session.execute(
            select(Invite).order_by(Invite.created_at.desc(), Invite.id.desc())
        )
    ).scalars().all()
    if status is None:
        return list(rows)
    return [row for row in rows if status_of(row) == status]


async def revoke(session: AsyncSession, *, invite_id: UUID) -> Invite:
    """Void a code. Idempotent — revoking an already-revoked code is not an
    error, because the operator's intent ("this must not work") is already
    satisfied and a second revocation usually means a retry."""
    invite = await session.get(Invite, invite_id)
    if invite is None:
        raise AppError("invite_not_found", "No such invite", status_code=404)
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(UTC)
        await session.flush()
    return invite


async def ensure_available(session: AsyncSession, *, code: str) -> None:
    """Raise `InviteInvalid` unless this code could be consumed. Consumes nothing.

    Needed because `consume` needs a `user_id`, which only exists after the
    user row is written — and writing that row before the code is known good
    is how a bogus code ends up answering `409 email_taken` for an address
    that has an account and `400 invite_invalid` for one that does not. That
    is account enumeration on a public endpoint, needing no valid invite.

    So the code is *checked* here, before the email lookup, and *claimed*
    afterwards. The gap between the two is closed by `consume` still being the
    atomic UPDATE, so a code that is spent in between is refused there rather
    than used twice; this function only has to be right about the common case
    of a code that was never usable at all.
    """
    live = select(Invite.id).where(
        Invite.code_hash == hash_code(code),
        Invite.used_by.is_(None),
        Invite.revoked_at.is_(None),
        (Invite.expires_at.is_(None)) | (Invite.expires_at > datetime.now(UTC)),
    )
    if (await session.execute(live)).scalar_one_or_none() is None:
        raise InviteInvalid(INVALID_INVITE_CODE, INVALID_INVITE_MESSAGE)


async def consume(
    session: AsyncSession, *, code: str, user_id: UUID
) -> Invite:
    """Claim an invite for `user_id`, or raise `InviteInvalid`.

    The UPDATE and the RETURNING are one statement on purpose. Every
    disqualifying condition is in the WHERE clause, so the row is claimed by
    exactly one transaction: the loser's UPDATE matches nothing, its
    RETURNING is empty, and it gets the same error as a code that never
    existed. There is no window between "is this still unused?" and "mark it
    used" for a second signup to slip through.
    """
    digest = hash_code(code)
    claimed = (
        await session.execute(
            update(Invite)
            .where(
                Invite.code_hash == digest,
                Invite.used_by.is_(None),
                Invite.revoked_at.is_(None),
                (Invite.expires_at.is_(None)) | (Invite.expires_at > datetime.now(UTC)),
            )
            .values(used_by=user_id, used_at=datetime.now(UTC))
            .returning(Invite.id)
        )
    ).scalar_one_or_none()
    if claimed is None:
        # Deliberately one message for unknown / used / revoked / expired.
        raise InviteInvalid(INVALID_INVITE_CODE, INVALID_INVITE_MESSAGE)
    await session.flush()
    invite = await session.get(Invite, claimed)
    if invite is None:  # pragma: no cover - the row was just claimed
        raise InviteInvalid(INVALID_INVITE_CODE, INVALID_INVITE_MESSAGE)
    return invite


async def attach_google_first_time(session: AsyncSession, *, code: str, user: User) -> None:
    """Consume an invite for a first-time Google sign-in.

    Same rule as `POST /auth/signup` (item 4): Google authenticates the
    *account with Google*, not the person, so without this a `signup_mode=invite`
    deployment is open to anyone with any Google account. A returning user's
    existing row is untouched and no code is needed — they were already
    admitted once.
    """
    await consume(session, code=code, user_id=user.id)


def require_code(code: str | None) -> str:
    """Reject a missing code with the same error an invalid one gets.

    Distinct from `consume`'s, because a missing field never reaches the
    database: it is a request-shape problem, and answering it differently
    from an unknown code would still be fine (the caller already knows they
    sent nothing) — but answering it *identically* keeps one rule to hold
    and one message to remember.
    """
    if not code or not code.strip():
        raise InviteInvalid(INVALID_INVITE_CODE, INVALID_INVITE_MESSAGE)
    return code.strip()