from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
import shutil

from backend.config import get_settings


class Docs2MdError(RuntimeError):
    pass


_MD_LIKE_EXTS = {".md", ".markdown", ".txt"}


def _is_md_like_file(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in _MD_LIKE_EXTS


def _scan_for_non_md_like_files(root: Path) -> list[Path]:
    """
    Return a small sample of non-md-like files. Used to decide md passthrough.
    """
    root = root.resolve()
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).resolve().relative_to(root).as_posix()
        if rel.startswith(".tmp") or rel.startswith("tmp") or rel.startswith(".git"):
            dirnames[:] = []
            continue
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.is_symlink():
                continue
            if _is_md_like_file(p):
                continue
            out.append(p)
            if len(out) >= 20:
                return out
    return out


def _copy_md_like_tree(src: Path, dst: Path) -> int:
    """
    Copy .md/.txt files from src into dst, preserving relative paths.
    Returns number of files copied.
    """
    src = src.resolve()
    dst = dst.resolve()
    copied = 0
    for dirpath, dirnames, filenames in os.walk(src):
        rel_dir = Path(dirpath).resolve().relative_to(src).as_posix()
        if rel_dir.startswith(".tmp") or rel_dir.startswith("tmp") or rel_dir.startswith(".git"):
            dirnames[:] = []
            continue
        for fn in filenames:
            p = Path(dirpath) / fn
            if not _is_md_like_file(p):
                continue
            rel = p.resolve().relative_to(src)
            target = (dst / rel).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            # lightweight validation: ensure readable as UTF-8 (replace ok), and non-empty
            text = p.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                continue
            shutil.copy2(p, target)
            copied += 1
    return copied


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

    non_md_like = _scan_for_non_md_like_files(input_dir)
    if not non_md_like:
        yield "[hint] 检测到输入目录仅包含 md/txt：跳过转换，仅检查并复制到 md_out。\n"
        copied = _copy_md_like_tree(input_dir, output_dir)
        if copied <= 0:
            raise Docs2MdError("输入目录未发现可用的 md/txt 内容（或内容为空）")
        yield f"[ok] 已复制 {copied} 个 md/txt 文件到：{output_dir}\n"
        return

    cmd: list[str]
    cwd: str | None = None
    # Use installed CLI (python -m docs2md.cli) if no local docs2md_root is configured
    py = st.docs2md_python
    if st.docs2md_root and Path(st.docs2md_root).is_dir():
        script = all2md_script_path()
        cmd = [py, str(script), str(input_dir), "-o", str(output_dir), "-f", format_]
        cwd = str(script.parent)
    else:
        # 与 all2md 分支一致使用 docs2md_python，便于 DOCS2MD_PYTHON 指向含最新 docs2md 的 venv
        cmd = [py, "-m", "docs2md.cli", str(input_dir), "-o", str(output_dir), "--format", format_]

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

    # Throttle noisy per-page logs to avoid UI spam.
    last_progress_emit = 0.0
    progress_seen = 0
    image_parse_mismatch_warned = False
    page_re = re.compile(r"(?i)(page\\s*\\d+|第\\s*\\d+\\s*页|\\bpages?\\b)")
    progress_re = re.compile(r"(?i)(\\b\\d+%\\b|\\b\\d+/\\d+\\b)")

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
    # 用线程读 stdout，主生成器只在 yield 处暂停，便于客户端断开 SSE 时尽快 close 生成器并在 finally 中 kill 子进程
    line_queue: queue.Queue[str | None] = queue.Queue(maxsize=512)

    def _drain_stdout() -> None:
        try:
            for raw in proc.stdout:
                line_queue.put(raw)
        except Exception:
            pass
        finally:
            line_queue.put(None)

    threading.Thread(target=_drain_stdout, daemon=True).start()

    try:
        while True:
            line = line_queue.get()
            if line is None:
                break
            # Reduce per-page/progress spam: emit aggregated summary at most every ~2s.
            if page_re.search(line) or progress_re.search(line):
                progress_seen += 1
                now = time.time()
                if now - last_progress_emit >= 2.0:
                    last_progress_emit = now
                    yield f"[progress] 转换进行中…（已收到 {progress_seen} 条进度输出）\n"
                continue
            yield line
            if (
                disable_image_parse
                and (not image_parse_mismatch_warned)
                and "解析图片（" in line
            ):
                image_parse_mismatch_warned = True
                yield (
                    "[warn] 已启用“不解析图片”，但 docs2md 仍在尝试 VL 解析图片。"
                    "常见原因：① DOCS2MD_PYTHON 曾默认为系统 `python`，与后端解释器不一致（已改为默认使用后端同解释器，可显式设置 DOCS2MD_PYTHON）；"
                    "② DOCS2MD_ROOT 指向的 docs2md 源码较旧，docx 转换未在禁用时跳过 VL 调用——请拉取最新 docs2md 仓库后重启后端。\n"
                )
            lo = line.lower()
            if "missingdependencyexception" in lo and "xlsx" in lo:
                yield "[hint] 检测到缺少 xlsx 依赖：请在运行环境安装 markitdown[xlsx] 或 markitdown[all]，再重试。\n"
        proc.wait()
        if proc.returncode != 0:
            raise Docs2MdError(f"docs2md exited with code {proc.returncode}")
    finally:
        # 前端关闭 SSE 时会关闭生成器；此处终止子进程，避免「终止」后 docs2md 仍在后台跑
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
