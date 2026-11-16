"""Reset the owner's forgotten PIN from the server (decisions 0039, 0050).

    uv run python -m app.reset_owner_pin

Nobody else may reset the owner's PIN in the admin app, so a forgotten one
is reset here, by whoever has a shell on the server (and so the
``.env`` with the database key). It asks for the new PIN twice without
showing it, checks it against the usual PIN rules, and then, as a PIN reset
in the admin app does: lifts a lockout, ends every open session of the
owner, and writes "PIN reset" to the activity log as done by the owner.

The apps may keep running: it is one short transaction, which waits its
turn on the write lock like a request. It changes the owner's PIN only.
"""

import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import staff
from app.core.db import IMMEDIATE, get_engine
from app.core.models import StaffUser
from app.core.permissions import Role
from app.core.pins import InvalidPinError
from app.core.startup import DatabaseNotReadyError, check_database_is_current


class NoOwnerError(RuntimeError):
    """The database has no owner yet (first-run setup hasn't been done)."""


def reset_owner_pin(pin: str) -> str:
    """Give the owner ``pin`` as their new PIN, in one transaction, and
    return the owner's display name. Raises ``InvalidPinError`` for a PIN
    that breaks the rules and ``NoOwnerError`` before first-run setup;
    nothing is changed then."""
    engine = get_engine().execution_options(**{IMMEDIATE: True})
    with Session(engine) as db, db.begin():
        owner = db.scalars(
            select(StaffUser).where(StaffUser.role == Role.OWNER)
        ).one_or_none()
        if owner is None:
            raise NoOwnerError(
                "there is no owner yet: first-run setup in the admin app makes one"
            )
        staff.reset_pin(db, owner, pin, by=owner)
        return owner.display_name


def main() -> None:
    try:
        check_database_is_current()
    except DatabaseNotReadyError as error:
        raise SystemExit(f"Not reset: {error}.") from error
    pin = getpass.getpass("The owner's new PIN: ")
    if getpass.getpass("The same PIN again: ") != pin:
        raise SystemExit("Not reset: the two PINs don't match. Nothing was changed.")
    try:
        name = reset_owner_pin(pin)
    except (InvalidPinError, NoOwnerError) as error:
        raise SystemExit(f"Not reset: {error}. Nothing was changed.") from error
    print(f"The owner's PIN ({name}) is reset, and any lockout is lifted.")
    print("Their open sessions have ended: log in with the new PIN.")


if __name__ == "__main__":
    main()
