"""Shared fixtures for backend tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Redirect the application's global engine before any backend module is
# imported. Without this, tests that forget a dependency override write into
# the developer's real data/spider_xhs.db.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="xhs-backend-tests-"))
os.environ["DATABASE_SQLITE_PATH"] = str(_TEST_ROOT / "spider_xhs.db")
os.environ["XHS_STORAGE_DIR"] = str(_TEST_ROOT / "storage")

from backend.app.core.config import Settings, get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _ignore_local_dotenv(monkeypatch, tmp_path):
    """Keep a developer's local ``.env`` out of the test suite.

    ``.env`` is a legitimate way to run the app locally (it may switch the data
    provider to RedFox), but tests must stay hermetic: the suite assumes the
    default PC provider unless a test explicitly overrides ``get_settings``.
    """
    monkeypatch.setattr("backend.app.core.config._ENV_FILE", tmp_path / ".env.absent")
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
