"""CSRF protection for the admin app, in two layers (FastAPI has none of
its own).

1. **Same origin.** Every POST, PUT, PATCH and DELETE must carry an
   ``Origin`` header naming this app itself, and, when the browser sends
   one, ``Sec-Fetch-Site: same-origin``. Browsers set both and pages can't
   fake them, so a form on another website is refused before any route
   runs. This is the only layer for the lock screen and first-run setup,
   which have no session yet.
2. **A signed token per session** (OWASP's signed, session-bound token):
   ``HMAC-SHA256(GYM_SECRET_KEY, "csrf:" + session token)``. Pages put it
   in a hidden ``csrf_token`` field, or HTMX sends it as ``X-CSRF-Token``;
   ``security.CurrentStaff`` checks it on every logged-in unsafe request.
   Nothing is stored: it's recomputed from the cookie each time, so it
   ends with the session. Another site can't compute it without both the
   key and the HttpOnly cookie.
"""

import hashlib
import hmac

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings

# Methods that change something. GET and HEAD must never change anything.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

# Keeps this use of the key apart from any later one (e.g. "link-code:").
_PURPOSE = b"csrf:"


def csrf_token(session_token: str) -> str:
    """The CSRF token for the session whose cookie holds
    ``session_token``."""
    return hmac.new(
        get_settings().signing_key,
        _PURPOSE + session_token.encode(),
        hashlib.sha256,
    ).hexdigest()


def csrf_token_matches(session_token: str, submitted: str | None) -> bool:
    """Whether ``submitted`` is this session's CSRF token. Compared in
    constant time, so timing reveals nothing about the right value."""
    if not submitted:
        return False
    return hmac.compare_digest(csrf_token(session_token), submitted)


class SameOriginMiddleware:
    """Refuses (403) any unsafe request that doesn't come from a page of
    this app: layer 1 above."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in UNSAFE_METHODS
            and not _from_this_origin(Request(scope))
        ):
            response = PlainTextResponse("Cross-site request refused", status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _from_this_origin(request: Request) -> bool:
    # A missing Origin is refused too: every browser this app supports
    # sends one on POST, so only a non-browser client or a stripped header
    # leaves it out.
    origin = request.headers.get("origin")
    if origin != f"{request.url.scheme}://{request.url.netloc}":
        return False
    site = request.headers.get("sec-fetch-site")
    return site is None or site == "same-origin"
