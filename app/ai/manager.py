"""Điều phối AI viết nội dung: 2 bước Content (rule_content) → SEO (rule_seo)."""
from __future__ import annotations

import html
import json
import re
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
  "title": "tiêu đề SEO",
  "focus_keyword": "từ khóa chính",
  "description": "mô tả ngắn",
  "tags": "thẻ 1, thẻ 2, thẻ 3"
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
1) ĐẦU TIÊN: DUY NHẤT 1 khối JSON thông tin SEO (điền nội dung THẬT, không trả lại mẫu):
{SEO_JSON_SPEC}

2) NGAY SAU KHỐI JSON: TOÀN BỘ NỘI DUNG BÀI VIẾT dưới dạng **HTML thật**, đủ các mục:
{CONTENT_OUTPUT_SPEC}

Yêu cầu HTML: dùng <h2>, <h3> cho tiêu đề mục; <p> cho đoạn văn; <ul><li> cho danh sách;
và <table><tr><td> cho bảng thông số kỹ thuật. KHÔNG dùng Markdown, KHÔNG bọc trong ```.

Không giải thích gì thêm, không thêm tiêu đề phụ nào khác.
"""


def build_combined_short_prompt(source: dict) -> str:
    """1 prompt ngắn cho ChatGPT (2 file rule nằm trong Project đã đính kèm)."""
    return f"""Đọc bài viết tại link dưới đây, viết lại thành 1 bài viết mới theo file **rule_content.pdf**
đã đính kèm (sources) trong Project này, sau đó tạo thông tin SEO theo file **rule_seo.pdf**
cũng trong Project này.

Link bài viết nguồn: {source.get('url', '')}

=== THỨ TỰ TRẢ VỀ (BẮT BUỘC) ===
1) ĐẦU TIÊN: DUY NHẤT 1 khối JSON thông tin SEO (điền nội dung THẬT, không trả lại mẫu):
{SEO_JSON_SPEC}

2) NGAY SAU KHỐI JSON: TOÀN BỘ NỘI DUNG BÀI VIẾT dưới dạng **HTML thật** theo rule_content.pdf, đủ các mục:
{CONTENT_OUTPUT_SPEC}

Yêu cầu HTML: dùng <h2>, <h3> cho tiêu đề mục; <p> cho đoạn văn; <ul><li> cho danh sách;
và <table><tr><td> cho bảng thông số kỹ thuật. KHÔNG dùng Markdown, KHÔNG bọc trong ```.

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
    if not errors:
        return "Không rõ nguyên nhân."
    head = " | ".join(errors[:3])
    if len(errors) > 3:
        head += f" (+{len(errors) - 3} lỗi khác)"
    return head


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
    raise providers.AIError("Không tạo được nội dung. " + _fmt_errors(errors))


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


def _site_tokens(site_url: str, site_name: str) -> list[str]:
    """Các biến thể tên miền CÓ 'www.' để chèn link (tự thêm www nếu site chưa có)."""
    tokens: list[str] = []
    for raw in (site_name or "", site_url or ""):
        t = (raw or "").strip().rstrip("/")
        if not t:
            continue
        t = re.sub(r"^https?://", "", t).lower()
        if not t:
            continue
        bare = t[4:] if t.startswith("www.") else t
        for cand in (t, f"www.{bare}"):
            if cand.startswith("www.") and cand not in tokens:
                tokens.append(cand)
    return sorted(tokens, key=len, reverse=True)


def _looks_like_html(text: str) -> bool:
    """True nếu nội dung đã là HTML (có thẻ khối)."""
    return bool(re.search(r"<\s*(h[1-6]|p|ul|ol|table|div|figure)\b", text or "", re.I))


def extract_product_name(raw_content: str, fallback: str = "") -> str:
    """Lấy tên sản phẩm: dòng ngay sau 'Tiêu đề bài viết' (chấp nhận cả HTML)."""
    text = re.sub(r"<[^>]+>", "\n", raw_content or "")
    m = re.search(r"Tiêu đề bài viết[^\n]*\n+\s*([^\n]{3,200})", text, re.I)
    if m:
        name = m.group(1).strip(" •-*#\t")
        if name:
            return name
    return (fallback or "").strip()


def autolink_html(html_text: str, site_url: str = "", site_name: str = "",
                  product_name: str = "") -> str:
    """Chèn link external: (1) một lần vào TÊN SẢN PHẨM, (2) cho tên miền dạng www."""
    if not html_text:
        return html_text
    base = (site_url or "").strip().rstrip("/")
    if base and not base.startswith("http"):
        base = "https://" + base
    if not base:
        return html_text

    tokens = _site_tokens(site_url, site_name)
    parts = re.split(r"(<[^>]+>)", html_text)
    out: list[str] = []
    in_a = False
    product_done = False
    pname = (product_name or "").strip()

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
        # (1) chèn 1 lần link external vào tên sản phẩm
        if pname and not product_done:
            idx = text.find(pname)
            if idx >= 0:
                text = (text[:idx] + f'<a href="{base}">{pname}</a>'
                        + text[idx + len(pname):])
                product_done = True
        # (2) chèn link cho tên miền dạng www.
        for tok in tokens:
            pattern = re.compile(rf"(?<![\w./-])({re.escape(tok)})(?![\w/-])", re.I)
            text = pattern.sub(lambda m: f'<a href="{base}">{m.group(1)}</a>', text)
        out.append(text)
    return "".join(out)


# --------------------------------------------------------------------------- #
# Luồng chính: 1 lần gọi (JSON SEO trước, nội dung sau)
# --------------------------------------------------------------------------- #
def generate_content(store, source: dict, log=None) -> dict:
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
            if provider == "chatgpt":
                from .chatgpt_browser import generate_combined

                raw = generate_combined(pcfg, short, log)
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

            seo["content_html"] = (
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
    raise providers.AIError("Không tạo được nội dung. " + _fmt_errors(errors))


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
