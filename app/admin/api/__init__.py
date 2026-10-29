"""The admin app's JSON API, under ``/api`` (decision 0020).

Routes stay thin: they check the login (``CurrentStaff`` or
``require_permission``), validate the request with its Pydantic schema
(``schemas``), call ``app.core`` and return the result. Errors are codes,
never Hebrew text: the React app holds the wording.

This module imports none of its route modules, so ``security`` can use
``schemas`` without an import cycle; ``main`` mounts the routers.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_PREFIX = "/api"


class NoStoreMiddleware:
    """Marks every ``/api`` response ``Cache-Control: no-store``, errors
    included: they carry staff names and CSRF tokens, and after Lock the
    browser must not have a copy to show."""

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
