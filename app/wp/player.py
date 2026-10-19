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
    # Bước về ĐƯỜNG DẪN (slug) -> TUYỆT ĐỐI không dùng dự phòng ô Tiêu đề
    # (trước đây gõ nhầm slug vào ô tiêu đề khi ô đường dẫn chưa mở)
    is_slug = any(k in text for k in ("slug", "đường dẫn", "duong dan", "permalink"))
    if not is_slug and ("title" in text or "tiêu đề" in text or "tieu de" in text):
        out += TITLE_FALLBACKS
    if ("content" in text or "nội dung" in text or "noi dung" in text
            or "body" in text or "editor" in text):
        out += CONTENT_FALLBACKS
    return out


def _make(page: Page, sel: str):
    if sel.startswith("text="):
        return page.get_by_text(sel[5:].strip('"'), exact=False)
    return page.locator(sel)


_PANEL_STATE_JS = r"""el => {
    let node = el;
    while (node && node !== document.body) {
        const cls = (node.className || '').toString();
        if (/(^|\s)postbox(\s|$)/.test(cls)) {
            const inside = node.querySelector('.inside');
            if (!inside) return true;                       // không có .inside -> coi như mở
            return getComputedStyle(inside).display !== 'none'
                   && !/(^|\s)closed(\s|$)/.test(cls);
        }
        node = node.parentElement;
    }
    return true;                                            // không nằm trong card nào
}"""

_PANEL_OPEN_JS = r"""el => {
    let node = el;
    while (node && node !== document.body) {
        const cls = (node.className || '').toString();
        if (/(^|\s)postbox(\s|$)/.test(cls)) {
            const btn = node.querySelector('.handlediv') || node.querySelector('button.handlediv');
            if (btn) { btn.click(); return true; }
            return false;
        }
        node = node.parentElement;
    }
    return false;
}"""


def _in_postbox(el) -> bool:
    """Phần tử có nằm trong 1 card (postbox) không?"""
    try:
        return bool(el.evaluate(
            r"""el => { let n = el;
                while (n && n !== document.body) {
                    if (/(^|\s)postbox(\s|$)/.test((n.className || '').toString())) return true;
                    n = n.parentElement;
                }
                return false; }"""
        ))
    except Exception:
        return False


def _panel_open_state(el) -> bool:
    """Card (postbox) chứa phần tử này đã MỞ chưa?"""
    try:
        return bool(el.evaluate(_PANEL_STATE_JS))
    except Exception:
        return True


def _ensure_panel_open(page: Page, el, tries: int = 3) -> bool:
    """Mở card (postbox) đang thu gọn chứa `el` — BẤM RỒI KIỂM TRA LẠI (thử tối đa `tries` lần).

    - Bấm nút `.handlediv` bằng Playwright (bấm thật, đã thử chạy được).
    - KHÔNG bấm khi card đang mở (nút này là TOGGLE -> bấm nữa là ĐÓNG lại).
    """
    ok = _panel_open_state(el)
    for _ in range(max(1, int(tries))):
        if ok:
            return True
        clicked = False
        try:      # nút mở card = .handlediv trong .postbox chứa phần tử này
            btn = el.locator(
                "xpath=ancestor-or-self::*[contains(@class,'postbox')][1]"
                "//*[contains(@class,'handlediv')]"
            ).first
            btn.click(force=True, timeout=5000)
            clicked = True
        except Exception:
            clicked = False
        if not clicked:
            try:
                el.evaluate(_PANEL_OPEN_JS)
            except Exception:
                pass
        page.wait_for_timeout(500)
        ok = _panel_open_state(el)
    return ok


def _auto_open_panel(page: Page, el) -> bool:
    """Nếu phần tử nằm trong 1 bảng (metabox) đang THU GỌN -> mở bảng đó (có kiểm tra lại)."""
    if _panel_open_state(el):
        return False                    # đang mở -> không cần làm gì
    return _ensure_panel_open(page, el)


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


_ATTACH_FIELDS = ("#attachment-details-title", "#attachment-details-alt-text",
                  "#attachment-details-caption", "#attachment-details-description")


def fill_all_attachment_fields(page: Page, value: str, log=None) -> int:
    """Điền 4 ô (Tiêu đề / Văn bản thay thế / Image Caption / Miêu tả) cho MỌI ảnh trong khung thư viện.

    WP chỉ hiện bảng chi tiết khi CHỌN 1 ảnh -> lần lượt chọn từng ảnh rồi điền.
    """
    val = str(value or "").strip()
    if not val:
        return 0
    try:
        items = page.locator(".attachments .attachment, .attachment-preview")
        total = items.count()
    except Exception:
        return 0
    done = 0
    for i in range(total):
        try:
            it = items.nth(i)
            if not it.is_visible():
                continue
            try:
                it.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            it.click(timeout=6000)
            shown = False
            for _ in range(12):                     # chờ bảng chi tiết hiện ra
                try:
                    if page.locator("#attachment-details-title").count():
                        shown = True
                        break
                except Exception:
                    pass
                page.wait_for_timeout(200)
            if not shown:
                continue
            for sel in _ATTACH_FIELDS:
                try:
                    page.locator(sel).first.fill(val, timeout=6000)
                except Exception:
                    pass
            done += 1
        except Exception:
            continue
    if log:
        log(f"  (đã điền mô tả ảnh cho {done}/{total} ảnh trong thư viện)")
    return done


def _sidebar_attach_id(page: Page) -> int:
    """Mã ảnh mà BẢNG CHI TIẾT bên phải đang hiển thị (0 nếu chưa hiện)."""
    try:
        return int(page.evaluate(
            r"""() => {
                const links = Array.from(document.querySelectorAll('.media-sidebar .edit-attachment'));
                const vis = links.filter(a => {
                    const md = a.closest('.media-modal');
                    return md ? !!(md.offsetWidth || md.offsetHeight) : true;
                });
                const a = vis[0] || null;
                if (!a) return 0;
                const m = (a.getAttribute('href') || '').match(/post=(\d+)/);
                return m ? parseInt(m[1], 10) : 0; }"""
        ) or 0)
    except Exception:
        return 0


def slug_if_needed(page: Page, new_slug: str, limit: int = 65, log=None) -> bool:
    """Chỉnh đường dẫn (slug) — CHỈ KHI slug hiện tại DÀI TỪ `limit` ký tự trở lên.

    Slug hiện tại < 65 ký tự -> BỎ QUA (giữ nguyên slug WordPress tự tạo).
    """
    cur = ""
    try:
        cur = str(page.evaluate(
            """() => {
                const el = document.querySelector('#editable-post-name');
                if (el) return (el.innerText || el.textContent || '').trim();
                const p = document.querySelector('#sample-permalink');
                return p ? (p.innerText || p.textContent || '').trim() : ''; }"""
        ) or "").strip()
    except Exception:
        cur = ""
    if cur and "/" in cur:
        cur = cur.rstrip("/").split("/")[-1]
    if cur and len(cur) < int(limit):
        if log:
            log(f"  (bỏ qua chỉnh slug — slug hiện tại {len(cur)} ký tự < {limit}: {cur[:40]})")
        return False
    if not str(new_slug or "").strip():
        return False
    try:
        # mở ô chỉnh slug
        opened = False
        for sel in ("#edit-slug-buttons .edit-slug", "#edit-slug-box .edit-slug", "button.edit-slug"):
            try:
                loc = page.locator(sel).first
                if loc.count():
                    loc.click(timeout=6000)
                    page.wait_for_timeout(500)
                    if page.locator("#new-post-slug:visible").count():
                        opened = True
                        break
            except Exception:
                continue
        if not opened:
            if log:
                log("  (không mở được ô chỉnh slug — bỏ qua)")
            return False
        page.locator("#new-post-slug:visible").first.fill(str(new_slug), timeout=6000)
        page.wait_for_timeout(200)
        for sel in ("#edit-slug-buttons .save", "#edit-slug-box .save", "button.save"):
            try:
                loc = page.locator(sel).first
                if loc.count():
                    loc.click(timeout=6000)
                    break
            except Exception:
                continue
        page.wait_for_timeout(600)
        if log:
            log(f"  (đã chỉnh slug: {cur[:30] or '(trống)'} -> {str(new_slug)[:40]})")
        return True
    except Exception as exc:      # noqa: BLE001
        if log:
            log(f"  (lỗi chỉnh slug: {str(exc)[:80]})")
        return False


def add_gallery_images_one_by_one(page: Page, files: list[str], fallback_title: str = "",
                                  log=None) -> int:
    """Thêm ảnh vào THƯ VIỆN ảnh sản phẩm — TỪNG ẢNH MỘT (giống cách làm ảnh đại diện).

    Mỗi ảnh: mở "Thêm ảnh thư viện" -> tab "Tải lên tệp mới" -> upload 1 ảnh
             -> chờ bảng chi tiết -> điền các ô TRỐNG (tiêu đề của chính ảnh)
             -> bấm "Thêm vào thư viện" (chèn + đóng modal) -> ảnh kế tiếp.
    """
    done = 0
    for f in files:
        try:
            if not f or not Path(f).exists():
                continue
            # 0) ĐÓNG modal cũ (có thể còn mở từ bước ảnh đại diện) -> tránh bấm nhầm / tab không bấm được
            try:
                for _ in range(4):
                    if page.locator(".media-modal:visible").count() == 0:
                        break
                    try:
                        page.locator(".media-modal-close:visible").first.click(timeout=3000)
                    except Exception:
                        try:
                            page.keyboard.press("Escape")
                        except Exception:
                            pass
                    page.wait_for_timeout(600)
            except Exception:
                pass
            # 1) mở modal thư viện — BẤM RỒI KIỂM TRA modal đã mở chưa (bấm lại tối đa 3 lần)
            opened = False
            for _try in range(3):
                try:
                    page.locator("a.add_product_images, a:has-text('Thêm ảnh thư viện sản phẩm')").first.click(timeout=12000)
                except Exception:
                    pass
                for _w in range(40):
                    page.wait_for_timeout(200)
                    try:
                        if page.locator(".media-modal:visible").count():
                            opened = True
                            break
                    except Exception:
                        pass
                if opened:
                    break
                page.wait_for_timeout(800)
            if log:
                log("  (đã mở khung thư viện ảnh)" if opened else "  ⚠ KHÔNG mở được khung thư viện ảnh")
            # XOÁ LỰA CHỌN CŨ (để chỉ ảnh vừa upload được tick, không dính ảnh trước)
            try:
                page.evaluate("""() => { try {
                    if (window.wp && wp.media && wp.media.frame) {
                        wp.media.frame.state().get('selection').reset();
                    }
                    document.querySelectorAll('li.attachment.selected').forEach(li => li.classList.remove('selected'));
                } catch (e) {} }""")
            except Exception:
                pass
            # chờ thanh tab hiện
            for _w in range(40):
                page.wait_for_timeout(200)
                try:
                    if page.locator(".media-menu-item:visible").count():
                        break
                except Exception:
                    pass
            page.wait_for_timeout(300)
            # 2) BẮT BUỘC chọn tab "Tải lên tệp mới" (bấm + kiểm tra đã active, thử 3 lần)
            ok_tab = False
            for _try in range(3):
                for sel in (".media-menu-item:has-text('Tải lên tệp mới'):visible",
                            "#menu-item-upload:visible",
                            "button.media-menu-item#menu-item-upload:visible",
                            ".media-frame-router .media-menu-item:has-text('Tải lên'):visible",
                            ".media-menu-item:has-text('Tải lên'):visible"):
                    try:
                        loc = page.locator(sel).first
                        if not loc.count():
                            continue
                        loc.click(timeout=6000)
                        page.wait_for_timeout(600)
                        # KIỂM TRA: khung tải lên hiện HOẶC tab đã active
                        if (page.locator(".uploader-inline:visible").count()
                                or page.locator("#menu-item-upload.active,"
                                                " .media-menu-item.active:has-text('Tải lên')").count()):
                            ok_tab = True
                            break
                    except Exception:
                        continue
                if ok_tab:
                    break
                page.wait_for_timeout(500)
            if log:
                if ok_tab:
                    log("  (đã bấm tab “Tải lên tệp mới”)")
                else:
                    try:
                        tabs = page.evaluate(
                            """() => Array.from(document.querySelectorAll('.media-menu-item'))
                                .map(b => ((b.innerText || '').trim().slice(0, 24)) + '|' + (b.id || '')
                                          + ((b.className || '').toString().indexOf('active') >= 0 ? '*' : ''))"""
                        )
                    except Exception:
                        tabs = []
                    log(f"  ⚠ Chưa bấm được tab “Tải lên tệp mới” | tab đang có: {tabs}")
            # 3) SAU KHI BẤM TAB -> chờ 0,2 giây rồi bấm chọn file
            page.wait_for_timeout(200)
            page.locator("input[type='file']").first.set_input_files(f)
            # 4) chờ bảng chi tiết hiện
            ok = False
            for _ in range(80):
                page.wait_for_timeout(500)
                try:
                    if page.locator("#attachment-details-title:visible").count():
                        ok = True
                        break
                except Exception:
                    pass
            if ok:
                # 5) điền các ô TRỐNG = TIÊU ĐỀ CỦA CHÍNH ẢNH
                try:
                    own = str(page.locator("#attachment-details-title:visible").first
                              .input_value(timeout=2000) or "").strip()
                except Exception:
                    own = ""
                use = own or str(fallback_title or "").strip()   # ảnh chưa có tiêu đề -> dùng tiêu đề bài
                patch: dict = {}
                for sel, key in (("#attachment-details-title", "title"),
                                 ("#attachment-details-alt-text", "alt"),
                                 ("#attachment-details-caption", "caption"),
                                 ("#attachment-details-description", "description")):
                    loc = page.locator(sel + ":visible").first
                    try:
                        cur = str(loc.input_value(timeout=2000) or "").strip()
                    except Exception:
                        cur = ""
                    if cur or not use:
                        continue
                    try:
                        loc.fill(use, timeout=6000)
                        patch[key] = use
                    except Exception:
                        pass
                if patch:
                    try:
                        page.evaluate("""(patch) => { try {
                            const a = document.querySelector('.media-sidebar .edit-attachment');
                            const m = a && (a.getAttribute('href') || '').match(/post=(\\d+)/);
                            if (m) { const md = wp.media.attachment(m[1]); md.set(patch); md.save(); }
                        } catch (e) {} }""", patch)
                    except Exception:
                        pass
                if log:
                    log(f"  (ảnh {Path(f).name}: điền {', '.join(sorted(patch)) or 'không có ô trống'})")
            elif log:
                log(f"  (ảnh {Path(f).name}: không thấy bảng chi tiết)")
            # 6) chèn vào thư viện (đóng modal)
            # nút "Thêm vào thư viện" — CHỈ nút trong modal ĐANG HIỆN
            page.locator("button.media-button-select:visible, .media-toolbar-primary .media-button-select:visible").first.click(timeout=20000)
            page.wait_for_timeout(1500)
            done += 1
        except Exception as exc:      # noqa: BLE001
            if log:
                log(f"  (lỗi thêm ảnh {Path(f).name}: {str(exc)[:80]})")
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(600)
            except Exception:
                pass
    if log:
        log(f"  (đã thêm {done}/{len(files)} ảnh vào thư viện — làm TỪNG ẢNH)")
    return done


def fill_uploaded_attachment_fields(page: Page, value: str, min_id: int = 0,
                                     expect: int = 0, log=None) -> int:
    """Điền ô TRỐNG (Alt / Image Caption / Miêu tả) cho các ảnh VỪA UPLOAD — qua API WordPress.

    KHÔNG bấm vào ảnh: bấm vào ảnh là ĐỔI TRẠNG THÁI CHỌN -> mất lựa chọn -> "Thêm vào thư viện"
    chỉ chèn được 1 ảnh.

    - Chờ "Đang tải lên" biến mất (tối đa 120 giây).
    - Ảnh cần điền = các <li class="attachment selected"> TRONG MODAL ĐANG HIỆN (ảnh vừa upload);
      không có -> lấy theo danh sách đang chọn của wp.media; cuối cùng -> N ảnh đầu.
    - Giá trị = TIÊU ĐỀ CỦA CHÍNH ẢNH; ô nào đã có nội dung -> giữ nguyên.
    """
    val = str(value or "").strip()
    want = max(1, int(expect or 1))
    # 1) CHỜ upload xong: hết chữ "Đang tải lên" + đã có ảnh được chọn
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            st = page.evaluate(
                """() => { const md = Array.from(document.querySelectorAll('.media-modal'))
                                        .find(m => m.offsetWidth || m.offsetHeight);
                    const root = md || document;
                    let pick = 0;
                    try { pick = (window.wp && wp.media && wp.media.frame)
                                ? wp.media.frame.state().get('selection').length : 0; } catch (e) {}
                    const up = Array.from(document.querySelectorAll('.media-uploader-status'))
                                   .some(e => e.offsetWidth || e.offsetHeight);
                    return { all: root.querySelectorAll('li.attachment').length,
                             sel: root.querySelectorAll('li.attachment.selected').length,
                             pick: pick, up: up }; }"""
            ) or {}
        except Exception:
            st = {}
        if int(st.get("pick") or 0) >= want:
            break
        if not st.get("up") and (int(st.get("pick") or 0) >= 1 or int(st.get("sel") or 0) >= 1):
            break
        time.sleep(0.3)
    # 2) LẤY MÃ ẢNH (chỉ trong modal đang hiện)
    js_ids = """(expect) => {
        const out = [];
        const md = Array.from(document.querySelectorAll('.media-modal')).find(m => m.offsetWidth || m.offsetHeight);
        const root = md || document;
        root.querySelectorAll('li.attachment.selected').forEach(li => {
            const id = li.getAttribute('data-id'); if (id) out.push(String(id));
        });
        if (!out.length && window.wp && wp.media && wp.media.frame) {
            try { wp.media.frame.state().get('selection').each(m => { if (m && m.id) out.push(String(m.id)); }); } catch (e) {}
        }
        if (!out.length) {
            root.querySelectorAll('li.attachment').forEach((li, i) => {
                if (i < (expect || 0)) { const id = li.getAttribute('data-id'); if (id) out.push(String(id)); }
            });
        }
        return out;
    }"""
    try:
        ids = [str(x) for x in (page.evaluate(js_ids, want) or [])]
    except Exception:
        ids = []
    if not ids:
        if log:
            log("  (không thấy ảnh vừa upload để điền mô tả)")
        return 0
    try:
        ids = sorted(set(ids), key=lambda x: int(x), reverse=True)      # mới nhất trước: 4 -> 3 -> 2
    except Exception:
        ids = list(dict.fromkeys(reversed(ids)))
    # 3) ĐIỀN QUA API (không bấm ảnh -> giữ nguyên lựa chọn để chèn đủ ảnh)
    js_fill = """({ids, val}) => {
        const res = {done: 0, fields: []}; const fset = new Set();
        ids.forEach(id => {
            try {
                const m = wp.media.attachment(id);
                const t = ((m.get('title') || '').trim()) || val;
                if (!t) return;
                const patch = {};
                if (!((m.get('alt') || '').trim())) { patch.alt = t; fset.add('alt'); }
                if (!((m.get('caption') || '').trim())) { patch.caption = t; fset.add('caption'); }
                if (!((m.get('description') || '').trim())) { patch.description = t; fset.add('description'); }
                if (Object.keys(patch).length) { m.set(patch); m.save(); res.done += 1; }
            } catch (e) {}
        });
        res.fields = Array.from(fset);
        return res;
    }"""
    try:
        res = page.evaluate(js_fill, {"ids": ids, "val": val}) or {}
    except Exception as exc:      # noqa: BLE001
        if log:
            log(f"  (không điền được mô tả ảnh: {str(exc)[:80]})")
        return 0
    done = int(res.get("done") or 0)
    fields = res.get("fields") or []
    if log:
        log(f"  (đã điền mô tả cho {done}/{len(ids)} ảnh vừa upload — chỉ điền ô trống"
            + (f" | ô đã điền: {', '.join(fields)}" if fields else "") + ")")
    return done


def _tagify_committed(loc, value: str) -> bool:
    """Ô tagify ĐÃ nhận giá trị chưa? (đọc tag hiển thị + input ẩn trong hộp .tagify)."""
    v = str(value or "").strip().lower()
    if not v:
        return True
    try:
        got = loc.evaluate(
            """el => {
                const box = el.closest('.tagify');
                if (!box) return '';
                const tags = Array.from(box.querySelectorAll('.tagify__tag'))
                    .map(t => (t.innerText || '').trim()).join(' | ');
                const wrap = box.parentElement || box;
                const hid = wrap.querySelector('input[type=hidden], input[type=text][style*="display"]');
                return tags + ' || ' + (hid ? (hid.value || '') : '');
            }"""
        )
    except Exception:
        return False
    return v in str(got or "").lower()


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
                cond_val = render(cond, ctx).strip()
                # Biến KHÔNG tồn tại (vd {{image_2}} khi job chỉ có 1 ảnh) -> coi như RỖNG -> BỎ QUA bước.
                # (render giữ nguyên "{{image_2}}" nếu thiếu key -> trước đây tưởng là CÓ nên vẫn chạy)
                if (not cond_val) or ("{{" in cond_val):
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
                loc = _locate(page, step)
                check = str(step.value or "").strip()      # value = selector KIỂM TRA (nếu có)
                if not check:
                    loc.click(force=bool(step.force), timeout=15000)
                else:
                    # Bấm rồi KIỂM TRA phần tử cần mở đã hiện chưa -> chưa hiện thì bấm lại (tối đa 3 lần)
                    done = False
                    for _try in range(3):
                        try:
                            loc.click(force=bool(step.force), timeout=15000)
                        except Exception:
                            pass
                        page.wait_for_timeout(500)
                        try:
                            tgt = _make(page, check)
                            n = min(tgt.count(), 5)
                            if any(tgt.nth(i).is_visible() for i in range(n)):
                                done = True
                                break
                        except Exception:
                            pass
                        try:
                            loc = _locate(page, step)          # tìm lại nút (DOM có thể đổi)
                        except Exception:
                            pass
                    if not done and log:
                        log(f"  (bấm “{step.note or 'nút'}” nhưng chưa thấy {check} — đi tiếp)")
            elif action == "type":
                value = render(step.value, ctx)
                try:
                    _locate(page, step).fill(value, force=bool(step.force), timeout=15000)
                except Exception:
                    # Ô soạn thảo TinyMCE đang ở chế độ "Trực quan" -> điền thẳng vào khung soạn thảo
                    if not _fill_editor_iframe(page, step, value, log=log):
                        raise
            elif action in ("slug_if_needed", "slug_auto"):
                # Chỉnh slug CHỈ KHI slug hiện tại >= 65 ký tự
                slug_if_needed(page, render(step.value or "{{slug}}", ctx), log=log)
            elif action in ("add_gallery_images", "gallery_add_each"):
                # Thêm ảnh vào thư viện TỪNG ẢNH MỘT (upload -> điền -> chèn) rồi kết thúc
                # lặp cho TỚI HẾT số ảnh (tối đa 20 ảnh như app cho phép)
                files = []
                for i in range(2, 21):
                    fp = str(ctx.get(f"image_{i}") or "")
                    if fp and Path(fp).exists():
                        files.append(fp)
                if files:
                    add_gallery_images_one_by_one(
                        page, files, fallback_title=render("{{title}}", ctx), log=log)
                elif log:
                    log("  (không có ảnh nào để thêm vào thư viện)")
            elif action in ("attachment_fields_uploaded", "fill_attachment_uploaded"):
                # Điền ô TRỐNG cho ĐÚNG những ảnh VỪA upload (không đụng ảnh cũ trong thư viện)
                fill_uploaded_attachment_fields(
                    page, render(step.value or "{{title}}", ctx),
                    int(ctx.get("__max_attach_id") or 0),
                    int(ctx.get("__uploaded_count") or 0), log=log)
            elif action in ("attachment_fields_all", "fill_attachment_all"):
                # Điền 4 ô mô tả ảnh cho TẤT CẢ ảnh trong khung thư viện (ảnh 2, 3, 4…)
                fill_all_attachment_fields(page, render(step.value or "{{title}}", ctx), log=log)
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
                ok_fill = False
                # Ô tagify hay "chưa sẵn sàng" (metabox vừa mở) -> gõ rồi KIỂM TRA, chưa vào thì gõ lại.
                for _attempt in range(3):
                    loc = _locate(page, step)
                    _ensure_panel_open(page, loc)     # ô nằm trong card đang đóng -> mở trước
                    loc = _locate(page, step)         # tìm lại sau khi mở (ô có thể vừa hiện)
                    try:
                        loc.scroll_into_view_if_needed(timeout=5000)
                    except Exception:
                        pass
                    try:
                        loc.click(force=True, timeout=8000)
                    except Exception:
                        pass
                    try:
                        loc.fill(value, timeout=8000)
                    except Exception:
                        try:      # gõ vào CHÍNH ô này (không phải ô đang focus)
                            loc.press_sequentially(value, timeout=8000)
                        except Exception:
                            pass
                    try:
                        page.keyboard.press("Enter")
                    except Exception:
                        pass
                    if _tagify_committed(loc, value):
                        ok_fill = True
                        break
                    page.wait_for_timeout(600)      # chờ ô sẵn sàng rồi gõ lại
                if not ok_fill and log:
                    log("⚠ Ô nhập từ khoá (tagify) không điền được — BỎ QUA bước này.")
                time.sleep(0.4)
            elif action in ("panel", "open_panel"):
                # Mở card (metabox) nếu đang THU GỌN.
                # LƯU Ý: nút này là TOGGLE -> chỉ bấm khi đang ĐÓNG (bấm lúc đang mở là ĐÓNG lại!)
                el = _locate(page, step)
                if _in_postbox(el):
                    _ensure_panel_open(page, el)       # mở + KIỂM TRA LẠI (tối đa 3 lần)
                else:
                    try:
                        el.click(force=True, timeout=8000)
                    except Exception:
                        pass
                time.sleep(0.2)
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
                try:      # ghi lại MỐC trước khi upload (để biết ảnh nào là ảnh MỚI)
                    mx = page.evaluate(
                        """() => { let mx = 0;
                            document.querySelectorAll('.attachments .attachment, .attachment-preview')
                                .forEach(el => { const id = parseInt(el.getAttribute('data-id') || '0', 10) || 0;
                                                 if (id > mx) mx = id; });
                            return mx; }"""
                    )
                    ctx["__max_attach_id"] = int(mx or 0)
                    ctx["__uploaded_count"] = len(vals)
                except Exception:
                    pass
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
