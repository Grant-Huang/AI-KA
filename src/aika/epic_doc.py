from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EpicDocResult:
    command: list[str]
    output_path: Path


class EpicDocError(RuntimeError):
    pass


def build_generate_command(*, config_path: Path, output_path: Path) -> list[str]:
    return [
        "epic-doc",
        "generate",
        str(config_path),
        "-o",
        str(output_path),
    ]


def generate_docx(
    *,
    config_path: Path,
    output_path: Path,
    dry_run: bool = False,
) -> EpicDocResult:
    if not config_path.exists():
        raise EpicDocError(f"config not found: {config_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_generate_command(config_path=config_path, output_path=output_path)

    if dry_run:
        return EpicDocResult(command=cmd, output_path=output_path)

    if shutil.which("epic-doc") is None:
        raise EpicDocError("epic-doc not found in PATH (install: pip install epic-doc)")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip()
        out = (e.stdout or "").strip()
        msg = err or out or str(e)
        raise EpicDocError(f"epic-doc generate failed: {msg}") from e

    if not output_path.exists():
        raise EpicDocError(f"docx not generated: {output_path}")

    return EpicDocResult(command=cmd, output_path=output_path)

