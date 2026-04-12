#!/usr/bin/env bash
# 释放本机指定 TCP 端口（默认 AI-KA 后端 8765）。macOS / Linux 可用（依赖 lsof）。
set -euo pipefail
PORT="${1:-8765}"
PIDS=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
if [[ -z "$PIDS" ]]; then
  echo "端口 ${PORT} 当前无监听进程。"
  exit 0
fi
echo "占用端口 ${PORT} 的进程: $PIDS"
# shellcheck disable=SC2086
kill $PIDS 2>/dev/null || true
sleep 0.3
STILL=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
if [[ -n "$STILL" ]]; then
  echo "普通 kill 未结束，执行 kill -9 …"
  # shellcheck disable=SC2086
  kill -9 $STILL 2>/dev/null || true
fi
if lsof -iTCP:"$PORT" -sTCP:LISTEN -n -P 2>/dev/null | grep -q .; then
  echo "警告: 端口 ${PORT} 仍被占用，请手动检查: lsof -iTCP:${PORT} -sTCP:LISTEN"
  exit 1
fi
echo "端口 ${PORT} 已释放。"
