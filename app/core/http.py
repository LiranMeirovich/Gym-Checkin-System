"""HTTP plumbing both apps share: the ``/api`` prefix, ``no-store`` on every
API answer, and the same-origin check on every unsafe request.

Here rather than in ``app.admin`` so the public app, the one reachable
from the internet, never imports admin code.
"""

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_PREFIX = "/api"

# Methods that change something. GET and HEAD must never change anything.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class NoStoreMiddleware:
    """Marks every ``/api`` response ``Cache-Control: no-store``, errors
    included: they carry names, CSRF tokens and login answers, and after a
    lock or an unlink the browser must not have a copy to show."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(API_PREFIX + "/"):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_no_store)


class SameOriginMiddleware:
    """Refuses (403) any unsafe request that doesn't come from a page of
    this app.

    Every POST, PUT, PATCH and DELETE must carry an ``Origin`` header
    naming this app itself, and, when the browser sends one,
    ``Sec-Fetch-Site: same-origin``. Browsers set both and pages can't fake
    them, so a form on another website is refused before any route runs.

    Behind the tunnel, ``cloudflared`` reaches the public app over plain
    http from 127.0.0.1 while the phone's ``Origin`` is ``https://...``.
    uvicorn trusts ``X-Forwarded-Proto`` from 127.0.0.1 by default
    (``--forwarded-allow-ips``), so the request's own scheme is https too
    and the two match.
    """

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
    # A missing Origin is refused too: every browser this system supports
    # sends one on POST, so only a non-browser client or a stripped header
    # leaves it out.
    origin = request.headers.get("origin")
    if origin != f"{request.url.scheme}://{request.url.netloc}":
        return False
    site = request.headers.get("sec-fetch-site")
    return site is None or site == "same-origin"
