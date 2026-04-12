from __future__ import annotations

from pathlib import Path

from aika import db as dbm


def test_list_recent_messages_order_and_filter(tmp_path: Path) -> None:
    db_file = tmp_path / "aika.sqlite3"
    conn = dbm.connect(db_file)
    dbm.ensure_schema(conn)
    prj = dbm.create_project(conn, "p", (tmp_path / "proj").as_posix())
    conv = dbm.create_conversation(conn, project_id=prj.id, analysis_type="KA", title="t")

    for i in range(12):
        role = "user" if i % 2 == 0 else "assistant"
        dbm.insert_message(conn, conversation_id=conv.id, role=role, content=f"m{i}")

    dbm.insert_message(conn, conversation_id=conv.id, role="system", content="meta")

    recent = dbm.list_recent_messages(conn, conversation_id=conv.id, limit=5)
    assert len(recent) == 5
    assert [m.role for m in recent] == ["assistant", "user", "assistant", "user", "assistant"]
    assert recent[0].content == "m7"
    assert recent[-1].content == "m11"

