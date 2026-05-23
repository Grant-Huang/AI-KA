"""G1 – Meso v1.0 SSE protocol contract tests.

Every streaming endpoint must produce events in the Meso v1.0 envelope:
  {"type": "<type>", "schema_version": "1.0", "payload": {...}}

The stream must terminate with exactly one "done" or "error" event.
These tests document the TARGET state; they are intentionally RED
until G2 (backend SSE migration) lands.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse_events(raw: bytes) -> list[dict[str, Any]]:
    """Extract JSON objects from a raw SSE response body."""
    events: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload_str = line[len("data:"):].strip()
        if payload_str == "[DONE]":
            # OpenAI-compat sentinel – not required, but tolerated
            continue
        try:
            events.append(json.loads(payload_str))
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise AssertionError(f"SSE line is not valid JSON: {payload_str!r}") from exc
    return events


def _assert_meso_envelope(events: list[dict[str, Any]]) -> None:
    """Assert every event conforms to the Meso v1.0 envelope."""
    assert events, "No SSE events received"
    for ev in events:
        assert "type" in ev, f"Event missing 'type': {ev}"
        assert ev.get("schema_version") == "1.0", (
            f"Event missing or wrong schema_version (expected '1.0'): {ev}"
        )
        assert "payload" in ev and isinstance(ev["payload"], dict), (
            f"Event missing 'payload' dict: {ev}"
        )


def _assert_terminal_event(events: list[dict[str, Any]]) -> None:
    """Assert the stream ends with exactly one 'done' or 'error' event."""
    assert events, "No SSE events received"
    last = events[-1]
    assert last["type"] in ("done", "error"), (
        f"Last event must be 'done' or 'error', got: {last.get('type')!r}\n"
        f"All events: {[e.get('type') for e in events]}"
    )
    # At most one terminal event
    terminal_types = [e["type"] for e in events if e.get("type") in ("done", "error")]
    assert len(terminal_types) == 1, (
        f"Expected exactly one terminal event, got: {terminal_types}"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeAnalyzeProvider:
    """LLM stub for Meso protocol tests."""

    def chat_stream(  # type: ignore[no-untyped-def]
        self, *, system: str, user: str, config: object, prior_messages=None
    ):
        yield "## Analysis Result\n\nThis is a test result.\n"


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[return]
    get_settings.cache_clear()
    yield  # type: ignore[misc]
    get_settings.cache_clear()


@pytest.fixture
def analyze_stream_response(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> bytes:
    """POST to /analyze/stream and return raw SSE body."""
    monkeypatch.setenv("AIKA_REPO_ROOT", str(tmp_path))
    (tmp_path / "default_skills.md").write_text(
        "# r\n\n## 关注点块\n\n### focus:req | 需求\n关注点提示\n",
        encoding="utf-8",
    )
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "get_provider", lambda _p: _FakeAnalyzeProvider())
    monkeypatch.setattr(
        main_mod.dbm,
        "list_chunk_entries",
        lambda *a, **k: [
            {
                "doc_path": "a.md",
                "chunk_index": 0,
                "text": "hello chunk",
                "locator": {"start_line": 1, "end_line": 1, "heading_path": []},
            }
        ],
    )

    from backend.main import app

    client = TestClient(app)
    src = tmp_path / "docs_in"
    src.mkdir()
    create = client.post(
        "/api/v1/projects/ensure",
        json={"name": f"p-{uuid.uuid4().hex[:8]}", "root_path": str(src)},
    )
    assert create.status_code == 200
    project_id = int(create.json()["data"]["id"])

    conv = client.post(
        f"/api/v1/projects/{project_id}/conversations",
        json={"analysis_type": "KA", "title": "T1"},
    )
    assert conv.status_code == 200
    conversation_id = int(conv.json()["data"]["id"])

    resp = client.post(
        f"/api/v1/projects/{project_id}/conversations/{conversation_id}/analyze/stream",
        json={"chunk_limit": 40, "focus_points": ["需求"]},
    )
    assert resp.status_code == 200
    return resp.content


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMesoEnvelopeFormat:
    """All streaming events must conform to Meso v1.0 envelope."""

    def test_every_event_has_schema_version(self, analyze_stream_response: bytes) -> None:
        events = _parse_sse_events(analyze_stream_response)
        _assert_meso_envelope(events)

    def test_stream_terminates_with_done_or_error(self, analyze_stream_response: bytes) -> None:
        events = _parse_sse_events(analyze_stream_response)
        _assert_meso_envelope(events)
        _assert_terminal_event(events)

    def test_stage_events_have_name_and_state(self, analyze_stream_response: bytes) -> None:
        """stage events must use 'name' and 'state' (not 'stage'/'status')."""
        events = _parse_sse_events(analyze_stream_response)
        stage_events = [e for e in events if e.get("type") == "stage"]
        assert stage_events, "Expected at least one stage event"
        for ev in stage_events:
            payload = ev["payload"]
            assert "name" in payload, f"stage payload missing 'name': {ev}"
            assert "state" in payload, f"stage payload missing 'state': {ev}"
            assert payload["state"] in ("active", "done", "error"), (
                f"stage.state must be active/done/error, got {payload['state']!r}: {ev}"
            )

    def test_text_events_have_delta(self, analyze_stream_response: bytes) -> None:
        """text events (LLM token stream) must have payload.delta."""
        events = _parse_sse_events(analyze_stream_response)
        text_events = [e for e in events if e.get("type") == "text"]
        for ev in text_events:
            assert "delta" in ev["payload"], f"text event missing 'delta': {ev}"

    def test_no_bare_delta_events(self, analyze_stream_response: bytes) -> None:
        """Legacy bare {type: delta, text: ...} must not appear in stream."""
        events = _parse_sse_events(analyze_stream_response)
        bare_delta = [e for e in events if e.get("type") == "delta"]
        assert not bare_delta, (
            f"Found {len(bare_delta)} legacy 'delta' event(s) – must be migrated to 'text': "
            f"{bare_delta[:3]}"
        )

    def test_no_bare_final_events(self, analyze_stream_response: bytes) -> None:
        """Legacy {type: final, markdown: ...} must become extension or done."""
        events = _parse_sse_events(analyze_stream_response)
        bare_final = [e for e in events if e.get("type") == "final"]
        assert not bare_final, (
            f"Found {len(bare_final)} legacy 'final' event(s) – must be migrated: "
            f"{bare_final[:3]}"
        )

    def test_extension_events_have_name_and_data(self, analyze_stream_response: bytes) -> None:
        """extension events must have payload.name and payload.data."""
        events = _parse_sse_events(analyze_stream_response)
        ext_events = [e for e in events if e.get("type") == "extension"]
        for ev in ext_events:
            payload = ev["payload"]
            assert "name" in payload, f"extension missing 'name': {ev}"
            assert "data" in payload, f"extension missing 'data': {ev}"


class TestStageStateValues:
    """Stage state must use Meso values (active/done/error) not AI-KA legacy (start/end)."""

    def test_no_legacy_start_end_state(self, analyze_stream_response: bytes) -> None:
        events = _parse_sse_events(analyze_stream_response)
        stage_events = [e for e in events if e.get("type") == "stage"]
        for ev in stage_events:
            state = ev.get("payload", {}).get("state", "")
            assert state not in ("start", "end"), (
                f"stage.state uses legacy value {state!r} – use 'active'/'done': {ev}"
            )
