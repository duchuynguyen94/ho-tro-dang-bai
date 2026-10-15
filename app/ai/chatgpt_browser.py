"""Tạo nội dung bằng ChatGPT qua trình duyệt riêng của phần mềm (miễn phí)."""
from __future__ import annotations

import time

from .providers import AIError

COMPOSER_SELECTORS = [
    "#prompt-textarea",
    "div[contenteditable='true'][id='prompt-textarea']",
    "textarea[data-id]",
    "form textarea",
    "div[contenteditable='true']",
]

LOGIN_HINT = (
    "Chưa đăng nhập ChatGPT. Vào Cấu hình → AI nội dung → ChatGPT → "
    "bấm “Đăng nhập ChatGPT” rồi đăng nhập, sau đó thử lại."
)


def _composer(page):
    for sel in COMPOSER_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _last_answer(page) -> str:
    try:
        loc = page.locator('[data-message-author-role="assistant"]')
        n = loc.count()
        if n == 0:
            return ""
        return (loc.nth(n - 1).inner_text() or "").strip()
    except Exception:
        return ""


def _open_project(page, project: str, log=None) -> None:
    """Thử mở đúng Project theo tên (best-effort)."""
    if not project:
        return
    try:
        btn = page.get_by_role("button", name="Projects")
        if btn.count():
            btn.first.click(timeout=4000)
            page.wait_for_timeout(800)
    except Exception:
        pass
    try:
        item = page.get_by_text(project, exact=False).first
        item.click(timeout=6000)
        page.wait_for_timeout(1500)
        if log:
            log(f"Đã mở Project “{project}”.")
        return
    except Exception:
        if log:
            log(f"Không mở được Project “{project}” — dùng ChatGPT thường.")


def generate_with_chatgpt(pcfg: dict, prompt: str, log=None, timeout: int = 240) -> str:
    """Mở ChatGPT bằng trình duyệt riêng, gửi prompt, trả về câu trả lời."""
    from ..wp import WPBrowser

    project = (pcfg or {}).get("project", "") or ""
    br = WPBrowser(headless=False, site_id="chatgpt")
    try:
        if log:
            log("Đang mở ChatGPT…")
        page = br.open()
        page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        box = _composer(page)
        if box is None:
            raise AIError(LOGIN_HINT)

        if project:
            _open_project(page, project, log)

        box = _composer(page) or box
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
        page.wait_for_timeout(300)
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
