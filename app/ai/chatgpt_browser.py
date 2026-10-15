"""Tạo nội dung bằng ChatGPT qua trình duyệt riêng của phần mềm (miễn phí)."""
from __future__ import annotations

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


def _last_answer(page) -> str:
    try:
        loc = page.locator('[data-message-author-role="assistant"]')
        n = loc.count()
        if n == 0:
            return ""
        return (loc.nth(n - 1).inner_text() or "").strip()
    except Exception:
        return ""


def generate_with_chatgpt(pcfg: dict, prompt: str, log=None, timeout: int = 300) -> str:
    """Mở ChatGPT bằng trình duyệt riêng, gửi prompt, trả về câu trả lời."""
    from ..wp import WPBrowser

    project_url = (pcfg or {}).get("project_url", "") or ""
    br = WPBrowser(headless=False, site_id="chatgpt")
    try:
        if log:
            log("Đang mở ChatGPT…")
        page = br.open()
        page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
        _wait_composer(page, 8)
        _dismiss_modals(page)

        if project_url and project_url.startswith("http"):
            if log:
                log("Đang mở Project đã cấu hình…")
            try:
                page.goto(project_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                raise AIError(f"Không mở được URL Project: {exc}") from exc
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

        # Chờ câu trả lời ổn định
        deadline = time.time() + timeout
        last = ""
        stable = 0
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            text = _last_answer(page)
            if text and text == last and len(text) > 20:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
                last = text
        if not last:
            raise AIError("ChatGPT không trả về nội dung (quá thời gian chờ).")
        if log:
            log("ChatGPT đã trả lời.")
        return last
    finally:
        try:
            br.close()
        except Exception:
            pass
