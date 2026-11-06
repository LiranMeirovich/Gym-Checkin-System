"""``GET /api/branding``: the gym's name and whether there is a logo
(decision 0034), so every screen can show one or the other.

No login, like ``/api/lock-screen``: the lock screen and first-run setup
show it before anyone is logged in. The logo itself is ``/branding/logo``
(``app.core.branding.serve_logo``).
"""

from fastapi import APIRouter, Request

from app.admin.api.schemas import Branding
from app.core.branding import load_branding
from app.core.db import DbSession

router = APIRouter()


@router.get("/branding")
def branding(request: Request, db: DbSession) -> Branding:
    found = load_branding(db, request.app.state.branding_dir)
    return Branding(gym_name=found.gym_name, has_logo=found.has_logo)
