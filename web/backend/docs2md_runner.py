from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from backend.config import get_settings


class Docs2MdError(RuntimeError):
    pass


def all2md_script_path() -> Path:
    root = get_settings().docs2md_root
    if not root:
        raise Docs2MdError("DOCS2MD_ROOT is not set")
    script = Path(root) / "all2md.py"
    if not script.is_file():
        raise Docs2MdError(f"all2md.py not found under DOCS2MD_ROOT: {script}")
    return script.resolve()


def run_convert_directory(
    *,
    input_dir: Path,
    output_dir: Path,
    format_: str = "md",
) -> Iterator[str]:
    """
    Stream lines from docs2md stdout/stderr (merged).

    Prefer the installed CLI (`python -m docs2md.cli`). If `DOCS2MD_ROOT` is
    configured and contains `all2md.py`, use that as an override/compat path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    st = get_settings()

    cmd: list[str]
    cwd: str | None = None
    if st.docs2md_root:
        script = all2md_script_path()
        py = st.docs2md_python
        cmd = [py, str(script), str(input_dir), "-o", str(output_dir), "-f", format_]
        cwd = str(script.parent)
    else:
        cmd = [sys.executable, "-m", "docs2md.cli", str(input_dir), "-o", str(output_dir), "--format", format_]

    yield f"[cmd] {' '.join(cmd)}\n"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        yield line
    proc.wait()
    if proc.returncode != 0:
        raise Docs2MdError(f"docs2md exited with code {proc.returncode}")
