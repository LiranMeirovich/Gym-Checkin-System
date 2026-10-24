"""Admin app: the staff screens. Served only on 127.0.0.1:8000.

Run with: uvicorn app.admin.main:app --host 127.0.0.1 --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Load and validate the config before serving anything, so a bad value
    # stops uvicorn at startup instead of failing on some later request.
    get_settings()
    yield


app = FastAPI(title="Gym admin", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check (decision 0009)."""
    return {"status": "ok"}
