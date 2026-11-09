"""HTTP plumbing both apps share: the ``/api`` prefix, the base of every API
answer, ``no-store`` on every API answer, the same-origin check on every
unsafe request, reading an image sent as a data URL, the date-of-birth
field type, and keeping query strings out of the access log.

Here rather than in ``app.admin`` so the public app, the one reachable
from the internet, never imports admin code.
"""

import base64
import binascii
import logging
import re
from datetime import date
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_PREFIX = "/api"

# Methods that change something. GET and HEAD must never change anything.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# What a browser sends for an image: a canvas's ``toDataURL()`` or a
# FileReader's ``readAsDataURL()``.
PNG_DATA_URL = "data:image/png;base64,"
JPEG_DATA_URL = "data:image/jpeg;base64,"


_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _iso_date_text(value: object) -> object:
    # Pydantic would also take a number (a Unix time) or a date-time with
    # a zero time; a date of birth is only ever "YYYY-MM-DD".
    if not (isinstance(value, str) and _ISO_DATE.fullmatch(value)):
        raise ValueError("a date is YYYY-MM-DD")
    return value


# A date of birth in a request: only "YYYY-MM-DD" text. Whether it's a
# believable one is app.core.customers' rule.
DateOfBirth = Annotated[date, BeforeValidator(_iso_date_text)]


def data_url_bytes(data_url: str, *prefixes: str) -> bytes:
    """The bytes inside a base64 data URL starting with one of
    ``prefixes``; empty when it isn't one, which the caller's image check
    then refuses. The bytes' real format is checked by that caller."""
    for prefix in prefixes:
        if data_url.startswith(prefix):
            try:
                return base64.b64decode(data_url.removeprefix(prefix), validate=True)
            except binascii.Error:
                return b""
    return b""


class Answer(BaseModel):
    """Base for response shapes. Fields with a default are always sent, so
    the generated TypeScript types mark them required, not optional."""

    model_config = ConfigDict(
        json_schema_mode_override="serialization",
        json_schema_serialization_defaults_required=True,
    )


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


# uvicorn's access log, one line per request.
ACCESS_LOGGER = "uvicorn.access"


class DropQueryStrings(logging.Filter):
    """Logs a request's path without its query string.

    Some GETs carry customer data in the query string (the customer list's
    search text is a name or a phone number), and real customer data never
    goes in a log. uvicorn's access record is ``(client, method, path with
    query, HTTP version, status)``; anything else passes untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (args[0], args[1], args[2].partition("?")[0], *args[3:])
        return True


def drop_query_strings_from_access_log() -> None:
    """Install ``DropQueryStrings`` on uvicorn's access logger, once. Called
    at startup, after uvicorn has set up its logging."""
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, DropQueryStrings) for f in logger.filters):
        logger.addFilter(DropQueryStrings())
