from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """
    Provide a TestClient with an isolated repo root.

    Many API endpoints rely on AIKA_REPO_ROOT for resolving skill packages,
    app_settings, and .tmp paths.
    """
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    from backend.main import app

    return TestClient(app)

