from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class MissingDep:
    name: str
    commands: list[str]
    purpose: str
    install_hint: str


def _which_any(cmds: list[str]) -> str | None:
    for c in cmds:
        hit = shutil.which(c)
        if hit:
            return hit
    return None


def _install_hint(tool: str) -> str:
    sys = platform.system().lower()
    if sys == "darwin":
        if tool == "pandoc":
            return "macOS: `brew install pandoc`"
        if tool == "graphviz":
            return "macOS: `brew install graphviz`"
    if sys == "linux":
        if tool == "pandoc":
            return "Linux: `sudo apt-get update && sudo apt-get install -y pandoc`（或使用发行版对应包管理器）"
        if tool == "graphviz":
            return "Linux: `sudo apt-get update && sudo apt-get install -y graphviz`（或使用发行版对应包管理器）"
    if sys == "windows":
        if tool == "pandoc":
            return "Windows: 安装 Pandoc（可用 `choco install pandoc` 或 `scoop install pandoc`）。"
        if tool == "graphviz":
            return "Windows: 安装 Graphviz（可用 `choco install graphviz` 或 `scoop install graphviz`），并确保 `dot.exe` 在 PATH 中。"
    return f"请安装 {tool} 并确保相关命令在 PATH 中可用。"


def check_runtime_system_deps() -> list[MissingDep]:
    """
    Check non-Python system dependencies.

    This app does not auto-install system tools. It only detects and prints hints.
    """
    missing: list[MissingDep] = []

    # epic-doc: optional extra outputs.
    if _which_any(["pandoc"]) is None:
        missing.append(
            MissingDep(
                name="pandoc",
                commands=["pandoc"],
                purpose="epic-doc：可选，用于 HTML/PDF 等输出能力（若你只生成 docx 可忽略）。",
                install_hint=_install_hint("pandoc"),
            )
        )

    if _which_any(["dot"]) is None:
        missing.append(
            MissingDep(
                name="graphviz",
                commands=["dot"],
                purpose="epic-doc：可选，用于流程图渲染（若文档包含 graphviz 图可需要）。",
                install_hint=_install_hint("graphviz"),
            )
        )

    return missing

