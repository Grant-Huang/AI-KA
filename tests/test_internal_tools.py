from __future__ import annotations

from backend.tools.registry import invoke_tool, list_tool_names


def test_list_tool_names_contains_validate() -> None:
    assert "validate_review_domain" in list_tool_names()


def test_validate_review_domain_tool_invalid() -> None:
    r = invoke_tool("validate_review_domain", text="not valid markdown structure")
    assert r.get("status") == "error"
