"""CSRF protection for the admin app, in two layers (FastAPI has none of
its own).

1. **Same origin** (``app.core.http.SameOriginMiddleware``, shared with
   the public app): every unsafe request must come from this app's own
   pages. This is the only layer for the lock screen and first-run setup,
   which have no session yet.
2. **A signed token per session** (OWASP's signed, session-bound token):
   ``HMAC-SHA256(GYM_SECRET_KEY, "csrf:" + session token)``. The React app
   gets it from ``GET /api/session`` (or the login/setup answer), keeps it
   in memory and sends it as the ``X-CSRF-Token`` header;
   ``security.CurrentStaff`` checks it on every logged-in unsafe request.
   Nothing is stored: it's recomputed from the cookie each time, so it
   ends with the session. Another site can't compute it without both the
   key and the HttpOnly cookie.
"""

import hashlib
import hmac

from app.core.config import get_settings

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
