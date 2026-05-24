from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Low-level wire format
# ---------------------------------------------------------------------------

def _meso_wrap(event_type: str, payload: dict[str, Any]) -> str:
    """Serialize one Meso v1.0 event as an SSE data line."""
    obj = {"type": event_type, "schema_version": "1.0", "payload": payload}
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _normalize_state(state: str) -> str:
    """Map AI-KA legacy stage state values to Meso v1.0 values."""
    return {"start": "active", "end": "done"}.get(state, state)


# ---------------------------------------------------------------------------
# sse_event – transparent Meso v1.0 upgrade shim
#
# All existing _sse_line({...}) call-sites produce the old flat format.
# This function intercepts every dict and wraps it in the Meso v1.0 envelope,
# mapping legacy field names and type values where necessary.
# Call-sites do NOT need to be changed for the shim to take effect.
# ---------------------------------------------------------------------------

def sse_event(obj: dict[str, Any]) -> str:
    """Convert any AI-KA event dict to a Meso SSE data line.

    Already-wrapped events (any schema_version) pass through unchanged so that
    pre-wrapped v2.0+ events are never double-wrapped.
    Legacy flat events are upgraded to the Meso v1.0 envelope transparently.
    """
    # Already Meso-wrapped (any version) – pass through unchanged.
    # Detect by structural check rather than a hard-coded version string so
    # that v2.0+ events are forwarded correctly without re-wrapping.
    if "schema_version" in obj and "payload" in obj and "type" in obj:
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    event_type = obj.get("type", "extension")

    if event_type == "stage":
        # Support both naming conventions used across the codebase:
        #   name / stage,  state / status,  start→active / end→done
        name = obj.get("name") or obj.get("stage") or ""
        raw_state = obj.get("state") or obj.get("status") or ""
        state = _normalize_state(raw_state)
        payload: dict[str, Any] = {"name": name, "state": state}
        if obj.get("detail"):
            payload["detail"] = obj["detail"]
        meso_type = "stage"

    elif event_type in ("delta", "assistant_delta"):
        # Streaming LLM text token
        meso_type = "text"
        payload = {"delta": obj.get("text", "")}

    elif event_type == "error":
        meso_type = "error"
        payload = {"message": obj.get("message", str(obj))}

    elif event_type == "done":
        # Explicit done sentinel – pass through as Meso done
        meso_type = "done"
        payload = {}

    elif event_type == "memory":
        meso_type = "memory"
        payload = {"snippets": obj.get("snippets", [])}

    else:
        # All AI-KA-specific types (final, finding, chunk_index, explain_*,
        # pass_done, status, critique, agent_stage, agent_decision, …)
        # become Meso extension events.
        meso_type = "extension"
        data = {k: v for k, v in obj.items() if k != "type"}
        # Normalize any "state" field so agent_stage events use active/done
        # vocabulary, matching what the frontend expects after mesoToFlat.
        if "state" in data:
            data = {**data, "state": _normalize_state(data["state"])}
        payload = {"name": event_type, "data": data}

    return _meso_wrap(meso_type, payload)


# ---------------------------------------------------------------------------
# Named helpers (used by new code and for explicit clarity)
# ---------------------------------------------------------------------------

def sse_stage(name: str, state: str, *, detail: str | None = None) -> str:
    """stage event: pipeline progress indicator."""
    p: dict[str, Any] = {"type": "stage", "name": name, "state": state}
    if detail:
        p["detail"] = detail
    return sse_event(p)


def sse_text(delta: str) -> str:
    """text event: incremental LLM response token."""
    return _meso_wrap("text", {"delta": delta})


def sse_done() -> str:
    """done event: stream ended successfully (terminal)."""
    return _meso_wrap("done", {})


def sse_error(message: str) -> str:
    """error event: unrecoverable error (terminal)."""
    return _meso_wrap("error", {"message": message})


def sse_extension(name: str, data: dict[str, Any]) -> str:
    """extension event: AI-KA domain-specific event."""
    return _meso_wrap("extension", {"name": name, "data": data})


def sse_memory(snippets: list[dict[str, Any]]) -> str:
    """memory event: recalled memory snippets."""
    return _meso_wrap("memory", {"snippets": snippets})
