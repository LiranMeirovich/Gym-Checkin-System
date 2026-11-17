"""The wall QR: the one fixed code at the entrance that phones scan to
check in (design doc: "The wall QR").

It always encodes ``https://<GYM_PUBLIC_HOSTNAME>/c``, the address the
public app answers on, so the printed code can never point at a host the
public app refuses (decision 0051). Nothing about it is stored or
editable: changing the domain means printing a new one.
"""

import segno

from app.core.config import Settings

# The public app's check-in page (frontend/src/public/App.tsx).
CHECK_IN_PATH = "/c"


def checkin_url(settings: Settings) -> str | None:
    """The address the wall QR opens, or ``None`` when no public hostname
    is configured (possible in dev only; prod requires one)."""
    if settings.public_hostname is None:
        return None
    return f"https://{settings.public_hostname}{CHECK_IN_PATH}"


def qr_image(url: str) -> str:
    """The QR code for ``url`` as an SVG ``data:`` URL, for an ``<img>``.

    Error correction "Q" (25%) so a scuffed or partly covered print still
    scans; the standard 4-module quiet zone. No fixed size, so the page
    scales it to the paper.
    """
    code = segno.make(url, error="q", micro=False)
    return code.svg_data_uri(border=4, omitsize=True)
