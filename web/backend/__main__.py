from __future__ import annotations

import os
import sys

from backend.sysdeps import check_runtime_system_deps


def main() -> None:
    import uvicorn

    missing = check_runtime_system_deps()
    if missing:
        print("AI-KA Web 启动前检测到缺失的系统依赖（不会自动安装）：", file=sys.stderr)
        for d in missing:
            cmds = ", ".join(d.commands)
            print(f"- {d.name}（命令: {cmds}）: {d.purpose}", file=sys.stderr)
            print(f"  安装提示: {d.install_hint}", file=sys.stderr)
        print("", file=sys.stderr)

    host = os.environ.get("AIKA_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("AIKA_WEB_PORT", "8765"))
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
