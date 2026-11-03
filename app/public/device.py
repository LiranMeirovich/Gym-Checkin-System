"""The ``gym_device`` cookie: the one place a linked phone's login lives
(design doc: "Login cookie").

Set only by the server: HttpOnly, so page scripts can never read it, and
never copied into localStorage or the like (Safari deletes script-written
storage after 7 days without a visit; server-set cookies are kept).
Secure: phones reach the public app only over the tunnel's https.
SameSite=Lax rather than Strict, so a phone opening the wall QR's link
from the Camera app (a top-level navigation from outside) still sends it.
"""

from fastapi import Request, Response

from app.core.db import DbSession
from app.core.models import DeviceSession
from app.core.phone_links import DEVICE_SESSION_LIFETIME, find_device

DEVICE_COOKIE = "gym_device"

_MAX_AGE = int(DEVICE_SESSION_LIFETIME.total_seconds())


def set_device_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        DEVICE_COOKIE,
        token,
        max_age=_MAX_AGE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_device_cookie(response: Response) -> None:
    response.delete_cookie(
        DEVICE_COOKIE, path="/", secure=True, httponly=True, samesite="lax"
    )


def this_device(request: Request, db: DbSession) -> DeviceSession | None:
    """The live device session behind this request's cookie, if any."""
    token = request.cookies.get(DEVICE_COOKIE)
    return find_device(db, token) if token else None
