"""分析前后钩子注册与执行。"""

from backend.hooks.builtin import register_builtin_hooks
from backend.hooks.registry import (
    clear_hooks_for_tests,
    register_after_analyze,
    register_before_analyze,
    run_after_analyze_hooks,
    run_before_analyze_hooks,
)

__all__ = [
    "clear_hooks_for_tests",
    "register_after_analyze",
    "register_before_analyze",
    "register_builtin_hooks",
    "run_after_analyze_hooks",
    "run_before_analyze_hooks",
]
