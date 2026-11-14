#!/usr/bin/env bash
# Manufacturing Control Tower 演示系统一键启动（macOS / Linux）
set -euo pipefail
cd "$(dirname "$0")"
PORT="${CT_PORT:-8050}"
if ! command -v python3 >/dev/null; then
  echo "需要 python3（3.10+）"; exit 1
fi
# 可选：本地 venv（系统已有依赖时可跳过）
if [[ "${CT_USE_VENV:-0}" == "1" ]]; then
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
if [[ ! -f data/control_tower.db ]]; then
  echo "正在生成示例数据库（约数秒）…"
  python3 -m etl.pipeline
fi
echo "打开浏览器访问 http://127.0.0.1:${PORT}  （全部为示例数据，Ctrl+C 退出）"
exec python3 app.py --host 127.0.0.1 --port "$PORT"
