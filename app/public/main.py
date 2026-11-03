"""Public app: the customer check-in pages. Served on 127.0.0.1:8001 and
reachable from the internet through the tunnel, so it registers only
customer routes, never admin ones.

Run with: uvicorn app.public.main:app --host 127.0.0.1 --port 8001
"""

from fastapi import FastAPI

from app.core.http import API_PREFIX, NoStoreMiddleware, SameOriginMiddleware
from app.core.spa import FRONTEND_DIST, serve_frontend
from app.core.startup import lifespan
from app.public.api import link as api_link

# FastAPI adds /docs, /redoc and /openapi.json by default. On the public app
# they would publish a map of every route to anyone, so they're turned off.
app = FastAPI(
    title="Gym check-in",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(NoStoreMiddleware)
# Without it, another website could post a link form from the customer's
# own phone. The tunnel hostname check waits on hosting (decision 0028).
app.add_middleware(SameOriginMiddleware)
app.include_router(api_link.router, prefix=API_PREFIX)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check (decision 0009). Must never return more than "ok"."""
    return {"status": "ok"}


# Last: its catch-all answers every GET no route above claimed. The public
# build only: vite.config.ts keeps admin code out of it.
serve_frontend(app, FRONTEND_DIST / "public")
