from __future__ import annotations

from typing import Any


def ok(data: Any = None, message: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "success", "data": data}
    if message is not None:
        out["message"] = message
    return out


def err(message: str, data: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "error", "message": message}
    if data is not None:
        out["data"] = data
    return out
