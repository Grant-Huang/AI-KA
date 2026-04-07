from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from backend.config import get_settings


class Docs2MdError(RuntimeError):
    pass


def _vl_api_key_present(explicit_key: str | None = None) -> bool:
    if (explicit_key or "").strip():
        return True
    keys = (
        "AIKA_VL_API_KEY",
        "DASHSCOPE_API_KEY",
        "VL_API_KEY",
        "OPENAI_VL_API_KEY",
        "QWEN_VL_API_KEY",
    )
    return any((os.environ.get(k) or "").strip() for k in keys)


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
    vl_api_key: str | None = None,
    vl_model: str | None = None,
    vl_base_url: str | None = None,
    disable_image_parse: bool = False,
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
    # Use installed CLI (python -m docs2md.cli) if no local docs2md_root is configured
    if st.docs2md_root and Path(st.docs2md_root).is_dir():
        script = all2md_script_path()
        py = st.docs2md_python
        cmd = [py, str(script), str(input_dir), "-o", str(output_dir), "-f", format_]
        cwd = str(script.parent)
    else:
        cmd = [sys.executable, "-m", "docs2md.cli", str(input_dir), "-o", str(output_dir), "--format", format_]

    child_env = dict(os.environ)
    if (vl_api_key or "").strip():
        child_env["AIKA_VL_API_KEY"] = str(vl_api_key).strip()
        child_env["DASHSCOPE_API_KEY"] = str(vl_api_key).strip()
        child_env["VL_API_KEY"] = str(vl_api_key).strip()
        child_env["OPENAI_VL_API_KEY"] = str(vl_api_key).strip()
        child_env["QWEN_VL_API_KEY"] = str(vl_api_key).strip()
    if (vl_model or "").strip():
        child_env["AIKA_VL_MODEL"] = str(vl_model).strip()
        child_env["QWEN_VL_MODEL"] = str(vl_model).strip()
    if (vl_base_url or "").strip():
        child_env["AIKA_VL_BASE_URL"] = str(vl_base_url).strip()
        child_env["DASHSCOPE_BASE_URL"] = str(vl_base_url).strip()
        child_env["VL_BASE_URL"] = str(vl_base_url).strip()
        child_env["OPENAI_VL_BASE_URL"] = str(vl_base_url).strip()
        child_env["QWEN_VL_BASE_URL"] = str(vl_base_url).strip()

    if disable_image_parse:
        child_env["DOCS2MD_DISABLE_IMAGE_PARSE"] = "1"
        child_env["DOCS2MD_SKIP_IMAGE"] = "1"
        child_env["DOCS2MD_VL_ENABLED"] = "0"
        yield "[hint] 已配置为“不解析文件中的图片”：将跳过图片提取与解析。\n"
        yield (
            "[debug] 已设置环境变量："
            "DOCS2MD_DISABLE_IMAGE_PARSE=1, DOCS2MD_SKIP_IMAGE=1, DOCS2MD_VL_ENABLED=0\n"
        )
    elif not _vl_api_key_present(vl_api_key):
        # Best-effort flag: if docs2md supports these envs, image/VL parsing will be skipped.
        child_env["DOCS2MD_DISABLE_IMAGE_PARSE"] = "1"
        child_env["DOCS2MD_SKIP_IMAGE"] = "1"
        child_env["DOCS2MD_VL_ENABLED"] = "0"
        yield "[hint] 未检测到 VL API Key：将跳过图片解析环节（若 docs2md 支持该开关）。\n"

    yield f"[debug] disable_image_parse={disable_image_parse}\n"
    yield f"[cmd] {' '.join(cmd)}\n"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=child_env,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        yield line
        if disable_image_parse and "解析图片（" in line:
            yield (
                "[warn] 已启用“不解析图片”，但 docs2md 仍在解析图片。"
                "这通常表示运行的 docs2md 版本未支持该开关，或子进程未收到环境变量。"
                "请检查是否使用了最新 docs2md，以及 AI-KA 的 DOCS2MD_ROOT 是否指向最新仓库根目录（含 all2md.py），然后重启后端。\n"
            )
        lo = line.lower()
        if "missingdependencyexception" in lo and "xlsx" in lo:
            yield "[hint] 检测到缺少 xlsx 依赖：请在运行环境安装 markitdown[xlsx] 或 markitdown[all]，再重试。\n"
    proc.wait()
    if proc.returncode != 0:
        raise Docs2MdError(f"docs2md exited with code {proc.returncode}")
