from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class FolderPickerError(RuntimeError):
    pass


def _pick_macos() -> str | None:
    script = 'POSIX path of (choose folder with prompt "请选择项目根目录")'
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError as e:
        raise FolderPickerError("osascript not found") from e
    except subprocess.TimeoutExpired as e:
        raise FolderPickerError("folder dialog timed out") from e
    if r.returncode != 0:
        return None
    raw = (r.stdout or "").strip()
    if not raw:
        return None
    # AppleScript may return paths like "/Users/x/" with trailing slash
    return str(Path(raw))


def _pick_zenity() -> str | None:
    zenity = shutil.which("zenity")
    if not zenity:
        return None
    try:
        r = subprocess.run(
            [zenity, "--file-selection", "--directory", "--title=请选择项目根目录"],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as e:
        raise FolderPickerError("zenity dialog timed out") from e
    if r.returncode != 0:
        return None
    raw = (r.stdout or "").strip()
    return str(Path(raw)) if raw else None


def _pick_tkinter_subprocess() -> str | None:
    """Run Tk file dialog in a separate interpreter process (avoids uvicorn thread issues)."""
    code = """import tkinter as tk
from tkinter import filedialog
r = tk.Tk()
r.withdraw()
try:
    r.attributes('-topmost', True)
except Exception:
    pass
p = filedialog.askdirectory(title='请选择项目根目录')
r.destroy()
print(p or '', end='')
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ},
        )
    except subprocess.TimeoutExpired as e:
        raise FolderPickerError("tkinter dialog timed out") from e
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if err:
            raise FolderPickerError(f"tkinter picker failed: {err}")
        return None
    raw = (r.stdout or "").strip()
    return str(Path(raw)) if raw else None


def pick_folder_native() -> str | None:
    """
    Open a native folder chooser on the machine where the backend process runs.
    Returns an absolute path string, or None if the user cancelled / closed the dialog.
    """
    plat = sys.platform
    if plat == "darwin":
        return _pick_macos()
    if plat.startswith("linux"):
        z = _pick_zenity()
        if z is not None:
            return z
        return _pick_tkinter_subprocess()
    if plat == "win32":
        return _pick_tkinter_subprocess()
    # fallback
    return _pick_tkinter_subprocess()
