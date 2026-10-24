"""Shared test setup."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.db import get_engine


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Run each test in an empty directory with no GYM_* variables, so the
    developer's own .env or environment never leaks into a test. The cached
    settings and engine are reset around each test, so each test's database
    is a file in its own directory."""
    for name in list(os.environ):
        if name.startswith("GYM_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield tmp_path
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()
