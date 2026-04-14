from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("aika.hooks")

_before: list[Callable[[dict[str, Any]], None]] = []
_after: list[Callable[[dict[str, Any]], None]] = []


def list_hook_names() -> dict[str, list[str]]:
    def _fmt(fn: Callable[[dict[str, Any]], None]) -> str:
        mod = getattr(fn, "__module__", "") or ""
        name = getattr(fn, "__name__", "") or ""
        return f"{mod}.{name}".strip(".") or repr(fn)

    return {
        "before_analyze": [_fmt(fn) for fn in _before],
        "after_analyze": [_fmt(fn) for fn in _after],
    }


def register_before_analyze(fn: Callable[[dict[str, Any]], None]) -> None:
    _before.append(fn)


def register_after_analyze(fn: Callable[[dict[str, Any]], None]) -> None:
    _after.append(fn)


def run_before_analyze_hooks(ctx: dict[str, Any]) -> None:
    for fn in _before:
        try:
            fn(ctx)
        except Exception:
            logger.exception("before_analyze hook failed")


def run_after_analyze_hooks(ctx: dict[str, Any]) -> None:
    for fn in _after:
        try:
            fn(ctx)
        except Exception:
            logger.exception("after_analyze hook failed")


def clear_hooks_for_tests() -> None:
    _before.clear()
    _after.clear()
    try:
        import backend.hooks.builtin as hb

        hb._registered = False  # type: ignore[attr-defined]
    except Exception:
        pass
