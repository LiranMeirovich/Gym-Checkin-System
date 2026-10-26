"""Jinja2 templates for the admin app's pages (decisions 0002, 0003).

Every page extends ``base.html``, which sets Hebrew and right-to-left.
Autoescaping is on for ``.html`` files (Jinja2Templates' default), so a
staff or customer name can never inject markup into a page.

Pages for a logged-in staff member go through ``staff_page``, which adds
what every one of them needs: who is logged in, the CSRF token, the
auto-lock timer, and headers that keep the page out of the browser cache.
"""

from pathlib import Path
from typing import Any

from fastapi import Request, status
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.admin.security import StaffLogin
from app.core.permissions import Role

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)

ROLE_NAMES = {Role.MANAGER: "מנהל/ת", Role.INSTRUCTOR: "מדריך/ה"}
templates.env.globals["role_names"] = ROLE_NAMES


def staff_page(
    request: Request,
    login: StaffLogin,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    """Render the template ``name`` for the logged-in staff member."""
    response = templates.TemplateResponse(
        request,
        name,
        {
            **(context or {}),
            "staff": login.staff,
            "csrf_token": login.csrf_token,
            # The page goes to the lock screen on its own once the server's
            # idle timeout has passed, so customer data doesn't stay on
            # screen. The server enforces the timeout either way.
            "lock_after_seconds": int(login.lock_after.total_seconds()),
        },
        status_code=status_code,
    )
    # After Lock, the Back button must not bring a staff page back from
    # the browser's cache.
    response.headers["Cache-Control"] = "no-store"
    return response
