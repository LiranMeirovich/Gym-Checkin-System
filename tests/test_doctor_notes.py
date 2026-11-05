"""Checking an uploaded doctor's note: what is accepted, the clean copy
that is stored (upright, shrunk, no metadata), and what is refused. The
images are made up."""

import io

import pytest
from PIL import Image

from app.core.doctor_notes import (
    NOTE_MAX_SIDE,
    UPLOAD_MAX_BYTES,
    InvalidNoteImageError,
    check_note_image,
)
from app.core.models import ImageType

# EXIF tags: orientation, and GPS info (where a phone photo was taken).
_ORIENTATION = 0x0112
_GPS_INFO = 0x8825


def image(fmt: str = "JPEG", size: tuple[int, int] = (800, 600), **save) -> bytes:
    mode = "RGBA" if fmt == "PNG" else "RGB"
    out = io.BytesIO()
    Image.new(mode, size, (200, 180, 160)).save(out, format=fmt, **save)
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_a_jpeg_comes_back_as_a_clean_jpeg() -> None:
    checked = check_note_image(image())

    assert checked.content_type is ImageType.JPEG
    with opened(checked.data) as copy:
        assert copy.format == "JPEG"
        assert copy.size == (800, 600)


def test_a_transparent_png_becomes_a_jpeg_on_white() -> None:
    checked = check_note_image(image("PNG"))

    with opened(checked.data) as copy:
        assert copy.format == "JPEG"
        assert copy.mode == "RGB"


def test_a_large_photo_is_shrunk() -> None:
    checked = check_note_image(image(size=(5000, 3000)))

    with opened(checked.data) as copy:
        assert max(copy.size) == NOTE_MAX_SIDE
        assert copy.size == (NOTE_MAX_SIDE, 1500)


def test_metadata_is_removed_and_the_orientation_applied() -> None:
    exif = Image.Exif()
    # Rotated 90°: the stored pixels are landscape, the photo is portrait.
    exif[_ORIENTATION] = 6
    exif[_GPS_INFO] = {1: "N"}

    checked = check_note_image(image(exif=exif.tobytes()))

    with opened(checked.data) as copy:
        assert copy.size == (600, 800)
        assert not copy.getexif()


@pytest.mark.parametrize(
    "upload",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"%PDF-1.7 not an image", id="pdf"),
        pytest.param(b"\xff\xd8\xff a broken jpeg", id="broken"),
        pytest.param(image("GIF"), id="gif"),
        pytest.param(image(size=(150, 1000)), id="too-small"),
        # Named by hand: pytest would otherwise spell out 12 MB as its id.
        pytest.param(b"\xff\xd8\xff" + b"\0" * UPLOAD_MAX_BYTES, id="too-large"),
    ],
)
def test_a_bad_upload_is_refused(upload: bytes) -> None:
    with pytest.raises(InvalidNoteImageError):
        check_note_image(upload)


def test_an_image_claiming_too_many_pixels_is_refused() -> None:
    # A small file (one bit per pixel, all blank) that claims a huge
    # image: refused before it's decoded.
    out = io.BytesIO()
    Image.new("1", (10_000, 6_000)).save(out, format="PNG")
    assert len(out.getvalue()) < UPLOAD_MAX_BYTES

    with pytest.raises(InvalidNoteImageError):
        check_note_image(out.getvalue())
