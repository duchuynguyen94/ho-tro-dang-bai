#!/usr/bin/env bash
# Build lại .app macOS rồi tắt app cũ và mở lại để xem thay đổi ngay.
set -euo pipefail
cd "$(dirname "$0")"

echo "→ Tắt app đang chạy…"
pkill -f "HoTroDangBai.app/Contents/MacOS" 2>/dev/null || true
sleep 1

echo "→ Build lại .app…"
rm -rf build dist
./build_mac.sh >/dev/null

echo "→ Mở app…"
open dist/HoTroDangBai.app
echo "✔ Đã mở bản mới."
