#!/usr/bin/env bash
# Build .app cho macOS (chỉ đóng gói các module Qt thực sự dùng).
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
  --collect-all playwright \
  --hidden-import app
  --hidden-import pypdf \
  --exclude-module PySide6.Qt3DCore \
  --exclude-module PySide6.Qt3DRender \
  --exclude-module PySide6.Qt3DAnimation \
  --exclude-module PySide6.Qt3DExtras \
  --exclude-module PySide6.Qt3DInput \
  --exclude-module PySide6.Qt3DLogic \
  --exclude-module PySide6.QtWebEngineCore \
  --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.QtWebEngineQuick \
  --exclude-module PySide6.QtCharts \
  --exclude-module PySide6.QtDataVisualization \
  --exclude-module PySide6.QtGraphs \
  --exclude-module PySide6.QtGraphsWidgets \
  --exclude-module PySide6.QtMultimedia \
  --exclude-module PySide6.QtMultimediaWidgets \
  --exclude-module PySide6.QtQuick \
  --exclude-module PySide6.QtQuick3D \
  --exclude-module PySide6.QtQuickControls2 \
  --exclude-module PySide6.QtQuickWidgets \
  --exclude-module PySide6.QtQml \
  --exclude-module PySide6.QtDesigner \
  --exclude-module PySide6.QtSql \
  --exclude-module PySide6.QtTest \
  --exclude-module PySide6.QtBluetooth \
  --exclude-module PySide6.QtNfc \
  --exclude-module PySide6.QtLocation \
  --exclude-module PySide6.QtPositioning \
  --exclude-module PySide6.QtSensors \
  --exclude-module PySide6.QtSerialPort \
  --exclude-module PySide6.QtSerialBus \
  --exclude-module PySide6.QtWebSockets \
  --exclude-module PySide6.QtWebChannel \
  --exclude-module PySide6.QtHelp \
  --exclude-module PySide6.QtPdf \
  --exclude-module PySide6.QtPdfWidgets \
  --exclude-module PySide6.QtTextToSpeech \
  --exclude-module PySide6.QtStateMachine \
  --exclude-module PySide6.QtRemoteObjects \
  --exclude-module PySide6.QtScxml \
  --exclude-module PySide6.QtSpatialAudio \
  --exclude-module PySide6.QtUiTools \
  --exclude-module PySide6.QtHttpServer \
  --exclude-module PySide6.QtNetworkAuth \
  main.py

echo
echo "✔ Xong: dist/$APP_NAME.app"
echo "  Chạy: open dist/$APP_NAME.app"
