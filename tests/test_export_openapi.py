"""The OpenAPI export the frontend's types are generated from."""

import json
from pathlib import Path

import pytest

from app.export_openapi import api_only, main


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def test_only_schemas_the_api_paths_use_are_kept() -> None:
    spec = {
        "paths": {
            "/api/session": {"get": {"responses": {"200": ref("SessionInfo")}}},
            "/form": {"post": {"requestBody": ref("Body_form")}},
        },
        "components": {
            "schemas": {
                "SessionInfo": {"properties": {"staff": ref("StaffInfo")}},
                "StaffInfo": {"properties": {}},
                "Body_form": {"properties": {"x": ref("Shared")}},
                "Shared": {"properties": {}},
            }
        },
    }

    result = api_only(spec)

    assert list(result["paths"]) == ["/api/session"]
    # StaffInfo is kept because SessionInfo refers to it; the form route's
    # schemas go with the route.
    assert list(result["components"]["schemas"]) == ["SessionInfo", "StaffInfo"]


def test_the_admin_export_has_only_the_api_paths(tmp_path: Path) -> None:
    target = tmp_path / "out" / "admin.json"

    main(["admin", str(target)])

    spec = json.loads(target.read_text(encoding="utf-8"))
    assert "/api/login" in spec["paths"]
    assert all(path.startswith("/api/") for path in spec["paths"])


def test_response_fields_with_defaults_are_required(tmp_path: Path) -> None:
    # Otherwise TypeScript would treat always-sent fields as optional.
    target = tmp_path / "admin.json"

    main(["admin", str(target)])

    schemas = json.loads(target.read_text(encoding="utf-8"))["components"]["schemas"]
    assert "locked_until" in schemas["LoginRefused"]["required"]
    assert "detail" in schemas["NotLoggedIn"]["required"]


def test_the_public_export_works_with_its_docs_switched_off(tmp_path: Path) -> None:
    target = tmp_path / "public.json"

    main(["public", str(target)])

    assert json.loads(target.read_text(encoding="utf-8"))["paths"] == {}


@pytest.mark.parametrize("argv", [[], ["admin"], ["nope", "x.json"]])
def test_bad_arguments_stop_with_a_message(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        main(argv)
