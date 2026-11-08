"""The gym's logo and name, as the screens show them (decision 0034).

The logo is gym-specific, so it never goes in the repo (decisions 0006,
0034): each install keeps it in the git-ignored ``branding/`` folder in the
project root, as ``branding/logo.jpg``. Both apps serve it from the same
address, ``GET /branding/logo``, and both answer ``GET /api/branding`` with
the gym's name and whether there is a logo, so a screen shows the name in
its place when the file is missing.

Neither needs a login: the lock screen, first-run setup and the phone's
link page show them before anyone is known, and the gym's name and logo
are on the wall anyway.
"""

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.gym_settings import load_gym_settings

BRANDING_DIR = Path(__file__).resolve().parents[2] / "branding"
LOGO_FILE = "logo.jpg"
LOGO_ADDRESS = "/branding/logo"


@dataclass(frozen=True)
class Branding:
    gym_name: str | None
    has_logo: bool


def logo_path(branding_dir: Path) -> Path | None:
    """The logo file in ``branding_dir``, or None if there isn't one."""
    path = branding_dir / LOGO_FILE
    return path if path.is_file() else None


def load_branding(db: Session, branding_dir: Path) -> Branding:
    """The gym's name (None before first-run setup) and whether the logo
    file exists."""
    return Branding(
        gym_name=load_gym_settings(db).gym_name,
        has_logo=logo_path(branding_dir) is not None,
    )


def serve_logo(app: FastAPI, branding_dir: Path) -> None:
    """Serve the logo in ``branding_dir`` at ``LOGO_ADDRESS`` from ``app``.

    Call it before ``serve_frontend()``, whose catch-all would answer in
    its place. A missing file is a 404. ``no-cache`` makes the browser
    check with the server (by its ETag) before using its copy, so a
    replaced logo shows on the next load.
    """
    # Read on each request (here and by /api/branding), so the tests can
    # point it at a folder of their own.
    app.state.branding_dir = branding_dir

    @app.get(LOGO_ADDRESS, include_in_schema=False)
    def logo() -> FileResponse:
        path = logo_path(app.state.branding_dir)
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )
