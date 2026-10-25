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


# Đuôi USP thường bị AI nhét vào CUỐI tiêu đề -> bỏ khỏi slug
SLUG_TAIL_PHRASES = (
    "hang-chinh-hang",
    "gia-tot",
    "co-cq-day-du",
    "cocq-day-du",
    "bao-gia-nhanh-toan-quoc",
    "bao-gia-nhanh",
    "hang-san",
    "giao-nhanh",
    "dai-ly",
    "phan-phoi",
    "ho-tro-ky-thuat",
    "bao-hanh-chinh-hang",
)


def _strip_slug_tails(s: str) -> str:
    """Bỏ các cụm USP ở CUỐI slug (lặp tới khi không còn)."""
    changed = True
    while changed and s:
        changed = False
        for tail in SLUG_TAIL_PHRASES:
            if s == tail:
                return ""
            if s.endswith("-" + tail):
                s = s[: -(len(tail) + 1)].rstrip("-")
                changed = True
                break
    return s


def make_slug(text: str, max_len: int = 60) -> str:
    """Tạo đường dẫn (slug) từ tiêu đề: bỏ dấu tiếng Việt, thường hoá, nối bằng '-'.

    Tối đa `max_len` ký tự (cắt ở ranh giới từ, không để dấu '-' ở cuối).
    BỎ các cụm USP ở cuối (hàng chính hãng / giá tốt / CO-CQ…).
    """
    import unicodedata

    s = (text or "").strip().lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = _strip_slug_tails(s)
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


_FILL_CURRENT_JS = r"""({val}) => new Promise(resolveMain => {
    const mods = Array.from(document.querySelectorAll('.media-modal'))
                     .filter(m => (m.offsetWidth || m.offsetHeight));
    const md = mods.length ? mods[mods.length - 1] : document;   // MODAL TRÊN CÙNG
    const t = md.querySelector('#attachment-details-title');
    const own = t ? (t.value || '').trim() : '';
    const use = own || (val || '');
    const res = {own: own, hasTitle: !!t, done: [], saved: false};
    let finished = false;
    const finish = (saved) => {
        if (finished) return;
        finished = true;
        res.saved = !!saved;
        resolveMain(res);
    };
    if (!use) return finish(false);
    const patch = {};
    [['#attachment-details-alt-text', 'alt'], ['#attachment-details-caption', 'caption'],
     ['#attachment-details-description', 'description']].forEach(([sel, key]) => {
        const el = md.querySelector(sel);
        if (!el) return;
        if ((el.value || '').trim()) return;                     // ô đã có nội dung -> giữ nguyên
        el.value = use;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        patch[key] = use;
    });
    res.done = Object.keys(patch);
    try {      // lưu đúng MODEL của ảnh trong modal này + CHỜ AJAX lưu xong
        const e = md.querySelector('.edit-attachment');
        const m = e && (e.getAttribute('href') || '').match(/post=(\d+)/);
        if (m && Object.keys(patch).length) {
            const model = wp.media.attachment(m[1]);
            model.set(patch);
            const pr = model.save();
            if (pr && pr.always) {
                pr.always(() => finish(true));
            } else {
                finish(true);
            }
        } else {
            finish(false);
        }
    } catch (err) {
        finish(false);
    }
    setTimeout(() => finish(false), 20000);      // an toàn: tối đa 20 giây
})"""


_WAIT_SAVED_JS = r"""(timeoutSec) => new Promise(async (resolveMain) => {
    const mods = Array.from(document.querySelectorAll('.media-modal'))
                     .filter(m => (m.offsetWidth || m.offsetHeight));
    const md = mods.length ? mods[mods.length - 1] : document;
    const e = md.querySelector('.edit-attachment');
    const m = e && (e.getAttribute('href') || '').match(/post=(\d+)/);
    if (!m || !window.wp || !wp.media) return resolveMain(true);
    const id = m[1];
    const val = (sel) => {
        const el = md.querySelector(sel);
        return el ? (el.value || '').trim() : '';
    };
    const want = {alt: val('#attachment-details-alt-text'),
                  caption: val('#attachment-details-caption'),
                  description: val('#attachment-details-description')};
    const deadline = Date.now() + Math.max(3, timeoutSec) * 1000;
    while (Date.now() < deadline) {
        const model = wp.media.attachment(id);
        await new Promise(res => {
            try { model.fetch().done(() => res()).fail(() => res()); } catch (err) { res(); }
            setTimeout(res, 2000);
        });
        const got = (k) => String(model.get(k) || '').trim();
        if (got('alt') === want.alt && got('caption') === want.caption
                && got('description') === want.description) {
            return resolveMain(true);
        }
        await new Promise(res => setTimeout(res, 500));
    }
    resolveMain(false);
})"""


def _fill_attachment_in_top_modal(page: Page, value: str = "", log=None) -> int:
    """Điền các ô TRỐNG của bảng chi tiết trong MODAL TRÊN CÙNG.

    Ưu tiên GIÁ TRỊ ô #attachment-details-title (tiêu đề CỦA CHÍNH ẢNH đó);
    chỉ khi ô đó trống mới dùng `value` (tiêu đề bài viết).
    """
    # CHỜ ô Tiêu đề có giá trị (WordPress đặt tiêu đề = tên file ngay sau khi upload)
    for _w in range(12):
        try:
            ok_title = page.evaluate(
                """() => {
                    const mods = Array.from(document.querySelectorAll('.media-modal'))
                                     .filter(m => (m.offsetWidth || m.offsetHeight));
                    const md = mods.length ? mods[mods.length - 1] : document;
                    const t = md.querySelector('#attachment-details-title');
                    return !!(t && (t.value || '').trim()); }"""
            )
        except Exception:
            ok_title = False
        if ok_title:
            break
        page.wait_for_timeout(200)
    try:
        res = page.evaluate(_FILL_CURRENT_JS, {"val": str(value or "")}) or {}
    except Exception as exc:      # noqa: BLE001
        if log:
            log(f"  (lỗi điền mô tả ảnh: {str(exc)[:80]})")
        return 0
    # CHỜ WordPress LƯU XONG thật sự (đối chiếu lại với server) trước khi cho bấm chèn
    if (res.get("done") or []) and not res.get("saved"):
        try:
            page.evaluate(_WAIT_SAVED_JS, 20)
        except Exception:      # noqa: BLE001
            pass
    done = res.get("done") or []
    if log:
        own = str(res.get("own") or "")
        log(f"  (ảnh: điền {', '.join(done) if done else 'không có ô trống'}"
            + (f" | tiêu đề ảnh: {own[:30]}" if own else " | tiêu đề ảnh TRỐNG -> dùng tiêu đề bài") + ")")
    return len(done)


# Các khối LUÔN ẩn trên trang WordPress (chỉ ẩn trong trình duyệt của app)
# CSS LUÔN ÁP trên trang WordPress (mọi website, mọi lần tải)
DEFAULT_EXTRA_CSS = (
    "#product_tag { max-height: 300px; overflow: auto; position: relative; }",
)

DEFAULT_HIDE_SELECTORS = (
    "#rank_math_metabox_link_suggestions",
    "#rank_math_metabox_content_ai",
    "#commentsdiv",
    "#woocommerce-product-data",
    "#wpcode-metabox-snippets",
)


def build_hide_script(selectors, extra_css=None) -> str:
    """Script tiêm SỚM (init script): ẩn khối + TỰ ẨN LẠI mỗi khi trang vẽ thêm phần tử."""
    import json as _json

    sels = _json.dumps([str(x) for x in (selectors or []) if str(x).strip()])
    extra = _json.dumps([str(x) for x in (extra_css if extra_css is not None else DEFAULT_EXTRA_CSS)
                         if str(x).strip()])
    return """
(() => {
  const SELS = %s;
  const EXTRA = %s;
  if (!SELS.length && !EXTRA.length) return;
  const CSS = SELS.map(s => s + ' { display: none !important; }')
                  .concat(EXTRA).join('\\n');
  let scheduled = false;
  const apply = () => {
    scheduled = false;
    try {
      let st = document.getElementById('htdb-hide-style');
      if (!st) {
        st = document.createElement('style');
        st.id = 'htdb-hide-style';
        (document.head || document.documentElement).appendChild(st);
      }
      if (st.textContent !== CSS) st.textContent = CSS;
      SELS.forEach(sel => {
        try {
          document.querySelectorAll(sel).forEach(e => {
            if (e.style.display !== 'none') e.style.display = 'none';
          });
        } catch (err) {}
      });
    } catch (err) {}
  };
  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    setTimeout(apply, 150);
  };
  const start = () => {
    apply();
    try {
      new MutationObserver(schedule).observe(document.documentElement,
                                             {childList: true, subtree: true});
    } catch (e) {}
    setInterval(apply, 2000);      // lưới an toàn (trang tự vẽ lại nhiều lần)
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
""" % (sels, extra)


def hide_elements(page: Page, extra: list | None = None) -> None:
    """Ẩn các khối không dùng trên trang (tiêm CSS — KHÔNG sửa gì trên website)."""
    sels = list(DEFAULT_HIDE_SELECTORS) + [str(x).strip() for x in (extra or []) if str(x).strip()]
    if not sels:
        return
    css = "\n".join([f"{x} {{ display: none !important; }}" for x in sels]
                     + list(DEFAULT_EXTRA_CSS))
    try:
        page.add_style_tag(content=css)
    except Exception:
        pass
    try:      # khối có thể được thêm SAU khi trang tải -> ẩn lại 1 lần nữa
        page.evaluate(
            """(sels) => {
                sels.forEach(sel => {
                    try {
                        document.querySelectorAll(sel).forEach(e => { e.style.display = 'none'; });
                    } catch (err) {}
                });
            }""", sels)
    except Exception:
        pass


def _dismiss_translate(page: Page) -> None:
    """Dọn bong bóng Google Dịch / banner dịch (hay che nút và chặn click)."""
    try:
        page.evaluate(
            """() => {
                ['#gtx-trans', '.goog-te-banner-frame', 'iframe.skiptranslate',
                 '#goog-gt-tt', '.goog-te-balloon-frame'].forEach(sel => {
                    document.querySelectorAll(sel).forEach(e => {
                        try { e.remove(); } catch (err) {}
                    });
                });
                try { document.body.style.top = '0px'; } catch (err) {}
            }"""
        )
    except Exception:
        pass


def _safe_click(page: Page, loc, force: bool = False, timeout: int = 15000) -> None:
    """Bấm nút; nếu bị popup che (Google dịch…) thì dọn popup + Esc rồi bấm lại."""
    for attempt in (1, 2):
        try:
            loc.click(force=force, timeout=timeout)
            return
        except Exception as exc:      # noqa: BLE001
            if attempt == 2:
                raise
            _dismiss_translate(page)
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(300)


def _norm_vn(s: str) -> str:
    """Bỏ dấu + viết thường + gộp khoảng trắng (để so khớp tên danh mục/thương hiệu)."""
    import unicodedata as _ud

    t = _ud.normalize("NFD", str(s or "").lower())
    t = "".join(ch for ch in t if _ud.category(ch) != "Mn")
    t = t.replace("đ", "d")
    return re.sub(r"\s+", " ", t).strip()


def _taxonomy_terms(page: Page, tax: str) -> list:
    """Danh sách term hiện có trong hộp taxonomy: [{id, text, checked}]."""
    try:
        return page.evaluate(
            """(tax) => {
                const root = document.querySelector('#' + tax + 'checklist')
                          || document.querySelector('#' + tax + 'div');
                if (!root) return [];
                const out = [];
                root.querySelectorAll('li').forEach(li => {
                    const inp = li.querySelector('input[type=checkbox]');
                    const lab = li.querySelector('label');
                    if (!inp || !lab) return;
                    // BỎ các link phụ do plugin chèn trong nhãn (vd "Make Term Primary")
                    let txt = '';
                    try {
                        const copy = lab.cloneNode(true);
                        copy.querySelectorAll(
                            'input, a, button, .rank-math-tooltip, [class*="tooltip"],'
                            + ' [class*="make-primary"]').forEach(x => x.remove());
                        txt = (copy.textContent || '');
                    } catch (e) {
                        txt = (lab.innerText || '');
                    }
                    txt = txt.replace(/\\s+/g, ' ').trim();
                    out.push({id: inp.id, value: String(inp.value || ''),
                              text: txt, checked: !!inp.checked,
                              vis: !!(inp.offsetWidth || inp.offsetHeight)});
                });
                return out;
            }""", tax) or []
    except Exception:
        return []


def split_term_names(raw: str, multi: bool = True) -> list:
    """Tách chuỗi tên loại: "A; B; C" -> [A, B, C] (bỏ trùng, bỏ rỗng)."""
    if not multi:
        one = str(raw or "").strip()
        return [one] if one else []
    out, seen = [], set()
    for part in re.split(r"[;,]", str(raw or "")):
        t = part.strip(" \t-•*").strip()
        k = _norm_vn(t)
        if t and k and k not in seen:
            seen.add(k)
            out.append(t)
        if len(out) >= 2:               # tối đa 2 loại (1 chính + 1 con)
            break
    return out


def pick_taxonomy_terms(page: Page, tax: str, raw: str, label: str = "",
                        multi: bool = True, log=None) -> int:
    """Chọn/thêm NHIỀU loại một lượt (mỗi loại làm 1 lần — WordPress chỉ thêm 1 term/lần)."""
    names = split_term_names(raw, multi)
    if not names:
        if log:
            log(f"  (bỏ qua {label} — để trống)")
        return 0
    done = 0
    for i, name in enumerate(names, 1):
        try:
            if pick_taxonomy_term(page, tax, name, label=label, log=log):
                done += 1
        except Exception as exc:      # noqa: BLE001
            if log:
                log(f"  ({label}: lỗi “{name}” — {str(exc)[:60]})")
    if log and len(names) > 1:
        log(f"  ({label}: xong {done}/{len(names)} loại)")
    return done


def _tag_box_list(page: Page, box_id: str = "tagsdiv-product_tag") -> list:
    """Các thẻ ĐÃ CÓ trong hộp Thẻ sản phẩm (bỏ nút xoá khỏi tên)."""
    try:
        return page.evaluate(
            """(box) => {
                const b = document.getElementById(box);
                if (!b) return [];
                const cl = b.querySelector('.tagchecklist');
                if (!cl) return [];
                return Array.from(cl.querySelectorAll('span')).map(sp => {
                    const c = sp.cloneNode(true);
                    c.querySelectorAll('a, button').forEach(x => x.remove());
                    return (c.textContent || '').replace(/\\s+/g, ' ').trim();
                }).filter(Boolean);
            }""", box_id) or []
    except Exception:
        return []


def scroll_top(page: Page, log=None) -> None:
    """Cuộn lên ĐẦU TRANG (sau khi thêm thẻ) — giúp các bước sau thao tác ổn định."""
    done = False
    try:
        page.evaluate(
            """() => { try { window.scrollTo({top: 0, left: 0, behavior: 'instant'}); }
                       catch (e) { window.scrollTo(0, 0); }
                       const sc = document.scrollingElement || document.documentElement;
                       if (sc) sc.scrollTop = 0; }"""
        )
        done = True
    except Exception:
        pass
    if not done:
        try:
            page.keyboard.press("Home")
        except Exception:
            pass
    try:
        page.wait_for_timeout(300)
    except Exception:
        pass


def add_tags(page: Page, tags: str, input_sel: str = "", log=None,
             box_id: str = "tagsdiv-product_tag") -> bool:
    """Thêm THẺ (tags) chắc chắn: gõ -> bấm "Thêm" -> KIỂM TRA -> thử lại 3 lần.

    `tags` nhiều thẻ cách nhau dấu phẩy / chấm phẩy.
    """
    names = [t.strip() for t in re.split(r"[,;]", str(tags or "")) if t.strip()]
    if not names:
        if log:
            log("  (bỏ qua thẻ — để trống)")
        return False

    def norm(t: str) -> str:
        return _norm_vn(t)

    wants = [norm(n) for n in names]

    def done() -> bool:
        have = [norm(t) for t in _tag_box_list(page, box_id)]
        return all(any(w == h or w in h for h in have) for w in wants)

    # mở hộp Thẻ nếu đang thu gọn
    try:
        page.evaluate(
            """(id) => { const b = document.getElementById(id);
                if (b && b.classList.contains('closed')) b.classList.remove('closed'); }""", box_id)
    except Exception:
        pass
    try:
        if not page.locator(f"#{box_id} .tagchecklist").count():
            page.locator(f"#{box_id} .hndle").first.click(timeout=2500)
            page.wait_for_timeout(300)
    except Exception:
        pass

    inp = page.locator(input_sel or "#new-tag-product_tag").first
    if not inp.count():
        if log:
            log("  (thẻ: không thấy ô nhập thẻ — bỏ qua)")
        return False
    btn = page.locator(f"#{box_id} .tagadd").first

    for attempt in (1, 2, 3):
        if done():                      # đã có đủ từ lần trước
            break
        try:
            inp.fill(", ".join(names), timeout=5000)
        except Exception:               # ô bị ẩn -> đặt giá trị trực tiếp
            try:
                page.evaluate(
                    """([sel, v]) => { const i = document.querySelector(sel);
                        if (!i) return; i.value = v;
                        i.dispatchEvent(new Event('input', {bubbles: true})); }""",
                    [input_sel or "#new-tag-product_tag", ", ".join(names)])
            except Exception:
                return False
        page.wait_for_timeout(250)
        clicked = False
        try:
            if btn.count() and btn.is_visible() and btn.is_enabled():
                btn.click(timeout=4000)
                clicked = True
        except Exception:
            clicked = False
        if not clicked:
            try:
                page.evaluate(
                    """(id) => { const b = document.querySelector('#' + id + ' .tagadd');
                        if (b) b.click(); }""", box_id)
            except Exception:
                pass
        # chờ tối đa ~6 giây
        deadline = time.time() + 6.0
        while time.time() < deadline:
            page.wait_for_timeout(300)
            if done():
                if log:
                    log(f"  (thẻ: đã thêm {len(names)} thẻ)")
                return True
        # thử Enter trong ô nhập (WordPress hỗ trợ)
        try:
            inp.click(timeout=2000)
            inp.press("Enter", timeout=2000)
        except Exception:
            pass
        if log and attempt < 3:
            log(f"  (thẻ: chưa thấy đủ thẻ — thử lại lần {attempt + 1}…)")
    ok = done()
    if log:
        log(f"  (thẻ: {'đã thêm' if ok else 'KHÔNG thêm được'} {len(names)} thẻ)")
    return ok


def _ensure_tax_box_open(page: Page, tax: str, timeout: float = 6.0) -> None:
    """Mở hộp taxonomy (nếu đang thu gọn) — bỏ class 'closed' + bấm tiêu đề nếu cần."""
    try:
        page.evaluate(
            """(tax) => { const b = document.getElementById(tax + 'div');
                if (b && b.classList.contains('closed')) b.classList.remove('closed'); }""",
            tax)
    except Exception:
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            vis = page.evaluate(
                """(tax) => { const l = document.getElementById(tax + 'checklist');
                    if (!l) return false;
                    return !!(l.offsetWidth || l.offsetHeight); }""", tax)
        except Exception:
            vis = True
        if vis:
            return
        try:
            page.locator(f"#{tax}div .hndle").first.click(timeout=2500)
        except Exception:
            pass
        page.wait_for_timeout(400)


def _taxonomy_terms_settled(page: Page, tax: str, timeout: float = 5.0) -> list:
    """Đọc danh sách term; nếu TRỐNG thì chờ thêm (trang có thể còn đang tải)."""
    terms = _taxonomy_terms(page, tax)
    if terms:
        return terms
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.wait_for_timeout(400)
        terms = _taxonomy_terms(page, tax)
        if terms:
            return terms
    return terms


def _find_term(page: Page, tax: str, want: str):
    """Tìm term theo tên (khớp KHÔNG DẤU): trùng khít -> bắt đầu bằng -> chứa."""

    def find():
        terms = _taxonomy_terms_settled(page, tax)
        if not terms:
            return None
        for t in terms:
            if _norm_vn(t["text"]) == want:
                return t
        for t in terms:
            if _norm_vn(t["text"]).startswith(want):
                return t
        for t in terms:
            if want in _norm_vn(t["text"]):
                return t
        return None

    hit = find()
    if hit is None:                      # thử tab "Tất cả" (nếu có) rồi tìm lại
        try:
            tab = page.locator(f"#{tax}-tab-all").first
            if tab.count():
                tab.click(timeout=3000)
                page.wait_for_timeout(400)
        except Exception:
            pass
        hit = find()
    return hit


def _is_term_checked(page: Page, tax: str, value: str) -> bool:
    """Có checkbox NÀO của term này đang được tick không (so theo GIÁ TRỊ, không theo id)."""
    if not value:
        return False
    try:
        return bool(page.evaluate(
            """([tax, v]) => Array.from(
                document.querySelectorAll('input[name="tax_input[' + tax + '][]"]'))
                .some(i => String(i.value) === String(v) && i.checked)""",
            [tax, str(value)]))
    except Exception:
        return False


def _tick_term(page: Page, tax: str, value: str, wait_ms: int = 4000) -> bool:
    """Tick term + KIỂM TRA LẠI.

    Ưu tiên CLICK BẰNG JS (không cần cuộn/chờ actionability -> không bị "đứng")
    rồi mới tới các cách dự phòng của Playwright.
    """
    if _is_term_checked(page, tax, value):
        return True

    # 1) JS: cuộn hộp vào khung nhìn + click các ô CHƯA tick của term này
    try:
        page.evaluate(
            """([tax, v]) => {
                const all = Array.from(document.querySelectorAll(
                    'input[name="tax_input[' + tax + '][]"]'));
                const list = all.filter(i => String(i.value) === String(v));
                if (!list.length) return;
                try {
                    const el = list[0].closest('li') || list[0];
                    el.scrollIntoView({block: 'center'});
                } catch (e) {}
                list.filter(i => !i.checked).forEach(i => {
                    try { i.click(); } catch (e) {}
                });
            }""", [tax, str(value)])
    except Exception:
        pass
    if _is_term_checked(page, tax, value):
        return True

    # 2) JS: bấm vào NHÃN của ô đầu tiên
    try:
        page.evaluate(
            """([tax, v]) => {
                const el = Array.from(document.querySelectorAll(
                    'input[name="tax_input[' + tax + '][]"]'))
                    .find(i => String(i.value) === String(v));
                if (!el) return;
                const lab = el.closest('label') || document.querySelector(`label[for="${el.id}"]`);
                if (lab) lab.click(); else el.click();
            }""", [tax, str(value)])
    except Exception:
        pass
    if _is_term_checked(page, tax, value):
        return True

    # 3) Playwright (dự phòng): cuộn tới rồi tick ô đang hiện
    sel = f'input[name="tax_input[{tax}][]"][value="{value}"]'
    try:
        cb = page.locator(sel).first
        if cb.count():
            try:
                cb.scroll_into_view_if_needed(timeout=4000)
            except Exception:
                pass
            try:
                cb.check(force=True, timeout=4000)
            except Exception:
                try:
                    cb.click(force=True, timeout=4000)
                except Exception:
                    pass
    except Exception:
        pass
    if _is_term_checked(page, tax, value):
        return True

    deadline = time.time() + wait_ms / 1000.0
    while time.time() < deadline:
        if _is_term_checked(page, tax, value):
            return True
        page.wait_for_timeout(250)
    return _is_term_checked(page, tax, value)


def _add_term_once(page: Page, tax: str, name: str, timeout: float = 12.0) -> str:
    """Thêm 1 term mới. Trả về id checkbox của term vừa thêm (nếu thấy), ngược lại ""."""
    _ensure_tax_box_open(page, tax)
    inp = page.locator(f"#new{tax}").first
    for _ in range(4):                   # mở ô "Thêm ... mới" (đang ĐÓNG mới bấm toggle)
        try:
            if inp.count() and inp.is_visible():
                break
        except Exception:
            pass
        try:
            toggle = page.locator(f"#{tax}-add-toggle").first
            if toggle.count():
                toggle.click(timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(400)
    if not inp.count():
        return ""
    try:
        inp.fill(name, timeout=5000)
    except Exception:                    # ô bị ẩn -> đặt giá trị trực tiếp
        try:
            page.evaluate(
                """([tax, v]) => { const i = document.getElementById('new' + tax);
                    if (!i) return;
                    i.value = v;
                    i.dispatchEvent(new Event('input', {bubbles: true}));
                    i.dispatchEvent(new Event('change', {bubbles: true})); }""",
                [tax, name])
        except Exception:
            return ""
    page.wait_for_timeout(200)
    btn = page.locator(f"#{tax}-add-submit").first
    if not btn.count():
        return ""
    try:
        btn.click(timeout=6000)
    except Exception:
        try:
            page.evaluate(
                """(tax) => { const b = document.getElementById(tax + '-add-submit');
                    if (b) b.click(); }""", tax)
        except Exception:
            return ""
    want = _norm_vn(name)
    deadline = time.time() + timeout
    while time.time() < deadline:        # chờ term mới xuất hiện trong danh sách
        page.wait_for_timeout(300)
        m = next((t for t in _taxonomy_terms(page, tax) if _norm_vn(t["text"]) == want), None)
        if m:
            return str(m.get("value") or "")
    return ""


def pick_taxonomy_term(page: Page, tax: str, name: str, label: str = "", log=None) -> bool:
    """Chọn 1 term trong hộp taxonomy của WooCommerce (product_cat / product_brand).

    - Đã có trên web  -> TICK đúng term + KIỂM TRA lại đã tick.
    - Chưa có         -> THÊM MỚI -> CHỜ term xuất hiện -> TICK chính term mới đó -> kiểm tra.
    `name` rỗng -> bỏ qua bước.
    """
    name = str(name or "").strip()
    label = label or tax
    if not name:
        if log:
            log(f"  (bỏ qua {label} — để trống)")
        return False
    want = _norm_vn(name)

    # 0) mở hộp metabox nếu đang thu gọn
    _ensure_tax_box_open(page, tax)

    # 1) ĐÃ CÓ -> tick + kiểm tra
    hit = _find_term(page, tax, want)
    if hit:
        ok = _tick_term(page, tax, str(hit.get("value") or ""))
        if log:
            log(f"  ({label}: {'đã chọn' if ok else 'KHÔNG tick được'} “{hit['text']}”"
                + ("" if ok else " — thử tick lại bằng tay trên web"))
        return ok

    # 2) CHƯA CÓ -> thêm mới (thử 2 lần) rồi CHỌN chính term mới
    new_val = ""
    for attempt in (1, 2):
        new_val = _add_term_once(page, tax, name)
        if new_val:
            break
        if attempt == 1 and log:
            log(f"  ({label}: chưa thấy “{name}” — thử thêm lại lần 2…")
    if not new_val:
        hit = _find_term(page, tax, want)      # có thể WP báo trùng -> term đã có sẵn
        if hit:
            ok = _tick_term(page, tax, str(hit.get("value") or ""))
            if log:
                log(f"  ({label}: đã có sẵn “{hit['text']}” -> "
                    + ("ĐÃ CHỌN" if ok else "KHÔNG tick được"))
            return ok
        if log:
            log(f"  ({label}: KHÔNG thêm được “{name}” — kiểm tra quyền/trùng tên")
        return False
    ok = _tick_term(page, tax, new_val)
    text = next((t["text"] for t in _taxonomy_terms(page, tax)
                 if str(t.get("value")) == str(new_val)), name)
    if log:
        log(f"  ({label}: chưa có -> ĐÃ THÊM MỚI “{text}”"
            + (" + ĐÃ CHỌN" if ok else " (CHƯA tick được — thử tick lại bằng tay)"))
    return ok


def fill_current_attachment_fields(page: Page, value: str = "", log=None) -> int:
    """Điền 4 ô của ảnh đang hiện (modal TRÊN CÙNG) — 1 lần, ưu tiên tiêu đề của chính ảnh."""
    return _fill_attachment_in_top_modal(page, value, log=log)


def save_post(page: Page, log=None, timeout: float = 120.0) -> bool:
    """Bấm nút Lưu/Cập nhật (#publish) và CHỜ WordPress lưu xong."""
    # Trạng thái KHÁC "publish" -> phải bấm nút LƯU (name="save"), KHÔNG bấm "Xuất bản"
    status = ""
    try:
        status = str(page.evaluate(
            "() => (document.querySelector('#post_status') || {}).value || ''") or "")
    except Exception:
        status = ""
    if status and status != "publish":
        sels = ("#save-post", "input[name='save']", "#publish")
    else:
        sels = ("#publish", "#save-post", "input[name='save']")
    btn = None
    for sel in sels:
        try:
            loc = page.locator(sel).first
            if loc.count():
                btn = loc
                break
        except Exception:
            continue
    if btn is None:
        if log:
            log("  (lưu: không thấy nút Lưu — bỏ qua)")
        return False
    url_before = ""
    try:
        url_before = page.url
    except Exception:
        pass
    if log:
        log("  (đang lưu…)")
    clicked = False
    try:
        btn.click(timeout=8000)
        clicked = True
    except Exception:
        clicked = False
    if not clicked:
        try:
            page.evaluate(
                """(sel) => { const b = document.querySelector(sel); if (b) b.click(); }""",
                sels[0])
        except Exception:
            if log:
                log("  (lưu: không bấm được nút Lưu)")
            return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.wait_for_timeout(600)
        try:
            url = page.url
        except Exception:
            break
        if url and url != url_before and ("post.php" in url or "message=" in url):
            if log:
                log("  (đã lưu xong — bài đang ở trạng thái đã chọn)")
            return True
        try:      # thông báo "Sản phẩm đã cập nhật." / "Product updated"
            txt = page.evaluate(
                """() => { const n = document.querySelector('#message, .notice-success, .updated');
                    return n ? (n.innerText || '') : ''; }""")
        except Exception:
            txt = ""
        low = str(txt or "").lower()
        if any(k in low for k in ("đã cập nhật", "đã lưu", "updated", "published", "đã đăng")):
            if log:
                log("  (đã lưu xong)")
            return True
    if log:
        log("  (lưu: chưa thấy xác nhận — kiểm tra trên web)")
    return False


def set_post_status(page: Page, status: str = "pending", label: str = "", log=None) -> bool:
    """Đổi TRẠNG THÁI bài viết/sản phẩm (ô #post_status) — KHÔNG bấm Lưu.

    Mặc định "Chờ duyệt" (pending). Người dùng tự bấm Lưu trên WordPress.
    """
    want = str(status or "pending").strip() or "pending"
    names = {"pending": "Chờ duyệt", "draft": "Bản nháp",
             "publish": "Xuất bản", "private": "Riêng tư"}
    lab = label or names.get(want, want)
    sel = None
    for s_ in ("#post_status", "select[name='post_status']"):
        try:
            loc = page.locator(s_).first
            if loc.count():
                sel = loc
                break
        except Exception:
            continue
    if sel is None:
        if log:
            log("  (trạng thái: không thấy ô trạng thái — bỏ qua)")
        return False
    try:
        cur = str(sel.input_value() or "")
    except Exception:
        cur = ""
    if cur == want:
        if log:
            log(f"  (trạng thái: đã là “{lab}”)")
        return True
    # ô trạng thái của WordPress thường BỊ ẨN -> bấm "Chỉnh sửa" để mở
    try:
        if not sel.is_visible():
            for s2 in ("#post-status-edit", "a.edit-post-status"):
                try:
                    loc = page.locator(s2).first
                    if loc.count():
                        loc.click(timeout=4000)
                        page.wait_for_timeout(400)
                        break
                except Exception:
                    continue
    except Exception:
        pass
    try:
        try:
            sel.select_option(want, timeout=6000)
        except Exception:            # vẫn ẩn -> đặt giá trị trực tiếp + bắn sự kiện change
            page.evaluate(
                """(v) => { const s = document.querySelector('#post_status');
                    if (!s) return;
                    s.value = v;
                    s.dispatchEvent(new Event('change', {bubbles: true})); }""", want)
        page.wait_for_timeout(400)
        for s2 in ("#post-status-save", "a.save-post-status"):
            try:
                ok_btn = page.locator(s2).first
                if ok_btn.count() and ok_btn.is_visible():
                    ok_btn.click(timeout=4000)
                    page.wait_for_timeout(400)
                    break
            except Exception:
                continue
        page.wait_for_timeout(300)
        now = str(sel.input_value() or "")
        if log:
            log(f"  (trạng thái -> “{lab}”" + ("" if now == want else f" (hiện: {now})") + ")")
        return now == want
    except Exception as exc:      # noqa: BLE001
        if log:
            log(f"  (trạng thái: lỗi — {str(exc)[:70]})")
        return False


def slug_if_needed(page: Page, new_slug: str, limit: int = 0, log=None) -> bool:
    """Đặt đường dẫn (slug) = slug đã make_slug (KHÔNG kiểm tra độ dài nữa).

    WordPress vừa sinh slug từ tiêu đề -> ghi đè luôn bằng slug sạch của app.
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
    if not str(new_slug or "").strip():
        return False
    if cur and cur == str(new_slug).strip():
        if log:
            log("  (slug đã đúng — không cần chỉnh)")
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


def wait_upload(page: Page, log=None, timeout: float = 300.0) -> bool:
    """Chờ ảnh vừa chọn TẢI LÊN XONG (có bảng chi tiết + tiêu đề) — tối đa 5 phút."""
    deadline = time.time() + timeout
    next_log = time.time() + 15.0
    start = time.time()
    while time.time() < deadline:
        try:
            if page.locator("#attachment-details-title:visible").count():
                try:
                    val = str(page.locator("#attachment-details-title:visible").first
                              .input_value(timeout=1500) or "").strip()
                except Exception:
                    val = ""
                if val:
                    if log:
                        log(f"  (ảnh đã tải lên xong sau {int(time.time() - start)}s)")
                    return True
        except Exception:
            pass
        if log and time.time() >= next_log:
            next_log = time.time() + 15.0
            log(f"  (đang chờ ảnh tải lên… {int(time.time() - start)}s / tối đa {int(timeout)}s)")
        page.wait_for_timeout(500)
    if log:
        log("  (hết thời gian chờ ảnh tải lên — đi tiếp)")
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
            # 3) bấm chọn file (không delay)
            page.locator("input[type='file']").first.set_input_files(f)
            # 4) chờ bảng chi tiết hiện (tối đa 300 giây = 5 phút mỗi ảnh)
            ok = False
            _t0 = time.time()
            _next = _t0 + 15.0
            for _ in range(600):
                page.wait_for_timeout(500)
                try:
                    if page.locator("#attachment-details-title:visible").count():
                        ok = True
                        break
                except Exception:
                    pass
                if log and time.time() >= _next:
                    _next = time.time() + 15.0
                    log(f"  (đang chờ ảnh tải lên… {int(time.time() - _t0)}s / tối đa 300s)")
            if ok:
                # 5) điền các ô TRỐNG — ƯU TIÊN tiêu đề của CHÍNH ẢNH trong modal này
                _fill_attachment_in_top_modal(page, fallback_title, log=log)
            elif log:
                log(f"  (ảnh {Path(f).name}: không thấy bảng chi tiết)")
            # 6) chờ WordPress LƯU XONG (đối chiếu server) rồi mới chèn
            try:
                page.evaluate(_WAIT_SAVED_JS, 20)
            except Exception:      # noqa: BLE001
                page.wait_for_timeout(600)
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

    - Chờ "Đang tải lên" biến mất (tối đa 300 giây — web chậm vẫn chờ).
    - Ảnh cần điền = các <li class="attachment selected"> TRONG MODAL ĐANG HIỆN (ảnh vừa upload);
      không có -> lấy theo danh sách đang chọn của wp.media; cuối cùng -> N ảnh đầu.
    - Giá trị = TIÊU ĐỀ CỦA CHÍNH ẢNH; ô nào đã có nội dung -> giữ nguyên.
    """
    val = str(value or "").strip()
    want = max(1, int(expect or 1))
    # 1) CHỜ upload xong: hết chữ "Đang tải lên" + đã có ảnh được chọn
    deadline = time.time() + 300
    _up_next_log = time.time() + 15.0
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
        if log and time.time() >= _up_next_log:
            _up_next_log = time.time() + 15.0
            log("  (đang tải ảnh lên… web chậm thì chờ thêm)")
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


def wait_editor_ready(page: Page, log=None, timeout: int = 60000) -> None:
    """Chờ trang soạn thảo (Gutenberg/Classic) SẴN SÀNG rồi mới phát lại kịch bản.

    Tối ưu: **KHUNG SOẠN THẢO CÓ MẶT LÀ ĐI** — không chờ `load`/`networkidle` nữa
    (WordPress có "nhịp tim" nên `networkidle` hay treo đủ 15 giây).
    Trang chậm thì tự quay lại cách chờ cũ.
    """
    _t0 = time.time()

    def _ready() -> bool:
        for sel in EDITOR_READY:
            try:
                if page.locator(sel).count() > 0:
                    return True
            except Exception:
                continue
        return False

    def _finish() -> None:
        # mạng ngắn (tối đa 1,5 giây) để dữ liệu danh mục/attribute kịp về
        try:
            page.wait_for_load_state("networkidle", timeout=1500)
        except Exception:
            pass
        _dismiss_overlays(page)
        _wait_editors_ready(page)

    try:
        page.wait_for_load_state("domcontentloaded", timeout=min(timeout, 20000))
    except Exception:
        pass

    # ĐƯỜNG NHANH: chờ khung soạn thảo xuất hiện (tối đa 8 giây)
    quick_deadline = min(time.time() + 8.0, _t0 + timeout / 1000.0)
    while time.time() < quick_deadline:
        if _ready():
            time.sleep(0.4)
            _finish()
            return
        time.sleep(0.15)

    # ĐƯỜNG CHẬM (trang nặng): chờ load ngắn rồi tìm lại
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception:
        pass
    if _ready():
        time.sleep(0.4)
        _finish()
        return

    # cuối cùng: chờ tới hạn rồi đi tiếp
    deadline = _t0 + timeout / 1000.0
    while time.time() < deadline:
        if _ready():
            time.sleep(0.4)
            break
        time.sleep(0.3)
    _finish()


def _dismiss_overlays(page: Page) -> None:
    """Đóng các popup hướng dẫn (Gutenberg welcome guide, WooCommerce tour…)."""
    try:
        if page.locator(".components-modal__screen-overlay").count() > 0:
            page.keyboard.press("Escape")
            time.sleep(0.4)
    except Exception:
        pass


def play(page: Page, script: Script, ctx: dict, log=None, delay: float = 0.4,
         hide_selectors: list | None = None) -> None:
    hide_elements(page, hide_selectors)      # ẩn khối không dùng TRƯỚC khi phát lại
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
                _dismiss_translate(page)                   # dọn popup Google dịch trước khi bấm
                loc = _locate(page, step)
                check = str(step.value or "").strip()      # value = selector KIỂM TRA (nếu có)
                if not check:
                    _safe_click(page, loc, force=bool(step.force))
                else:
                    # Bấm rồi KIỂM TRA phần tử cần mở đã hiện chưa -> chưa hiện thì bấm lại (tối đa 3 lần)
                    done = False
                    for _try in range(3):
                        try:
                            _safe_click(page, loc, force=bool(step.force))
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
                _dismiss_translate(page)
                value = render(step.value, ctx)
                try:
                    _locate(page, step).fill(value, force=bool(step.force), timeout=15000)
                except Exception:
                    # Ô soạn thảo TinyMCE đang ở chế độ "Trực quan" -> điền thẳng vào khung soạn thảo
                    if not _fill_editor_iframe(page, step, value, log=log):
                        raise
            elif action in ("save_post", "luu_bai", "submit_post"):
                save_post(page, log=log)
            elif action in ("wait_upload", "upload_wait", "wait_image_upload"):
                wait_upload(page, log=log)
            elif action in ("scroll_top", "scroll_to_top", "top"):
                scroll_top(page, log=log)
            elif action in ("add_tags", "add_tag", "tags_add"):
                add_tags(page, render(step.value or "{{tags}}", ctx),
                         input_sel=step.selector, log=log)
            elif action in ("set_status", "post_status", "status"):
                set_post_status(page, render(step.value or "pending", ctx), log=log)
            elif action in ("taxonomy_pick", "pick_term", "taxonomy_select"):
                # Chọn danh mục / thương hiệu (chưa có thì THÊM MỚI)
                tax = str(step.selector or "").strip() or "product_cat"
                lab = "Thương hiệu" if "brand" in tax else "Danh mục"
                pick_taxonomy_terms(page, tax, render(step.value, ctx), label=lab,
                                    multi=("brand" not in tax), log=log)
            elif action in ("attachment_fields", "fill_attachment_now"):
                # Điền 4 ô (Tiêu đề/Alt/Caption/Miêu tả) của ảnh đang hiện — MỘT LẦN
                fill_current_attachment_fields(page, render(step.value or "{{title}}", ctx), log=log)
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
