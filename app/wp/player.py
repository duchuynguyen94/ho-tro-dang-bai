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
    """Ô soạn thảo TinyMCE đang bị ẩn (đang ở chế độ Trực quan) -> bấm tab "Mã" của ô đó.

    Bấm lại 1 lần nữa nếu chưa ăn (trang còn đang nạp) và CHỈ trả về True khi ô đã hiện.
    """
    try:
        eid = el.get_attribute("id") or ""
        cls = (el.get_attribute("class") or "")
        if not eid or "wp-editor-area" not in cls:
            return False
        tab = page.locator(f"#{eid}-html").first
        for _ in range(2):
            if not (tab.count() and tab.is_visible()):
                break
            tab.click(timeout=3000)
            page.wait_for_timeout(600)
            try:
                if el.is_visible():          # đã sang chế độ "Mã" -> điền được
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _is_fillable(loc) -> bool:
    """Phần tử có điền được bằng fill() không (input / textarea / select / contenteditable)?"""
    try:
        return bool(loc.evaluate(
            """el => {
                const tag = (el.tagName || '').toLowerCase();
                if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
                if (el.isContentEditable) return true;
                const role = (el.getAttribute('role') || '').toLowerCase();
                return ['textbox', 'searchbox', 'combobox', 'spinbutton'].indexOf(role) >= 0;
            }"""
        ))
    except Exception:
        return False


def _editor_iframe_selectors(step: ScriptStep) -> list[str]:
    """Các selector là KHUNG soạn thảo TinyMCE (#content_ifr, #excerpt_ifr…)."""
    out: list[str] = []
    for sel in [*_selectors(step), *_fallbacks_for(step)]:
        s = (sel or "").strip()
        if s.startswith("#") and s.endswith("_ifr") and s not in out:
            out.append(s)
    return out


def _fill_editor_iframe(page: Page, step: ScriptStep, value: str, log=None) -> bool:
    """Ô soạn thảo TinyMCE đang ở chế độ "Trực quan": điền thẳng vào khung soạn thảo.

    Đồng thời ghi lại vào ô ẩn + TinyMCE để lúc bấm Lưu/Cập nhật KHÔNG bị mất nội dung.
    """
    for sel in _editor_iframe_selectors(step):
        eid = sel[1:-4]                       # "#content_ifr" -> "content"
        try:
            body = page.frame_locator(sel).locator("body")
            if body.count() == 0:
                continue
            body.fill(value, timeout=10000)
            try:
                page.evaluate(
                    """([id, html]) => {
                        const ta = document.getElementById(id);
                        if (ta) ta.value = html;
                        const ed = (window.tinymce && window.tinymce.get) ? window.tinymce.get(id) : null;
                        if (ed) { try { ed.setContent(html); } catch (e) {} }
                    }""",
                    [eid, value],
                )
            except Exception:
                pass
            if log:
                log("  (ô soạn thảo đang ở chế độ Trực quan — đã điền thẳng vào khung soạn thảo)")
            return True
        except Exception:
            continue
    return False


def _locate(page: Page, step: ScriptStep):
    """Tìm phần tử theo selector chính rồi tới các selector dự phòng.

    - Ưu tiên phần tử ĐANG HIỆN (tránh input ẩn của WordPress/Gutenberg).
    - Bước ĐIỀN nội dung: bỏ qua phần tử KHÔNG điền được (khung iframe TinyMCE…).
    - Nếu phần tử bị ẩn do BẢNG THU GỌN -> tự mở bảng rồi dùng lại.
    - Nếu là ô soạn thảo TinyMCE đang ẩn -> tự bấm tab "Mã" rồi dùng lại.
    """
    fillable = str(getattr(step, "action", "") or "") in ("type", "tagify", "tag_input")
    sels = _selectors(step)
    for extra in _fallbacks_for(step):
        if extra not in sels:
            sels.append(extra)

    last = None
    # 1) phần tử đang hiện (bước điền: phải ĐIỀN ĐƯỢC — tránh chọn nhầm khung iframe)
    for sel in sels:
        try:
            loc = _make(page, sel)
            n = min(loc.count(), 10)
            for i in range(n):
                cand = loc.nth(i)
                try:
                    if not cand.is_visible():
                        continue
                    if fillable and not _is_fillable(cand):
                        continue
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
                        try:
                            if cand.is_visible() and (not fillable or _is_fillable(cand)):
                                return cand
                        except Exception:
                            pass
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


def _wait_editors_ready(page: Page, timeout: int = 15000) -> None:
    """Chờ các ô soạn thảo TinyMCE (Mô tả sản phẩm / Mô tả ngắn) khởi tạo xong.

    Chỉ chờ những ô CÓ trên trang; trang Gutenberg (không có ô nào) -> xong ngay.
    """
    deadline = time.time() + timeout / 1000.0
    while time.time() < deadline:
        try:
            ok = page.evaluate(
                """() => {
                    for (const id of ['content', 'excerpt']) {
                        const area = document.getElementById(id);
                        if (!area) continue;                       // trang không có ô này -> bỏ qua
                        if (!area.classList.contains('wp-editor-area')) continue;
                        if (!document.getElementById(id + '-html')) return false;   // chưa có tab "Mã"
                        // ô đang HIỆN = đang ở chế độ Mã (không cần TinyMCE) -> không phải chờ
                        if (area.offsetWidth || area.offsetHeight || area.getClientRects().length) continue;
                        if (!window.tinymce || !window.tinymce.get || !window.tinymce.get(id)) {
                            return false;                          // TinyMCE chưa khởi tạo xong
                        }
                    }
                    return true;
                }"""
            )
            if ok:
                return
        except Exception:
            pass
        time.sleep(0.3)


def wait_editor_ready(page: Page, log=None, timeout: int = 15000) -> None:
    """Chờ trang soạn thảo (Gutenberg/Classic) TẢI XONG mới cho phát lại kịch bản."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    # trang tải xong hẳn (ảnh / script) — tối đa 10 giây rồi đi tiếp
    try:
        page.wait_for_load_state("load", timeout=10000)
    except Exception:
        pass
    # mạng tạm yên (WordPress hay có "nhịp tim" nên chỉ chờ tối đa 10 giây)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    # khung soạn thảo đã có mặt
    deadline = time.time() + timeout / 1000.0
    while time.time() < deadline:
        for sel in EDITOR_READY:
            try:
                if page.locator(sel).count() > 0:
                    time.sleep(0.6)
                    _dismiss_overlays(page)
                    _wait_editors_ready(page)
                    return
            except Exception:
                continue
        time.sleep(0.4)
    _dismiss_overlays(page)
    _wait_editors_ready(page)


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
        # ĐIỀU KIỆN BƯỚC: có "when" mà render ra RỖNG -> BỎ QUA bước này
        cond = str(getattr(step, "when", "") or "")
        if cond:
            try:
                if not render(cond, ctx).strip():
                    if log:
                        log(f"[{i}/{len(script.steps)}] (bỏ qua: {step.note or action})")
                    continue
            except Exception:
                pass
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
                try:
                    _locate(page, step).fill(value, force=bool(step.force), timeout=15000)
                except Exception:
                    # Ô soạn thảo TinyMCE đang ở chế độ "Trực quan" -> điền thẳng vào khung soạn thảo
                    if not _fill_editor_iframe(page, step, value, log=log):
                        raise
            elif action in ("open_details", "open_attachment_details"):
                # Mở BẢNG CHI TIẾT ẢNH (chỉ bấm vào ảnh khi bảng CHƯA hiện —
                # bấm lúc đã chọn sẽ bị BỎ CHỌN)
                try:
                    if page.locator("#attachment-details-title").count() == 0:
                        for sel in (".attachments .attachment", ".attachment-preview",
                                    ".media-frame-content .attachment"):
                            try:
                                loc2 = page.locator(sel)
                                if loc2.count():
                                    loc2.nth(0).click(timeout=8000)
                                    break
                            except Exception:
                                continue
                        page.wait_for_timeout(1200)
                    if page.locator("#attachment-details-title").count() == 0:
                        if log:
                            log("⚠ Không mở được bảng chi tiết ảnh.")
                except Exception as exc:      # noqa: BLE001
                    if log:
                        log(f"⚠ Lỗi mở bảng chi tiết ảnh: {str(exc)[:60]}")
            elif action in ("tagify", "tag_input"):
                # Ô nhập kiểu Tagify (Rank Math focus keyword): gõ rồi Enter để chốt.
                # TUYỆT ĐỐI không gõ "mù" vào ô đang focus (sẽ chèn nhầm vào ô Mô tả…).
                value = render(step.value, ctx)
                loc = _locate(page, step)
                try:
                    loc.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
                ok_click = False
                try:
                    loc.click(force=True, timeout=8000)
                    ok_click = True
                except Exception:
                    pass
                ok_fill = False
                if ok_click:
                    try:
                        loc.fill(value, timeout=8000)
                        ok_fill = True
                    except Exception:
                        try:      # gõ vào CHÍNH ô này (không phải ô đang focus)
                            loc.press_sequentially(value, timeout=8000)
                            ok_fill = True
                        except Exception:
                            ok_fill = False
                if not ok_fill:
                    if log:
                        log("⚠ Ô nhập từ khoá (tagify) không điền được — BỎ QUA bước này.")
                else:
                    try:
                        page.keyboard.press("Enter")
                    except Exception:
                        pass
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
