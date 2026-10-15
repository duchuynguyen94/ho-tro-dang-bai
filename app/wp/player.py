"""Phát lại kịch bản (điền form) trên trang WordPress."""
from __future__ import annotations

import re
import time

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


def _locate(page: Page, step: ScriptStep):
    """Tìm phần tử theo selector chính rồi tới các selector dự phòng.

    Ưu tiên phần tử ĐANG HIỆN (tránh các input ẩn của WordPress/Gutenberg).
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
    # 2) không có cái nào hiện -> lấy cái đầu tiên tồn tại (để báo lỗi rõ ràng)
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
                _locate(page, step).click()
            elif action == "type":
                value = render(step.value, ctx)
                loc = _locate(page, step)
                try:
                    loc.fill(value)
                except Exception:
                    loc.click()
                    page.keyboard.insert_text(value)
            elif action == "select":
                _locate(page, step).select_option(render(step.value, ctx))
            elif action == "upload":
                paths = [render(p, ctx) for p in ctx.get("__upload_files", [])]
                _locate(page, step).set_input_files([p for p in paths if p])
            elif action == "press":
                _locate(page, step).press(render(step.value or "Enter", ctx))
            elif action == "wait":
                time.sleep(float(step.value or 1))
            else:
                if log:
                    log(f"  (bỏ qua hành động lạ: {action})")
        except Exception as exc:
            raise RuntimeError(f"Bước {i} ({step.note or action}) lỗi: {exc}") from exc
        time.sleep(delay)
