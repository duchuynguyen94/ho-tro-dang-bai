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
def build_content_prompt(rules, source: dict) -> str:
    rule = read_rule(getattr(rules, "content", ""))
    images_hint = "\n".join(f"- {u}" for u in source.get("images", [])[:6])
    return f"""Bạn là chuyên gia viết nội dung kỹ thuật. Hãy tạo BÀI VIẾT cho website WordPress
dựa trên BÀI VIẾT NGUỒN và TUYỆT ĐỐI tuân thủ QUY ĐỊNH (RULE CONTENT) dưới đây.

=== RULE CONTENT ===
{rule or "(Không có quy định riêng.)"}

=== BÀI VIẾT NGUỒN ===
Tiêu đề gốc: {source.get('title', '')}
URL: {source.get('url', '')}
Nội dung:
{source.get('text', '')[:6000]}

Ảnh trong bài nguồn (tham khảo):
{images_hint}

=== YÊU CẦU ĐẦU RA (đủ các mục, theo đúng thứ tự) ===
{CONTENT_OUTPUT_SPEC}

Chỉ trả về nội dung bài viết (được phép dùng Markdown), không giải thích thêm.
"""


def build_content_short_prompt(source: dict) -> str:
    """Prompt ngắn cho ChatGPT (rule nằm trong Project đã đính kèm)."""
    return f"""Đọc bài viết tại link dưới đây và viết lại thành 1 bài viết mới,
TUYỆT ĐỐI tuân thủ tài liệu đã đính kèm (sources) trong Project này — cụ thể là file **rule_content.pdf**.

Link bài viết nguồn: {source.get('url', '')}

Trả về đủ các mục sau, đúng thứ tự:
{CONTENT_OUTPUT_SPEC}

Chỉ trả về nội dung, không giải thích thêm.
"""


# --------------------------------------------------------------------------- #
# Prompt bước 2 — SEO
# --------------------------------------------------------------------------- #
def build_seo_prompt(rules, raw_content: str) -> str:
    rule = read_rule(getattr(rules, "seo", ""))
    return f"""Dưới đây là BÀI VIẾT đã hoàn thành. Hãy tạo thông tin SEO cho bài viết này,
TUYỆT ĐỐI tuân thủ QUY ĐỊNH (RULE SEO) dưới đây.

=== RULE SEO ===
{rule or "(Không có quy định riêng.)"}

=== BÀI VIẾT ===
{raw_content[:12000]}

=== YÊU CẦU ĐẦU RA ===
ĐIỀN NỘI DUNG THẬT vào JSON (KHÔNG trả lại nguyên mẫu).
CHỈ trả về DUY NHẤT 1 JSON hợp lệ, không giải thích, đúng định dạng:
{SEO_JSON_SPEC}
"""


def build_seo_short_prompt(raw_content: str) -> str:
    return f"""Dựa vào BÀI VIẾT dưới đây, hãy tạo thông tin SEO theo đúng tài liệu đã đính kèm
(sources) trong Project này — cụ thể là file **rule_seo.pdf**.

=== BÀI VIẾT ===
{raw_content[:12000]}

CHỈ trả về DUY NHẤT 1 JSON hợp lệ, không giải thích:
{SEO_JSON_SPEC}
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


def _call_ai_json(store, prompt: str, short_prompt: str, log=None) -> dict:
    """Như _call_ai nhưng bắt buộc trả JSON (cho bước SEO)."""
    cfg = store.ai_content
    errors: list[str] = []
    for provider in _active_chain(cfg):
        pcfg = (cfg.get("providers") or {}).get(provider, {})
        api_key = crypto.decrypt(pcfg.get("api_key_enc", ""))
        if provider in API_PROVIDERS and not api_key:
            errors.append(f"{provider}: thiếu API key")
            continue
        if log:
            log(f"Đang gọi AI (SEO): {provider}…")
        try:
            if provider == "chatgpt":
                from .chatgpt_browser import generate_with_chatgpt

                raw = generate_with_chatgpt(pcfg, short_prompt, log, require_json=True)
            else:
                raw = providers.generate_text(provider, pcfg, prompt, api_key)
            data = providers.parse_json_response(raw)
            missing = [k for k in REQUIRED_KEYS if not str(data.get(k, "")).strip()]
            if missing:
                raise providers.AIError(f"thiếu trường {missing}")
            if _is_placeholder(data.get("title")):
                raise providers.AIError("AI trả về mẫu rỗng cho tiêu đề.")
            return data
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            if log:
                log(f"{provider} lỗi → thử provider khác…")
    limit = next((e for e in errors if "GIỚI HẠN" in e.upper()), "")
    if limit:
        raise providers.AIError(limit.split(":", 1)[-1].strip())
    raise providers.AIError("Không tạo được thông tin SEO. " + _fmt_errors(errors))


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
                out.append("<table>")
                in_table = True
            out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        # tiêu đề
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            close_lists()
            lvl = min(6, len(m.group(1)) + 1)
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


# --------------------------------------------------------------------------- #
# Luồng chính: 2 bước
# --------------------------------------------------------------------------- #
def generate_content(store, source: dict, log=None) -> dict:
    """2 bước: Rule Content → Rule SEO. ChatGPT chạy cả 2 trong 1 lần chat."""
    rules = store.formats
    cfg = store.ai_content
    content_full = build_content_prompt(rules, source)
    content_short = build_content_short_prompt(source)
    seo_full = None
    errors: list[str] = []

    for provider in _active_chain(cfg):
        pcfg = (cfg.get("providers") or {}).get(provider, {})
        api_key = crypto.decrypt(pcfg.get("api_key_enc", ""))
        if provider in API_PROVIDERS and not api_key:
            errors.append(f"{provider}: thiếu API key")
            continue
        try:
            if provider == "chatgpt":
                from .chatgpt_browser import generate_two_step

                seo_short = build_seo_short_prompt_placeholder()
                raw_content, seo_text = generate_two_step(
                    pcfg, content_short, seo_short, log
                )
                seo = providers.parse_json_response(seo_text)
            else:
                if log:
                    log("Bước 1/2 — viết nội dung theo Rule Content…")
                raw_content = providers.generate_text(provider, pcfg, content_full, api_key)
                if log:
                    log("Bước 2/2 — tạo thông tin SEO theo Rule SEO…")
                seo_full = build_seo_prompt(rules, raw_content)
                seo_text = providers.generate_text(provider, pcfg, seo_full, api_key)
                seo = providers.parse_json_response(seo_text)

            missing = [k for k in REQUIRED_KEYS if not str(seo.get(k, "")).strip()]
            if missing:
                raise providers.AIError(f"thiếu trường {missing}")
            if _is_placeholder(seo.get("title")):
                raise providers.AIError("AI trả về mẫu rỗng cho tiêu đề.")

            seo["content_html"] = text_to_html(raw_content)
            seo["raw_content"] = raw_content
            if log:
                log("Đã có kết quả cuối (SEO).")
            return seo
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            if log:
                log(f"{provider} lỗi → thử provider khác…")

    limit = next((e for e in errors if "GIỚI HẠN" in e.upper()), "")
    if limit:
        raise providers.AIError(limit.split(":", 1)[-1].strip())
    raise providers.AIError("Không tạo được nội dung. " + _fmt_errors(errors))


def build_seo_short_prompt_placeholder() -> str:
    """Prompt SEO ngắn cho ChatGPT — nội dung bài viết nằm ngay trong đoạn chat."""
    return (
        "Dựa vào BÀI VIẾT bạn vừa viết ở trên, hãy tạo thông tin SEO theo đúng tài liệu "
        "đã đính kèm (sources) trong Project này — cụ thể là file **rule_seo.pdf**.\n\n"
        "CHỈ trả về DUY NHẤT 1 JSON hợp lệ, không giải thích:\n"
        + SEO_JSON_SPEC
    )


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
