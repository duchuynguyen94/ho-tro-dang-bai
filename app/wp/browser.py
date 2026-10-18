"""Trình duyệt riêng của phần mềm (Playwright + Chrome)."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from ..config import sessions_dir

def _no_window_kwargs() -> dict:
    """Trên Windows: ẩn cửa sổ console khi gọi PowerShell/taskkill (tránh nháy cửa sổ)."""
    if os.name != "nt":
        return {}
    kw: dict = {}
    try:
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW      # type: ignore[attr-defined]
    except Exception:
        pass
    try:      # dự phòng cho bản Python cũ
        si = subprocess.STARTUPINFO()                          # type: ignore[attr-defined]
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW          # type: ignore[attr-defined]
        si.wShowWindow = 0                                     # SW_HIDE
        kw["startupinfo"] = si
    except Exception:
        pass
    return kw


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

# --------------------------------------------------------------------------- #
# Khoá theo PROFILE: mỗi website (và "chatgpt") chỉ cho 1 trình duyệt cùng lúc.
# Việc thứ 2 sẽ CHỜ việc thứ nhất đóng trình duyệt rồi tự chạy tiếp.
# --------------------------------------------------------------------------- #
_PROFILE_LOCKS: dict[str, threading.Lock] = {}
_PROFILE_LOCKS_GUARD = threading.Lock()


def profile_lock(site_id: str) -> threading.Lock:
    with _PROFILE_LOCKS_GUARD:
        return _PROFILE_LOCKS.setdefault(site_id or "default", threading.Lock())


def _pids_using_profile(user_data_dir: str) -> list[int]:
    """Các tiến trình Chrome/Edge đang dùng profile của app (do lần trước còn sót)."""
    pids: list[int] = []
    want = user_data_dir.lower()
    if os.name == "nt":
        try:
            ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*"
                  + user_data_dir.replace("'", "''") + "*' } | ForEach-Object { $_.ProcessId }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20,
                                 **_no_window_kwargs())
            for line in (out.stdout or "").splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            pass
        return pids
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,command="],
                             capture_output=True, text=True, timeout=15)
    except Exception:
        return pids
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if not line or want not in line.lower():
            continue
        pid_s, _, cmd = line.partition(" ")
        low = cmd.lower()
        if not any(k in low for k in ("chrome", "chromium", "msedge", "edge")):
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        if pid > 0 and pid != os.getpid():
            pids.append(pid)
    return pids


def _kill_profile_browsers(user_data_dir: str) -> int:
    """Tắt hẳn các tiến trình Chrome/Edge đang giữ profile của app.

    An toàn: chỉ đụng tới tiến trình có `--user-data-dir` = thư mục session của app
    (trình duyệt cá nhân của người dùng dùng profile khác).
    """
    pids = _pids_using_profile(user_data_dir)
    if not pids:
        return 0
    killed = 0
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=15, **_no_window_kwargs())
            else:
                os.kill(pid, signal.SIGTERM)
            killed += 1
        except Exception:
            pass
    if os.name != "nt":
        # chờ tối đa ~4s cho tiến trình thoát hẳn
        for _ in range(16):
            if not any(_pid_alive(p) for p in pids):
                break
            time.sleep(0.25)
        for pid in pids:                       # còn cứng đầu -> kill -9
            if _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
    return killed


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

    def __init__(self, headless: bool = False, site_id: str = "default",
                 log=None) -> None:
        self.headless = headless
        self.site_id = site_id
        self.log = log
        self._pw = None
        self.context = None
        self.page: Page | None = None
        self.channel_used = ""
        self._lock = None

    # ------------------------------------------------------------------ #
    def open(self) -> Page:
        if self.page:
            return self.page
        # mỗi profile chỉ 1 trình duyệt: chờ tới lượt (tối đa 30 phút)
        lock = profile_lock(self.site_id)
        if not lock.acquire(timeout=0.5):
            if self.log:
                self.log("Đang chờ trình duyệt của việc khác đóng lại…")
            if not lock.acquire(timeout=180):
                raise RuntimeError(
                    "Trình duyệt của việc khác đang mở quá lâu (quá 3 phút). "
                    "Hãy đóng cửa sổ Chrome đó rồi thử lại."
                )
        self._lock = lock
        try:
            return self._open_locked()
        except Exception:
            self._release_lock()
            raise

    def _release_lock(self) -> None:
        if self._lock is not None:
            try:
                self._lock.release()
            except Exception:
                pass
            self._lock = None

    def _open_locked(self) -> Page:
        self._pw = sync_playwright().start()

        attempts: list[tuple[str, dict]] = []
        for ch in CHANNELS:
            attempts.append((f"channel={ch}" if ch else "Chromium kèm theo", {"channel": ch} if ch else {}))
        for p in BROWSER_PATHS:
            if Path(p).exists():
                attempts.append((f"exe={Path(p).name}", {"executable_path": p}))

        errors: list[str] = []
        for label, extra in attempts:
            opened = False
            for retry in (False, True):
                try:
                    kwargs = dict(
                        user_data_dir=_user_data_dir(self.site_id),
                        headless=self.headless,
                        # giữ SANDBOX của Chrome (tránh cảnh báo "--no-sandbox")
                        chromium_sandbox=True,
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
                    opened = True
                    break
                except Exception as exc:  # thử cách khác
                    first_line = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
                    low = str(exc).lower()
                    in_use = any(k in low for k in (
                        "singleton", "in use", "existing browser session",
                        "user data directory", "processsingleton", "profile"))
                    if in_use and not retry:
                        # Chrome cũ còn giữ profile (lần chạy trước chưa tắt)
                        # -> tắt nó rồi thử lại CHÍNH cách này
                        d = _user_data_dir(self.site_id)
                        _clear_profile_lock(d)
                        _kill_profile_browsers(d)
                        _clear_profile_lock(d)
                        try:
                            self._pw.stop()
                        except Exception:
                            pass
                        self._pw = sync_playwright().start()
                        continue
                    errors.append(f"- {label}: {first_line}")
                    try:
                        self._pw.stop()
                    except Exception:
                        pass
                    self._pw = sync_playwright().start()
                    break
            if opened:
                break
        if self.context is None:
            detail = "\n".join(errors) if errors else "không rõ"
            raise RuntimeError(
                "Không mở được trình duyệt. Đã thử:\n" + detail
                + "\n\nCách xử lý: đóng hết cửa sổ Chrome của phần mềm rồi thử lại, "
                "hoặc cài Google Chrome, hoặc mở Cài đặt → website → kiểm tra lại."
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
        target = (site.new_post_url or "").strip() or f"{base}/wp-admin/post-new.php?post_type=product"
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
        self._release_lock()          # NHẢ KHOÁ TRƯỚC (đóng Chrome có thể treo lâu)
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
        self._release_lock()
        self._pw = None
