"""Điều phối AI viết nội dung: ghép quy định (file format) + link nguồn -> JSON."""
from __future__ import annotations

import json
from pathlib import Path

from ..storage import crypto
from . import providers

def _fmt_errors(errors: list[str]) -> str:
    if not errors:
        return "Không rõ nguyên nhân."
    head = " | ".join(errors[:3])
    if len(errors) > 3:
        head += f" (+{len(errors) - 3} lỗi khác)"
    return head


REQUIRED_KEYS = ("title", "focus_keyword", "description", "tags", "content_html")


def read_rule(path: str, limit: int = 8000) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def build_prompt(rules, source: dict) -> str:
    rules_title = read_rule(getattr(rules, "title", ""))
    rules_content = read_rule(getattr(rules, "content", ""))
    rules_desc = read_rule(getattr(rules, "description", ""))
    rules_tags = read_rule(getattr(rules, "tags", ""))

    images_hint = "\n".join(f"- {u}" for u in source.get("images", [])[:6])

    return f"""Bạn là chuyên gia content SEO tiếng Việt. Hãy tạo bài viết cho website WordPress dựa trên BÀI VIẾT NGUỒN và TUYỆT ĐỐI tuân thủ QUY ĐỊNH dưới đây.

=== QUY ĐỊNH TIÊU ĐỀ ===
{rules_title or "(Không có quy định riêng — viết tiêu đề hấp dẫn, có từ khóa chính.)"}

=== QUY ĐỊNH NỘI DUNG ===
{rules_content or "(Không có quy định riêng — viết nội dung rõ ràng, có thẻ <h2>, <p>, <ul>.)"}

=== QUY ĐỊNH DESCRIPTION ===
{rules_desc or "(Không có quy định riêng — mô tả SEO dưới 160 ký tự.)"}

=== QUY ĐỊNH SEARCH TAGS ===
{rules_tags or "(Không có quy định riêng — 4-8 thẻ, cách nhau bởi dấu phẩy.)"}

=== BÀI VIẾT NGUỒN ===
Tiêu đề gốc: {source.get('title', '')}
URL: {source.get('url', '')}
Nội dung:
{source.get('text', '')[:5000]}

Ảnh trong bài nguồn (tham khảo):
{images_hint}

=== YÊU CẦU ĐẦU RA ===
CHỈ trả về DUY NHẤT 1 JSON hợp lệ, không giải thích, đúng định dạng:
{{
  "title": "tiêu đề theo quy định",
  "focus_keyword": "từ khóa chính",
  "description": "mô tả SEO",
  "tags": "thẻ 1, thẻ 2, thẻ 3",
  "content_html": "<h2>...</h2><p>...</p>"
}}
"""


def _active_chain(cfg: dict) -> list[str]:
    """Thứ tự thử provider: cái đang chọn trước, rồi theo thứ tự người dùng sắp (fallback)."""
    providers = [p for p in (cfg.get("providers") or {})]
    order = [p for p in (cfg.get("order") or []) if p in providers]
    order += [p for p in providers if p not in order]
    active = cfg.get("active") or (order[0] if order else "")
    if active in order:
        order.remove(active)
    chain = ([active] if active else []) + order
    if not cfg.get("fallback", True):
        chain = [active]
    return chain


FIELD_RULES = {
    "title": ("Tiêu đề", "title"),
    "focus_keyword": ("Focus keyword (từ khóa chính)", None),
    "description": ("Description (mô tả SEO)", "description"),
    "tags": ("Search tags (thẻ, cách nhau bởi dấu phẩy)", "tags"),
    "content_html": ("Nội dung dạng HTML", "content"),
}


CHATGPT_SHORT_PROMPT = """Đọc bài viết tại link dưới đây và viết lại thành 1 bài viết mới,
TUYỆT ĐỐI tuân thủ tài liệu / quy định đã được đính kèm trong Project này.

Link bài viết nguồn: {url}

CHỈ trả về DUY NHẤT 1 JSON hợp lệ, không giải thích, đúng định dạng:
{{"title": "...", "focus_keyword": "...", "description": "...", "tags": "thẻ 1, thẻ 2", "content_html": "<h2>...</h2><p>...</p>"}}
"""


def build_short_prompt(source: dict) -> str:
    """Prompt ngắn cho ChatGPT (nội dung/quy định nằm trong Project đã đính kèm)."""
    return CHATGPT_SHORT_PROMPT.format(url=source.get("url", ""))


def build_field_prompt(rules, source: dict, field: str, current: str = "") -> str:
    label, rule_key = FIELD_RULES.get(field, ("Nội dung", None))
    rules_text = read_rule(getattr(rules, rule_key, "") if rule_key else "")
    return f"""Bạn là chuyên gia content SEO tiếng Việt. Hãy tạo lại DUY NHẤT trường "{label}" cho bài viết.

=== QUY ĐỊNH ===
{rules_text or "(Không có quy định riêng.)"}

=== BÀI VIẾT NGUỒN ===
Tiêu đề gốc: {source.get('title', '')}
URL: {source.get('url', '')}
Nội dung:
{source.get('text', '')[:4000]}

=== BẢN HIỆN TẠI (cần viết lại KHÁC đi, hay hơn) ===
{current}

CHỈ trả về đúng nội dung của trường "{label}", không thêm nhãn, không giải thích, không bọc JSON.
"""


def generate_field(store, source: dict, field: str, current: str = "", log=None) -> str:
    prompt = build_field_prompt(store.formats, source, field, current)
    cfg = store.ai_content
    errors: list[str] = []
    for provider in _active_chain(cfg):
        pcfg = cfg.get("providers", {}).get(provider, {})
        api_key = crypto.decrypt(pcfg.get("api_key_enc", ""))
        if provider in ("gemini", "groq", "openrouter", "openai", "deepseek") and not api_key:
            errors.append(f"{provider}: thiếu API key")
            continue
        try:
            if provider == "chatgpt":
                from .chatgpt_browser import generate_with_chatgpt

                label = FIELD_RULES.get(field, ("Nội dung", None))[0]
                short = (
                    f"Đọc bài viết tại link dưới đây và viết lại DUY NHẤT trường “{label}” "
                    "theo tài liệu / quy định đã đính kèm trong Project này.\n"
                    f"Link bài viết nguồn: {source.get('url', '')}\n"
                    f"Chỉ trả về nội dung của trường đó, không thêm nhãn, không giải thích."
                )
                return generate_with_chatgpt(pcfg, short, log).strip()
            return providers.generate_text(provider, pcfg, prompt, api_key).strip()
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    raise providers.AIError("Không tạo được trường này. " + _fmt_errors(errors))


def generate_content(store, source: dict, log=None) -> dict:
    prompt = build_prompt(store.formats, source)
    short_prompt = build_short_prompt(source)
    cfg = store.ai_content
    errors: list[str] = []

    for provider in _active_chain(cfg):
        pcfg = cfg.get("providers", {}).get(provider, {})
        api_key = crypto.decrypt(pcfg.get("api_key_enc", ""))
        if provider in ("gemini", "groq", "openrouter", "openai", "deepseek") and not api_key:
            errors.append(f"{provider}: thiếu API key")
            continue
        if log:
            log(f"Đang gọi AI: {provider}…")
        try:
            if provider == "chatgpt":
                from .chatgpt_browser import generate_with_chatgpt

                raw = generate_with_chatgpt(pcfg, short_prompt, log)
            else:
                raw = providers.generate_text(provider, pcfg, prompt, api_key)
            data = providers.parse_json_response(raw)
            missing = [k for k in REQUIRED_KEYS if not str(data.get(k, "")).strip()]
            if missing:
                raise providers.AIError(f"thiếu trường {missing}")
            if log:
                log(f"Xong bằng {provider}.")
            return data
        except Exception as exc:  # thử provider kế tiếp
            errors.append(f"{provider}: {exc}")
            if log:
                log(f"{provider} lỗi → thử provider khác…")

    raise providers.AIError("Không tạo được nội dung. " + _fmt_errors(errors))
