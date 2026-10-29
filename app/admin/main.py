"""Admin app: the staff screens. Served only on 127.0.0.1:8000.

Run with: uvicorn app.admin.main:app --host 127.0.0.1 --port 8000
"""

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.admin import auth, security, setup
from app.admin.api import API_PREFIX, NoStoreMiddleware
from app.admin.api import auth as api_auth
from app.admin.api import setup as api_setup
from app.admin.csrf import SameOriginMiddleware
from app.core.spa import FRONTEND_DIST, serve_frontend
from app.core.startup import lifespan

# The only names the admin app answers to. Binding to 127.0.0.1 keeps other
# machines out, but not a website open in the gym PC's own browser: with DNS
# rebinding, a page on evil.example can point its name at 127.0.0.1 and send
# requests here as its "own" site. Those carry Host: evil.example, so this
# refuses them (400). It matters most before first-run setup, when nobody
# is logged in yet. Changes if hosting puts the admin app behind a domain.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

app = FastAPI(title="Gym admin", lifespan=lifespan)
# The last one added runs first: the Host is checked before the Origin is
# compared with it.
app.add_middleware(NoStoreMiddleware)
app.add_middleware(SameOriginMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
security.install(app)
app.include_router(api_setup.router, prefix=API_PREFIX)
app.include_router(api_auth.router, prefix=API_PREFIX)
app.include_router(setup.router)
app.include_router(auth.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check (decision 0009)."""
    return {"status": "ok"}


# Last: its catch-all answers every GET no route above claimed.
serve_frontend(app, FRONTEND_DIST / "admin")
