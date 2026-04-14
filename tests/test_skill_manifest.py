from __future__ import annotations

import pytest

from aika.skill_manifest import validate_skill_manifest


def test_validate_skill_manifest_ok() -> None:
    m = validate_skill_manifest(
        {
            "schema_version": "1",
            "id": "p1",
            "name": "N",
            "version": "1.0.0",
            "focus_ids": ["a", "b"],
        }
    )
    assert m["id"] == "p1"
    assert m["focus_ids"] == ["a", "b"]


def test_validate_skill_manifest_rejects_bad_version() -> None:
    with pytest.raises(ValueError):
        validate_skill_manifest({"schema_version": "2", "id": "x", "name": "n", "version": "1", "focus_ids": ["a"]})
