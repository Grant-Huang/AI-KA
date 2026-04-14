from __future__ import annotations

from pathlib import Path

from backend.memory_recall import memory_root_under_repo, recall_memory_snippets


def test_recall_respects_already_surfaced(tmp_path: Path) -> None:
    root = memory_root_under_repo(tmp_path)
    d = root / "user"
    d.mkdir(parents=True)
    (d / "a.md").write_text("离散制造 SAP 接口", encoding="utf-8")
    (d / "b.md").write_text("其他", encoding="utf-8")
    out = recall_memory_snippets(
        memory_root=root,
        project_id=1,
        query="SAP 离散",
        already_surfaced=set(),
        limit=5,
    )
    assert len(out) >= 1
    ids = {x["id"] for x in out}
    out2 = recall_memory_snippets(
        memory_root=root,
        project_id=1,
        query="SAP",
        already_surfaced=ids,
        limit=5,
    )
    assert all(x["id"] not in ids for x in out2)
