from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("aika.tools")

_registry: dict[str, Callable[..., dict[str, Any]]] = {}


def register_tool(name: str, fn: Callable[..., dict[str, Any]]) -> None:
    _registry[str(name)] = fn


def list_tool_names() -> list[str]:
    return sorted(_registry.keys())


def invoke_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    fn = _registry.get(str(name))
    if fn is None:
        return {"status": "error", "message": f"unknown tool: {name}"}
    try:
        out = fn(**kwargs)
        if isinstance(out, dict) and out.get("status") in ("success", "error"):
            return out
        return {"status": "success", "data": out}
    except Exception as e:
        logger.exception("tool %s failed", name)
        return {"status": "error", "message": str(e)}


def _impl_validate_review_domain(*, text: str) -> dict[str, Any]:
    from backend.skills.review_domain_io import read_settings_from_domain_text, review_domain_strict_schema_error

    strict = review_domain_strict_schema_error(text)
    if strict:
        return {"status": "error", "message": strict, "strict_error": strict}
    parsed, parse_error = read_settings_from_domain_text(text)
    if parse_error:
        return {"status": "error", "message": parse_error}
    fps = (parsed or {}).get("focus_points") if isinstance(parsed, dict) else None
    n = len(fps) if isinstance(fps, list) else 0
    return {"status": "success", "focus_point_count": n, "strict_error": None}


def _impl_compute_scope_metrics_stub(*, project_id: int) -> dict[str, Any]:
    return {"status": "success", "project_id": int(project_id), "metrics": {}}


def _register_defaults() -> None:
    register_tool("validate_review_domain", _impl_validate_review_domain)
    register_tool("compute_scope_metrics", _impl_compute_scope_metrics_stub)


_register_defaults()
