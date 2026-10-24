"""Public app: the customer check-in pages. Served on 127.0.0.1:8001 and
reachable from the internet through the tunnel, so it registers only
customer routes, never admin ones.

Run with: uvicorn app.public.main:app --host 127.0.0.1 --port 8001
"""

from fastapi import FastAPI

from app.core.startup import lifespan

# FastAPI adds /docs, /redoc and /openapi.json by default. On the public app
# they would publish a map of every route to anyone, so they're turned off.
app = FastAPI(
    title="Gym check-in",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check (decision 0009). Must never return more than "ok"."""
    return {"status": "ok"}
