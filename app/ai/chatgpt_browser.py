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
    "reached your limit",
    "usage limit",
    "usage cap",
    "chat paused",
    "limit will reset",
    "you've reached",
    "limit for chats",
    "resets at",
    "out of messages",
    "đã đạt giới hạn",
    "hết lượt",
    "hạn mức sử dụng",
    "tạm dừng cuộc trò chuyện",
    "giới hạn tin nhắn",
)

LIMIT_MSG = (
    "ChatGPT BỊ GIỚI HẠN (đã hết lượt dùng miễn phí). "
    "Hãy chờ tới khi lượt được làm mới, hoặc đổi sang provider khác "
    "(Gemini/DeepSeek…) trong Cấu hình → AI nội dung."
)

_REPLY_JS = r"""() => {
  const clean = (t) => (t || '').trim();
  const notUser = (el) => {
    if (el.matches('[data-message-author-role="user"]')) return false;
    if (el.closest('[data-message-author-role="user"]')) return false;
    if (el.matches('[class*="user-message"]')) return false;
    if (el.closest('[class*="user-message"]')) return false;
    return true;
  };
  // 1) phần tử mang role assistant (ổn định nhất)
  const asst = [...document.querySelectorAll('[data-message-author-role="assistant"]')]
      .filter(el => clean(el.innerText));
  if (asst.length) return clean(asst[asst.length - 1].innerText);
  // 2) lượt hội thoại (article / conversation-turn) không phải của người dùng
  const turns = [...document.querySelectorAll('article, [data-testid^="conversation-turn"]')]
      .filter(el => clean(el.innerText) && notUser(el));
  if (turns.length) {
    const outer = turns.filter(el => !turns.some(o => o !== el && el.contains(o)));
    const pick = outer.length ? outer : turns;
    return clean(pick[pick.length - 1].innerText);
  }
  // 3) các selector cũ (giao diện đổi tên)
  const sels = ['[class*="MarkdownRoot"]','[class*="DilResponseRoot"]',
                '[class*="assistant-message"]','.prose','[class*="prose"]'];
  for (const s of sels) {
    const els = [...document.querySelectorAll(s)].filter(el => clean(el.innerText) && notUser(el));
    if (!els.length) continue;
    const outer = els.filter(el => !els.some(o => o !== el && el.contains(o)));
    const pick = outer.length ? outer : els;
    return clean(pick[pick.length - 1].innerText);
  }
  return '';
}"""

# Nút "Dừng tạo" của ChatGPT: còn hiện = câu trả lời đang được viết
_STOP_SELECTORS = (
    '[data-testid="stop-button"]',
    '[aria-label*="Stop generating"]',
    '[aria-label*="Stop streaming"]',
    'button[aria-label*="Stop"]',
    'button[aria-label*="Dừng"]',
)


def _is_streaming(page) -> bool:
    for sel in _STOP_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                return True
        except Exception:
            continue
    return False


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


def _wait_composer(page, timeout: float = 25.0, should_stop=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if should_stop and should_stop():
            raise AIError("Đã dừng theo yêu cầu.")
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
        # dự phòng: đọc trực tiếp phần tử cuối bằng locator
        for sel in ('[data-message-author-role="assistant"]', "article",
                    '[data-testid^="conversation-turn"]'):
            try:
                loc = page.locator(sel)
                n = loc.count()
            except Exception:
                continue
            for i in range(n - 1, -1, -1):
                try:
                    t = (loc.nth(i).inner_text() or "").strip()
                except Exception:
                    continue
                if t:
                    txt = t
                    break
            if txt:
                break
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


_LIMIT_UI_JS = r"""() => {
  const sels = ['[role="alert"]', '[data-testid*="limit"]', '[class*="limit"]',
                '[class*="banner"]', '[class*="toast"]', '[class*="notice"]'];
  const out = [];
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) {
      const t = (el.innerText || '').trim();
      if (t) out.push(t);
    }
  }
  return out.join('\n');
}"""


def _limit_reached(page, extra_text: str = "") -> str:
    """Phát hiện ChatGPT hết lượt.

    CHỈ soi THÔNG BÁO CỦA GIAO DIỆN (banner/alert/limit) — KHÔNG quét nội dung
    bài viết, vì bài viết tiếng Việt có thể chứa các từ như "giới hạn".
    """
    texts: list[str] = []
    try:
        texts.append(page.evaluate(_LIMIT_UI_JS) or "")
    except Exception:
        pass
    if extra_text:
        texts.append(extra_text)
    low = "\n".join(texts).lower()
    for marker in LIMIT_MARKERS:
        if marker in low:
            i = low.find(marker)
            return low[max(0, i - 80): i + 120].replace("\n", " ").strip()
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
def _open_page(br, project_url: str, log=None, should_stop=None):
    if log:
        log("Đang mở ChatGPT…")
    if should_stop and should_stop():
        raise AIError("Đã dừng theo yêu cầu.")
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
    """Tìm khối JSON đầu tiên có 'title' (dùng JSON decoder chuẩn để không lệch)."""
    if not text:
        return None, -1, -1
    decoder = json.JSONDecoder()
    idx = 0
    n = len(text)
    while idx < n:
        i = text.find("{", idx)
        if i < 0:
            return None, -1, -1
        try:
            data, end = decoder.raw_decode(text, i)
        except (json.JSONDecodeError, ValueError):
            idx = i + 1
            continue
        if isinstance(data, dict) and str(data.get("title", "")).strip() \
                and not _is_placeholder(data.get("title")):
            return data, i, end
        idx = i + 1
    return None, -1, -1


def split_reply(text: str) -> tuple[dict | None, str]:
    """Tách câu trả lời thành (JSON SEO, nội dung bài viết).

    Chấp nhận JSON ở đầu HOẶC ở cuối; phần còn lại (bỏ khối JSON) là nội dung.
    """
    raw = text or ""
    data, i, j = _find_json_block(raw)
    if data is None:
        return None, _strip_fences(raw)

    before = raw[:i]
    after = raw[j:]
    content = _strip_fences(before + "\n" + after)
    if not content:
        content = _strip_fences(after or before)
    return data, content


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _wait_reply_full(page, prompt: str, timeout: int = 420, should_stop=None,
                     log=None) -> str:
    """Chờ tới khi câu trả lời có đủ JSON + nội dung và ChatGPT viết xong."""
    deadline = time.time() + timeout
    last = ""
    stable = 0
    best = ""
    next_log = time.time() + 6.0
    while time.time() < deadline:
        if should_stop and should_stop():
            raise AIError("Đã dừng theo yêu cầu.")
        page.wait_for_timeout(1500)
        text = _reply_text(page, prompt)
        if log and time.time() >= next_log:
            next_log = time.time() + 6.0
            left = max(0, int(deadline - time.time()))
            log(f"ChatGPT đang viết… đã nhận {len(text)} ký tự (còn tối đa {left}s)."
                if text else f"Đang chờ ChatGPT bắt đầu trả lời… (còn tối đa {left}s).")
        data, i, j = _find_json_block(text)
        has_both = data is not None and (len(text) - (j - i)) > 150
        if has_both and len(text) > len(best):
            best = text
        streaming = _is_streaming(page)
        if has_both and (not streaming or text == last):
            stable += 1
            if not streaming or stable >= 2:
                return text
        else:
            stable = 0
        last = text
        if _limit_reached(page):      # chỉ soi thông báo giao diện, KHÔNG quét nội dung trả lời
            raise AIError(LIMIT_MSG)
    # hết thời gian: nếu từng có JSON thì trả về bản dài nhất để bước sau tự xử lý
    if best:
        return best
    data, _i, _j = _find_json_block(last)
    if data is not None:
        return last
    if last.strip():
        return last
    raise AIError(
        "ChatGPT không trả về đủ JSON SEO + nội dung. Thử lại hoặc đổi provider khác."
    )


def _wait_reply(page, prompt: str, timeout: int = 300, require_json: bool = False,
                should_stop=None, log=None) -> str:
    deadline = time.time() + timeout
    last = ""
    stable = 0
    result = ""
    next_log = time.time() + 6.0
    while time.time() < deadline:
        if should_stop and should_stop():
            raise AIError("Đã dừng theo yêu cầu.")
        page.wait_for_timeout(1500)
        text = _reply_text(page, prompt)
        if log and time.time() >= next_log:
            next_log = time.time() + 6.0
            left = max(0, int(deadline - time.time()))
            log(f"ChatGPT đang trả lời… đã nhận {len(text)} ký tự (còn tối đa {left}s)."
                if text else f"Đang chờ ChatGPT trả lời… (còn tối đa {left}s).")
        streaming = _is_streaming(page)
        if require_json:
            data = _try_extract_json(text)
            if data is not None and not streaming:
                return json.dumps(data, ensure_ascii=False)
        elif text and text == last and (not streaming or stable >= 1):
            stable += 1
            if not streaming or stable >= 2:
                return text
        if text != last:
            stable = 0
            last = text
        if _limit_reached(page):      # chỉ soi thông báo giao diện, KHÔNG quét nội dung trả lời
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
                          require_json: bool = False, show_browser: bool = True) -> str:
    """1 lượt: gửi prompt, chờ trả lời. show_browser=False -> chạy ẩn (có tự thử lại khi lỗi)."""
    from ..wp import WPBrowser

    project_url = (pcfg or {}).get("project_url", "") or ""

    def _run(headless: bool) -> str:
        br = WPBrowser(headless=headless, site_id="chatgpt")
        try:
            page = _open_page(br, project_url, log)
            if log:
                log("Đang gửi yêu cầu cho ChatGPT…")
            _send(page, prompt)
            return _wait_reply(page, prompt, timeout, require_json, log=log)
        finally:
            try:
                br.close()
            except Exception:
                pass

    try:
        return _run(not show_browser)
    except AIError as exc:
        if show_browser or "Đã dừng" in str(exc):
            raise
        if log:
            log("Chế độ ẩn không chạy được — mở cửa sổ Chrome và thử lại…")
        return _run(False)


def _run_combined(pcfg: dict, prompt: str, project_url: str, headless: bool,
                  log=None, timeout: int = 420, should_stop=None) -> str:
    from ..wp import WPBrowser

    br = WPBrowser(headless=headless, site_id="chatgpt")
    try:
        page = _open_page(br, project_url, log, should_stop)
        if log:
            log("Đang gửi yêu cầu cho ChatGPT (nội dung + SEO)…")
        _send(page, prompt)
        return _wait_reply_full(page, prompt, timeout, should_stop, log=log)
    finally:
        try:
            br.close()
        except Exception:
            pass


def generate_combined(pcfg: dict, prompt: str, log=None, timeout: int = 420,
                      should_stop=None) -> str:
    """1 tin nhắn: JSON SEO + nội dung. Có thể chạy ẩn (không hiện cửa sổ)."""
    project_url = (pcfg or {}).get("project_url", "") or ""
    show = bool((pcfg or {}).get("show_browser", False))
    if not show and log:
        log("Đang chạy ChatGPT ở chế độ ẩn (bật “Hiện cửa sổ Chrome” nếu muốn xem).")
    try:
        return _run_combined(pcfg, prompt, project_url, not show, log, timeout, should_stop)
    except AIError as exc:
        if show or "Đã dừng" in str(exc):
            raise
        if log:
            log("Chế độ ẩn không chạy được — mở cửa sổ Chrome và thử lại…")
        return _run_combined(pcfg, prompt, project_url, False, log, timeout, should_stop)


def _unused_generate_combined(pcfg: dict, prompt: str, log=None, timeout: int = 420,
                              should_stop=None) -> str:
    try:
        page = _open_page(br, project_url, log, should_stop)
        if log:
            log("Đang gửi yêu cầu cho ChatGPT (nội dung + SEO)…")
        _send(page, prompt)
        return _wait_reply_full(page, prompt, timeout, should_stop)
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
        raw = _wait_reply(page, content_prompt, timeout, require_json=False, log=log)

        if log:
            log("Bước 2/2 — gửi yêu cầu SEO (rule_seo) trong cùng đoạn chat…")
        _send(page, seo_prompt)
        seo = _wait_reply(page, seo_prompt, timeout, require_json=True, log=log)
        return raw, seo
    finally:
        try:
            br.close()
        except Exception:
            pass
