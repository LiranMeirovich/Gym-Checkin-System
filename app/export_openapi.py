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
from typing import Any

from fastapi import FastAPI

from app.admin.api import API_PREFIX

_SCHEMA_REF = "#/components/schemas/"


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
    spec = api_only(load_app(name).openapi())
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")


def api_only(spec: dict[str, Any]) -> dict[str, Any]:
    """``spec`` with only the ``/api`` paths and the schemas they use.

    The frontend calls only /api: page routes, /health and the models only
    they use don't belong in its types.
    """
    paths = {
        path: item
        for path, item in spec["paths"].items()
        if path.startswith(API_PREFIX + "/")
    }
    schemas = spec.get("components", {}).get("schemas", {})
    used: set[str] = set()
    pending = _schema_refs(paths)
    while pending:
        name = pending.pop()
        if name not in used and name in schemas:
            used.add(name)
            # A schema can refer to others (SessionInfo -> StaffInfo).
            pending |= _schema_refs(schemas[name])
    result = {**spec, "paths": paths}
    if "components" in spec:
        result["components"] = {
            **spec["components"],
            "schemas": {n: s for n, s in schemas.items() if n in used},
        }
    return result


def _schema_refs(node: object) -> set[str]:
    """Names of every component schema referred to anywhere in ``node``."""
    if isinstance(node, dict):
        found = {
            ref.removeprefix(_SCHEMA_REF)
            for key, ref in node.items()
            if key == "$ref" and isinstance(ref, str) and ref.startswith(_SCHEMA_REF)
        }
        for value in node.values():
            found |= _schema_refs(value)
        return found
    if isinstance(node, list):
        return set().union(*(_schema_refs(value) for value in node))
    return set()


if __name__ == "__main__":
    main(sys.argv[1:])
