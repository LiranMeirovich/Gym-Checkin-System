"""Shared test setup."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Run each test in an empty directory with no GYM_* variables, so the
    developer's own .env or environment never leaks into a test."""
    for name in list(os.environ):
        if name.startswith("GYM_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
