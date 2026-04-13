from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aika.db as dbm
from backend.repo_paths import project_export_dir
from backend.services.outputs_files_service import (
    append_milestone_event,
    finalize_milestones_file,
    init_milestones_file,
    make_outputs_filenames,
)


@dataclass(frozen=True)
class OutputIndexItem:
    id: int
    conversation_id: int
    kind: str
    created_at: str
    final_download_path: str
    milestones_download_path: str
    fragments_index_download_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_outputs_index(
    conn,
    *,
    project_id: int,
    conversation_id: int,
    limit: int = 50,
) -> list[OutputIndexItem]:
    rows = dbm.list_conversation_outputs(conn, conversation_id=conversation_id, limit=limit)

    def dl(filename: str) -> str:
        return f"/api/v1/files/{int(project_id)}/{filename}"

    if not rows:
        # 兼容旧数据：历史版本可能只写入 analysis_runs.output_markdown_path 或 messages(assistant)，但未落 conversation_outputs
        exp_dir = project_export_dir(project_id)
        exp_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_base = f"conv-{int(conversation_id)}-legacy"
        files = make_outputs_filenames(kind="analyze", safe_base=safe_base, ts=ts, include_fragments_index=False)
        out_path = exp_dir / files.final_filename
        milestones_path = exp_dir / files.milestones_filename

        body = ""
        run = dbm.get_latest_analysis_run(conn, conversation_id=conversation_id)
        if run is not None:
            src = Path(str(run.output_markdown_path))
            if src.is_file():
                body = src.read_text(encoding="utf-8")

        if not body.strip():
            msgs = dbm.list_recent_messages(conn, conversation_id=conversation_id, limit=50)
            assistants = [m.content for m in msgs if m.role == "assistant"]
            body = (assistants[-1] if assistants else "").strip()

        if body.strip():
            out_path.write_text(body, encoding="utf-8")
            init_milestones_file(milestones_path)
            append_milestone_event(milestones_path, {"type": "stage", "stage": "呈现结果", "status": "end"})
            append_milestone_event(milestones_path, {"type": "final", "output_markdown_path": str(out_path)})
            finalize_milestones_file(milestones_path)
            dbm.insert_conversation_output(
                conn,
                conversation_id=conversation_id,
                kind="analyze",
                final_filename=files.final_filename,
                milestones_filename=files.milestones_filename,
                fragments_index_filename=None,
            )
            rows = dbm.list_conversation_outputs(conn, conversation_id=conversation_id, limit=limit)

    out: list[OutputIndexItem] = []
    for r in rows:
        out.append(
            OutputIndexItem(
                id=int(r.id),
                conversation_id=int(r.conversation_id),
                kind=str(r.kind),
                created_at=str(r.created_at),
                final_download_path=dl(str(r.final_filename)),
                milestones_download_path=dl(str(r.milestones_filename)),
                fragments_index_download_path=(
                    dl(str(r.fragments_index_filename)) if r.fragments_index_filename else None
                ),
            )
        )
    return out

