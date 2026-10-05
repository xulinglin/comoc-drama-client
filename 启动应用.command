#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin"

if [[ ! -x .venv/bin/python ]]; then
  echo "请先按照 docs/DEVELOPMENT.md 的 macOS 步骤安装 Python 环境。"
  exit 1
fi

if [[ ! -f frontend/dist/index.html ]]; then
  (
    cd frontend
    npm ci
    npm run build
  )
fi

exec .venv/bin/python launcher.py
