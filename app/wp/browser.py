"""Trình duyệt riêng của phần mềm (Playwright + Chrome)."""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from ..config import sessions_dir

# Ưu tiên dùng Chrome/Edge có sẵn; nếu không có thì dùng Chromium kèm theo.
CHANNELS = ["chrome", "msedge", None]


def _user_data_dir(site_id: str) -> str:
    d = sessions_dir() / site_id
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


class WPBrowser:
    """Bọc 1 phiên trình duyệt gắn với 1 website (giữ session đăng nhập)."""

    def __init__(self, headless: bool = False, site_id: str = "default") -> None:
        self.headless = headless
        self.site_id = site_id
        self._pw = None
        self.context = None
        self.page: Page | None = None
        self.channel_used = ""

    # ------------------------------------------------------------------ #
    def open(self) -> Page:
        if self.page:
            return self.page
        self._pw = sync_playwright().start()
        last_err: Exception | None = None
        for channel in CHANNELS:
            try:
                kwargs = dict(
                    user_data_dir=_user_data_dir(self.site_id),
                    headless=self.headless,
                    viewport={"width": 1400, "height": 900},
                    args=["--disable-blink-features=AutomationControlled"],
                )
                if channel:
                    kwargs["channel"] = channel
                self.context = self._pw.chromium.launch_persistent_context(**kwargs)
                self.channel_used = channel or "chromium"
                break
            except Exception as exc:  # thử kênh khác
                last_err = exc
                try:
                    self._pw.stop()
                except Exception:
                    pass
                self._pw = sync_playwright().start()
        else:
            raise RuntimeError(f"Không mở được trình duyệt: {last_err}")

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(20000)
        return self.page

    # ------------------------------------------------------------------ #
    def login(self, site) -> bool:
        """Đăng nhập WordPress; trả True nếu đã đăng nhập."""
        page = self.open()
        base = (site.url or "").rstrip("/")
        if not base:
            return False
        admin = f"{base}/wp-admin/"
        page.goto(admin, wait_until="domcontentloaded")
        time.sleep(1.0)
        if "/wp-login.php" not in page.url:
            return True  # session còn hiệu lực

        page.goto(f"{base}/wp-login.php", wait_until="domcontentloaded")
        try:
            page.fill("#user_login", site.username or "")
            page.fill("#user_pass", site.get_password() or "")
            # tick "Ghi nhớ tài khoản" để Chrome lưu phiên đăng nhập
            try:
                remember = page.locator("#rememberme")
                if remember.count() > 0:
                    remember.check()
            except Exception:
                pass
            page.click("#wp-submit")
            page.wait_for_load_state("domcontentloaded")
            time.sleep(1.5)
        except PWTimeout:
            pass
        return "/wp-login.php" not in page.url

    def goto(self, url: str) -> None:
        page = self.open()
        page.goto(url, wait_until="domcontentloaded")

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self.context = None
        self.page = None
        self._pw = None
