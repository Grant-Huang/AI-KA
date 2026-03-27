from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from backend.config import get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_fs_capabilities_ok() -> None:
    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/fs/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert "native_folder_picker" in body["data"]


def test_pick_directory_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIKA_ENABLE_NATIVE_FOLDER_PICKER", "0")
    from backend.main import app

    client = TestClient(app)
    r = client.post("/api/v1/fs/pick-directory")
    assert r.status_code == 403


def test_pick_directory_returns_validated_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    d = tmp_path / "proj"
    d.mkdir()

    def fake_pick() -> str:
        return str(d)

    monkeypatch.setattr("backend.main.pick_folder_native", fake_pick)
    from backend.main import app

    client = TestClient(app)
    r = client.post("/api/v1/fs/pick-directory")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["data"]["path"] == str(d.resolve())
