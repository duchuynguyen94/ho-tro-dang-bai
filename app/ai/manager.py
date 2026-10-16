"""Điều phối AI viết nội dung: 2 bước Content (rule_content) → SEO (rule_seo)."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urlparse
from pathlib import Path

from ..storage import crypto
from . import providers

API_PROVIDERS = ("gemini", "groq", "openai", "deepseek")

REQUIRED_KEYS = ("title", "focus_keyword", "description", "tags")

# Kết quả bước 1 (theo Rule Content)
CONTENT_OUTPUT_SPEC = (
    "• Tiêu đề bài viết\n"
    "• Nội dung bài viết\n"
    "• Danh sách Product Models\n"
    "• Bảng thông số kỹ thuật\n"
    "• Thông tin liên hệ"
)

# Kết quả bước 2 (theo Rule SEO)
SEO_JSON_SPEC = """{
  "title": "tiêu đề SEO 55-60 ký tự, dạng: [Keyword] [Brand] [Model] + [USP] (chọn ngẫu nhiên 1 USP)",
  "focus_keyword": "từ khoá chính (thường là Model của sản phẩm)",
  "description": "mô tả siêu ngắn theo mẫu rule_seo, GỒM CẢ: dòng liên hệ (website | hotline | email) và danh sách tối đa 5 MODEL TIÊU BIỂU của hãng, mỗi model 1 dòng",
  "tags": "danh sách thẻ tìm kiếm đầy đủ, mở rộng nhất có thể, thuần Việt, cách nhau dấu phẩy"
}"""


# --------------------------------------------------------------------------- #
# Đọc file rule
# --------------------------------------------------------------------------- #
def read_rule(path: str, limit: int = 12000) -> str:
    """Đọc file rule: .txt/.html/.md/.doc/.docx đọc thẳng, .pdf trích text."""
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(p))
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
            return text[:limit]
        except Exception:
            return ""
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# Prompt bước 1 — CONTENT
# --------------------------------------------------------------------------- #
def build_combined_prompt(rules, source: dict) -> str:
    """1 prompt cho provider API: yêu cầu JSON SEO trước, nội dung sau."""
    rule_content = read_rule(getattr(rules, "content", ""))
    rule_seo = read_rule(getattr(rules, "seo", ""))
    images_hint = "\n".join(f"- {u}" for u in source.get("images", [])[:6])
    return f"""Bạn là chuyên gia viết nội dung kỹ thuật & SEO tiếng Việt.
Hãy làm theo ĐÚNG 2 file quy định dưới đây.

=== RULE CONTENT (quy tắc viết bài) ===
{rule_content or "(Không có quy định riêng.)"}

=== RULE SEO (thông tin SEO đầu ra) ===
{rule_seo or "(Không có quy định riêng.)"}

=== BÀI VIẾT NGUỒN ===
Tiêu đề gốc: {source.get('title', '')}
URL: {source.get('url', '')}
Nội dung:
{source.get('text', '')[:6000]}

Ảnh trong bài nguồn (tham khảo):
{images_hint}

=== THỨ TỰ TRẢ VỀ (BẮT BUỘC) ===
1) ĐẦU TIÊN: TOÀN BỘ NỘI DUNG BÀI VIẾT dưới dạng **HTML thật**, đủ các mục:
{CONTENT_OUTPUT_SPEC}

Yêu cầu HTML: dùng <h2>, <h3> cho tiêu đề mục; <p> cho đoạn văn; <ul><li> cho danh sách;
và <table><tr><td> cho bảng thông số kỹ thuật. KHÔNG dùng Markdown, KHÔNG bọc trong ```.
GIỮ ĐÚNG ĐỊNH DẠNG CỦA RULE CONTENT, kể cả các ký hiệu/icon đầu dòng (●, ▪, ►, ✅…).

2) SAU CÙNG: DUY NHẤT 1 khối JSON thông tin SEO, TẠO THEO **RULE SEO Ở TRÊN**
và TRÍCH XUẤT TỪ CHÍNH NỘI DUNG VỪA VIẾT (điền nội dung THẬT, không trả lại mẫu):
{SEO_JSON_SPEC}

Không giải thích gì thêm, không thêm tiêu đề phụ nào khác.
"""


def build_combined_short_prompt(source: dict) -> str:
    """1 prompt ngắn cho ChatGPT (2 file rule nằm trong Project đã đính kèm)."""
    return f"""Đọc bài viết tại link dưới đây, viết lại thành 1 bài viết mới theo file **rule_content.pdf**
đã đính kèm (sources) trong Project này, sau đó tạo thông tin SEO theo file **rule_seo.pdf**
cũng trong Project này.

Link bài viết nguồn: {source.get('url', '')}

=== THỨ TỰ TRẢ VỀ (BẮT BUỘC) ===
1) ĐẦU TIÊN: TOÀN BỘ NỘI DUNG BÀI VIẾT dưới dạng **HTML thật** theo rule_content.pdf, đủ các mục:
{CONTENT_OUTPUT_SPEC}


2) SAU CÙNG: DUY NHẤT 1 khối JSON thông tin SEO, TRÍCH XUẤT TỪ CHÍNH NỘI DUNG TRÊN:
{SEO_JSON_SPEC}

Không giải thích gì thêm.
"""


# --------------------------------------------------------------------------- #
# Gọi provider (có fallback)
# --------------------------------------------------------------------------- #
def _active_chain(cfg: dict) -> list[str]:
    providers_order = [p for p in (cfg.get("providers") or {})]
    order = [p for p in (cfg.get("order") or []) if p in providers_order]
    order += [p for p in providers_order if p not in order]
    active = cfg.get("active") or (order[0] if order else "")
    if active in order:
        order.remove(active)
    chain = ([active] if active else []) + order
    if not cfg.get("fallback", True):
        chain = [active]
    return chain


def _fmt_errors(errors: list[str]) -> str:
    """Ưu tiên lỗi của provider ĐANG CHỌN (phần tử đầu), phần còn lại chỉ đếm."""
    if not errors:
        return "Không rõ nguyên nhân."
    first = errors[0]
    rest = len(errors) - 1
    return first if rest <= 0 else f"{first} (và {rest} provider khác không dùng được)"


def _is_placeholder(value) -> bool:
    t = str(value or "").strip()
    return (not t) or all(ch in ".-_…~ " for ch in t)


def _call_ai(store, prompt: str, short_prompt: str, log=None) -> str:
    """Gọi provider đang chọn (ChatGPT dùng prompt ngắn + Project)."""
    cfg = store.ai_content
    errors: list[str] = []
    for provider in _active_chain(cfg):
        pcfg = (cfg.get("providers") or {}).get(provider, {})
        api_key = crypto.decrypt(pcfg.get("api_key_enc", ""))
        if provider in API_PROVIDERS and not api_key:
            errors.append(f"{provider}: thiếu API key")
            continue
        if log:
            log(f"Đang gọi AI: {provider}…")
        try:
            if provider == "chatgpt":
                from .chatgpt_browser import generate_with_chatgpt

                return generate_with_chatgpt(pcfg, short_prompt, log)
            return providers.generate_text(provider, pcfg, prompt, api_key)
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            if log:
                log(f"{provider} lỗi → thử provider khác…")
    limit = next((e for e in errors if "GIỚI HẠN" in e.upper()), "")
    if limit:
        raise providers.AIError(limit.split(":", 1)[-1].strip())
    raise providers.AIError(_fmt_errors(errors))


# --------------------------------------------------------------------------- #
# Chuyển text (markdown đơn giản) -> HTML
# --------------------------------------------------------------------------- #
def text_to_html(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    out: list[str] = []
    in_ul = False
    in_table = False

    def close_lists() -> None:
        nonlocal in_ul, in_table
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_table:
            out.append("</table>")
            in_table = False

    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if not s:
            close_lists()
            continue
        # bảng markdown
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # dòng phân cách
            if not in_table:
                close_lists()
                out.append(
                    '<table border="1" cellspacing="0" cellpadding="6" '
                    'style="border-collapse:collapse;width:100%">'
                )
                in_table = True
                first_row = True
            else:
                first_row = False
            cells_html = "".join(
                f'<td style="border:1px solid #999;padding:6px">'
                f'{"<b>" + html.escape(c) + "</b>" if first_row else html.escape(c)}</td>'
                for c in cells
            )
            out.append(f"<tr>{cells_html}</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        # tiêu đề
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            close_lists()
            lvl = min(6, max(2, len(m.group(1))))
            out.append(f"<h{lvl}>{html.escape(m.group(2).strip())}</h{lvl}>")
            continue
        # gạch đầu dòng
        if re.match(r"^[•\-*+]\s+", s):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append("<li>" + html.escape(re.sub(r"^[•\-*+]\s+", "", s)) + "</li>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        # đậm/nghiêng đơn giản
        safe = html.escape(s)
        safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
        out.append(f"<p>{safe}</p>")

    close_lists()
    return "\n".join(out)


def _norm_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if u and not u.startswith("http"):
        u = "https://" + u
    return u


def _domain_of(url_or_name: str) -> str:
    d = re.sub(r"^https?://", "", (url_or_name or "").strip().rstrip("/")).lower()
    return d


def _dom_variants(url_or_name: str) -> list[str]:
    d = _domain_of(url_or_name)
    if not d:
        return []
    bare = d[4:] if d.startswith("www.") else d
    out = [d]
    if bare and bare != d:
        out.append(bare)
    w = f"www.{bare}"
    if w not in out:
        out.append(w)
    # ưu tiên chuỗi dài trước để khớp 'www.x' trước 'x'
    return sorted(set(out), key=len, reverse=True)


def linkify_site(html_text: str, site_url: str, site_name: str = "") -> str:
    """Chèn link cho MỌI lần xuất hiện tên miền của website -> URL của chính website đó."""
    if not html_text:
        return html_text
    base = _norm_url(site_url)
    variants: list[str] = []
    for src in (site_name, site_url):
        for v in _dom_variants(src):
            if v.startswith("www.") and v not in variants:
                variants.append(v)
    variants = [v for v in variants if len(v) >= 5]
    if not base or not variants:
        return html_text

    parts = re.split(r"(<[^>]+>)", html_text)
    out: list[str] = []
    in_a = False
    for part in parts:
        if part.startswith("<"):
            low = part.lower()
            if low.startswith("<a "):
                in_a = True
            elif low.startswith("</a"):
                in_a = False
            out.append(part)
            continue
        if in_a or not part.strip():
            out.append(part)
            continue
        text = part
        for var in variants:
            pattern = re.compile(rf"(?<![\w./-])({re.escape(var)})(?![\w/-])", re.I)
            text = pattern.sub(lambda m: f'<a href="{base}">{m.group(1)}</a>', text)
        out.append(text)
    return "".join(out)


HEADING_RE = re.compile(r"^<h([2-6])\b", re.I)


DOMAIN_RE = re.compile(
    r"(?<![\w.@/])www\.([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9][a-z0-9\-]*)*\.[a-z]{2,})",
    re.I,
)


def linkify_domains(html_text: str, sites: list[tuple[str, str]]) -> str:
    """Bọc mọi 'www.<tên-miền>' trong bài thành thẻ <a> trỏ về ĐÚNG tên miền đó (bỏ www).

    - sites: danh sách (url, tên) các website đã cấu hình -> nếu tên miền khớp thì dùng
      đúng URL đã cấu hình; nếu không khớp thì dùng https://<tên-miền>.
    - Không đụng vào chữ đã nằm trong thẻ <a>.
    """
    if not html_text:
        return html_text
    # map: tên miền (bỏ www, chữ thường) -> URL cấu hình
    by_domain: dict[str, str] = {}
    for url, _name in sites or []:
        u = (url or "").strip().rstrip("/")
        if not u:
            continue
        host = urlparse(u if "://" in u else "https://" + u).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        if host:
            by_domain[host] = u if "://" in u else "https://" + u

    parts = re.split(r"(<[^>]+>)", html_text)
    out: list[str] = []
    in_a = False
    for part in parts:
        if part.startswith("<"):
            low = part.lower()
            if low.startswith("<a "):
                in_a = True
            elif low.startswith("</a"):
                in_a = False
            out.append(part)
            continue
        if in_a or not part.strip():
            out.append(part)
            continue

        def repl(m):
            host = m.group(1).lower()
            href = by_domain.get(host) or f"https://{host}"
            return f'<a href="{href}">{m.group(0)}</a>'

        out.append(DOMAIN_RE.sub(repl, part))
    return "".join(out)


def insert_external_links(html_text: str, links: list[tuple[str, str]],
                          candidates: list[str] | None) -> str:
    """Chèn link ngoài vào TỪ KHOÁ/MÃ SẢN PHẨM nằm trong thẻ <h2>..<h5>.

    - links: danh sách (url, tên site) — mỗi site chèn 1 lần.
    - Nếu không tìm thấy trong heading thì chèn vào đoạn văn bất kỳ sau heading đầu tiên.
    """
    if not html_text or not links:
        return html_text
    cands = [c.strip() for c in (candidates or []) if c and len(c.strip()) >= 3]
    if not cands:
        return html_text

    parts = re.split(r"(<[^>]+>)", html_text)
    out: list[str] = []
    pending = list(links)
    depth_heading = 0
    used_urls: set[str] = set()

    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith("<"):
            if HEADING_RE.match(part):
                depth_heading += 1
            elif re.match(r"^</h[2-6]", part, re.I):
                depth_heading = max(0, depth_heading - 1)
            out.append(part)
            i += 1
            continue

        text = part
        if depth_heading and pending:
            url, name = None, None
            for idx, (u, n) in enumerate(pending):
                if u in used_urls:
                    continue
                for cand in cands:
                    m = re.search(re.escape(cand), text, re.I)
                    if m:
                        url, name = u, n
                        text = (text[:m.start()]
                                + f'<a href="{_norm_url(u)}">{m.group(0)}</a>'
                                + text[m.end():])
                        break
                if url:
                    break
            if url:
                used_urls.add(url)
                pending = [x for x in pending if x[0] not in used_urls]
        out.append(text)
        i += 1

    return "".join(out)


DEFAULT_SECTIONS = (
    "giới thiệu tổng quan",
    "tính năng kỹ thuật nổi bật",
    "thông số kỹ thuật tiêu chuẩn",
)


def insert_title_links(html_text: str, site_url: str, links: list[str],
                       candidates: list[str] | None,
                       sections: tuple[str, ...] | None = None) -> str:
    """Chèn link vào TIÊU ĐỀ MỤC của bài viết.

    - TIÊU ĐỀ ĐẦU TIÊN (<h1> hoặc <h2>, cái nào xuất hiện trước) -> chèn link của
      CHÍNH website (site_url, thường là https://ngochuyduong.com).
    - Các tiêu đề TIẾP THEO có chứa tên mục chuẩn ("Giới thiệu tổng quan",
      "Tính năng kỹ thuật nổi bật", "Thông số kỹ thuật tiêu chuẩn") -> chèn lần lượt
      các link trong danh sách cấu hình (mỗi link 1 lần, đúng số lượng link).
    - Link được chèn vào phần TỪ KHOÁ trong tiêu đề (sau tên mục);
      nếu tiêu đề không có từ khoá thì bọc cả tiêu đề.
    """
    if not html_text:
        return html_text
    cands = [c.strip() for c in (candidates or []) if c and len(c.strip()) >= 3]
    secs = [x.strip().lower() for x in (sections or DEFAULT_SECTIONS) if str(x).strip()]

    head_re = re.compile(r"^<h([1-6])\b", re.I)      # tính cả h1 (tiêu đề bài viết)
    close_re = re.compile(r"^</h[1-6]", re.I)

    parts = re.split(r"(<[^>]+>)", html_text)
    out: list[str] = []
    pending = [l for l in (links or []) if str(l).strip()]
    used: set[str] = set()
    heading_seen = 0        # đếm h1 + h2 (tiêu đề đầu tiên = h1 hoặc h2)
    depth = 0
    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith("<"):
            m = head_re.match(part)
            if m:
                depth += 1
                if m.group(1) in ("1", "2"):
                    heading_seen += 1
            elif close_re.match(part):
                depth = max(0, depth - 1)
            out.append(part)
            i += 1
            continue

        text = part
        if depth and text.strip():
            low = text.lower()
            href = ""
            if heading_seen == 1:
                href = _norm_url(site_url) if site_url else ""
            elif any(sec in low for sec in secs):
                href = next((l for l in pending if l not in used), "")
            if href:
                # tìm TÊN MỤC CHUẨN trong tiêu đề -> bọc TOÀN BỘ chữ còn lại sau nó
                hit = None
                for sec in secs:
                    mm = re.search(re.escape(sec), low)
                    if mm:
                        hit = mm
                        break
                if hit is not None and text[hit.end():].strip():
                    tail_raw = text[hit.end():]
                    tail = tail_raw.strip()
                    sep = " " if tail_raw[:1].isspace() else ""
                    text = f'{text[:hit.end()]}{sep}<a href="{_norm_url(href)}">{tail}</a>'
                else:
                    # không có chữ sau tên mục (hoặc không phải tiêu đề mục chuẩn)
                    # -> bọc cả tiêu đề
                    text = f'<a href="{_norm_url(href)}">{text.strip()}</a>'
                used.add(href)
        out.append(text)
        i += 1
    return "".join(out)


def clean_content_html(html_text: str) -> str:
    """Bỏ rác ở đầu/cuối: rào ```html, thẻ html/head/body, chữ "html", "Writing"…"""
    t = (html_text or "").strip()

    # 1) rào ```html ... ```
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)

    # 2) thẻ bao ngoài do AI trả về cả trang
    t = re.sub(r"^\s*<!DOCTYPE[^>]*>", "", t, flags=re.I)
    t = re.sub(r"<head[^>]*>.*?</head>", "", t, flags=re.I | re.S)
    t = re.sub(r"^\s*<html[^>]*>", "", t, flags=re.I)
    t = re.sub(r"</html>\s*$", "", t, flags=re.I)
    t = re.sub(r"^\s*<body[^>]*>", "", t, flags=re.I)
    t = re.sub(r"</body>\s*$", "", t, flags=re.I)

    # 3) chữ rác ở đầu (kể cả chữ "html"/"HTML" thừa)
    for _ in range(4):
        t = re.sub(
            r"^\s*(Writing|Đang viết|Đang soạn|ChatGPT said|ChatGPT|html|HTML)\s*[:.\-–]?\s*",
            "", t, flags=re.I,
        )
    t = t.strip()
    t = re.sub(r"^\s*<p>\s*(Writing|Đang viết)\s*</p>\s*", "", t, flags=re.I)
    # ký hiệu đầu dòng trùng trong <li> (rule dùng ● nhưng <ul> đã tự có bullet)
    t = re.sub(r"(<li[^>]*>)\s*[●•▪◦‣·►▶]\s*", r"\1", t, flags=re.I)
    t = re.sub(r"(<li[^>]*>)\s*[-*+]\s+", r"\1", t)
    return t.strip()


def _looks_like_html(text: str) -> bool:
    """True nếu nội dung đã là HTML (có thẻ khối)."""
    return bool(re.search(r"<\s*(h[1-6]|p|ul|ol|table|div|figure)\b", text or "", re.I))


def extract_product_name(raw_content: str, fallback: str = "") -> str:
    """Lấy tên sản phẩm trong nội dung (ưu tiên dòng sau 'Tiêu đề bài viết')."""
    raw = raw_content or ""
    plain = re.sub(r"<[^>]+>", "\n", raw)
    m = re.search(r"Tiêu đề bài viết[^\n]*\n+\s*([^\n]{3,200})", plain, re.I)
    if m:
        name = m.group(1).strip(" •-*#\t")
        if name:
            return name
    # dự phòng: thẻ <h1> hoặc <h2> đầu tiên
    for tag in ("h1", "h2"):
        mm = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", raw, re.S | re.I)
        if mm:
            name = re.sub(r"<[^>]+>", "", mm.group(1)).strip(" •-*#\t")
            if 3 <= len(name) <= 200 and "tiêu đề bài viết" not in name.lower():
                return name
    return (fallback or "").strip()


def autolink_html(html_text: str, site_url: str = "", site_name: str = "",
                  product_name: str = "", keywords: list[str] | None = None) -> str:
    """Chèn 1 link external vào từ khoá đầu tiên tìm thấy, + link cho tên miền dạng www."""
    if not html_text:
        return html_text
    base = (site_url or "").strip().rstrip("/")
    if base and not base.startswith("http"):
        base = "https://" + base
    if not base:
        return html_text

    candidates: list[str] = []
    for cand in [product_name, *list(keywords or [])]:
        c = (cand or "").strip()
        if len(c) >= 3 and c not in candidates:
            candidates.append(c)

    tokens = _site_tokens(site_url, site_name)
    parts = re.split(r"(<[^>]+>)", html_text)
    out: list[str] = []
    in_a = False
    product_done = False

    for part in parts:
        if part.startswith("<"):
            low = part.lower()
            if low.startswith("<a "):
                in_a = True
            elif low.startswith("</a"):
                in_a = False
            out.append(part)
            continue
        if in_a or not part.strip():
            out.append(part)
            continue

        text = part
        # (1) chèn 1 lần link external vào từ khoá đầu tiên tìm thấy
        if candidates and not product_done:
            for cand in candidates:
                idx = text.find(cand)
                if idx >= 0:
                    text = (text[:idx] + f'<a href="{base}">{cand}</a>'
                            + text[idx + len(cand):])
                    product_done = True
                    break
        # (2) chèn link cho tên miền dạng www.
        for tok in tokens:
            pattern = re.compile(rf"(?<![\w./-])({re.escape(tok)})(?![\w/-])", re.I)
            text = pattern.sub(lambda m: f'<a href="{base}">{m.group(1)}</a>', text)
        out.append(text)
    return "".join(out)


# --------------------------------------------------------------------------- #
# Luồng chính: 1 lần gọi (JSON SEO trước, nội dung sau)
# --------------------------------------------------------------------------- #
def generate_content(store, source: dict, log=None, should_stop=None) -> dict:
    """1 lần gọi: AI trả JSON SEO TRƯỚC, rồi tới nội dung bài viết."""
    rules = store.formats
    cfg = store.ai_content
    full = build_combined_prompt(rules, source)
    short = build_combined_short_prompt(source)
    errors: list[str] = []

    for provider in _active_chain(cfg):
        pcfg = (cfg.get("providers") or {}).get(provider, {})
        api_key = crypto.decrypt(pcfg.get("api_key_enc", ""))
        if provider in API_PROVIDERS and not api_key:
            errors.append(f"{provider}: thiếu API key")
            continue
        try:
            if should_stop and should_stop():
                raise providers.AIError("Đã dừng theo yêu cầu.")
            if provider == "chatgpt":
                from .chatgpt_browser import generate_combined

                raw = generate_combined(pcfg, short, log, should_stop=should_stop)
            else:
                if log:
                    log("Đang gọi AI (SEO + nội dung)…")
                raw = providers.generate_text(provider, pcfg, full, api_key)

            from .chatgpt_browser import split_reply

            seo, content = split_reply(raw)
            if seo is None:
                raise providers.AIError("AI không trả về khối JSON SEO ở đầu.")
            missing = [k for k in REQUIRED_KEYS if not str(seo.get(k, "")).strip()]
            if missing:
                raise providers.AIError(f"thiếu trường {missing}")
            if not content or len(content) < 50:
                raise providers.AIError("AI không trả về nội dung bài viết.")

            inner = str(seo.get("content_html", "") or "").strip()
            if inner and not _is_placeholder(inner) and _looks_like_html(inner):
                content = inner        # AI để nội dung trong JSON -> dùng luôn
            seo["provider_used"] = provider
            seo["content_html"] = clean_content_html(
                content if _looks_like_html(content) else text_to_html(content)
            )
            seo["raw_content"] = content
            if log:
                log("Đã có kết quả (JSON SEO + nội dung).")
            return seo
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            if log:
                log(f"{provider} lỗi → thử provider khác…")

    limit = next((e for e in errors if "GIỚI HẠN" in e.upper()), "")
    if limit:
        raise providers.AIError(limit.split(":", 1)[-1].strip())
    raise providers.AIError(_fmt_errors(errors))


# --------------------------------------------------------------------------- #
# Random 1 trường
# --------------------------------------------------------------------------- #
FIELD_RULES = {
    "title": ("Tiêu đề SEO", "seo"),
    "focus_keyword": ("Từ khóa chính", "seo"),
    "description": ("Mô tả ngắn", "seo"),
    "tags": ("Thẻ sản phẩm (tags)", "seo"),
    "content_html": ("Nội dung bài viết", "content"),
}


def build_field_prompt(rules, source: dict, field: str, current: str = "") -> str:
    label, rule_key = FIELD_RULES.get(field, ("Nội dung", "content"))
    rule = read_rule(getattr(rules, rule_key, ""))
    return f"""Bạn là chuyên gia SEO tiếng Việt. Hãy tạo lại DUY NHẤT trường "{label}".

=== QUY ĐỊNH ({rule_key.upper()}) ===
{rule or "(Không có quy định riêng.)"}

=== BÀI VIẾT NGUỒN ===
Tiêu đề gốc: {source.get('title', '')}
URL: {source.get('url', '')}
Nội dung:
{source.get('text', '')[:5000]}

=== BẢN HIỆN TẠI (cần viết lại KHÁC đi, hay hơn) ===
{current}

CHỈ trả về đúng nội dung của trường "{label}", không thêm nhãn, không giải thích.
"""


def generate_field(store, source: dict, field: str, current: str = "", log=None) -> str:
    rules = store.formats
    label, rule_key = FIELD_RULES.get(field, ("Nội dung", "content"))
    full = build_field_prompt(rules, source, field, current)
    if rule_key == "seo":
        short = (
            f"Dựa vào bài viết tại link dưới đây, hãy tạo DUY NHẤT trường “{label}” theo đúng "
            "tài liệu đã đính kèm (sources) trong Project này — cụ thể là file **rule_seo.pdf**.\n"
            f"Link bài viết nguồn: {source.get('url', '')}\n"
            f"Chỉ trả về nội dung của trường đó, không thêm nhãn, không giải thích."
        )
    else:
        short = (
            f"Dựa vào bài viết tại link dưới đây, hãy viết lại DUY NHẤT trường “{label}” theo đúng "
            "tài liệu đã đính kèm (sources) trong Project này — cụ thể là file **rule_content.pdf**.\n"
            f"Link bài viết nguồn: {source.get('url', '')}\n"
            f"Chỉ trả về nội dung của trường đó, không thêm nhãn, không giải thích."
        )
    return _call_ai(store, full, short, log).strip()


def parse_json_response(text: str) -> dict:  # tương thích ngược
    return providers.parse_json_response(text)


# --------------------------------------------------------------------------- #
# Model Extractor: trích xuất product models từ danh sách link nguồn
# --------------------------------------------------------------------------- #
def build_extractor_prompt(rules, url: str, text: str) -> str:
    """Prompt cho provider API: nhúng nội dung file Rule Model Extractor."""
    rule = read_rule(getattr(rules, "extractor", ""))
    return f"""Bạn là chuyên gia trích xuất dữ liệu sản phẩm.
Hãy làm theo ĐÚNG file quy định dưới đây.

=== RULE MODEL EXTRACTOR ===
{rule or "(Không có quy định riêng — hãy liệt kê mọi model sản phẩm tìm thấy.)"}

=== NỘI DUNG TRANG NGUỒN ===
URL: {url}
{text}

=== YÊU CẦU ===
Trích xuất TOÀN BỘ product models theo đúng rule trên.

ĐỊNH DẠNG KẾT QUẢ (BẮT BUỘC):
- MỖI DÒNG chỉ ghi ĐÚNG 1 mã model, không gì khác.
- KHÔNG đánh số (1., 2., …), KHÔNG gạch đầu dòng (-, •, *), KHÔNG markdown.
- KHÔNG thêm tiêu đề, không giải thích, không dòng trống.

Ví dụ kết quả đúng:
BI15U-EM30WDTC-AP6X
BI10U-EM30WDTC-AP6X
BI8U-EM30WDTC-AP6X
"""


def build_extractor_short_prompt(url: str, text: str) -> str:
    """Prompt ngắn cho ChatGPT (file rule nằm trong Project)."""
    return f"""Đọc nội dung trang nguồn dưới đây và trích xuất TOÀN BỘ product models theo file
**Rule_Model_Extractor.pdf** đã đính kèm (sources) trong Project này.

Link nguồn: {url}

=== NỘI DUNG TRANG NGUỒN ===
{text}

ĐỊNH DẠNG KẾT QUẢ (BẮT BUỘC): MỖI DÒNG chỉ ghi ĐÚNG 1 mã model, không đánh số,
không gạch đầu dòng, không markdown, không thêm chữ nào khác. Ví dụ:
BI15U-EM30WDTC-AP6X
BI10U-EM30WDTC-AP6X
"""


def extract_models(store, link: str, text: str, log=None, should_stop=None) -> str:
    """Gọi provider (theo chuỗi ưu tiên) để trích xuất product models từ 1 link nguồn."""
    cfg = store.ai_content
    rules = store.formats
    full = build_extractor_prompt(rules, link, text)
    short = build_extractor_short_prompt(link, text)
    errors: list[str] = []

    for provider in _active_chain(cfg):
        pcfg = (cfg.get("providers") or {}).get(provider, {})
        api_key = crypto.decrypt(pcfg.get("api_key_enc", ""))
        if provider in API_PROVIDERS and not api_key:
            errors.append(f"{provider}: thiếu API key")
            continue
        try:
            if should_stop and should_stop():
                raise providers.AIError("Đã dừng theo yêu cầu.")
            if provider == "chatgpt":
                from .chatgpt_browser import generate_with_chatgpt

                show = bool(pcfg.get("show_browser", False))
                return generate_with_chatgpt(pcfg, short, log, show_browser=show) or ""
            if log:
                log(f"Đang trích xuất bằng {provider}…")
            return providers.generate_text(provider, pcfg, full, api_key) or ""
        except Exception as exc:      # noqa: BLE001
            errors.append(f"{provider}: {exc}")
            if log:
                log(f"{provider} lỗi → thử provider khác…")
    raise providers.AIError(_fmt_errors(errors))


def clean_model_lines(text: str) -> str:
    """Dọn kết quả Model Extractor: mỗi dòng 1 mã, bỏ gạch đầu dòng / số thứ tự / markdown."""
    out: list[str] = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        s = re.sub(r"^[-*•·▪◦‣–—]+\s*", "", s)      # gạch đầu dòng
        s = re.sub(r"^\d+[.)]\s+", "", s)           # "1. " / "2) "
        s = re.sub(r"^[*_`]{1,3}", "", s)
        s = re.sub(r"[*_`]{1,3}$", "", s)
        s = s.strip().strip(",\"'").strip()
        # bỏ nhãn ở đầu dòng nhưng GIỮ LẠI mã phía sau ("Kết quả: ABC-123" -> "ABC-123")
        s = re.sub(r"^(output|kết quả|ket qua|ví dụ|vi du|product\s*models?)\s*[:.\-–]?\s*",
                   "", s, flags=re.I).strip()
        if not s:
            continue
        out.append(s)
    return "\n".join(out)
