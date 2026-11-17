"""The wall QR's address and image (decision 0051)."""

import base64
from urllib.parse import unquote

import pytest

from app.core import wall_qr
from app.core.config import Settings


def settings_with(monkeypatch: pytest.MonkeyPatch, hostname: str | None) -> Settings:
    monkeypatch.setenv("GYM_ENVIRONMENT", "dev")
    if hostname is None:
        monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", "")
    else:
        monkeypatch.setenv("GYM_PUBLIC_HOSTNAME", hostname)
    return Settings()


def test_the_address_is_the_public_hostnames_check_in_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_with(monkeypatch, "CheckIn.Example.com")

    assert wall_qr.checkin_url(settings) == "https://checkin.example.com/c"


def test_no_address_without_a_public_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_with(monkeypatch, None)

    assert wall_qr.checkin_url(settings) is None


def test_the_image_is_an_svg_data_url_without_a_fixed_size() -> None:
    image = wall_qr.qr_image("https://checkin.example.com/c")

    prefix = "data:image/svg+xml"
    assert image.startswith(prefix)
    payload = image.split(",", 1)[1]
    svg = (
        base64.b64decode(payload).decode()
        if ";base64" in image.split(",", 1)[0]
        else unquote(payload)
    )
    assert "<svg" in svg
    assert 'width="' not in svg
    # Nothing a browser would run.
    assert "<script" not in svg


def test_the_same_address_always_gives_the_same_image() -> None:
    url = "https://checkin.example.com/c"

    assert wall_qr.qr_image(url) == wall_qr.qr_image(url)
    assert wall_qr.qr_image(url) != wall_qr.qr_image("https://other.example.com/c")
