#!/usr/bin/env bash
# Build .app cho macOS.
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="HoTroDangBai"

if [ ! -d ".venv" ]; then
  echo "Chưa có .venv — chạy: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

.venv/bin/pip install pyinstaller >/dev/null

.venv/bin/pyinstaller --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --collect-all PySide6 \
  --collect-all playwright \
  --collect-all cryptography \
  --collect-all bs4 \
  --collect-all lxml \
  --hidden-import app \
  main.py

echo
echo "✔ Xong: dist/$APP_NAME.app"
echo "  Chạy: open dist/$APP_NAME.app"
