"""Shared pytest fixtures."""

import pytest

from app import config
from app.store import store as global_store


@pytest.fixture(autouse=True)
def isolate_uploads(tmp_path, monkeypatch):
    """Point the global store's upload dir at a temp dir for every test.

    FileStore resolves its directory lazily from config.UPLOAD_DIR, so
    patching config alone is enough.
    """
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(config, "UPLOAD_DIR", upload_dir)
    yield
