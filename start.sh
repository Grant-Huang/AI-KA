#!/usr/bin/env bash
# AI-KA 后端一键启动：先释放监听端口，再激活 venv 并运行 aika-web。
# 用法：./start.sh
# 端口默认 8765；若使用其它端口，请先 export AIKA_WEB_PORT=xxxx（与后端一致）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PORT="${AIKA_WEB_PORT:-8765}"
echo "[start] 项目目录: $ROOT"
echo "[start] 释放端口: $PORT（与 AIKA_WEB_PORT 一致）"
"$ROOT/scripts/kill_port.sh" "$PORT"

if [[ ! -f .venv/bin/activate ]]; then
  echo "[start] 错误: 未找到 .venv/bin/activate，请先创建虚拟环境并安装依赖。" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[start] 启动 aika-web …"
exec aika-web "$@"
