from __future__ import annotations

import json
from typing import Any


def sse_event(obj: dict[str, Any]) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def sse_stage(name: str, state: str, *, detail: str | None = None) -> str:
    payload: dict[str, Any] = {"type": "stage", "name": name, "state": state}
    if detail:
        payload["detail"] = detail
    return sse_event(payload)
