"""Serving a built React app from a FastAPI app (decision 0020).

Each app serves its own Vite build from ``frontend/dist/<app>``: the admin
app ``dist/admin``, the public app ``dist/public``, so production needs no
Node, only the built files. ``serve_frontend()`` registers two things, and
must be called **after** every other route, since its catch-all would
otherwise answer in their place:

- ``/assets/...``: the build's JS and CSS. Their names carry a hash of
  their contents, so a changed file gets a new name and browsers may keep
  each one for a year.
- every other GET: the app's ``index.html``, where React Router picks the
  screen from the address. Never cached, so a new build shows on the next
  load. It holds no data: everything comes from ``/api``, which checks the
  login, so this needs no ``CurrentStaff``.

Not sent ``index.html``: unknown ``/api/...`` paths (a JSON 404, so a typo
in the frontend fails loudly instead of parsing HTML) and paths that look
like files (``/favicon.ico``, ``/robots.txt``), which get a 404.

A missing build gives a 503 page saying so, rather than stopping the app:
the Python tests and the Python CI job run without Node. The host's build
step must produce the files before the apps start (milestone 6).
"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse, Response
from starlette.staticfiles import StaticFiles

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

NOT_BUILT_MESSAGE = (
    "The frontend isn't built. Run `npm ci` and `npm run build` in frontend/."
)


class _HashedAssets(StaticFiles):
    """Vite's hashed build files: cached for a year, and a plain 404 (not
    a crash) while the build is missing."""

    async def check_config(self) -> None:
        if self.directory is not None and Path(self.directory).is_dir():
            await super().check_config()

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def serve_frontend(app: FastAPI, build_dir: Path) -> None:
    """Serve the Vite build in ``build_dir`` from ``app``. Call it last."""
    app.state.frontend_dir = build_dir
    app.mount(
        "/assets",
        _HashedAssets(directory=build_dir / "assets", check_dir=False),
        name="assets",
    )

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        if "." in path.rsplit("/", 1)[-1]:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        index = build_dir / "index.html"
        if not index.is_file():
            return PlainTextResponse(
                NOT_BUILT_MESSAGE, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        # After Lock, the Back button must not bring a page back from the
        # browser's cache, and a new build must show on the next load.
        return FileResponse(index, headers={"Cache-Control": "no-store"})
