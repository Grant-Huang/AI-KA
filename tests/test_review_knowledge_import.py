"""Tests for review knowledge DB import."""
import sqlite3
from pathlib import Path
import pytest

from aika.db import ensure_schema
from backend.skills.review_domain_parser import import_review_domain_to_db


PACKAGE_DIR = Path(__file__).parent.parent / "review_skill_packages" / "package-solution-review-fs-v2"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_schema(c)
    yield c
    c.close()


def test_import_phases(conn):
    result = import_review_domain_to_db(conn, PACKAGE_DIR, "pkg-v2")
    assert result["phases"] >= 2
    phases = conn.execute("SELECT * FROM review_phases ORDER BY order_index").fetchall()
    phase_ids = {p["id"] for p in phases}
    assert "phase-1review" in phase_ids
    assert "phase-2review" in phase_ids


def test_import_focus_points(conn):
    result = import_review_domain_to_db(conn, PACKAGE_DIR, "pkg-v2")
    assert result["focus_points"] == 17
    fps = conn.execute("SELECT * FROM review_focus_points_ext").fetchall()
    assert len(fps) == 17
    # Check phase assignment
    phase1_fps = conn.execute(
        "SELECT * FROM review_focus_points_ext WHERE phase_id='phase-1review'"
    ).fetchall()
    assert len(phase1_fps) == 5
    phase2_fps = conn.execute(
        "SELECT * FROM review_focus_points_ext WHERE phase_id='phase-2review'"
    ).fetchall()
    assert len(phase2_fps) == 12


def test_import_categories(conn):
    result = import_review_domain_to_db(conn, PACKAGE_DIR, "pkg-v2")
    assert result["categories"] >= 30  # at least 30 categories across all focus points


def test_import_presets(conn):
    result = import_review_domain_to_db(conn, PACKAGE_DIR, "pkg-v2")
    assert result["presets"] == 3
    presets = conn.execute("SELECT * FROM review_presets_ext ORDER BY order_index").fetchall()
    assert len(presets) == 3
    # Check 二审 preset has pass_threshold
    preset_2 = next((p for p in presets if "二审" in p["name"]), None)
    assert preset_2 is not None
    assert preset_2["pass_threshold"] == 0.80


def test_preset_focus_members(conn):
    import_review_domain_to_db(conn, PACKAGE_DIR, "pkg-v2")
    members = conn.execute("SELECT * FROM preset_focus_members").fetchall()
    assert len(members) >= 15  # 5 + 12 + some for transition preset
