from __future__ import annotations

from backend.hooks import (
    clear_hooks_for_tests,
    register_after_analyze,
    register_before_analyze,
    register_builtin_hooks,
    run_after_analyze_hooks,
    run_before_analyze_hooks,
)


def test_hooks_run_in_order() -> None:
    clear_hooks_for_tests()
    order: list[str] = []

    def b(ctx: dict) -> None:
        order.append("b")

    def a(ctx: dict) -> None:
        order.append("a")

    register_before_analyze(b)
    register_before_analyze(a)
    run_before_analyze_hooks({})
    assert order == ["b", "a"]

    order.clear()

    def x(ctx: dict) -> None:
        order.append("x")

    def y(ctx: dict) -> None:
        order.append("y")

    register_after_analyze(x)
    register_after_analyze(y)
    run_after_analyze_hooks({})
    assert order == ["x", "y"]

    clear_hooks_for_tests()
    register_builtin_hooks()
