from __future__ import annotations

import logging

from backend.hooks.registry import register_after_analyze, register_before_analyze

_audit = logging.getLogger("aika.hooks.audit")


def _audit_before(ctx: dict[str, object]) -> None:
    _audit.info(
        "before_analyze project=%s conversation=%s focus=%s",
        ctx.get("project_id"),
        ctx.get("conversation_id"),
        ctx.get("focus_points"),
    )


def _audit_after(ctx: dict[str, object]) -> None:
    _audit.info(
        "after_analyze project=%s conversation=%s meta_keys=%s",
        ctx.get("project_id"),
        ctx.get("conversation_id"),
        list((ctx.get("run_metadata") or {}).keys()) if isinstance(ctx.get("run_metadata"), dict) else None,
    )


_registered = False


def register_builtin_hooks() -> None:
    global _registered
    if _registered:
        return
    _registered = True
    register_before_analyze(_audit_before)
    register_after_analyze(_audit_after)
