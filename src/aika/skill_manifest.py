from __future__ import annotations

from typing import Any


def validate_skill_manifest(obj: dict[str, Any]) -> dict[str, Any]:
    """校验 SkillManifest v1，返回规范化 dict。"""
    if not isinstance(obj, dict):
        raise ValueError("manifest must be a JSON object")
    sv = str(obj.get("schema_version") or "").strip()
    if sv != "1":
        raise ValueError("schema_version must be '1'")
    mid = str(obj.get("id") or "").strip()
    if not mid:
        raise ValueError("id is required")
    name = str(obj.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    ver = str(obj.get("version") or "").strip()
    if not ver:
        raise ValueError("version is required")
    focus_ids = obj.get("focus_ids")
    if not isinstance(focus_ids, list) or not focus_ids:
        raise ValueError("focus_ids must be a non-empty array of strings")
    for x in focus_ids:
        if not isinstance(x, str) or not str(x).strip():
            raise ValueError("focus_ids must contain non-empty strings")
    return {
        "schema_version": sv,
        "id": mid,
        "name": name,
        "version": ver,
        "focus_ids": [str(x).strip() for x in focus_ids],
        "review_role": obj.get("review_role"),
        "review_goals_principles": obj.get("review_goals_principles"),
        "output_requirements": obj.get("output_requirements"),
        "description": obj.get("description"),
        "tags": obj.get("tags") if isinstance(obj.get("tags"), list) else [],
    }
