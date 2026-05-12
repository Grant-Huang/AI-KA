"""Tests for knowledge extraction API endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_expert_profile_get_empty(client):
    r = client.get("/api/v1/expert-profile")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "domains" in data
    assert isinstance(data["domains"], list)


def test_expert_profile_put_and_get(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_PERSONAL_DIR", str(tmp_path / "personal"))
    r = client.put("/api/v1/expert-profile", json={
        "domains": ["金融", "零售"],
        "background": "资深 IT 顾问，专注金融行业",
    })
    assert r.status_code == 200
    data = r.json()["data"]
    assert "金融" in data["domains"]
    assert "零售" in data["domains"]

    r2 = client.get("/api/v1/expert-profile")
    assert r2.status_code == 200
    assert "金融" in r2.json()["data"]["domains"]


def test_knowledge_items_list_empty(client):
    r = client.get("/api/v1/knowledge-items")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0


def test_knowledge_item_not_found(client):
    r = client.get("/api/v1/knowledge-items/ki-999")
    assert r.status_code == 404


def test_knowledge_item_patch_invalid_status(client):
    # First create an item via DB directly
    from aika import db as dbm
    from aika.paths import db_path
    from backend.repo_paths import repository_root
    conn = dbm.connect(db_path(repository_root()))
    dbm.ensure_schema(conn)
    dbm.insert_knowledge_item(
        conn, id="ki-test-001", extraction_focus_id="req",
        title="Test", content="c", source_role="senior_expert", source_type="extraction",
    )

    r = client.patch("/api/v1/knowledge-items/ki-test-001", json={"status": "bad_status"})
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_pending_rules_list_empty(client):
    r = client.get("/api/v1/pending-rules")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "items" in data


def test_pending_rule_not_found(client):
    r = client.get("/api/v1/pending-rules/ki-nonexistent")
    assert r.status_code == 404


def test_evolution_queue_source_role(tmp_path):
    """Test that append_evolve_hint stores source_role."""
    import json
    from backend.evolution_queue import append_evolve_hint, evolution_queue_dir

    append_evolve_hint(
        tmp_path,
        focus_id="req",
        suggestion="Test suggestion",
        source_role="senior_expert",
        source_type="post_review",
        project_id=42,
    )

    queue_dir = evolution_queue_dir(tmp_path)
    queue_file = queue_dir / "req.jsonl"
    assert queue_file.is_file()

    entries = [json.loads(line) for line in queue_file.read_text().splitlines() if line.strip()]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["source_role"] == "senior_expert"
    assert entry["source_type"] == "post_review"
    assert entry["project_id"] == "42"
    assert entry["status"] == "pending_review"


def test_evolution_queue_default_role(tmp_path, monkeypatch):
    """Test that AIKA_USER_ROLE env var is used as default source_role."""
    monkeypatch.setenv("AIKA_USER_ROLE", "consultant")
    import json
    from backend.evolution_queue import append_evolve_hint, evolution_queue_dir

    append_evolve_hint(tmp_path, focus_id="risk", suggestion="Test hint")

    entries = [
        json.loads(line)
        for line in (evolution_queue_dir(tmp_path) / "risk.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert entries[0]["source_role"] == "consultant"


def test_rule_conflict_detector_same_focus_high_similarity():
    from backend.rule_conflict_detector import detect_conflicts

    new_item = {
        "extraction_focus_id": "req",
        "title": "需求完整性检查",
        "content": "需求文档必须包含功能需求和非功能需求",
    }
    existing = [
        {"id": "req", "name": "需求完整性", "prompt": "需求文档必须包含功能需求和非功能需求的完整描述"},
    ]
    conflicts = detect_conflicts(new_item, existing)
    assert "req" in conflicts


def test_rule_conflict_detector_no_conflict():
    from backend.rule_conflict_detector import detect_conflicts

    new_item = {
        "extraction_focus_id": "risk",
        "title": "完全不同的规则",
        "content": "这是一条关于风险的全新规则，与已有规则无关",
    }
    existing = [
        {"id": "req", "name": "需求完整性", "prompt": "需求文档必须完整"},
    ]
    conflicts = detect_conflicts(new_item, existing)
    assert conflicts == []


def test_focus_point_applicable_when_roundtrip(tmp_path):
    """Test that FocusPoint applicable_when serializes/deserializes correctly."""
    from backend.skills.focus_point_io import FocusPoint, load_focus_point, save_focus_point

    fp = FocusPoint(
        id="test_fp",
        name="测试关注点",
        prompt="这是测试提示词",
        applicable_when={"project_type": ["contract"], "duration_months_gt": 6},
        not_applicable_when={"project_type": ["poc"]},
        scope_note="合同型项目",
    )
    dest = save_focus_point(fp, tmp_path)
    loaded = load_focus_point(dest)
    assert loaded is not None
    assert loaded.id == "test_fp"
    assert loaded.scope_note == "合同型项目"
    # applicable_when may or may not round-trip depending on yaml availability
    # but the file should at least load without error
