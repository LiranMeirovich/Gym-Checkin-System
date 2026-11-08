"""Linking a customer's phone: link codes and device sessions (design doc:
"Check-in flow"; decision 0028).

1. A staff member issues a 6-digit code on the customer's page
   (``issue_link_code``). It's valid for ``CODE_LIFETIME`` and usable
   once, and only the customer's newest code counts: issuing another
   cancels the earlier ones.
2. On the phone, the customer types their phone number and the code
   (``link_phone``). If both match, the phone gets a device session; its
   plain token goes into the ``gym_device`` cookie.
3. Every later request finds the customer through that token
   (``find_device``).

A new customer can skip the desk: ``sign_up`` creates them and this
phone's device session at once (decision 0035).

A customer has at most ``MAX_PHONES`` live sessions: linking one more
revokes the least recently used. A session dies when it's revoked (by
staff, by a newer phone, or because its customer was deactivated, which
revokes them all), or when it hasn't been seen for
``DEVICE_SESSION_LIFETIME`` (the cookie's own lifetime).

There's deliberately no wrong-code lockout: a code only exists while the
customer stands at the desk, it's used once and gone after 15 minutes
(the developer's call during planning). Codes and tokens are stored only
as SHA-256 hashes.

Every function works inside the caller's transaction and never commits.
Staff actions (issuing a code, unlinking) are written to the activity log
with ``by``; the customer linking their own phone is not, as logins
aren't (decision 0021). Whether ``by`` may do it is the route's check.
"""

import hmac
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from app.core.activity_log import Action, Target, record
from app.core.clock import utc_now
from app.core.customers import (
    CustomerInactiveError,
    find_by_phone,
    register_customer,
)
from app.core.models import Customer, DeviceSession, LinkCode, StaffUser
from app.core.models.phone_links import USER_AGENT_MAX_LENGTH
from app.core.staff_sessions import TOKEN_BYTES, hash_token

CODE_DIGITS = 6
CODE_LIFETIME = timedelta(minutes=15)
MAX_PHONES = 3
# The gym_device cookie's Max-Age; a check-in refreshes both.
DEVICE_SESSION_LIFETIME = timedelta(days=365)


class LinkRefusedError(ValueError):
    """The phone number and code don't link a phone. Deliberately one
    error for every reason (unknown number, inactive customer, wrong,
    used, expired or replaced code), so the answer never tells anyone
    whether a number belongs to a customer. Nothing was changed."""


@dataclass(frozen=True)
class IssuedCode:
    # The plain code, for the staff screen only. It exists only here and
    # can't be read back from the database.
    code: str
    expires_at: datetime


@dataclass(frozen=True)
class Linked:
    device: DeviceSession
    # The plain token, for the gym_device cookie only.
    token: str


def issue_link_code(db: Session, customer: Customer, *, by: StaffUser) -> IssuedCode:
    """A new link code for ``customer``; earlier ones stop working.
    Raises ``CustomerInactiveError`` for an inactive customer."""
    if not customer.active:
        raise CustomerInactiveError("reactivate the customer first")
    code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
    now = utc_now()
    row = LinkCode(
        customer_id=customer.id,
        code_hash=hash_token(code),
        created_by=by.id,
        created_at=now,
        expires_at=now + CODE_LIFETIME,
    )
    db.add(row)
    db.flush()
    # The code itself never goes into the log.
    record(
        db,
        by,
        Action.PHONE_ISSUE_CODE,
        Target.CUSTOMER,
        customer.id,
        after={"link_code_id": row.id},
    )
    return IssuedCode(code=code, expires_at=row.expires_at)


def link_phone(
    db: Session,
    *,
    phone: str,
    code: str,
    user_agent: str,
    replacing_token: str | None = None,
) -> Linked:
    """Link the phone this request comes from to the customer with
    ``phone``, if ``code`` is their newest live code.

    ``replacing_token`` is the gym_device token the browser already holds,
    if any: its session is revoked, so one browser holds one login.
    Raises ``LinkRefusedError``.
    """
    customer = find_by_phone(db, phone)
    if customer is None or not customer.active:
        raise LinkRefusedError
    newest = db.scalar(
        select(LinkCode)
        .where(LinkCode.customer_id == customer.id)
        .order_by(LinkCode.created_at.desc(), LinkCode.id.desc())
        .limit(1)
    )
    now = utc_now()
    if (
        newest is None
        or newest.used_at is not None
        or now >= newest.expires_at
        or not hmac.compare_digest(newest.code_hash, hash_token(code.strip()))
    ):
        raise LinkRefusedError

    newest.used_at = now
    return _start_session(db, customer, user_agent, replacing_token, now)


def sign_up(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    phone: str,
    date_of_birth: date,
    user_agent: str,
    replacing_token: str | None = None,
) -> Linked:
    """A new customer signing up on the phone this request comes from
    (decision 0035): the customer and this phone's device session, in the
    caller's transaction. Like linking, it isn't logged, and
    ``replacing_token`` is revoked.

    Raises ``InvalidCustomerError`` or ``PhoneTakenError`` (the number is
    already a customer's, active or not: they go to the desk).
    """
    customer = register_customer(
        db,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        date_of_birth=date_of_birth,
    )
    return _start_session(db, customer, user_agent, replacing_token, utc_now())


def _start_session(
    db: Session,
    customer: Customer,
    user_agent: str,
    replacing_token: str | None,
    now: datetime,
) -> Linked:
    """A new device session for ``customer`` on this browser: its old
    login (``replacing_token``) is revoked, and so are the customer's least
    recently used phones beyond ``MAX_PHONES``."""
    if replacing_token:
        _revoke_by_token(db, replacing_token, now)
    live = list_devices(db, customer)
    # Least recently used last; drop them until there's room for this one.
    for device in live[MAX_PHONES - 1 :]:
        device.revoked_at = now
    token = secrets.token_urlsafe(TOKEN_BYTES)
    device = DeviceSession(
        customer_id=customer.id,
        token_hash=hash_token(token),
        user_agent=user_agent[:USER_AGENT_MAX_LENGTH],
        created_at=now,
        last_seen_at=now,
    )
    db.add(device)
    db.flush()
    return Linked(device=device, token=token)


def find_device(db: Session, token: str) -> DeviceSession | None:
    """The live device session behind a gym_device ``token``, with its
    customer loaded, or ``None``: unknown, revoked, unused for a year, or
    its customer was deactivated."""
    return db.scalar(
        select(DeviceSession)
        .join(DeviceSession.customer)
        .options(contains_eager(DeviceSession.customer))
        .where(
            DeviceSession.token_hash == hash_token(token),
            *_live(utc_now()),
        )
    )


def list_devices(db: Session, customer: Customer) -> list[DeviceSession]:
    """``customer``'s live device sessions, most recently used first."""
    return list(
        db.scalars(
            select(DeviceSession)
            .where(
                DeviceSession.customer_id == customer.id,
                *_live(utc_now(), customer_active=False),
            )
            .order_by(DeviceSession.last_seen_at.desc(), DeviceSession.id.desc())
        )
    )


def unlink(db: Session, device: DeviceSession, *, by: StaffUser) -> None:
    """Revoke ``device``: that phone is no longer recognised and has to be
    linked again. Unlinking a revoked one changes nothing."""
    if device.revoked_at is not None:
        return
    device.revoked_at = utc_now()
    db.flush()
    record(
        db,
        by,
        Action.PHONE_UNLINK,
        Target.DEVICE_SESSION,
        device.id,
        before={"customer_id": device.customer_id, "revoked": False},
        after={"customer_id": device.customer_id, "revoked": True},
    )


def _live(now: datetime, *, customer_active: bool = True) -> list:
    conditions = [
        DeviceSession.revoked_at.is_(None),
        DeviceSession.last_seen_at > now - DEVICE_SESSION_LIFETIME,
    ]
    if customer_active:
        # Needs Customer joined in the query.
        conditions.append(Customer.active)
    return conditions


def _revoke_by_token(db: Session, token: str, now: datetime) -> None:
    device = db.scalar(
        select(DeviceSession).where(
            DeviceSession.token_hash == hash_token(token),
            DeviceSession.revoked_at.is_(None),
        )
    )
    if device is not None:
        device.revoked_at = now
        db.flush()
