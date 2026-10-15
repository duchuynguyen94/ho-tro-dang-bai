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
    """Đóng popup (ví dụ 'Requires upgrade') nếu có."""
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


_REPLY_JS = r"""() => {
  const sels = ['[data-message-author-role="assistant"]','[class*="MarkdownRoot"]',
                '[class*="DilResponseRoot"]','[class*="assistant-message"]',
                '.prose','[class*="prose"]'];
  const set = new Set();
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) set.add(el);
  }
  const arr = [...set].filter(el => (el.innerText || '').trim().length > 0);
  if (!arr.length) return '';
  arr.sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1);
  return arr[arr.length - 1].innerText || '';
}"""

LIMIT_MARKERS = (
    "reached the limit",
    "usage limit",
    "chat paused",
    "hết lượt",
    "limit will reset",
)


def _reply_text(page) -> str:
    """Lấy nội dung tin nhắn trả lời mới nhất của ChatGPT."""
    try:
        txt = page.evaluate(_REPLY_JS)
        if txt and txt.strip():
            return txt.strip()
    except Exception:
        pass
    # dự phòng: lấy phần sau "ChatGPT said:"
    try:
        body = page.inner_text("body")
        idx = body.rfind("ChatGPT said:")
        if idx >= 0:
            return body[idx + len("ChatGPT said:"):].strip()
    except Exception:
        pass
    return ""


def _limit_reached(page) -> str:
    """Kiểm tra ChatGPT có báo hết lượt miễn phí không."""
    try:
        body = page.inner_text("body").lower()
    except Exception:
        return ""
    for marker in LIMIT_MARKERS:
        if marker in body:
            i = body.find(marker)
            return body[max(0, i - 80): i + 120].replace("\n", " ").strip()
    return ""


def _try_extract_json(text: str) -> dict | None:
    """Tìm JSON kết quả trong câu trả lời."""
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
    content = str(data.get("content_html", "")).strip()
    if not data.get("title") and not content:
        return None
    if content.strip(". ") == "" or content == "...":
        return None
    return data


def generate_with_chatgpt(pcfg: dict, prompt: str, log=None, timeout: int = 300) -> str:
    """Mở ChatGPT bằng trình duyệt riêng, gửi prompt, trả về câu trả lời."""
    from ..wp import WPBrowser

    project_url = (pcfg or {}).get("project_url", "") or ""
    br = WPBrowser(headless=False, site_id="chatgpt")
    try:
        if log:
            log("Đang mở ChatGPT…")
        page = br.open()
        # Mở THẲNG Project nếu đã cấu hình URL, không cần qua trang chủ
        target = project_url if project_url.startswith("http") else CHATGPT_URL
        page.goto(target, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)
        _dismiss_modals(page)

        box = _wait_composer(page, 25)
        if box is None:
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

        if log:
            log("Đang gửi yêu cầu cho ChatGPT…")
        try:
            box.click(timeout=5000)
        except Exception:
            pass
        try:
            box.fill(prompt)
        except Exception:
            page.keyboard.type(prompt[:4000])
        page.wait_for_timeout(400)
        page.keyboard.press("Enter")

        # Chờ câu trả lời: nhận diện ngay khi thấy JSON kết quả
        deadline = time.time() + timeout
        last = ""
        stable = 0
        result_text = ""
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            text = _reply_text(page)
            data = _try_extract_json(text)
            if data is not None:
                result_text = json.dumps(data, ensure_ascii=False)
                if log:
                    log("Đã nhận kết quả từ ChatGPT.")
                break
            if _limit_reached(page):
                raise AIError(
                    "ChatGPT đã hết lượt dùng miễn phí. Chờ đến khi lượt được làm mới, "
                    "hoặc chuyển sang provider khác (Gemini/DeepSeek…) trong Cấu hình → AI nội dung."
                )
            if text and text == last and len(text) > 20:
                stable += 1
                if stable >= 2:
                    result_text = text
                    break
            else:
                stable = 0
                last = text
            if log and text:
                log(f"ChatGPT đang viết… ({len(text)} ký tự)")

        if not result_text:
            raise AIError("ChatGPT không trả về nội dung (quá thời gian chờ).")
        return result_text
    finally:
        try:
            br.close()
        except Exception:
            pass
