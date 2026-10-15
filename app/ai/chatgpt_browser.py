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
    """Ô nhập tin nhắn: ưu tiên các selector đặc trưng, cuối cùng lấy contenteditable CUỐI."""
    for sel in (
        "#prompt-textarea",
        "div.ProseMirror[contenteditable='true']",
        "textarea[data-id]",
        "form textarea",
    ):
        try:
            loc = page.locator(sel).last
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    try:
        loc = page.locator("div[contenteditable='true']")
        n = loc.count()
        for i in range(n - 1, -1, -1):     # ô nhập nằm dưới cùng
            el = loc.nth(i)
            if el.is_visible():
                return el
    except Exception:
        pass
    return None


def _composer_text(page) -> str:
    try:
        return (page.evaluate(
            """() => {
            const els = [...document.querySelectorAll('#prompt-textarea, div[contenteditable="true"], textarea')];
            const el = els.filter(e => e.offsetParent !== null).pop();
            if (!el) return '';
            return (el.value !== undefined ? el.value : el.innerText) || '';
        }"""
        ) or "").strip()
    except Exception:
        return ""


def _click_send(page) -> bool:
    """Bấm nút Gửi nếu có."""
    for name in ("Send", "Gửi", "Send message", "Send prompt"):
        try:
            btn = page.get_by_role("button", name=name)
            if btn.count():
                b = btn.last
                if b.is_visible() and b.is_enabled():
                    b.click(timeout=2500)
                    return True
        except Exception:
            continue
    try:
        btn = page.locator('[data-testid="send-button"], button[aria-label*="Send"], button[aria-label*="Gửi"]')
        if btn.count():
            b = btn.last
            if b.is_visible() and b.is_enabled():
                b.click(timeout=2500)
                return True
    except Exception:
        pass
    return False


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
    page.wait_for_timeout(500)

    # Gửi (thử nút Gửi, nếu không có thì Enter) + kiểm tra đã gửi
    for _ in range(4):
        _click_send(page)
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass
        page.wait_for_timeout(900)
        if not _composer_text(page):
            return
    raise AIError(
        "Không gửi được tin nhắn cho ChatGPT (ô nhập vẫn còn nội dung). "
        "Thử lại hoặc gửi bằng tay trên cửa sổ trình duyệt."
    )


def _find_json_block(text: str):
    """Tìm khối JSON đầu tiên có 'title'. Trả về (data, start, end)."""
    if not text:
        return None, -1, -1
    n = len(text)
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        for j in range(i, n):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[i:j + 1])
                    except (json.JSONDecodeError, ValueError):
                        data = None
                    if isinstance(data, dict) and str(data.get("title", "")).strip() \
                            and not _is_placeholder(data.get("title")):
                        return data, i, j
                    break
    return None, -1, -1


def split_reply(text: str) -> tuple[dict | None, str]:
    """Tách câu trả lời thành (JSON SEO, nội dung bài viết)."""
    data, _i, j = _find_json_block(text or "")
    if data is None:
        return None, (text or "").strip()
    content = (text or "")[j + 1:].strip()
    # bỏ dấu ``` thừa ở hai đầu nội dung
    content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
    content = re.sub(r"\s*```$", "", content).strip()
    return data, content


def _wait_reply_full(page, prompt: str, timeout: int = 420) -> str:
    """Chờ tới khi câu trả lời có đủ JSON SEO + nội dung và đã ổn định."""
    deadline = time.time() + timeout
    last = ""
    stable = 0
    while time.time() < deadline:
        page.wait_for_timeout(1500)
        text = _reply_text(page, prompt)
        data, i, j = _find_json_block(text)
        has_both = data is not None and (len(text) - (j - i)) > 150
        if has_both and text == last:
            stable += 1
            if stable >= 2:
                return text
        else:
            stable = 0
        last = text
        if _limit_reached(page, last):
            raise AIError(LIMIT_MSG)
    data, _i, _j = _find_json_block(last)
    if data is not None:
        return last
    raise AIError(
        "ChatGPT không trả về đủ JSON SEO + nội dung. Thử lại hoặc đổi provider khác."
    )


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


def generate_combined(pcfg: dict, prompt: str, log=None, timeout: int = 420) -> str:
    """1 tin nhắn: trả về JSON SEO ở đầu + nội dung bài viết phía sau."""
    from ..wp import WPBrowser

    project_url = (pcfg or {}).get("project_url", "") or ""
    br = WPBrowser(headless=False, site_id="chatgpt")
    try:
        page = _open_page(br, project_url, log)
        if log:
            log("Đang gửi yêu cầu cho ChatGPT (nội dung + SEO)…")
        _send(page, prompt)
        return _wait_reply_full(page, prompt, timeout)
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
