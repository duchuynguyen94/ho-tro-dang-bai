"""Trình duyệt riêng của phần mềm (Playwright + Chrome)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from ..config import sessions_dir

# Ưu tiên dùng Chrome/Edge có sẵn; nếu không có thì dùng Chromium kèm theo.
CHANNELS = ["chrome", "chrome-beta", "msedge", None]

# Đường dẫn trình duyệt có sẵn trên máy (thử trực tiếp nếu "channel" không chạy được)
BROWSER_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]


def _user_data_dir(site_id: str) -> str:
    d = sessions_dir() / site_id
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _clear_profile_lock(user_data_dir: str) -> bool:
    """Xoá lock cũ của profile (do lần chạy trước bị tắt đột ngột).

    Không xoá nếu tiến trình đang giữ lock vẫn còn sống.
    """
    d = Path(user_data_dir)
    lock = d / "SingletonLock"
    try:
        if lock.is_symlink():
            target = str(os.readlink(str(lock)))
            pid = int(target.rsplit("-", 1)[-1])
            if pid > 0 and _pid_alive(pid):
                return False          # đang có tiến trình dùng profile -> không đụng vào
    except Exception:
        pass
    for name in LOCK_FILES:
        try:
            p = d / name
            if p.is_symlink() or p.exists():
                p.unlink()
        except OSError:
            pass
    return True


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

        attempts: list[tuple[str, dict]] = []
        for ch in CHANNELS:
            attempts.append((f"channel={ch}" if ch else "Chromium kèm theo", {"channel": ch} if ch else {}))
        for p in BROWSER_PATHS:
            if Path(p).exists():
                attempts.append((f"exe={Path(p).name}", {"executable_path": p}))

        errors: list[str] = []
        for label, extra in attempts:
            try:
                kwargs = dict(
                    user_data_dir=_user_data_dir(self.site_id),
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
                )
                if self.headless:
                    kwargs["viewport"] = {"width": 1400, "height": 900}
                else:
                    # cửa sổ mở TO HẾT màn hình: tránh bị che mất thanh cuộn / phần dưới
                    kwargs["no_viewport"] = True
                kwargs.update(extra)
                self.context = self._pw.chromium.launch_persistent_context(**kwargs)
                self.channel_used = label
                break
            except Exception as exc:  # thử cách khác
                first_line = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
                errors.append(f"- {label}: {first_line}")
                low = str(exc).lower()
                if ("singleton" in low or "profile" in low or "in use" in low
                        or "user data directory" in low or "processsingleton" in low):
                    _clear_profile_lock(_user_data_dir(self.site_id))
                try:
                    self._pw.stop()
                except Exception:
                    pass
                self._pw = sync_playwright().start()
        else:
            detail = "\n".join(errors) if errors else "không rõ"
            raise RuntimeError(
                "Không mở được trình duyệt. Đã thử:\n" + detail
                + "\n\nCách xử lý: cài Google Chrome, hoặc mở Cấu hình → website → "
                "kiểm tra lại."
            )

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(20000)
        return self.page

    # ------------------------------------------------------------------ #
    def login(self, site) -> bool:
        """Mở THẲNG trang tạo bài (theo cấu hình); nếu chưa đăng nhập thì tự đăng nhập."""
        page = self.open()
        base = (site.url or "").rstrip("/")
        if not base:
            return False
        target = (site.new_post_url or "").strip() or f"{base}/wp-admin/"
        page.goto(target, wait_until="domcontentloaded")
        time.sleep(1.2)
        if "/wp-login.php" not in page.url:
            return True  # session còn hiệu lực -> đang ở đúng trang tạo bài

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
            time.sleep(1.8)
        except PWTimeout:
            pass
        if "/wp-login.php" in page.url:
            return False
        # đăng nhập xong: quay lại trang tạo bài (WP thường tự chuyển về nhờ redirect_to)
        if site.new_post_url and "post-new.php" not in page.url:
            try:
                page.goto(site.new_post_url, wait_until="domcontentloaded")
                time.sleep(1.0)
            except Exception:
                pass
        return True

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
