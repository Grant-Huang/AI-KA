#!/usr/bin/env python3
"""
将仓库根目录的 default_skills.md（或第一个参数指定的 .md）迁移到
review_skill_packages/package-general/review_domain.md。
需在 AIKA_REPO_ROOT 下执行，或传入环境变量 AIKA_REPO_ROOT。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    root = Path(os.environ.get("AIKA_REPO_ROOT") or os.getcwd()).resolve()
    name = sys.argv[1] if len(sys.argv) > 1 else "default_skills.md"
    src = root / name
    if not src.is_file():
        print(f"not found: {src}", file=sys.stderr)
        return 1
    dest_dir = root / "review_skill_packages" / "package-general"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "review_domain.md"
    shutil.copyfile(src, dest)
    print(f"copied {src} -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
