#!/usr/bin/env bash
# Build lại .app macOS rồi tắt app cũ và mở lại để xem thay đổi ngay.
set -euo pipefail
cd "$(dirname "$0")"

echo "→ Tắt app đang chạy…"
pkill -f "HoTroDangBai.app/Contents/MacOS" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
  pgrep -f "HoTroDangBai.app/Contents/MacOS" >/dev/null 2>&1 || break
  sleep 0.5
done

echo "→ Dọn thư mục build…"
for _ in 1 2 3 4 5; do
  rm -rf build dist 2>/dev/null || true
  [ ! -d dist ] && [ ! -d build ] && break
  sleep 0.5
done
rm -rf build dist 2>/dev/null || true

echo "→ Build lại .app…"
./build_mac.sh >/dev/null

echo "→ Mở app…"
open dist/HoTroDangBai.app
echo "✔ Đã mở bản mới."
