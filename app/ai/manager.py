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
    "Bám ĐÚNG mục 5. TEMPLATE của RULE CONTENT: đúng THỨ TỰ mục, đúng TÊN MỤC, đúng các dòng "
    "liên hệ lặp lại giữa các mục. (Nếu RULE CONTENT ghi khác danh sách này thì theo RULE CONTENT.)\n"
    "1. <h1> tiêu đề bài viết: [Keyword] [Brand] [Model] – [Tính năng hoặc ứng dụng nổi bật]\n"
    "2. <p> “Được phân phối chính hãng bởi Ngọc Huy Dương – Đơn vị chuyên cung cấp thiết bị "
    "công nghiệp tại Việt Nam”\n"
    "3. <p> dòng liên hệ: www.ngochuyduong.com | 0909 399 174 | thach.phan@ngochuyduong.com\n"
    "4. <h2>Giới thiệu tổng quan</h2>: 3 gạch đầu dòng như template (giới thiệu sản phẩm/dòng sản "
    "phẩm, công năng, mục đích sử dụng; giới thiệu thương hiệu: trụ sở, lịch sử, thị trường, chứng "
    "nhận uy tín; khẳng định Ngọc Huy Dương là nhà phân phối chính thức tại Việt Nam – hàng chính "
    "hãng, đủ CO/CQ, hỗ trợ kỹ thuật & bảo hành toàn quốc) → kết mục bằng dòng "
    "“Liên hệ ngay: 0909 399 174 | thach.phan@ngochuyduong.com - [Keyword] [Brand] [Model]”\n"
    "5. <h2>Tính năng kỹ thuật nổi bật [Keyword] [Brand] [Model]</h2>: 3–5 ưu điểm (hiệu suất, độ "
    "bền, chịu nhiệt, chống ăn mòn, thông minh, tiết kiệm năng lượng), ghi rõ chứng nhận CE/ISO/UL "
    "nếu có → dòng “Gửi yêu cầu tư vấn kỹ thuật: thach.phan@ngochuyduong.com”\n"
    "6. <h2>Thông số kỹ thuật tiêu chuẩn [Keyword] [Brand] [Model]</h2>: dòng liên hệ, rồi <table> "
    "2 cột “Thông số kỹ thuật” | “Giá trị điển hình” với ĐÚNG 5 hàng: Áp suất làm việc, Nhiệt độ làm "
    "việc, Kích thước kết nối, Chất liệu thân, Tín hiệu ra / Đầu vào → dòng “Hỗ trợ chọn cấu hình "
    "theo yêu cầu thực tế: 0909 399 174 - [Keyword] [Brand] [Model]”\n"
    "7. <h2>Vật liệu & xử lý – Độ bền vượt trội [Keyword] [Brand] [Model]</h2>: vật liệu (inox, nhôm, "
    "nhựa kỹ thuật, gang cầu…), xử lý bề mặt (sơn epoxy, mạ kẽm, tôi cứng, phủ PTFE…) kèm 1–2 ví dụ "
    "cụ thể → dòng liên hệ\n"
    "8. <h2>Tương thích – Thay thế – Mở rộng [Keyword] [Brand] [Model]</h2>: so sánh tương thích với "
    "thương hiệu khác (GEMÜ, Alfa Laval, Festo…), khả năng thay thế, chuẩn công nghiệp, dễ nâng cấp "
    "hệ thống → dòng liên hệ\n"
    "9. <h2>Ứng dụng thực tế [Keyword] [Brand] [Model]</h2>: dòng liên hệ, rồi 5 ứng dụng (nhà máy "
    "dược phẩm; dây chuyền thực phẩm – đồ uống; hệ thống xử lý nước – CIP; hệ thống khí sạch – phòng "
    "sạch; nhà máy hóa chất – mỹ phẩm) → dòng “Gọi tư vấn theo ngành: 0909 399 174 - [Keyword] "
    "[Brand] [Model]”\n"
    "10. <h2>Tại sao nên mua tại Ngọc Huy Dương?</h2>: 4 gạch đầu dòng như template (hơn 15 năm kinh "
    "nghiệm; chính hãng – giá cạnh tranh; hỗ trợ kỹ thuật tận tâm & sau bán hàng toàn quốc; hợp tác "
    "lâu dài với nhà máy, kỹ sư thiết kế, nhà thầu lớn) → dòng liên hệ\n"
    "11. <h2>Liên hệ – Đặt hàng / Tư vấn kỹ thuật [Keyword] [Brand] [Model]</h2>: CÔNG TY TNHH NGỌC "
    "HUY DƯƠNG + Website: www.ngochuyduong.com, Email: thach.phan@ngochuyduong.com, Hotline: 0909 399 "
    "174 + câu mời liên hệ để được tư vấn sản phẩm\n"
    "12. <h2>Phiên bản & Mã sản phẩm [Keyword] [Brand] [Model]</h2>: dòng liên hệ → dòng “Bạn cần "
    "bảng model [Keyword] [Brand] [Model] đầy đủ? Gửi yêu cầu: thach.phan@ngochuyduong.com”\n"
    "13. <h2>FAQ (5 câu)</h2>: 5 câu hỏi kèm câu trả lời ngắn, sát sản phẩm.\n"
    "Giữ NGUYÊN các dòng liên hệ lặp lại giữa các mục (không bỏ, không đổi website/điện thoại/email).\n"
    "ICON ĐẦU MỤC: CHỈ đặt ở thẻ <h2> của các mục (KHÔNG đặt ở h1/h3/h4…): "
    "📌 Giới thiệu tổng quan; "
    "⚙️ Tính năng kỹ thuật nổi bật; 📋 Thông số kỹ thuật tiêu chuẩn; 🧱 Vật liệu & xử lý – Độ bền vượt trội; "
    "🔄 Tương thích – Thay thế – Mở rộng; 🎯 Ứng dụng thực tế; 💡 Tại sao nên mua tại Ngọc Huy Dương?; "
    "📞 Liên hệ – Đặt hàng / Tư vấn kỹ thuật; 🧩 Phiên bản & Mã sản phẩm; 🧩 FAQ (5 câu).\n"
    "ICON Ở DÒNG LIÊN HỆ: 🌐 trước website; ☎️ trước số điện thoại và ✉️ trước email trong dòng liên hệ lặp lại; "
    "📞 trước hotline ở các dòng “Liên hệ ngay:”, “Hotline:”, “Hỗ trợ chọn cấu hình…”, “Gọi tư vấn theo ngành:”; "
    "📧 trước “Gửi yêu cầu tư vấn kỹ thuật”, ✉️ trước email trong dòng “Liên hệ ngay”, "
    "📩 trước “Bạn cần bảng model … đầy đủ?”."
)

# Dòng liên hệ CHUẨN trong "description" (mục 3 của rule_seo)
DESC_CONTACT = "🌐 www.ngochuyduong.com | ☎️ 0909 399 174 | thach.phan@ngochuyduong.com"


def normalize_description(desc: str) -> str:
    """Chuẩn hoá "description" theo mục 3 của rule_seo.pdf:
    1) câu mô tả; 2) dòng liên hệ (luôn đúng mẫu 🌐 | ☎️ | email);
    3) "Tên sản phẩm <Hãng> models tiêu biểu"; 4) tối đa 5 model tiêu biểu, mỗi dòng 1 model.
    """
    text = (desc or "").strip()
    if not text:
        return text
    text = re.sub(r"^\s*```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text).strip().strip('"').strip()
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    head = header = ""
    models: list[str] = []
    for ln in lines:
        low = ln.lower()
        if "ngochuyduong.com" in low:
            continue                      # dòng liên hệ -> dùng bản CHUẨN bên dưới
        if "models tiêu biểu" in low or "models tieu bieu" in low:
            header = ln
        elif not head:
            head = ln
        else:
            models.append(ln)

    out: list[str] = []
    if head:
        out.append(head)
    out.append(DESC_CONTACT)
    if header:
        out.append(header)
    out.extend(models[:5])                # không nhiều hơn 5 dòng
    return "\n".join(out)


# Kết quả bước 2 (theo Rule SEO)
SEO_JSON_SPEC = """{
  "title": "55-60 ký tự, dạng: [Keyword] [Brand] [Model] + [USP] — chọn NGẪU NHIÊN 1 USP trong: Chính hãng, Giá tốt, CO/CQ đầy đủ, Báo giá nhanh, Hàng sẵn, Giao nhanh, Đại lý, Phân phối, Hỗ trợ kỹ thuật, Bảo hành chính hãng, Tổng kho",
  "focus_keyword": "01 từ khoá chính duy nhất = Model của sản phẩm (vd: BI15U-EM30WDTC-AP6X)",
  "description": "mô tả siêu ngắn ĐÚNG mục 3 của rule_seo, gồm 4 phần trên các dòng riêng: (1) câu mô tả: “<Keyword> <Brand> <Model> được phân phối chính hãng bởi Công ty TNHH Ngọc Huy Dương – đơn vị phân phối <Keyword> <Brand> <Model> tại Việt Nam, giá tốt, hàng sẵn, giao nhanh toàn quốc.”; (2) dòng liên hệ: “🌐 www.ngochuyduong.com | ☎️ 0909 399 174 | thach.phan@ngochuyduong.com”; (3) “Tên sản phẩm <Brand> models tiêu biểu”; (4) tối đa 5 model tiêu biểu, MỖI DÒNG 1 model theo mẫu “<Tên sản phẩm> <Hãng> <Model>” (vd: Cảm biến siêu âm Carlo Gavazzi UA18CAD04PM1)",
  "tags": "trên 350 từ, mở rộng nhất có thể, thuần Việt, cách nhau dấu phẩy; GỒM: tên sản phẩm + đồng nghĩa, thương hiệu, sản phẩm + model nổi bật, từ khoá địa phương/tiếng Việt thông dụng, thông tin công ty"
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

2) SAU CÙNG: DUY NHẤT 1 khối JSON thông tin SEO, TẠO THEO **RULE SEO Ở TRÊN** và
DỰA TRÊN CHÍNH NỘI DUNG BÀI VIẾT Ở MỤC 1 (đúng sản phẩm, thương hiệu, model, thông số trong bài;
điền nội dung THẬT, không trả lại mẫu):
{SEO_JSON_SPEC}

Không giải thích gì thêm, không thêm tiêu đề phụ nào khác.
"""


def build_combined_short_prompt(source: dict) -> str:
    """1 prompt ngắn cho ChatGPT (2 file rule nằm trong Project đã đính kèm)."""
    return f"""Đọc bài viết tại link nguồn {source.get('url', '')} viết lại thành 1 bài viết mới theo file "rule_content.pdf" đã đính kèm (sources) trong Project này, sau đó tạo thông tin SEO theo file "rule_seo.pdf" đã đính kèm trong Project này.

=== THỨ TỰ TRẢ VỀ (BẮT BUỘC) ===
1) ĐẦU TIÊN: TOÀN BỘ NỘI DUNG BÀI VIẾT dưới dạng "HTML" theo template trong rule_content.pdf
2) SAU CÙNG: 1 khối JSON thông tin SEO theo file rule_seo.pdf bao gồm: title, focus_keyword, description, tags
   - TOÀN BỘ thông tin SEO phải DỰA TRÊN CHÍNH NỘI DUNG BÀI VIẾT Ở MỤC 1 (đúng sản phẩm, thương hiệu, model, thông số trong bài; không bịa thêm).
   - "title": 55-60 ký tự, dạng "[Keyword] [Brand] [Model] + [USP]", chọn NGẪU NHIÊN 1 USP trong danh sách: Chính hãng / Giá tốt / CO/CQ đầy đủ / Báo giá nhanh / Hàng sẵn / Giao nhanh / Đại lý / Phân phối / Hỗ trợ kỹ thuật / Bảo hành chính hãng / Tổng kho
   - "focus_keyword": 01 từ khoá chính duy nhất = Model của sản phẩm (vd: BI15U-EM30WDTC-AP6X)
   - "description": 4 phần trên dòng riêng: câu mô tả "<Keyword> <Brand> <Model> được phân phối chính hãng bởi Công ty TNHH Ngọc Huy Dương – đơn vị phân phối <Keyword> <Brand> <Model> tại Việt Nam, giá tốt, hàng sẵn, giao nhanh toàn quốc."; dòng liên hệ 🌐 www.ngochuyduong.com | ☎️ 0909 399 174 | thach.phan@ngochuyduong.com; "Tên sản phẩm <Brand> models tiêu biểu"; rồi tối đa 5 model tiêu biểu, MỖI DÒNG 1 model dạng "<Tên sản phẩm> <Hãng> <Model>"
   - "tags": trên 350 từ, mở rộng nhất có thể, thuần Việt, cách nhau dấu phẩy, gồm: tên sản phẩm + đồng nghĩa; thương hiệu; sản phẩm + model nổi bật; từ khoá địa phương/tiếng Việt thông dụng; thông tin công ty

Không giải thích gì thêm."""


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
    "Giới thiệu tổng quan",
    "Giới thiệu chung",
    "Tính năng kỹ thuật nổi bật",
    "Tính năng nổi bật",
    "Thông số kỹ thuật tiêu chuẩn",
    "Thông số kỹ thuật",
    "Vật liệu & xử lý – Độ bền vượt trội",
    "Vật liệu và xử lý",
    "Tương thích – Thay thế – Mở rộng",
    "Tương thích",
    "Ứng dụng thực tế",
    "Tại sao nên mua tại Ngọc Huy Dương?",
    "Liên hệ – Đặt hàng / Tư vấn kỹ thuật",
    "Phiên bản & Mã sản phẩm",
    "Phiên bản và Mã sản phẩm",
    "FAQ (5 câu)",
    "FAQ",
    "Hỏi đáp",
    "Hỏi & Đáp",
    "Câu hỏi thường gặp",
    "Câu hỏi đáp",
)


# Icon đầu mục theo template (mục 5. TEMPLATE của Rule_Content)
TITLE_ICON = "🏷️"
SECTION_ICONS = (
    ("Giới thiệu tổng quan", "📌"),
    ("Giới thiệu chung", "📌"),
    ("Tính năng kỹ thuật nổi bật", "⚙️"),
    ("Tính năng nổi bật", "⚙️"),
    ("Thông số kỹ thuật tiêu chuẩn", "📋"),
    ("Thông số kỹ thuật", "📋"),
    ("Vật liệu & xử lý", "🧱"),
    ("Vật liệu và xử lý", "🧱"),
    ("Tương thích – Thay thế", "🔄"),
    ("Tương thích", "🔄"),
    ("Ứng dụng thực tế", "🎯"),
    ("Tại sao nên mua", "💡"),
    ("Liên hệ – Đặt hàng", "📞"),
    ("Phiên bản & Mã sản phẩm", "🧩"),
    ("Phiên bản và Mã sản phẩm", "🧩"),
    ("FAQ", "🧩"),
    ("Hỏi đáp", "🧩"),
    ("Hỏi & Đáp", "🧩"),
    ("Câu hỏi thường gặp", "🧩"),
    ("Câu hỏi đáp", "🧩"),
)
_PHONE_RE = re.compile(r"0\d{2,4}[\s.\-]?\d{3}[\s.\-]?\d{3,4}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_HAS_ICON_RE = re.compile(r"^[\w\[\"'(\-]")


_ICON_CHARS = (r"\U0001F000-\U0001FAFF\u2190-\u27BF\u2B00-\u2BFF"
               r"\uFE0F\u200D\u2600-\u26FF")
_LEAD_ICON_RE = re.compile(rf"^(\s*[{_ICON_CHARS}]+\s*)")


def split_leading_icon(text: str) -> tuple[str, str]:
    """Tách icon ở ĐẦU chuỗi (nếu có) để icon không bị bọc vào thẻ <a>."""
    m = _LEAD_ICON_RE.match(text or "")
    if not m:
        return "", text
    return m.group(1), text[m.end():]


def _prepend_icon(s: str, icon: str, alt: tuple[str, ...] = ()) -> str:
    """Thêm icon vào đầu dòng (thay icon cũ cùng nhóm nếu có), giữ khoảng trắng đầu."""
    st = s.lstrip()
    if not st:
        return s
    lead = s[: len(s) - len(st)]
    for ic in (icon, *alt):
        if st.startswith(ic):
            return f"{lead}{icon}{st[len(ic):]}"
    return f"{lead}{icon} {st}"


def _section_icon(text: str) -> str:
    """Icon tương ứng với tên mục chuẩn trong template."""
    for key, icon in SECTION_ICONS:
        if _section_re(key).search(text):
            return icon
    return ""


def _decorate_line(text: str) -> str:
    """Chèn icon vào các DÒNG LIÊN HỆ theo đúng template (idempotent)."""
    s = text
    if not s.strip():
        return s
    # bỏ icon ở đầu để nhận dạng NHÃN (vd "☎️ Liên hệ ngay: …" -> "Liên hệ ngay: …")
    low = re.sub(rf"^[\s{_ICON_CHARS}]+", "", s).strip().lower()
    if not low:
        return s

    # dòng liên hệ có cả website + số điện thoại: 🌐 website | ☎️ phone | email
    if ("www." in low or "http" in low) and _PHONE_RE.search(s):
        s = re.sub(r"(?<!🌐\s)((?:https?://)?www\.[^\s|]+)", r"🌐 \1", s, count=1, flags=re.I)
        m = _PHONE_RE.search(s)
        if m:
            prefix = re.sub(r"[☎📞]️?\s*$", "", s[: m.start()])   # bỏ icon điện thoại cũ
            s = f"{prefix}☎️ {s[m.start():]}"
        m = _EMAIL_RE.search(s)
        if m:
            prefix = re.sub(r"[✉📧]️?\s*$", "", s[: m.start()])   # bỏ icon email cũ
            s = f"{prefix}✉️ {s[m.start():]}"
        return s

    if low.startswith("liên hệ ngay"):
        m = _EMAIL_RE.search(s)
        if m:
            prefix = re.sub(r"[✉📧]️?\s*$", "", s[: m.start()])   # bỏ icon email cũ
            s = f"{prefix}✉️ {s[m.start():]}"
        return _prepend_icon(s, "📞", ("☎️", "☎"))
    if low.startswith("gửi yêu cầu tư vấn kỹ thuật"):
        return _prepend_icon(s, "📧", ("✉️", "✉"))
    if low.startswith("hỗ trợ chọn cấu hình") or low.startswith("gọi tư vấn theo ngành"):
        return _prepend_icon(s, "📞", ("☎️", "☎"))
    if low.startswith("website:"):
        return _prepend_icon(s, "🌐")
    if low.startswith("email:"):
        return _prepend_icon(s, "📧", ("✉️", "✉"))
    if low.startswith("hotline:"):
        return _prepend_icon(s, "📞", ("☎️", "☎"))
    if low.startswith("bạn cần bảng model"):
        return _prepend_icon(s, "📩")
    return s


def apply_template_icons(html_text: str) -> str:
    """Chèn icon đầu mục (h1/h2) và icon ở các dòng liên hệ cho ĐÚNG template.

    Chạy TRƯỚC linkify_domains/insert_title_links. Nếu AI đã tự viết icon thì giữ nguyên.
    """
    if not html_text:
        return html_text
    parts = re.split(r"(<[^>]+>)", html_text)
    out: list[str] = []
    open_head: list[dict] = []      # heading đang mở
    for part in parts:
        if part.startswith("<"):
            m = re.match(r"^<h([1-6])\b", part, re.I)
            if m:
                open_head.append({"pos": len(out), "level": int(m.group(1)),
                                  "text": [], "first": None})
                out.append(part)
                continue
            if re.match(r"^</h[1-6]", part, re.I) and open_head:
                info = open_head.pop()
                inner = "".join(info["text"]).strip()
                # CHỈ thẻ <h2> của các mục mới có icon (h1/h3/h4/h5/h6: không icon)
                icon = _section_icon(inner) if info["level"] == 2 else ""
                idx = info["first"]
                if idx is not None:
                    old, rest = split_leading_icon(out[idx])
                    if icon:
                        # thay icon cũ (nếu AI viết sai) bằng icon ĐÚNG của template
                        out[idx] = f"{icon} {rest}" if rest.strip() else f"{icon} "
                    elif old:
                        out[idx] = rest          # xoá icon ở h1/h3/h4/h5/h6
                elif icon:
                    out.insert(info["pos"] + 1, f"{icon} ")
                out.append(part)
                continue
            out.append(part)
            continue
        if open_head:
            if open_head[-1]["first"] is None and part.strip():
                open_head[-1]["first"] = len(out)
            open_head[-1]["text"].append(part)
        out.append(_decorate_line(part))
    return "".join(out)


def _section_re(name: str) -> re.Pattern:
    """Regex linh hoạt cho tên mục: bỏ dấu câu cuối, cho phép “&”/“và”,
    gạch “-”/“–”/“—” và khoảng trắng (kể cả xuống dòng)."""
    toks = re.split(r"\s+", str(name or "").strip())
    parts: list[str] = []
    for t in toks:
        t = t.strip("?:.,;!()")
        if not t:
            continue
        if t in ("&", "và"):
            parts.append(r"(?:&amp;|&|và)")
        elif t in ("-", "–", "—"):
            parts.append(r"(?:&ndash;|&mdash;|[-–—])")
        else:
            parts.append(re.escape(t))
    if not parts:
        return re.compile(r"(?!)")
    # giữa các từ cho phép khoảng trắng + dấu câu (vd "FAQ (5 câu)")
    return re.compile(r"[\s\W_]*".join(parts), re.I)


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
    sec_res = [_section_re(x) for x in (sections or DEFAULT_SECTIONS) if str(x).strip()]

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
            href = ""
            # tìm TÊN MỤC CHUẨN trong tiêu đề (linh hoạt &/và, -/–/—, dấu câu)
            hit = None
            for _re_sec in sec_res:
                mm = _re_sec.search(text)
                if mm:
                    hit = mm
                    break
            if heading_seen == 1:
                href = _norm_url(site_url) if site_url else ""
            elif hit:
                href = next((l for l in pending if l not in used), "")
            if href:
                # bọc TOÀN BỘ chữ còn lại SAU tên mục (chỉ khi phần đuôi có nghĩa;
                # nếu đuôi chỉ là dấu câu như ")" thì bọc CẢ tiêu đề)
                tail_probe = text[hit.end():].strip() if hit is not None else ""
                if tail_probe and len(tail_probe) >= 3 and re.search(r"\w", tail_probe):
                    tail_raw = text[hit.end():]
                    tail = tail_raw.strip()
                    sep = " " if tail_raw[:1].isspace() else ""
                    text = f'{text[:hit.end()]}{sep}<a href="{_norm_url(href)}">{tail}</a>'
                else:
                    # không có chữ sau tên mục (hoặc không phải tiêu đề mục chuẩn)
                    # -> bọc cả tiêu đề (giữ icon đầu mục NẰM NGOÀI thẻ <a>)
                    lead, rest = split_leading_icon(text)
                    text = f'{lead}<a href="{_norm_url(href)}">{rest.strip()}</a>'
                used.add(href)
        out.append(text)
        i += 1
    return "".join(out)


# Những cụm từ cho thấy đoạn văn chỉ là NHÃN/ghi chú (không phải nội dung bài)
_NOTE_WORDS = (
    "nguồn tham chiếu", "tham chiếu", "tham khảo", "ghi chú", "lưu ý", "chú thích",
    "dưới đây là", "sau đây là", "nội dung bài viết", "thông tin seo", "html",
)


def _is_label_text(text: str) -> bool:
    """True nếu đoạn này chỉ là nhãn/ghi chú (ngắn hoặc chứa từ khoá ghi chú)."""
    s = re.sub(r"<[^>]+>", " ", str(text or ""))
    s = re.sub(r"[*_`#>\-•·▪◦‣]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return True
    if len(s) <= 25 and len(s.split()) <= 3 and not re.search(r"[.!?]$", s):
        return True          # nhãn ngắn: "HTML", "Nội dung:"
    low = s.lower()
    return any(w in low for w in _NOTE_WORDS)


def _strip_leading_junk(t: str) -> str:
    """Bỏ nhãn/ghi chú ở ĐẦU nội dung (vd "Nguồn tham chiếu: …", "HTML")."""
    m = re.search(r"<[a-zA-Z][^>]*>", t)
    if m and m.start() > 0 and _is_label_text(t[: m.start()]):
        t = t[m.start():]
    for _ in range(4):
        m = re.match(r"\s*<(p|div|span|strong|em)\b[^>]*>([\s\S]*?)</\1>\s*", t, re.I)
        if not m or not _is_label_text(m.group(2)):
            break
        t = t[m.end():]
    return t.lstrip()


def _strip_trailing_junk(t: str) -> str:
    """Bỏ khối JSON / nhãn ở CUỐI nội dung (vd "Thông tin SEO", "2) JSON SEO:")."""
    for _ in range(6):
        new = re.sub(r"\s*```\s*json\s*[\s\S]*$", "", t, flags=re.I)
        new = re.sub(r"\s*\{\s*[\"']?(?:title|focus_keyword|description|tags)[\s\S]*$",
                     "", new, flags=re.I)
        new = re.sub(r"\s*```[a-zA-Z]*\s*$", "", new)
        m = re.search(r"(\n|^)([^<\n]{1,120})$", new)
        if m:
            chunk = m.group(2).strip()
            low = chunk.lower()
            if (not chunk or chunk.endswith((":", "："))
                    or any(w in low for w in ("json", "seo", "html", "thông tin", "nội dung",
                                              "ghi chú", "lưu ý", "trên đây", "dưới đây"))):
                new = new[: m.start()].rstrip()
        if new == t:
            break
        t = new
    return t.rstrip()


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

    # 3b) dọn rác ở ĐẦU và CUỐI (nhãn "HTML", "Nguồn tham chiếu…", "Thông tin SEO", khối JSON)
    t = _strip_trailing_junk(t)
    t = _strip_leading_junk(t)

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
            seo["description"] = normalize_description(str(seo.get("description", "")))
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
    value = _call_ai(store, full, short, log).strip()
    if field == "description":
        value = normalize_description(value)
    return value


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
