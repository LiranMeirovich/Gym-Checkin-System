"""Write an app's OpenAPI spec to a file, for generating the frontend's
TypeScript types (decision 0020; ``npm run api:types`` in frontend/).

Run from the project root: ``python -m app.export_openapi admin <file>``.

The spec is built in-process from the app object, not fetched from a
running server, so nothing needs to be running and the public app can keep
``/openapi.json`` switched off. Importing an app doesn't run its startup
checks, so no database or ``.env`` is needed either.
"""

import json
import sys
from pathlib import Path

from fastapi import FastAPI

from app.admin.api import API_PREFIX


def load_app(name: str) -> FastAPI:
    if name == "admin":
        from app.admin.main import app
    elif name == "public":
        from app.public.main import app
    else:
        raise SystemExit(f"Unknown app {name!r}: use admin or public.")
    return app


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: python -m app.export_openapi {admin|public} <file>")
    name, target = argv
    spec = load_app(name).openapi()
    # The frontend calls only /api; page routes and /health don't belong in
    # its types.
    spec["paths"] = {
        path: item
        for path, item in spec["paths"].items()
        if path.startswith(API_PREFIX + "/")
    }
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
