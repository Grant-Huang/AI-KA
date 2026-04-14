from __future__ import annotations

from backend.run_metadata import build_run_metadata, sha256_short


def test_sha256_short_stable() -> None:
    assert len(sha256_short("hello")) == 16


def test_build_run_metadata() -> None:
    m = build_run_metadata(
        skill_id="s1",
        skill_version="1.0.0",
        rules_hash="abc",
        memory_injected=[{"id": "u/x.md", "title": "x"}],
        rules_filename="review_domain.md",
    )
    assert m["skill_id"] == "s1"
    assert m["memory_files_injected"][0]["id"] == "u/x.md"
