#!/usr/bin/env python3
"""Gợi ý NHIỀU công thức tiêu đề cho bài đang đọc (tools/out/current.json).

Chỉ dùng dữ kiện DÒ ĐƯỢC từ content (model, kích thước, lưu lượng, vật liệu,
ren) nên không bịa thông số. In ra ~15 phương án kèm số ký tự + slug để chọn.

Dùng:  python tools/suggest_titles.py [--json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from regen_titles import make_slug  # noqa: E402

CUR = TOOLS_DIR / "out" / "current.json"
KW = "Bơm màng khí nén"
BRAND = "SAMOA"
LINK_TAIL = "ngochuyduong.com"


def _facts(d: dict) -> dict:
    text = (d.get("content_text") or "")
    title_old = d.get("title_old") or ""

    # model: ưu tiên mã đứng sau từ khoá, nhiều lần xuất hiện, không phải mã chỉ có 1 lần
    codes = [c for c in d.get("codes") or [] if c.get("hits", 0) >= 2]
    codes.sort(key=lambda c: (not c.get("from_keyword"), -c["hits"]))
    model = codes[0]["code"] if codes else ""
    if not model:
        m = re.search(r"\b([A-Z]{2,}\d{2,}[A-Z0-9\-/.]*)\b", title_old or text)
        model = m.group(1) if m else ""

    # dòng sản phẩm (UP05, UP05A, UP05B, DP200...)
    series = ""
    m = re.search(r"\b(UP\d{2}[A-Z]?)\b", f"{title_old} {text}")
    if m:
        series = m.group(1)

    # kích thước: chọn cỡ XUẤT HIỆN NHIỀU NHẤT (tránh lấy nhầm cỡ của model so sánh)
    sizes = re.findall(r"(\d+/\d+|\d+)\s*(?:inch|\"|”)", f"{title_old} {text}", re.I)
    size = ""
    if sizes:
        from collections import Counter
        size = Counter(sizes).most_common(1)[0][0] + " inch"

    flow = ""
    m = re.search(r"(\d+[.,]?\d*)\s*(?:lít|l|L)\s*/\s*phút", text, re.I)
    if m:
        flow = m.group(1).replace(",", ",") + " lít/phút"

    mats = []
    for name, pat in (
        ("inox 316", r"(inox|AISI)\s*316"),
        ("PVDF", r"\bPVDF\b"),
        ("nhôm", r"\bnhôm\b"),
        ("PP", r"\bPP\b"),
        ("PTFE", r"\bPTFE\b"),
        ("Santoprene", r"Santoprene"),
        ("NBR", r"\bNBR\b"),
    ):
        if re.search(pat, text, re.I):
            mats.append(name)

    conn = ""
    has_bsp = re.search(r"\bBSP\b", text, re.I)
    has_npt = re.search(r"\bNPT\b", text, re.I)
    if has_bsp and has_npt:
        conn = "BSP/NPT"
    elif has_bsp:
        conn = "BSP"
    elif has_npt:
        conn = "NPT"

    return {
        "model": model,
        "series": series,
        "size": size,
        "flow": flow,
        "mats": mats,
        "conn": conn,
    }


USP_POOL = (
    "chính hãng",
    "giá kho",
    "tổng kho",
    "hàng sẵn",
    "báo giá nhanh",
    "đại lý Việt Nam",
    "nhập khẩu Tây Ban Nha",
    "giao toàn quốc",
    "bảo hành chính hãng",
    "CO/CQ đầy đủ",
    "hỗ trợ kỹ thuật",
    "mua ở đâu",
    "nơi bán",
    "tại sao chọn",
    "hàng mới 100%",
    "kỹ sư tư vấn",
    "giao nhanh",
)
# 1 USP dùng 1 lần/bài để không lặp
USP_SECOND = ("giá tốt", "chính hãng", "hàng sẵn", "giao nhanh", "báo giá nhanh")


def _candidates(f: dict) -> list[str]:
    kw = KW
    brand = BRAND
    model = f["model"] or f["series"] or ""
    size = f["size"]
    flow = f["flow"]
    conn = f["conn"]
    mats = f["mats"]
    inox = "inox 316" if "inox 316" in mats else ""

    base_kw = f"{kw} {brand} {model}".strip()
    base_short = f"{kw} {brand} {model}".replace(kw, "bơm màng").strip()

    out: list[str] = []

    def add(t: str) -> None:
        out.append(re.sub(r"\s{2,}", " ", t).strip())

    # A. keyword-first, mỗi phương án 1 USP khác nhau
    for usp in USP_POOL:
        add(f"{base_kw} {usp}")
    # B. model-first + USP
    for usp in USP_POOL[:6]:
        add(f"{brand} {model} – {kw.lower()} {usp}")
    # C. quy cách-first + USP
    if size:
        for usp in USP_POOL[:4]:
            add(f"{kw} {size} {brand} {model}, {usp}")
    # D. lưu lượng-first + USP
    if flow:
        for usp in USP_POOL[:3]:
            add(f"{kw} {flow} {brand} {model}, {usp}")
    # E. vật liệu-first + USP
    if inox:
        for usp in ("giá kho", "hàng sẵn", "bảo hành chính hãng"):
            add(f"{kw} {brand} {model} inox 316, {usp}")
    # F. ren + USP
    if conn:
        for usp in ("chính hãng", "tổng kho", "có sẵn"):
            add(f"{kw} {brand} {model} {conn}, {usp}")
    # G. lợi ích-first
    for usp in ("Chính hãng", "Hàng sẵn", "Giá kho", "Tổng kho", "Bảo hành chính hãng"):
        add(f"{usp} – {kw.lower()} {brand} {model}")
    # H. câu hỏi
    for usp in ("mua ở đâu", "nơi bán", "tại sao chọn"):
        add(f"{kw} {brand} {model} {usp}? Giá tốt, hàng sẵn")
    # I. 2 USP
    add(f"{base_kw} chính hãng, giá kho")
    add(f"{base_kw} hàng sẵn, giao toàn quốc")
    add(f"{base_kw} nhập khẩu Tây Ban Nha, bảo hành chính hãng")
    add(f"{base_kw} tổng kho, báo giá nhanh")

    seen, res = set(), []
    for t in out:
        if t in seen or not (50 <= len(t) <= 75):
            continue
        seen.add(t)
        res.append(t)
    return res


def main() -> int:
    path = CUR
    argv = sys.argv[1:]
    if "--id" in argv:
        try:
            path = TOOLS_DIR / "out" / f"current_{int(argv[argv.index('--id') + 1])}.json"
        except Exception:
            pass
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print("Chưa có tools/out/current.json — chạy `next` trước.")
        return 1
    f = _facts(d)
    if "--json" in sys.argv:
        print(json.dumps(f, ensure_ascii=False))
        return 0
    print(f"Bài #{d.get('id')} | cũ: {d.get('title_old')} ({len(d.get('title_old') or '')} ký tự)")
    print(
        f"Dữ kiện: model={f['model'] or '—'} · dòng={f['series'] or '—'} · "
        f"kích thước={f['size'] or '—'} · lưu lượng={f['flow'] or '—'} · "
        f"vật liệu={', '.join(f['mats']) or '—'} · ren={f['conn'] or '—'}"
    )
    print("")
    for i, t in enumerate(_candidates(f), 1):
        print(f"{i:2}. {len(t):3} | {t}")
        print(f"      /{make_slug(t)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
