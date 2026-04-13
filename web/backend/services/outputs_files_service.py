from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OutputsFilesPaths:
    final_filename: str
    milestones_filename: str
    fragments_index_filename: str | None


def make_outputs_filenames(
    *,
    kind: str,
    safe_base: str,
    ts: str | None = None,
    include_fragments_index: bool = False,
) -> OutputsFilesPaths:
    stamp = ts or datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{safe_base}-{stamp}-{kind}"
    final_filename = f"{base}-final.md"
    milestones_filename = f"{base}-milestones.md"
    fragments_index_filename = f"{base}-fragments-index.md" if include_fragments_index else None
    return OutputsFilesPaths(
        final_filename=final_filename,
        milestones_filename=milestones_filename,
        fragments_index_filename=fragments_index_filename,
    )


def init_milestones_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# Milestones",
        "",
        "```jsonl",
        "",
    ]
    path.write_text("\n".join(header), encoding="utf-8")


def append_milestone_event(path: Path, event: dict[str, Any]) -> None:
    line = json.dumps(event, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def finalize_milestones_file(path: Path) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write("```\n")

