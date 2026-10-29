#!/usr/bin/env python3
"""Đặt tiêu đề đã chọn cho bài đang đọc rồi để `apply` ghi lên WordPress.

Dùng:  python tools/apply_title.py "Tiêu đề đã chọn" [--id 1234]

- Không truyền --id: lấy id trong tools/out/current.json (bài vừa `next`).
- Slug tự sinh bằng make_slug (bỏ đuôi USP, tối đa 75 ký tự).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from regen_titles import CURRENT_FILE, STATE_FILE, load_state, make_slug, save_state  # noqa: E402


def main(argv: list[str]) -> int:
    pid_arg = None
    args: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--id" and i + 1 < len(argv):
            pid_arg = int(argv[i + 1])
            i += 2
            continue
        args.append(a)
        i += 1
    if not args:
        print('Thiếu tiêu đề. Ví dụ: python tools/apply_title.py "Bơm màng ..."')
        return 1
    title = args[0].strip()
    if not title:
        print("Tiêu đề rỗng.")
        return 1

    pid = pid_arg
    if pid is None:
        try:
            cur = json.loads(CURRENT_FILE.read_text(encoding="utf-8"))
            pid = int(cur["id"])
        except Exception:
            print("Không biết bài nào — thiếu tools/out/current.json (chạy `next` trước) hoặc --id")
            return 1

    st = load_state()
    item = st["items"].setdefault(str(pid), {})
    slug = make_slug(title)
    item.update({"status": "approved", "title_new": title, "slug_new": slug})
    item.pop("error", None)
    save_state(st)
    print(f"#{pid} ({len(title)} ký tự) → {title}")
    print(f"        slug: /{slug}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
