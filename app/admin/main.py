"""Admin app: the staff screens. Served only on 127.0.0.1:8000.

Run with: uvicorn app.admin.main:app --host 127.0.0.1 --port 8000
"""

from fastapi import FastAPI

app = FastAPI(title="Gym admin")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check (decision 0009)."""
    return {"status": "ok"}
