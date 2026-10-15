"""Tạo nội dung bằng ChatGPT qua trình duyệt riêng của phần mềm (miễn phí)."""
from __future__ import annotations

import json
import re
import time

from .providers import AIError

CHATGPT_URL = "https://chatgpt.com/"

# Ô nhập tin nhắn (ChatGPT đổi giao diện thường xuyên nên thử nhiều kiểu)
COMPOSER_SELECTORS = [
    "#prompt-textarea",
    "div[contenteditable='true']#prompt-textarea",
    "div.ProseMirror[contenteditable='true']",
    "div[contenteditable='true']",
    "textarea[data-id]",
    "form textarea",
]

LOGIN_HINT = (
    "Chưa đăng nhập ChatGPT. Vào Cấu hình → AI nội dung → ChatGPT → "
    "bấm “Đăng nhập ChatGPT” rồi đăng nhập, sau đó thử lại."
)
NEED_LOGIN_MARKERS = ("log in", "sign up", "đăng nhập", "đăng ký")

LIMIT_MARKERS = (
    "reached the limit",
    "usage limit",
    "chat paused",
    "limit will reset",
    "you've reached",
    "limit for chats",
    "resets at",
    "hết lượt",
    "giới hạn",
    "tạm dừng",
)

LIMIT_MSG = (
    "ChatGPT BỊ GIỚI HẠN (đã hết lượt dùng miễn phí). "
    "Hãy chờ tới khi lượt được làm mới, hoặc đổi sang provider khác "
    "(Gemini/DeepSeek…) trong Cấu hình → AI nội dung."
)

_REPLY_JS = r"""() => {
  const sels = ['[data-message-author-role="assistant"]','[class*="MarkdownRoot"]',
                '[class*="DilResponseRoot"]','[class*="assistant-message"]',
                '.prose','[class*="prose"]'];
  const set = new Set();
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) set.add(el);
  }
  const arr = [...set].filter(el => {
    const t = (el.innerText || '').trim();
    if (!t) return false;
    if (el.closest('[class*="user-message"]')) return false;
    if (el.matches('[class*="user-message"]')) return false;
    return true;
  });
  if (!arr.length) return '';
  arr.sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
  return arr[arr.length - 1].innerText || '';
}"""


# --------------------------------------------------------------------------- #
# Tiện ích
# --------------------------------------------------------------------------- #
def _composer(page):
    for sel in COMPOSER_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _wait_composer(page, timeout: float = 25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        box = _composer(page)
        if box is not None:
            return box
        try:
            page.wait_for_timeout(500)
        except Exception:
            return None
    return None


def _dismiss_modals(page) -> None:
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception:
            break
    for name in ("Dismiss", "Close", "Đóng", "Stay with free plan", "Stay on free"):
        try:
            btn = page.get_by_role("button", name=name)
            if btn.count():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(300)
        except Exception:
            continue


def _looks_logged_out(page) -> bool:
    try:
        body = page.inner_text("body")[:500].lower()
    except Exception:
        return False
    return any(m in body for m in NEED_LOGIN_MARKERS)


def _is_placeholder(value) -> bool:
    s = str(value or "").strip()
    if not s:
        return True
    return all(ch in ".-_…~ " for ch in s)


def _looks_template(html: str) -> bool:
    text = re.sub(r"<[^>]*>", " ", str(html or ""))
    return _is_placeholder(text)


def _same_as_prompt(text: str, prompt: str) -> bool:
    if not prompt:
        return False
    a = " ".join((text or "").split()).lower()
    b = " ".join(prompt.split()).lower()
    if not a or not b:
        return False
    if a == b:
        return True
    head = min(60, len(a), len(b))
    return head > 20 and a[:head] == b[:head]


def _reply_text(page, prompt: str = "") -> str:
    txt = ""
    try:
        txt = (page.evaluate(_REPLY_JS) or "").strip()
    except Exception:
        txt = ""
    if not txt:
        try:
            body = page.inner_text("body")
            idx = body.rfind("ChatGPT said:")
            if idx >= 0:
                txt = body[idx + len("ChatGPT said:"):].strip()
        except Exception:
            txt = ""
    if txt and _same_as_prompt(txt, prompt):
        return ""
    return txt


def _limit_reached(page, extra_text: str = "") -> str:
    body = ""
    try:
        body = page.inner_text("body").lower()
    except Exception:
        body = ""
    body += " " + (extra_text or "").lower()
    for marker in LIMIT_MARKERS:
        if marker in body:
            i = body.find(marker)
            return body[max(0, i - 80): i + 120].replace("\n", " ").strip()
    return ""


def _try_extract_json(text: str) -> dict | None:
    """Tìm JSON kết quả THẬT (bỏ qua JSON mẫu)."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 2:
            t = parts[1]
            if t.lower().lstrip().startswith("json"):
                t = t.lstrip()[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(t[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    content = data.get("content_html", "")
    if _is_placeholder(data.get("title")):
        return None
    if content and (_is_placeholder(content) or _looks_template(content)):
        return None
    return data


# --------------------------------------------------------------------------- #
# Mở trang + gửi / chờ trả lời
# --------------------------------------------------------------------------- #
def _open_page(br, project_url: str, log=None):
    if log:
        log("Đang mở ChatGPT…")
    page = br.open()
    target = project_url if project_url.startswith("http") else CHATGPT_URL
    page.goto(target, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)
    _dismiss_modals(page)
    if _wait_composer(page, 25) is None:
        if _looks_logged_out(page):
            raise AIError(LOGIN_HINT)
        try:
            title = page.title()
            body = re.sub(r"\s+", " ", page.inner_text("body"))[:200]
        except Exception:
            title, body = "", ""
        raise AIError(
            f"Không tìm thấy ô nhập tin nhắn của ChatGPT (tiêu đề: {title}; nội dung: {body}). "
            "Hãy mở lại ChatGPT trên trình duyệt của phần mềm rồi thử lại."
        )
    return page


def _send(page, text: str) -> None:
    box = _composer(page) or _wait_composer(page, 15)
    if box is None:
        raise AIError("Không tìm thấy ô nhập tin nhắn để gửi.")
    try:
        box.click(timeout=5000)
    except Exception:
        pass
    try:
        box.fill(text)
    except Exception:
        page.keyboard.type(text[:4000])
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")


def _wait_reply(page, prompt: str, timeout: int = 300, require_json: bool = False) -> str:
    deadline = time.time() + timeout
    last = ""
    stable = 0
    result = ""
    while time.time() < deadline:
        page.wait_for_timeout(1500)
        text = _reply_text(page, prompt)
        if require_json:
            data = _try_extract_json(text)
            if data is not None:
                return json.dumps(data, ensure_ascii=False)
        elif text and text == last and len(text) > 20:
            stable += 1
            if stable >= 2:
                return text
        if text != last:
            stable = 0
            last = text
        if _limit_reached(page, last):
            raise AIError(LIMIT_MSG)
    if require_json:
        raise AIError(
            "ChatGPT không trả về nội dung thật (chỉ trả lại mẫu). "
            "Nếu tài khoản đang bị giới hạn lượt, hãy chờ lượt làm mới "
            "hoặc đổi provider khác trong Cấu hình → AI nội dung."
        )
    raise AIError("ChatGPT không trả về nội dung (quá thời gian chờ).")


# --------------------------------------------------------------------------- #
# API chính
# --------------------------------------------------------------------------- #
def generate_with_chatgpt(pcfg: dict, prompt: str, log=None, timeout: int = 300,
                          require_json: bool = False) -> str:
    """1 lượt: gửi prompt, chờ trả lời."""
    from ..wp import WPBrowser

    project_url = (pcfg or {}).get("project_url", "") or ""
    br = WPBrowser(headless=False, site_id="chatgpt")
    try:
        page = _open_page(br, project_url, log)
        if log:
            log("Đang gửi yêu cầu cho ChatGPT…")
        _send(page, prompt)
        return _wait_reply(page, prompt, timeout, require_json)
    finally:
        try:
            br.close()
        except Exception:
            pass


def generate_two_step(pcfg: dict, content_prompt: str, seo_prompt: str,
                      log=None, timeout: int = 420) -> tuple[str, str]:
    """2 bước trong CÙNG 1 cửa sổ / đoạn chat: viết nội dung → tạo SEO.

    Trả về (nội dung bài viết, JSON SEO).
    """
    from ..wp import WPBrowser

    project_url = (pcfg or {}).get("project_url", "") or ""
    br = WPBrowser(headless=False, site_id="chatgpt")
    try:
        page = _open_page(br, project_url, log)
        if log:
            log("Bước 1/2 — gửi yêu cầu viết nội dung (rule_content)…")
        _send(page, content_prompt)
        raw = _wait_reply(page, content_prompt, timeout, require_json=False)

        if log:
            log("Bước 2/2 — gửi yêu cầu SEO (rule_seo) trong cùng đoạn chat…")
        _send(page, seo_prompt)
        seo = _wait_reply(page, seo_prompt, timeout, require_json=True)
        return raw, seo
    finally:
        try:
            br.close()
        except Exception:
            pass
