"""Phát lại kịch bản (điền form) trên trang WordPress."""
from __future__ import annotations

import re
import time

from playwright.sync_api import Page

from ..storage.models import Script, ScriptStep

_TOKEN_RE = re.compile(r"\{\{\s*([\w\.]+)\s*\}\}")


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


def _locate(page: Page, step: ScriptStep):
    """Tìm phần tử theo selector chính rồi tới các selector dự phòng."""
    last = None
    for sel in _selectors(step):
        try:
            if sel.startswith("text="):
                loc = page.get_by_text(sel[5:].strip('"'), exact=False)
            else:
                loc = page.locator(sel).first
            if loc.count() > 0:
                return loc
        except Exception as exc:  # selector sai -> thử tiếp
            last = exc
    if last:
        raise last
    raise RuntimeError("Không tìm thấy phần tử cho bước: " + (step.note or step.selector))


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
                else:
                    _locate(page, step).click()
            elif action == "click":
                _locate(page, step).click()
            elif action == "type":
                _locate(page, step).fill(render(step.value, ctx))
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
