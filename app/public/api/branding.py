"""``GET /api/branding``: the gym's name and whether there is a logo
(decision 0034), so the phone pages can show one or the other.

No device session needed: the link page shows it on a phone that isn't
linked yet. Only what's on the gym's wall anyway, nothing about anyone.
The logo itself is ``/branding/logo`` (``app.core.branding.serve_logo``).
"""

from fastapi import APIRouter, Request

from app.core.branding import load_branding
from app.core.db import ReadOnlyDbSession
from app.public.api.schemas import Branding

router = APIRouter()


@router.get("/branding")
def branding(request: Request, db: ReadOnlyDbSession) -> Branding:
    found = load_branding(db, request.app.state.branding_dir)
    return Branding(gym_name=found.gym_name, has_logo=found.has_logo)
