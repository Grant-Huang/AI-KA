"""Tests for Review Queue DB CRUD and API."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from aika import db as dbm
from aika.paths import db_path


@pytest.fixture
def conn(tmp_path: Path):
    c = dbm.connect(db_path(tmp_path))
    dbm.ensure_schema(c)
    return c


# ---------------------------------------------------------------------------
# DB CRUD tests
# ---------------------------------------------------------------------------

def test_upsert_and_get_review_queue(conn):
    item_id = f"rq-{uuid.uuid4().hex[:12]}"
    dbm.upsert_review_queue_item(
        conn,
        id=item_id,
        focus_id="req",
        suggestion="金融项目需要额外监管合规检查",
        source_role="ai_self",
        source_type="evolve_hint",
        project_id="42",
    )
    item = dbm.get_review_queue_item(conn, item_id)
    assert item is not None
    assert item["focus_id"] == "req"
    assert item["source_role"] == "ai_self"
    assert item["source_type"] == "evolve_hint"
    assert item["status"] == "pending_review"
    assert item["occurrences"] == 1


def test_upsert_increments_occurrences(conn):
    item_id = f"rq-{uuid.uuid4().hex[:12]}"
    for _ in range(3):
        dbm.upsert_review_queue_item(
            conn,
            id=item_id,
            focus_id="risk",
            suggestion="test",
            source_role="ai_self",
            source_type="evolve_hint",
        )
    item = dbm.get_review_queue_item(conn, item_id)
    assert item["occurrences"] == 3


def test_list_review_queue_sorted_by_occurrences(conn):
    ids = []
    for i, occ in enumerate([1, 3, 2]):
        item_id = f"rq-{uuid.uuid4().hex[:8]}-{i}"
        ids.append((item_id, occ))
        for _ in range(occ):
            dbm.upsert_review_queue_item(
                conn, id=item_id, focus_id="f", suggestion=f"s{i}",
                source_role="ai_self", source_type="evolve_hint",
            )
    items = dbm.list_review_queue(conn)
    occs = [it["occurrences"] for it in items]
    assert occs == sorted(occs, reverse=True)


def test_update_review_queue_status(conn):
    item_id = f"rq-{uuid.uuid4().hex[:12]}"
    dbm.upsert_review_queue_item(
        conn, id=item_id, focus_id="f", suggestion="s",
        source_role="senior_expert", source_type="extraction",
    )
    updated = dbm.update_review_queue_status(
        conn, item_id, status="approved", reviewed_by="expert1"
    )
    assert updated is True
    item = dbm.get_review_queue_item(conn, item_id)
    assert item["status"] == "approved"
    assert item["reviewed_by"] == "expert1"


def test_delete_review_queue_item(conn):
    item_id = f"rq-{uuid.uuid4().hex[:12]}"
    dbm.upsert_review_queue_item(
        conn, id=item_id, focus_id="f", suggestion="s",
        source_role="ai_self", source_type="evolve_hint",
    )
    deleted = dbm.delete_review_queue_item(conn, item_id)
    assert deleted is True
    assert dbm.get_review_queue_item(conn, item_id) is None


# ---------------------------------------------------------------------------
# DB CRUD tests: Knowledge Items
# ---------------------------------------------------------------------------

def test_insert_and_get_knowledge_item(conn):
    kid = "ki-001"
    dbm.insert_knowledge_item(
        conn,
        id=kid,
        extraction_focus_id="req",
        title="合规需求必须纳入",
        content="IF 金融类项目 THEN 需求列表必须包含监管合规章节",
        confidence="high",
        applicable_when={"project_type": ["finance"]},
        not_applicable_when={"project_type": ["poc"]},
        scope_note="仅适用于金融行业项目",
        source_role="senior_expert",
        source_type="extraction",
    )
    item = dbm.get_knowledge_item(conn, kid)
    assert item is not None
    assert item["title"] == "合规需求必须纳入"
    assert item["confidence"] == "high"
    assert item["applicable_when"] == {"project_type": ["finance"]}
    assert item["status"] == "pending"


def test_update_knowledge_item_status(conn):
    kid = "ki-002"
    dbm.insert_knowledge_item(
        conn, id=kid, extraction_focus_id="req", title="t", content="c",
        source_role="senior_expert", source_type="extraction",
    )
    updated = dbm.update_knowledge_item_status(conn, kid, status="approved")
    assert updated is True
    item = dbm.get_knowledge_item(conn, kid)
    assert item["status"] == "approved"


def test_list_knowledge_items_filter_by_status(conn):
    for i, status in enumerate(["pending", "pending", "approved"]):
        dbm.insert_knowledge_item(
            conn, id=f"ki-{i+1:03d}", extraction_focus_id="f",
            title=f"t{i}", content="c",
            source_role="senior_expert", source_type="extraction",
        )
        if status != "pending":
            dbm.update_knowledge_item_status(conn, f"ki-{i+1:03d}", status=status)
    pending = dbm.list_knowledge_items(conn, status="pending")
    approved = dbm.list_knowledge_items(conn, status="approved")
    assert len(pending) == 2
    assert len(approved) == 1


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

def test_review_queue_api_list(client):
    r = client.get("/api/v1/review-queue")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert "items" in data["data"]


def test_review_queue_api_create_and_get(client):
    r = client.post("/api/v1/review-queue", json={
        "focus_id": "req",
        "suggestion": "Test suggestion",
        "source_role": "senior_expert",
        "source_type": "extraction",
    })
    assert r.status_code == 200
    item = r.json()["data"]
    assert item["focus_id"] == "req"
    item_id = item["id"]

    r2 = client.get(f"/api/v1/review-queue/{item_id}")
    assert r2.status_code == 200
    assert r2.json()["data"]["id"] == item_id


def test_review_queue_api_patch_status(client):
    r = client.post("/api/v1/review-queue", json={
        "focus_id": "req",
        "suggestion": "Test",
        "source_role": "ai_self",
        "source_type": "evolve_hint",
    })
    item_id = r.json()["data"]["id"]

    r2 = client.patch(f"/api/v1/review-queue/{item_id}", json={"status": "in_review"})
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "in_review"


def test_review_queue_api_delete(client):
    r = client.post("/api/v1/review-queue", json={
        "focus_id": "req",
        "suggestion": "Delete me",
        "source_role": "ai_self",
        "source_type": "evolve_hint",
    })
    item_id = r.json()["data"]["id"]

    r2 = client.delete(f"/api/v1/review-queue/{item_id}")
    assert r2.status_code == 200

    r3 = client.get(f"/api/v1/review-queue/{item_id}")
    assert r3.status_code == 404


def test_review_queue_api_invalid_status(client):
    r = client.post("/api/v1/review-queue", json={
        "focus_id": "f", "suggestion": "s",
        "source_role": "ai_self", "source_type": "evolve_hint",
    })
    item_id = r.json()["data"]["id"]
    r2 = client.patch(f"/api/v1/review-queue/{item_id}", json={"status": "invalid_status"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "error"
