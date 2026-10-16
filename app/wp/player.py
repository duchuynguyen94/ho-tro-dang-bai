"""Phát lại kịch bản (điền form) trên trang WordPress."""
from __future__ import annotations

import re
import time
from pathlib import Path

from playwright.sync_api import Page

from ..storage.models import Script, ScriptStep

_TOKEN_RE = re.compile(r"\{\{\s*([\w\.]+)\s*\}\}")

# --------------------------------------------------------------------------- #
# Selector dự phòng cho WordPress (Gutenberg / Classic / WooCommerce)
# --------------------------------------------------------------------------- #
TITLE_FALLBACKS = [
    ".editor-post-title__input",
    "h1.wp-block-post-title",
    "[aria-label='Add title']",
    "[aria-label='Thêm tiêu đề']",
    "[aria-label*='title' i]",
    "[aria-label*='tiêu đề' i]",
    "[data-type='core/post-title'] [contenteditable='true']",
    "h1[contenteditable='true']",
    "#title",
    "input[name='post_title']",
]

CONTENT_FALLBACKS = [
    ".block-editor-block-list__layout",
    ".wp-block-post-content",
    "[data-type='core/paragraph']",
    ".editor-styles-wrapper",
    "#content_ifr",
    "#content",
]

EDITOR_READY = ["#wpbody-content", ".block-editor", "#editor", "#post", "#poststuff"]


def render(value: str, ctx: dict) -> str:
    def repl(m):
        return str(ctx.get(m.group(1), m.group(0)))

    return _TOKEN_RE.sub(repl, value or "")


def show_page_notice(page: Page, text: str, ok: bool = True, hold_ms: int = 30000) -> None:
    """Hiện thông báo NGAY TRÊN TRANG web (banner góc phải) để người dùng biết."""
    try:
        page.evaluate(
            """({text, ok, hold}) => {
                const id = 'htdb-notice';
                const old = document.getElementById(id);
                if (old) old.remove();
                const el = document.createElement('div');
                el.id = id;
                el.style.cssText = [
                    'position:fixed', 'z-index:2147483647', 'top:16px', 'right:16px',
                    'max-width:440px', 'padding:14px 18px', 'border-radius:10px',
                    'font:600 14px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif',
                    'color:#fff', 'box-shadow:0 10px 30px rgba(0,0,0,.25)',
                    'white-space:pre-line',
                    'background:' + (ok ? '#16a34a' : '#dc2626'),
                ].join(';');
                el.textContent = text;
                document.body.appendChild(el);
                setTimeout(() => {
                    el.style.transition = 'opacity .6s';
                    el.style.opacity = '0';
                    setTimeout(() => el.remove(), 700);
                }, hold);
            }""",
            {"text": text, "ok": bool(ok), "hold": int(hold_ms)},
        )
    except Exception:
        pass


def make_slug(text: str, max_len: int = 60) -> str:
    """Tạo đường dẫn (slug) từ tiêu đề: bỏ dấu tiếng Việt, thường hoá, nối bằng '-'.

    Tối đa `max_len` ký tự (cắt ở ranh giới từ, không để dấu '-' ở cuối).
    """
    import unicodedata

    s = (text or "").strip().lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if len(s) > max_len:
        cut = s[:max_len]
        if "-" in cut:
            cut = cut[:cut.rfind("-")]
        s = cut.rstrip("-") or s[:max_len].rstrip("-")
    return s


def _selectors(step: ScriptStep) -> list[str]:
    out = []
    for s in [step.selector, *step.selectors]:
        if s and s not in out:
            out.append(s)
    return out


def _fallbacks_for(step: ScriptStep) -> list[str]:
    """Gợi ý thêm selector theo từ khoá trong kịch bản (tiêu đề / nội dung)."""
    text = " ".join([step.selector or "", *(step.selectors or []), step.note or ""]).lower()
    out: list[str] = []
    if "title" in text or "tiêu đề" in text or "tieu de" in text:
        out += TITLE_FALLBACKS
    if ("content" in text or "nội dung" in text or "noi dung" in text
            or "body" in text or "editor" in text):
        out += CONTENT_FALLBACKS
    return out


def _make(page: Page, sel: str):
    if sel.startswith("text="):
        return page.get_by_text(sel[5:].strip('"'), exact=False)
    return page.locator(sel)


def _auto_open_panel(page: Page, el) -> bool:
    """Nếu phần tử nằm trong 1 bảng (metabox) đang THU GỌN -> tự bấm mở bảng đó."""
    try:
        return bool(el.evaluate(
            """el => {
                let node = el;
                while (node && node !== document.body) {
                    const cls = (node.className || '').toString();
                    if (cls.indexOf('postbox') >= 0) {
                        const inside = node.querySelector('.inside');
                        const hiddenInside = inside && getComputedStyle(inside).display === 'none';
                        const closed = cls.indexOf('closed') >= 0 || hiddenInside;
                        const btn = node.querySelector('.handlediv') || node.querySelector('button.handlediv');
                        if (closed && btn) { btn.click(); return true; }
                        return false;
                    }
                    node = node.parentElement;
                }
                return false;
            }"""
        ))
    except Exception:
        return False


def _auto_editor_text_mode(page: Page, el) -> bool:
    """Ô soạn thảo TinyMCE đang bị ẩn (đang ở chế độ Trực quan) -> bấm tab "Mã" của ô đó."""
    try:
        eid = el.get_attribute("id") or ""
        cls = (el.get_attribute("class") or "")
        if not eid or "wp-editor-area" not in cls:
            return False
        tab = page.locator(f"#{eid}-html").first
        if tab.count() and tab.is_visible():
            tab.click(timeout=3000)
            page.wait_for_timeout(500)
            return True
    except Exception:
        pass
    return False


def _locate(page: Page, step: ScriptStep):
    """Tìm phần tử theo selector chính rồi tới các selector dự phòng.

    - Ưu tiên phần tử ĐANG HIỆN (tránh input ẩn của WordPress/Gutenberg).
    - Nếu phần tử bị ẩn do BẢNG THU GỌN -> tự mở bảng rồi dùng lại.
    - Nếu là ô soạn thảo TinyMCE đang ẩn -> tự bấm tab "Mã" rồi dùng lại.
    """
    sels = _selectors(step)
    for extra in _fallbacks_for(step):
        if extra not in sels:
            sels.append(extra)

    last = None
    # 1) phần tử đang hiện
    for sel in sels:
        try:
            loc = _make(page, sel)
            n = min(loc.count(), 10)
            for i in range(n):
                cand = loc.nth(i)
                try:
                    if cand.is_visible():
                        return cand
                except Exception:
                    continue
        except Exception as exc:
            last = exc
    # 2) có tồn tại nhưng đang ẩn -> mở bảng / chuyển ô soạn thảo sang chế độ Mã
    for sel in sels:
        try:
            loc = _make(page, sel)
            n = min(loc.count(), 10)
            for i in range(n):
                cand = loc.nth(i)
                try:
                    changed = _auto_open_panel(page, cand) or _auto_editor_text_mode(page, cand)
                    if changed:
                        page.wait_for_timeout(700)
                        if cand.is_visible():
                            return cand
                except Exception:
                    continue
        except Exception as exc:
            last = exc
    # 3) không có cái nào hiện -> lấy cái đầu tiên tồn tại (để báo lỗi rõ ràng)
    for sel in sels:
        try:
            loc = _make(page, sel)
            if loc.count() > 0:
                return loc.first
        except Exception as exc:
            last = exc
    if last:
        raise last
    raise RuntimeError("Không tìm thấy phần tử cho bước: " + (step.note or step.selector))


def wait_editor_ready(page: Page, log=None, timeout: int = 15000) -> None:
    """Chờ trang soạn thảo (Gutenberg/Classic) sẵn sàng."""
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    deadline = time.time() + timeout / 1000.0
    while time.time() < deadline:
        for sel in EDITOR_READY:
            try:
                if page.locator(sel).count() > 0:
                    time.sleep(0.6)
                    _dismiss_overlays(page)
                    return
            except Exception:
                continue
        time.sleep(0.4)
    _dismiss_overlays(page)


def _dismiss_overlays(page: Page) -> None:
    """Đóng các popup hướng dẫn (Gutenberg welcome guide, WooCommerce tour…)."""
    try:
        if page.locator(".components-modal__screen-overlay").count() > 0:
            page.keyboard.press("Escape")
            time.sleep(0.4)
    except Exception:
        pass


def play(page: Page, script: Script, ctx: dict, log=None, delay: float = 0.4) -> None:
    for i, step in enumerate(script.steps, 1):
        action = step.action
        if log:
            log(f"[{i}/{len(script.steps)}] {step.note or action}")
        try:
            if action == "open":
                target = render(step.value or step.selector, ctx)
                if target.startswith("http"):
                    page.goto(target, wait_until="domcontentloaded")
                    wait_editor_ready(page, log=log)
                else:
                    _locate(page, step).click()
            elif action == "click":
                _locate(page, step).click(force=bool(step.force), timeout=15000)
            elif action == "type":
                value = render(step.value, ctx)
                _locate(page, step).fill(value, force=bool(step.force), timeout=15000)
            elif action in ("tagify", "tag_input"):
                # Ô nhập kiểu Tagify (Rank Math focus keyword): gõ rồi Enter để chốt
                value = render(step.value, ctx)
                loc = _locate(page, step)
                try:
                    loc.click(force=True, timeout=8000)
                except Exception:
                    pass
                try:
                    loc.fill(value, timeout=8000)
                except Exception:
                    page.keyboard.insert_text(value)
                page.keyboard.press("Enter")
                time.sleep(0.5)
            elif action in ("panel", "open_panel"):
                # Mở bảng (metabox) nếu phần tử bên trong đang bị ẩn
                check = render(step.value or "", ctx)
                need = True
                if check:
                    try:
                        loc = _make(page, check)
                        n = min(loc.count(), 5)
                        need = not any(loc.nth(i).is_visible() for i in range(n))
                    except Exception:
                        need = True
                if need:
                    _locate(page, step).click(force=True, timeout=8000)
                    time.sleep(0.6)
            elif action in ("fill_attachment", "attachment_fields"):
                # Điền cả 4 ô chi tiết ảnh (Tiêu đề, Văn bản thay thế, Caption, Miêu tả)
                value = render(step.value, ctx)
                if not value or value.startswith("{{"):      # token chưa thay được -> bỏ qua
                    if log:
                        log("  (bỏ qua: chưa có tên ảnh cho bước này)")
                    time.sleep(delay)
                    continue
                for sel in ("#attachment-details-title", "#attachment-details-alt-text",
                            "#attachment-details-caption", "#attachment-details-description"):
                    try:
                        loc = page.locator(sel).first
                        if loc.count():
                            loc.fill(value, timeout=6000)
                    except Exception:
                        continue
            elif action == "select":
                _locate(page, step).select_option(render(step.value, ctx))
            elif action == "upload":
                raw = (step.value or "").strip()
                if raw:
                    # CHỈ tách bằng dấu | (tên file có thể chứa dấu phẩy)
                    vals = [v.strip() for v in render(raw, ctx).split("|") if v.strip()]
                else:
                    vals = [render(p, ctx) for p in ctx.get("__upload_files", [])]
                # bỏ token chưa thay được ({{image_4}}…) và file không tồn tại
                vals = [v for v in vals if v and not v.startswith("{{")]
                keep = [v for v in vals if Path(v).exists()]
                if len(keep) < len(vals) and log:
                    log(f"  (bỏ qua {len(vals) - len(keep)} ảnh không có sẵn)")
                vals = keep
                if not vals:
                    if log:
                        log("  (bỏ qua: không có ảnh cho bước này)")
                    time.sleep(delay)
                    continue
                _locate(page, step).set_input_files(vals)
            elif action == "press":
                _locate(page, step).press(render(step.value or "Enter", ctx))
            elif action == "wait":
                time.sleep(float(step.value or 1))
            else:
                if log:
                    log(f"  (bỏ qua hành động lạ: {action})")
        except Exception as exc:
            if step.optional:
                if log:
                    log(f"  (bỏ qua bước {i} — {str(exc).splitlines()[0][:90]})")
                time.sleep(delay)
                continue
            raise RuntimeError(f"Bước {i} ({step.note or action}) lỗi: {exc}") from exc
        time.sleep(delay)
