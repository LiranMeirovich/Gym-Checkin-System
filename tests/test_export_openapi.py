"""The OpenAPI export the frontend's types are generated from."""

import json
from pathlib import Path

import pytest

from app.export_openapi import main


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
