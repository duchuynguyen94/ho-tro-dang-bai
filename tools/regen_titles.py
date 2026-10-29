#!/usr/bin/env python3
"""Công cụ RIÊNG (chạy ngoài app): tạo lại Title + Slug cho sản phẩm ĐÃ PUBLISH.

Website mặc định: https://samoapumps.com
Danh sách:        /wp-admin/edit.php?post_status=publish&post_type=product

Luồng chạy TỪNG BÀI (mỗi bài 1 vòng):
  1) python tools/regen_titles.py next --manual
       - mở Chrome: BẠN TỰ ĐĂNG NHẬP (bấm captcha nếu có), script chờ rồi chạy tiếp
       - session lưu vào profile riêng -> lần sau thường không phải đăng nhập lại
       - mở bài kế tiếp, lấy: title cũ, slug cũ, content, danh mục, thương hiệu, SKU
       - dò MÃ SẢN PHẨM trong content -> tools/out/current.json
  2) AI (trong phiên chat) đọc current.json và ghi tools/out/proposal.json
       {"id": 123, "title_new": "...", "usp": "Giá kho", "note": "..."}
  3) python tools/regen_titles.py review --manual
       - mở trang HTML duyệt: title cũ -> title mới, slug cũ -> slug mới
       - tick "Áp dụng" rồi bấm "Lưu duyệt" -> tools/out/approved.json
  4) python tools/regen_titles.py apply --manual
       - backup title/slug cũ ra tools/out/backup_*.csv
       - mở trang sửa, điền Title + Slug, bấm Cập nhật, đọc lại để xác nhận

Lệnh phụ:
  login --manual   kiểm tra đăng nhập (mở trình duyệt, bạn tự bấm)
  list             lấy danh sách sản phẩm publish -> tools/out/products.json
  skip --id 123    bỏ qua 1 bài
  status           xem tiến độ
  usp              in danh sách USP + độ dài (để chọn vừa 55–75 ký tự)

Đăng nhập:
  --manual         bạn TỰ bấm đăng nhập (dùng khi có captcha / không muốn lưu mật khẩu)
  (không --manual) tự điền tài khoản/mật khẩu đã lưu; GẶP CAPTCHA thì tự chuyển sang chờ bạn bấm
  --login-wait N   số giây chờ bạn đăng nhập (mặc định 600)

Tài khoản (chỉ dùng khi KHÔNG có --manual): tools/.regen_secret.json (600, đã gitignore)
           hoặc biến môi trường HTDB_WP_USER / HTDB_WP_PASS.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import html
import json
import os
import re
import sys
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_DIR = TOOLS_DIR.parent
OUT_DIR = TOOLS_DIR / "out"
PROFILE_DIR = TOOLS_DIR / ".regen_profile"
SECRET_FILE = TOOLS_DIR / ".regen_secret.json"
STATE_FILE = OUT_DIR / "state.json"
CURRENT_FILE = OUT_DIR / "current.json"
PROPOSAL_FILE = OUT_DIR / "proposal.json"
APPROVED_FILE = OUT_DIR / "approved.json"
PRODUCTS_FILE = OUT_DIR / "products.json"
LOCK_FILE = OUT_DIR / ".run.lock"

DEFAULT_BASE = "https://samoapumps.com"
CDP_PORT = 9222                       # Chrome giữ mở -> các lệnh nối vào cùng cửa sổ
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)
LIST_PATH = "/wp-admin/edit.php?post_status=publish&post_type=product"
TITLE_MIN, TITLE_MAX = 55, 75   # chấp nhận 55–75 (khuyến nghị 60–70)
SLUG_MAX = 75

# USP: danh sách người dùng chốt + chuẩn rule_seo.pdf + gợi ý thêm.
# Mỗi title chỉ dùng 1 USP (chọn ngẫu nhiên, ưu tiên vừa 55–75 ký tự).
USPS = (
    # nhóm chính
    "Chính hãng",
    "Giá tốt",
    "Giá kho",
    "Báo giá nhanh",
    "Hàng sẵn",
    "Giao nhanh",
    "Tổng kho",
    "Đại lý Việt Nam",
    "Nhập khẩu Tây Ban Nha",
    "CO/CQ đầy đủ",
    # nhóm bổ sung
    "Bảo hành chính hãng",
    "Hỗ trợ kỹ thuật",
    "Giao hàng toàn quốc",
    "Mua ở đâu",
    "Nơi bán",
    "Tại sao chọn",
    "Hàng mới 100%",
    "Kỹ sư tư vấn",
)

# --------------------------------------------------------------------------- #
# Slug — GIỮ ĐỒNG BỘ với app/wp/player.py (make_slug) + bổ sung đuôi USP mới
# --------------------------------------------------------------------------- #
SLUG_TAIL_PHRASES = (
    "hang-chinh-hang",
    "co-cq-day-du",
    "cocq-day-du",
    "bao-gia-nhanh",
    "bao-gia-nhanh-chinh-hang",
    "bao-gia-nhanh-toan-quoc",
    "hang-san",
    "phan-phoi-chinh-hang-viet-nam",
    "phan-phoi-chinh-hang",
    "ho-tro-ky-thuat",
    "bao-hanh-chinh-hang",
    "chinh-hang",
    "gia-tot",
    "giao-nhanh",
    "dai-ly",
    "phan-phoi",
    # --- bổ sung cho danh sách USP của samoapumps ---
    "gia-kho",
    "dai-ly-viet-nam",
    "nhap-khau-tay-ban-nha",
    "tong-kho",
    "giao-hang-toan-quoc",
    "mua-o-dau",
    "noi-ban",
    "tai-sao-chon",
    "hang-moi-100",
    "mien-phi-van-chuyen",
    "ky-su-tu-van",
    "doi-tra-1-1",
)


def _strip_slug_tails(s: str) -> str:
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


def make_slug(text: str, max_len: int = SLUG_MAX) -> str:
    """Tạo slug từ tiêu đề: bỏ dấu tiếng Việt, thường hoá, nối bằng '-'."""
    s = (text or "").strip().lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = _strip_slug_tails(s)
    if len(s) > max_len:
        cut = s[:max_len]
        if "-" in cut:
            cut = cut[: cut.rfind("-")]
        s = cut.rstrip("-") or s[:max_len].rstrip("-")
    return s


# --------------------------------------------------------------------------- #
# Tiện ích chung
# --------------------------------------------------------------------------- #
def log(msg: str = "") -> None:
    print(msg, flush=True)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict:
    st = _read_json(STATE_FILE, {})
    if not isinstance(st, dict):
        st = {}
    st.setdefault("base", DEFAULT_BASE)
    st.setdefault("queue", [])
    st.setdefault("items", {})
    st.setdefault("updated_at", "")
    return st


def save_state(st: dict) -> None:
    st["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(STATE_FILE, st)


def html_to_text(raw: str, limit: int = 9000) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw or "", flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|h[1-6]|li|tr)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.strip()
    return s[:limit]


# --------------------------------------------------------------------------- #
# Dò MÃ SẢN PHẨM trong content
# --------------------------------------------------------------------------- #
_CODE_AFTER_KW = re.compile(
    r"(?:m[aã]\s*s[ảa]n\s*ph[ẩa]m|m[aã]\s*h[àa]ng|model|part\s*(?:no|number)|"
    r"m[aã]\s*hi[ệe]u|sku)\s*[:#\-–]?\s*([A-Za-z0-9][A-Za-z0-9./_\-]{2,30})",
    re.I,
)
_CODE_GENERIC = re.compile(r"\b(?=[A-Za-z0-9./_\-]*\d)[A-Za-z0-9][A-Za-z0-9./_\-]{3,29}\b")
_BAD_CODE = re.compile(
    r"^(?:https?|www|com|vn|html|php|202\d|19\d\d|24/7|co|cq|vat|tp|hcm|hn)$",
    re.I,
)


def _code_ok(code: str) -> bool:
    c = code.strip(" .,;:()[]").strip()
    if len(c) < 4 or len(c) > 30:
        return False
    if _BAD_CODE.match(c):
        return False
    if not re.search(r"\d", c):          # mã sản phẩm luôn có số
        return False
    if not re.search(r"[A-Za-z]{2,}", c) and not re.search(r"[A-Za-z]\d|\d[A-Za-z]", c):
        return False
    if c.lower() in ("http", "https", "www"):
        return False
    # loại số điện thoại / số tiền / phần trăm
    if re.fullmatch(r"[\d.,%]+", c):
        return False
    return True


def detect_codes(text: str) -> list[dict]:
    """Trả về mã sản phẩm nghi ngờ, ưu tiên mã đứng sau từ khoá (Model/Mã sản phẩm)."""
    found: dict[str, dict] = {}
    for m in _CODE_AFTER_KW.finditer(text or ""):
        code = m.group(1).strip(" .,;:()[]")
        if _code_ok(code):
            rec = found.setdefault(code, {"code": code, "hits": 0, "from_keyword": True})
            rec["hits"] += 1
            rec["from_keyword"] = True
    for m in _CODE_GENERIC.finditer(text or ""):
        code = m.group(0).strip(" .,;:()[]")
        if _code_ok(code):
            rec = found.setdefault(code, {"code": code, "hits": 0, "from_keyword": False})
            rec["hits"] += 1
    out = sorted(found.values(), key=lambda r: (not r["from_keyword"], -r["hits"], -len(r["code"])))
    return out[:12]


# --------------------------------------------------------------------------- #
# Trình duyệt + đăng nhập
# --------------------------------------------------------------------------- #
def _accept_dialog(d) -> None:
    """Tự đồng ý confirm/prompt (bỏ qua lỗi 'No dialog is showing')."""
    try:
        d.accept()
    except Exception:
        pass


H1_RE = re.compile(r"<h1\b[^>]*>.*?</h1>", re.I | re.S)
SITE_LINK = "http://www.ngochuyduong.com/"
BRAND_LINK = "https://samoapumps.com/"      # link chèn vào 1 mã sản phẩm trong content
A_RE = re.compile(r"<a\b[^>]*>.*?</a>", re.I | re.S)


def with_linked_h1(content_html: str, title: str) -> tuple[str, str]:
    """Đặt <h1> = link về ngochuyduong.com với nội dung là Title mới.

    Trả về (html_mới, "replaced" | "inserted").
    """
    esc = html.escape((title or "").strip())
    new_h1 = f'<h1><a href="{SITE_LINK}">{esc}</a></h1>'
    src = content_html or ""
    m = H1_RE.search(src)
    if m:
        return src[: m.start()] + new_h1 + src[m.end():], "replaced"
    return new_h1 + "\n" + src, "inserted"


def with_brand_link(content_html: str, model: str) -> tuple[str, str]:
    """Bọc LINK CHÍNH vào lần xuất hiện ĐẦU TIÊN của mã sản phẩm trong content.

    Trả về (html_mới, "linked" | "already" | "no-model" | "not-found").
    Không chèn vào trong <a> có sẵn hay vào trong thẻ HTML.
    """
    src = content_html or ""
    code = (model or "").strip()
    if not code:
        return src, "no-model"

    # gỡ các link samoapumps.com đã có (tránh sai mã từ lần trước)
    src = re.sub(
        r'<a\b[^>]*href=["\']' + re.escape(BRAND_LINK) + r'["\'][^>]*>(.*?)</a>',
        r"\1",
        src,
        flags=re.I | re.S,
    )

    # vùng đã là link -> bỏ qua
    skip: list[tuple[int, int]] = [(m.start(), m.end()) for m in A_RE.finditer(src)]
    low = src.lower()
    needle = code.lower()
    start = 0
    while True:
        idx = low.find(needle, start)
        if idx < 0:
            return src, "not-found"
        end = idx + len(needle)
        inside_link = any(a <= idx < b for a, b in skip)
        inside_tag = False
        # nằm trong thẻ HTML? (giữa '<' và '>')
        lt = src.rfind("<", 0, idx)
        gt = src.rfind(">", 0, idx)
        if lt > gt:
            inside_tag = True
        if not inside_link and not inside_tag:
            if any(a <= idx < b for a, b in skip):
                return src, "already"
            return src[:idx] + f'<a href="{BRAND_LINK}">{src[idx:end]}</a>' + src[end:], "linked"
        start = end


def cdp_alive(timeout: float = 1.5) -> bool:
    """Chrome đang mở với cổng debug? (để nối vào thay vì mở cửa sổ mới)"""
    import urllib.request

    try:
        with urllib.request.urlopen(CDP_URL + "/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def find_chrome() -> str:
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    return ""


def load_credentials() -> tuple[str, str]:
    user = (os.environ.get("HTDB_WP_USER") or "").strip()
    pwd = os.environ.get("HTDB_WP_PASS") or ""
    if user and pwd:
        return user, pwd
    data = _read_json(SECRET_FILE, {})
    if isinstance(data, dict) and data.get("username") and data.get("password"):
        return str(data["username"]), str(data["password"])
    log("Chưa có tài khoản đăng nhập (tools/.regen_secret.json).")
    user = user or input("Tài khoản (username/email): ").strip()
    pwd = pwd or getpass.getpass("Mật khẩu: ")
    if not user or not pwd:
        raise SystemExit("Thiếu tài khoản hoặc mật khẩu.")
    save = input("Lưu lại cho lần sau? [Y/n] ").strip().lower() in ("", "y", "yes")
    if save:
        SECRET_FILE.write_text(
            json.dumps({"username": user, "password": pwd}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            SECRET_FILE.chmod(0o600)
        except Exception:
            pass
        log(f"Đã lưu: {SECRET_FILE}")
    return user, pwd


class Browser:
    """Playwright + Chrome (profile riêng của tool, KHÔNG dùng chung profile của app)."""
    def __init__(self, base: str, headless: bool = False, manual: bool = False,
                 login_wait: int = 600) -> None:
        self.base = (base or DEFAULT_BASE).rstrip("/")
        self.headless = headless
        self.manual = manual            # True = người dùng tự bấm đăng nhập (captcha)
        self.login_wait = max(60, int(login_wait))
        self._pw = None
        self.context = None
        self.page = None
        self._user, self._pass = "", ""
        self._external = False          # True = đang nối vào Chrome có sẵn (không tự đóng)

    # -- vòng đời -- #
    def open(self):
        if self.page:
            return self.page
        from playwright.sync_api import sync_playwright

        # Có Chrome đang mở (lệnh `start`) -> nối vào cửa sổ đó, KHÔNG mở cửa sổ mới
        if not self.headless and cdp_alive():
            self._pw = sync_playwright().start()
            try:
                browser = self._pw.chromium.connect_over_cdp(CDP_URL)
            except Exception as exc:      # noqa: BLE001
                self._pw.stop()
                self._pw = None
                raise SystemExit(
                    "Chrome đang mở nhưng không điều khiển được:\n"
                    f"  {str(exc).splitlines()[0][:160]}\n"
                    "Cách xử lý: chạy `tools/regen_titles.py stop` (hoặc đóng cửa sổ Chrome) "
                    "rồi `start` lại."
                )
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            self.context = ctx
            self._external = True
            self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
            log("Đang dùng Chrome đã mở sẵn (không mở thêm cửa sổ).")
            try:
                self.page.on("dialog", _accept_dialog)
            except Exception:
                pass
            try:
                self.page.set_default_timeout(60000)
                self.page.set_default_navigation_timeout(120000)
            except Exception:
                pass
            return self.page

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=self.headless,
            chromium_sandbox=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--disable-background-mode",
                "--disable-translate",
                "--disable-features=Translate,TranslateUI",
                "--no-default-browser-check",
            ],
        )
        if self.headless:
            kwargs["viewport"] = {"width": 1400, "height": 900}
        else:
            kwargs["no_viewport"] = True

        errors = []
        for channel in ("chrome", "msedge", None):
            try:
                self.context = self._pw.chromium.launch_persistent_context(
                    channel=channel, **kwargs
                )
                break
            except Exception as exc:      # noqa: BLE001
                errors.append(f"- {channel or 'Chromium kèm theo'}: {str(exc).splitlines()[0][:160]}")
                if channel is None:
                    raise SystemExit(
                        "Không mở được trình duyệt. Đã thử:\n"
                        + "\n".join(errors)
                        + "\nCách xử lý: đóng các cửa sổ Chrome còn giữ profile rồi chạy lại, "
                        "hoặc cài Google Chrome."
                    )
                self._pw.stop()
                self._pw = sync_playwright().start()

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        try:
            # Tự đồng ý hộp thoại (confirm "rời trang?" …) để không chặn việc lưu
            self.page.on("dialog", _accept_dialog)
        except Exception:
            pass
        try:
            self.page.set_default_timeout(60000)
            self.page.set_default_navigation_timeout(120000)
        except Exception:
            pass
        return self.page

    def close(self) -> None:
        if self._external:
            # Chrome do lệnh `start` mở -> chỉ ngắt kết nối, giữ cửa sổ cho bước sau
            self.context = None
            self.page = None
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass
            self._pw = None
            self._external = False
            return
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

    # -- đăng nhập -- #
    @staticmethod
    def _has_captcha(page) -> bool:
        try:
            return page.locator(
                ".g-recaptcha, #g-recaptcha-response, iframe[src*='recaptcha'], "
                ".h-captcha, iframe[src*='hcaptcha'], #captcha, "
                "input[name*='captcha' i]"
            ).count() > 0
        except Exception:
            return False

    def _logged_in(self) -> bool:
        page = self.page
        if not page:
            return False
        try:
            bar = page.locator("#wpadminbar")
            if bar.count() and bar.first.is_visible():
                return True
        except Exception:
            pass
        try:
            return "wp-login.php" not in page.url and "/wp-admin" in page.url
        except Exception:
            return False

    def _wait_login_done(self, timeout: int | None = None) -> None:
        """Chờ NGƯỜI DÙNG tự đăng nhập trong cửa sổ Chrome (có captcha)."""
        page = self.open()
        wait = timeout or self.login_wait
        log("")
        log("─" * 70)
        log("MỜI BẠN TỰ ĐĂNG NHẬP trong cửa sổ Chrome vừa mở")
        log("  (nhập tài khoản / mật khẩu + bấm captcha nếu có)")
        log(f"  Script sẽ tự chạy tiếp khi đăng nhập xong (chờ tối đa {wait // 60} phút).")
        log("─" * 70)
        deadline = time.time() + wait
        last_note = 0.0
        while time.time() < deadline:
            if self._logged_in():
                time.sleep(0.6)
                log("Đã đăng nhập — tiếp tục.")
                return
            if time.time() - last_note > 20:
                last_note = time.time()
                log(f"  … đang chờ đăng nhập ({int(deadline - time.time())} giây còn lại)")
            time.sleep(0.8)
        raise SystemExit("Hết thời gian chờ đăng nhập. Chạy lại lệnh và đăng nhập sớm hơn nhé.")

    def _manual_login(self) -> None:
        page = self.open()
        self._goto(self.base + "/wp-login.php")
        self._settle(4000)
        self._wait_login_done()
        try:
            self._goto(self.base + LIST_PATH)
            self._settle(4000)
        except Exception:
            pass

    def login(self) -> None:
        page = self.open()
        # nhanh: Chrome đang giữ phiên ở trang quản trị -> khỏi mở lại
        try:
            if "/wp-admin/" in (page.url or "") and page.locator("#wpadminbar").count():
                return
        except Exception:
            pass
        target = self.base + LIST_PATH
        self._goto(target)
        self._settle(4000)
        if "/wp-login.php" not in page.url:
            log("Đã đăng nhập (session còn hiệu lực).")
            return
        if self.manual:
            self._manual_login()
            return
        log("Chưa đăng nhập → tự đăng nhập…")
        page.goto(self.base + "/wp-login.php", wait_until="domcontentloaded")
        self._user, self._pass = load_credentials()
        try:
            page.fill("#user_login", self._user)
            page.fill("#user_pass", self._pass)
        except Exception:
            pass
        if self._has_captcha(page):
            log("Trang đăng nhập CÓ CAPTCHA → chuyển sang chế độ bạn tự bấm.")
            self._wait_login_done()
            return
        try:
            remember = page.locator("#rememberme")
            if remember.count() > 0:
                remember.check()
        except Exception:
            pass
        page.click("#wp-submit")
        page.wait_for_load_state("domcontentloaded")
        time.sleep(0.9)
        if "/wp-login.php" in page.url:
            if self._has_captcha(page):
                self._wait_login_done()
                return
            raise SystemExit("Đăng nhập THẤT BẠI — kiểm tra lại tài khoản/mật khẩu (hoặc chạy với --manual).")
        log("Đăng nhập thành công.")

    # -- mở trang (có thử lại khi mạng chậm) -- #
    def _goto(self, url: str, timeout: int = 60000) -> bool:
        page = self.open()
        for attempt in (1, 2):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                return True
            except Exception as exc:      # noqa: BLE001
                log(f"  ⚠ Mở trang chậm/lỗi (lần {attempt}): {str(exc).splitlines()[0][:140]}")
                # dọn hộp thoại "rời trang?" (nguyên nhân gây ERR_ABORTED)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                try:
                    page.evaluate("window.onbeforeunload = null")
                except Exception:
                    pass
                try:
                    page.evaluate("u => { window.location.href = u; }", url)
                except Exception:
                    pass
                time.sleep(1.5)
        return False

    # -- chờ trang thật sự sẵn sàng -- #
    def _settle(self, timeout: int = 4000) -> None:
        """Chờ trang tải xong (load) rồi nghỉ ngắn — KHÔNG chờ networkidle (chậm)."""
        page = self.page
        if not page:
            return
        try:
            page.wait_for_load_state("load", timeout=timeout)
        except Exception:
            pass
        try:
            page.wait_for_timeout(250)
        except Exception:
            pass

    def _wait_slug(self, slug: str, timeout: float = 10.0) -> bool:
        """Chờ tới khi ô đường dẫn hiển thị đúng slug mới (AJAX có thể trả về chậm)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._current_slug() == slug:
                return True
            time.sleep(0.3)
        return self._current_slug() == slug

    # -- đọc dữ liệu -- #
    def list_products(self) -> list[dict]:
        page = self.open()
        url = self.base + LIST_PATH
        products: list[dict] = []
        seen: set[int] = set()
        for _ in range(200):
            if not self._goto(url):
                break
            page.wait_for_selector("#the-list, .wp-list-table", timeout=60000)
            self._settle(4000)
            rows = page.eval_on_selector_all(
                "#the-list tr, .wp-list-table tbody tr",
                """rows => rows.map(tr => {
                    const a = tr.querySelector('a.row-title, td.title a, strong a');
                    const id = (tr.id || '').replace('post-', '');
                    return a ? {id: id, title: a.innerText.trim(), link: a.href} : null;
                }).filter(Boolean)""",
            )
            for r in rows:
                try:
                    pid = int(str(r.get("id") or "").strip())
                except Exception:
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                products.append({"id": pid, "title": r.get("title", ""), "link": r.get("link", "")})
            nxt = page.eval_on_selector_all("a.next-page", "as => as.map(a => a.href)")
            if not nxt:
                break
            url = nxt[0]
        return products

    def read_product(self, pid: int, model_code: str = "", reload: bool = True) -> dict:
        page = self.open()
        edit_url = f"{self.base}/wp-admin/post.php?post={pid}&action=edit"
        if reload:
            if not self._goto(edit_url):
                raise SystemExit(f"Không mở được trang sửa #{pid} (mạng chậm?) — thử lại sau.")
            try:
                page.wait_for_selector(
                    "#title, .editor-post-title__input, [aria-label*='tiêu đề' i]", timeout=60000
                )
            except Exception:
                pass
            self._settle(6000)

        title = ""
        try:
            if page.locator("#title").count():
                title = page.locator("#title").first.input_value()
            elif page.locator(".editor-post-title__input").count():
                title = page.locator(".editor-post-title__input").first.inner_text()
        except Exception:
            pass

        content_html = ""
        if page.locator("#content").count():
            try:
                content_html = page.locator("#content").first.input_value()
            except Exception:
                content_html = ""
        if not content_html:
            try:
                content_html = page.eval_on_selector(
                    ".block-editor-block-list__layout, .editor-styles-wrapper",
                    "el => el ? el.innerHTML : ''",
                )
            except Exception:
                content_html = ""

        slug = self._current_slug()

        sku = ""
        try:
            if page.locator("#_sku").count():
                sku = page.locator("#_sku").first.input_value().strip()
        except Exception:
            pass

        try:
            taxes = page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll("div[id$='checklist'] input[type=checkbox]:checked")
                      .forEach(cb => out.push((cb.parentElement && cb.parentElement.innerText || '').trim()));
                    return out;
                }"""
            )
        except Exception:
            taxes = []

        h1_html = ""
        m_h1 = H1_RE.search(content_html or "")
        if m_h1:
            h1_html = m_h1.group(0)
        h1_text = html_to_text(h1_html, limit=400).strip()
        focus_kw = self._read_focus_keyword()
        brand_links = len(re.findall(r'href=["\']' + re.escape(BRAND_LINK) + r'["\']', content_html or "", re.I))
        model_linked = False
        if model_code:
            pat = re.compile(
                r'<a\b[^>]*href=["\']' + re.escape(BRAND_LINK) + r'["\'][^>]*>\s*'
                + re.escape(model_code) + r'\s*</a>',
                re.I,
            )
            model_linked = bool(pat.search(content_html or ""))
        text = html_to_text(content_html)
        return {
            "id": pid,
            "h1_text": h1_text,
            "h1_has_link": bool(h1_html) and SITE_LINK in h1_html,
            "focus_keyword": focus_kw,
            "brand_links": brand_links,
            "model_linked": model_linked,
            "edit_url": edit_url,
            "public_url": f"{self.base}/product/{slug}/" if slug else "",
            "title_old": title.strip(),
            "slug_old": slug,
            "sku": sku,
            "taxonomies": [t for t in (taxes or []) if t],
            "content_text": text,
            "codes": detect_codes(f"{title}\n{text}"),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }

    # -- ghi dữ liệu -- #
    def _edit_url(self, pid: int) -> str:
        return f"{self.base}/wp-admin/post.php?post={pid}&action=edit"

    def _current_slug(self) -> str:
        """Slug ĐẦY ĐỦ: #editable-post-name-full -> #post_name -> href permalink.

        KHÔNG dùng text của #sample-permalink (WP rút gọn bằng dấu …).
        """
        page = self.page
        if not page:
            return ""
        for sel in ("#editable-post-name-full", "#post_name"):
            try:
                if page.locator(sel).count():
                    val = page.locator(sel).first.evaluate(
                        "el => (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')"
                        " ? (el.value || '') : (el.textContent || '')"
                    )
                    val = (val or "").strip().strip("/")
                    if val:
                        return val
            except Exception:
                pass
        try:
            if page.locator("#sample-permalink a").count():
                href = page.locator("#sample-permalink a").first.get_attribute("href") or ""
                parts = [p for p in href.split("?")[0].split("/") if p]
                if parts:
                    return parts[-1]
        except Exception:
            pass
        return ""

    def set_slug(self, pid: int, slug: str) -> bool:
        """Đổi slug: điền thẳng ô ẩn #post_name của form (WP lưu khi bấm Cập nhật).

        Vì AJAX "Đồng ý" của WordPress có thể không chạy (site dùng plugin/JS lỗi),
        nên ưu tiên cách chắc chắn: gán #post_name -> bấm Cập nhật là slug đổi.
        Nếu không có #post_name thì mới dùng giao diện Chỉnh sửa -> OK.
        """
        page = self.open()
        edit_url = self._edit_url(pid)
        if self._current_slug() == slug:
            return True

        # --- Cách 1: gán ô ẩn #post_name (form sẽ gửi lên khi Cập nhật) ---
        try:
            if page.locator("#post_name").count():
                done = page.evaluate(
                    """(slug) => {
                        const el = document.querySelector('#post_name');
                        if (!el) return false;
                        el.value = slug;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        const full = document.querySelector('#editable-post-name-full');
                        if (full) full.textContent = slug;
                        const name = document.querySelector('#editable-post-name');
                        if (name && name.tagName !== 'INPUT') name.textContent = slug;
                        return el.value === slug;
                    }""",
                    slug,
                )
                if done and self._current_slug() == slug:
                    return True
        except Exception as exc:      # noqa: BLE001
            log(f"  ⚠ Không gán được ô slug ẩn: {str(exc).splitlines()[0][:140]}")

        # --- Cách 2: giao diện Chỉnh sửa -> nhập -> OK ---
        for attempt in (1, 2):
            try:
                btn = page.locator(
                    "#edit-slug-buttons .edit-slug, button.edit-slug, a.edit-slug"
                )
                if btn.count():
                    btn.first.click(force=True)
                inp = page.locator("#new-post-slug")
                inp.wait_for(state="visible", timeout=10000)
                inp.fill(slug)
                save = page.locator("#edit-slug-buttons button.save, #edit-slug-buttons .save")
                if save.count():
                    try:
                        # chờ ĐÚNG phản hồi AJAX của WordPress rồi mới kiểm tra
                        with page.expect_response(
                            lambda r: "admin-ajax.php" in r.url, timeout=10000
                        ):
                            save.first.click()
                    except Exception:
                        save.first.click()
                else:
                    inp.press("Enter")
                self._wait_slug(slug, timeout=10.0)
            except Exception as exc:      # noqa: BLE001
                log(f"  ⚠ Lỗi thao tác ô slug (lần {attempt}): {str(exc).splitlines()[0][:140]}")

            if self._current_slug() == slug:
                return True
            if "post.php" not in page.url:
                log("  ⚠ Trang bị chuyển hướng -> quay lại trang sửa…")
                try:
                    self._goto(edit_url)
                    page.wait_for_selector("#title, .editor-post-title__input", timeout=60000)
                    self._settle(1500)
                except Exception:
                    pass
        return self._current_slug() == slug

    def _fill_content(self, html_text: str) -> bool:
        """Ghi HTML vào ô Mô tả sản phẩm bằng JS (cập nhật cả textarea lẫn TinyMCE)."""
        page = self.open()
        if not page.locator("#content").count():
            return False
        try:
            page.evaluate(
                """(html) => {
                    const ta = document.querySelector('#content');
                    if (!ta) return false;
                    ta.value = html;
                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                    ta.dispatchEvent(new Event('change', { bubbles: true }));
                    try {
                        const ed = window.tinymce ? window.tinymce.get('content') : null;
                        if (ed && !ed.isHidden()) ed.setContent(html);
                    } catch (e) {}
                    return true;
                }""",
                html_text,
            )
            return True
        except Exception:
            return False

    def _read_focus_keyword(self, timeout: float = 2.0) -> str:
        page = self.page
        if not page:
            return ""
        deadline = time.time() + timeout
        val = ""
        while time.time() < deadline:
            try:
                val = page.evaluate(
                    """() => {
                        const box = document.querySelector('.rank-math-focus-keyword');
                        if (!box) return '';
                        const tags = [...box.querySelectorAll('.tagify__tag-text')]
                            .map(e => e.textContent.trim()).filter(Boolean);
                        if (tags.length) return tags.join(', ');
                        const t = box.querySelector('.tagify');
                        return (t && t.value) ? String(t.value).trim() : '';
                    }"""
                ) or ""
            except Exception:
                val = ""
            if val:
                return val
            time.sleep(0.3)
        return val

    def _focus_tags(self) -> list[str]:
        page = self.page
        try:
            return page.evaluate(
                """() => {
                    const box = document.querySelector('.rank-math-focus-keyword');
                    if (!box) return [];
                    return [...box.querySelectorAll('.tagify__tag-text')]
                        .map(e => e.textContent.trim()).filter(Boolean);
                }"""
            ) or []
        except Exception:
            return []

    def _set_focus_keyword(self, keyword: str) -> bool:
        """Xoá Focus Keyword cũ (Rank Math) và thêm keyword mới.

        Trả True/False; None nếu không có ô (bài không dùng Rank Math).
        """
        if not keyword:
            return True
        page = self.open()
        inp = page.locator(".rank-math-focus-keyword .tagify__input")
        def _open_panel() -> None:
            # (a) mở hộp Rank Math nếu đang thu gọn
            try:
                box = page.locator("#rank_math_metabox")
                if box.count() and "closed" in (box.first.get_attribute("class") or ""):
                    hd = box.first.locator(".handlediv")
                    if not hd.count():
                        hd = box.first.locator(".hndle")
                    if hd.count():
                        hd.first.click(force=True)
                        page.wait_for_timeout(500)
            except Exception:
                pass
            # (b) mở panel "Từ khóa chính" nếu chưa mở
            try:
                panel = page.locator(".rank-math-focus-keyword")
                if panel.count() and "is-opened" not in (panel.first.get_attribute("class") or ""):
                    t = panel.first.locator(".components-panel__body-title")
                    if t.count():
                        t.first.click(force=True)
                        page.wait_for_timeout(400)
            except Exception:
                pass

        if not inp.count():
            _open_panel()
        # Rank Math (React) render trễ -> chờ tối đa ~8s
        deadline = time.time() + 8
        while time.time() < deadline and not inp.count():
            page.wait_for_timeout(400)
            _open_panel()
        if not inp.count():
            log("  ⚠ Không thấy ô Focus Keyword (Rank Math) — bỏ qua")
            return None
        try:
            if not inp.first.is_visible():
                _open_panel()
                page.wait_for_timeout(300)
            if not inp.first.is_visible():
                log("  ⚠ Ô Focus Keyword đang bị ẩn — bỏ qua")
                return None
        except Exception:
            pass

        for attempt in (1, 2, 3):
            try:
                try:
                    inp.first.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
                # đã gõ sẵn chữ trong ô (chưa thành tag) -> chỉ cần Enter
                try:
                    pending = (inp.first.text_content() or "").strip()
                except Exception:
                    pending = ""
                if pending and keyword.lower() in pending.lower():
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1000)
                    if any(keyword.lower() == t.lower() for t in self._focus_tags()):
                        return True
                    pending = ""
                inp.first.click(force=True)
                page.wait_for_timeout(300)
                # xoá tag cũ
                for _ in range(8):
                    rm = page.locator(".rank-math-focus-keyword .tagify__tag__removeBtn")
                    if not rm.count():
                        break
                    rm.first.click(force=True)
                    page.wait_for_timeout(150)
                page.keyboard.type(keyword, delay=60)
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
                page.wait_for_timeout(1400)
                tags = self._focus_tags()
                if any(keyword.lower() == t.lower() for t in tags):
                    return True
                log(f"  ⚠ Keyword chưa vào (lần {attempt}) — thử lại…")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
            except Exception as exc:      # noqa: BLE001
                log(f"  ⚠ Lỗi đặt Focus Keyword (lần {attempt}): {str(exc).splitlines()[0][:120]}")
        return False

    def _on_edit_page(self, pid: int) -> bool:
        try:
            return f"post={pid}" in (self.page.url or "")
        except Exception:
            return False

    def _fill_title(self, title_new: str) -> bool:
        page = self.open()
        if page.locator("#title").count():
            page.locator("#title").first.fill(title_new)
            return True
        if page.locator(".editor-post-title__input").count():
            page.locator(".editor-post-title__input").first.click()
            page.keyboard.press("Meta+A" if sys.platform == "darwin" else "Control+A")
            page.keyboard.type(title_new)
            return True
        return False

    def update_post(self, pid: int, title_new: str, slug_new: str, keyword: str = "") -> dict:
        page = self.open()
        edit_url = self._edit_url(pid)
        ok_page = self._goto(edit_url)
        if ok_page:
            try:
                page.wait_for_selector("#title, .editor-post-title__input", timeout=30000)
            except Exception:
                pass
        if not page.locator("#title, .editor-post-title__input").count():
            log("  ⚠ Chưa thấy ô tiêu đề — mở lại trang…")
            self._goto(edit_url)
            try:
                page.wait_for_selector("#title, .editor-post-title__input", timeout=30000)
            except Exception:
                pass
        self._settle(1200)
        if not self._on_edit_page(pid):
            return {"ok": False, "error": f"Sai trang (đang ở {page.url[:80]}) — KHÔNG ghi để tránh nhầm bài"}
        if not self._fill_title(title_new):
            return {"ok": False, "error": "Không thấy ô tiêu đề (#title)"}

        # Đặt <h1> trong mô tả = link ngochuyduong.com + Title mới
        h1_state = ""
        try:
            content_html = page.locator("#content").first.input_value() if page.locator("#content").count() else ""
            if not content_html:
                content_html = page.eval_on_selector(
                    ".block-editor-block-list__layout, .editor-styles-wrapper",
                    "el => el ? el.innerHTML : ''",
                )
            new_html, h1_state = with_linked_h1(content_html, title_new)
            link_state = ""
            if keyword:
                new_html, link_state = with_brand_link(new_html, keyword)
            if not self._fill_content(new_html):
                log("  ⚠ Không ghi được nội dung để thay <h1>")
        except Exception as exc:      # noqa: BLE001
            log(f"  ⚠ Lỗi thay <h1>: {str(exc).splitlines()[0][:140]}")

        kw_state = ""
        if keyword:
            kw_ok = self._set_focus_keyword(keyword)
            kw_state = "skip" if kw_ok is None else ("ok" if kw_ok else "fail")

        # Slug PHẢI đổi được trước khi lưu; lỗi slug -> DỪNG (không lưu nửa vời)
        if not self.set_slug(pid, slug_new):
            return {
                "ok": False,
                "error": f"Không đổi được slug (hiện tại: {self._current_slug() or '?'}) — đã dừng, KHÔNG bấm Cập nhật",
                "slug_now": self._current_slug(),
            }

        # Có thể bị chuyển trang trong lúc sửa slug -> quay lại và điền lại tiêu đề
        if "post.php" not in page.url:
            self._goto(edit_url)
            page.wait_for_selector("#title, .editor-post-title__input", timeout=60000)
            self._fill_title(title_new)
            if self._current_slug() != slug_new and not self.set_slug(pid, slug_new):
                return {"ok": False, "error": "Mất slug sau khi quay lại trang sửa — đã dừng"}
            self._fill_title(title_new)

        # Bấm "Cập nhật" và CHỜ ĐÚNG phản hồi lưu của WordPress
        # (trước đây điều kiện chờ luôn đúng ngay từ đầu -> không biết đã lưu hay chưa)
        btn = page.locator(
            "#publish, #save-post, .editor-post-publish-button, "
            "button.editor-post-publish-button__button"
        )
        if not btn.count():
            return {"ok": False, "error": "Không thấy nút Cập nhật"}

        if not self._on_edit_page(pid):
            return {"ok": False, "error": "Trang đã đổi trước khi lưu — KHÔNG bấm Cập nhật"}

        def _is_save_response(resp) -> bool:
            try:
                if resp.request.method != "POST":
                    return False
                url = resp.url or ""
                return "post.php" in url or "admin-ajax.php" in url
            except Exception:
                return False

        saved_ok = False
        for how in ("locator", "js"):
            try:
                with page.expect_response(_is_save_response, timeout=120000):
                    if how == "locator":
                        btn.first.scroll_into_view_if_needed(timeout=10000)
                        btn.first.click(timeout=8000)
                    else:
                        btn.first.evaluate("el => el.click()")
                saved_ok = True
                break
            except Exception as exc:      # noqa: BLE001
                log(f"  ⚠ Bấm Cập nhật ({how}) chưa lưu được: {str(exc).splitlines()[0][:140]}")
        if not saved_ok:
            return {"ok": False, "error": "Không nhận được phản hồi lưu từ WordPress (nút Cập nhật không gửi form)"}

        self._settle(1200)
        # Chờ thông báo "đã cập nhật" (1 số site lưu qua AJAX nên có thể không reload)
        try:
            page.wait_for_selector(
                "#message.updated, #message.notice-success, .notice-success, "
                "#message.updated, .components-snackbar",
                timeout=3000,
            )
        except Exception:
            pass
        page.wait_for_timeout(800)

        after = self.read_product(pid, model_code=keyword, reload=False)
        if not (after.get("title_old") or "").strip():
            log("  ⚠ Chưa đọc được tiêu đề sau khi lưu — mở lại trang để xác nhận…")
            after = self.read_product(pid, model_code=keyword, reload=True)
        return {
            "ok": after.get("title_old", "").strip() == title_new.strip(),
            "slug_ok": after.get("slug_old", "") == slug_new,
            "h1_ok": after.get("h1_text", "").strip() == title_new.strip()
            and bool(after.get("h1_has_link")),
            "h1_state": h1_state,
            "kw_ok": (
                True if (not keyword or kw_state == "skip")
                else keyword.lower() in (after.get("focus_keyword", "") or "").lower()
            ),
            "kw_state": kw_state,
            "link_state": link_state,
            "link_ok": (
                True if not keyword
                else bool(after.get("model_linked")) or link_state in ("not-found", "no-model")
            ),
            "kw_now": after.get("focus_keyword", ""),
            "h1_now": after.get("h1_text", ""),
            "title_now": after.get("title_old", ""),
            "slug_now": after.get("slug_old", ""),
        }


# --------------------------------------------------------------------------- #
# Lệnh: login / list / next
# --------------------------------------------------------------------------- #
def _browser(args) -> Browser:
    return Browser(
        getattr(args, "base", DEFAULT_BASE),
        getattr(args, "headless", False),
        manual=getattr(args, "manual", False),
        login_wait=getattr(args, "login_wait", 600),
    )


def cmd_start(args) -> int:
    """Mở Chrome MỘT LẦN với cổng debug; các lệnh sau dùng chung cửa sổ này."""
    if cdp_alive():
        log(f"Chrome đã mở sẵn ở {CDP_URL} — không mở thêm.")
        return 0
    # còn tiến trình Chrome kẹt profile nhưng không mở cổng -> dọn trước
    if kill_profile_chrome():
        time.sleep(1.5)
    chrome = find_chrome()
    if not chrome:
        raise SystemExit(
            "Không tìm thấy Google Chrome. Hãy cài Chrome hoặc chạy lệnh khác "
            "(khi không có `start`, mỗi lệnh sẽ tự mở/đóng trình duyệt)."
        )
    import subprocess

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            chrome,
            f"--user-data-dir={PROFILE_DIR}",
            f"--remote-debugging-port={CDP_PORT}",
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--disable-translate",
            "--no-default-browser-check",
            "--no-first-run",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        if cdp_alive(0.5):
            log(f"Chrome đã mở (cổng {CDP_PORT}). Giữ cửa sổ này cho các bước sau.")
            return 0
        time.sleep(0.5)
    raise SystemExit("Chrome không mở được cổng debug. Thử đóng Chrome rồi chạy lại.")


def kill_profile_chrome() -> int:
    """Tắt các tiến trình Chrome đang dùng profile của tool (khi CDP không điều khiển được)."""
    import subprocess

    killed = 0
    key = str(PROFILE_DIR)
    if sys.platform.startswith("win"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/FI", "IMAGENAME eq chrome.exe"],
                capture_output=True,
            )
            return 1
        except Exception:
            return 0
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if key in line and ("Chrome" in line or "chrome" in line):
                pid = line.strip().split(" ", 1)[0]
                try:
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    killed += 1
                except Exception:
                    pass
    except Exception:
        pass
    return killed


def cmd_stop(args) -> int:
    """Đóng Chrome đang giữ (kể cả khi CDP không điều khiển được)."""
    if not cdp_alive():
        n = kill_profile_chrome()
        log("Chrome không mở — không có gì để đóng." if not n else f"Đã tắt {n} tiến trình Chrome còn kẹt profile.")
        return 0
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        br = pw.chromium.connect_over_cdp(CDP_URL)
        br.close()
        log("Đã đóng Chrome.")
        return 0
    except Exception as exc:      # noqa: BLE001
        log(f"⚠ CDP không đóng được ({str(exc).splitlines()[0][:100]}) → tắt trực tiếp…")
    finally:
        try:
            pw.stop()
        except Exception:
            pass
    n = kill_profile_chrome()
    log(f"Đã tắt {n} tiến trình Chrome." if n else "Không tìm thấy tiến trình để tắt.")
    return 0 if n else 1


def cmd_login(args) -> int:
    br = _browser(args)
    try:
        br.login()
        page = br.open()
        log(f"Đang ở: {page.url}")
    finally:
        if not args.keep_open:
            br.close()
        else:
            input("Nhấn Enter để đóng trình duyệt…")
            br.close()
    return 0


def cmd_list(args) -> int:
    st = load_state()
    br = _browser(args)
    br.login()
    try:
        products = br.list_products()
    finally:
        br.close()
    _write_json(PRODUCTS_FILE, products)
    st["base"] = br.base
    st["queue"] = [p["id"] for p in products]
    for p in products:
        item = st["items"].setdefault(str(p["id"]), {})
        item.setdefault("title_old", p["title"])
        item.setdefault("link", p["link"])
        item.setdefault("status", "new")
    save_state(st)
    log(f"Đã lấy {len(products)} sản phẩm publish → {PRODUCTS_FILE}")
    return 0


def _next_pending(st: dict, only_id: int | None = None,
                  exclude: set[int] | None = None) -> int | None:
    done = {"applied", "skipped", "approved", "error"}
    skip = exclude or set()
    if only_id is not None:
        return only_id
    for pid in st.get("queue", []):
        item = st["items"].get(str(pid)) or {}
        if item.get("status") in done or int(pid) in skip:
            continue
        return int(pid)
    for pid, item in st["items"].items():
        if item.get("status") in done or int(pid) in skip:
            continue
        return int(pid)
    return None


def _store_article(br, st: dict, pid: int) -> dict:
    """Đọc 1 bài và lưu current.json + current_<id>.json; trả về dữ liệu."""
    log(f"Đang đọc bài #{pid}…")
    data = br.read_product(pid)
    item = st["items"].setdefault(str(pid), {})
    item.update(
        {
            "title_old": data["title_old"],
            "slug_old": data["slug_old"],
            "status": "fetched",
            "fetched_at": data["fetched_at"],
        }
    )
    # Focus keyword theo rule_seo.pdf: ưu tiên MODEL (mã sản phẩm) dò trong content
    kw = ""
    for c in data.get("codes") or []:
        if c.get("from_keyword") and c.get("hits", 0) >= 2:
            kw = c["code"]
            break
    if not kw and data.get("codes"):
        kw = data["codes"][0]["code"]
    if kw:
        item["keyword"] = kw
    save_state(st)
    _write_json(CURRENT_FILE, data)
    _write_json(OUT_DIR / f"current_{pid}.json", data)
    return data


def _print_article(data: dict) -> None:
    log("")
    log("=" * 78)
    log(f"#{data['id']}  {data['title_old']}  ({len(data['title_old'])} ký tự)")
    log(f"Slug cũ : {data['slug_old']}")
    log(f"Danh mục/Thương hiệu: {', '.join(data['taxonomies']) or '—'}")
    log(f"SKU     : {data['sku'] or '—'}")
    log("Mã SP dò được trong content:")
    if data["codes"]:
        for c in data["codes"][:4]:
            star = "★" if c["from_keyword"] else " "
            log(f"  {star} {c['code']}  (xuất hiện {c['hits']} lần)")
    else:
        log("  (không thấy — cần đọc content để chọn mã)")
    log(f"Content: {len(data['content_text'])} ký tự (xem tools/out/current_{data['id']}.json)")
    log("=" * 78)


def cmd_next(args) -> int:
    st = load_state()
    br = _browser(args)
    br.login()
    try:
        if not st.get("queue"):
            log("Chưa có danh sách → lấy danh sách sản phẩm publish…")
            products = br.list_products()
            _write_json(PRODUCTS_FILE, products)
            st["base"] = br.base
            st["queue"] = [p["id"] for p in products]
            for p in products:
                item = st["items"].setdefault(str(p["id"]), {})
                item.setdefault("title_old", p["title"])
                item.setdefault("link", p["link"])
                item.setdefault("status", "new")
            save_state(st)
            log(f"Danh sách: {len(products)} sản phẩm publish.")

        count = max(1, int(getattr(args, "count", 1) or 1))
        done = 0
        read_ids: set[int] = set()
        for _ in range(count):
            pid = _next_pending(st, args.id if done == 0 else None, exclude=read_ids)
            if pid is None:
                log("Đã xử lý HẾT sản phẩm trong danh sách.")
                break
            data = _store_article(br, st, pid)
            _print_article(data)
            read_ids.add(pid)
            done += 1
    finally:
        br.close()

    if not done:
        log("Không còn bài nào cần đọc.")
        return 0
    log("")
    log("Bước tiếp: chọn tiêu đề rồi chạy `apply` (áp dụng mọi bài đã duyệt).")
    return 0


# --------------------------------------------------------------------------- #
# Lệnh: review (trang HTML duyệt)
# --------------------------------------------------------------------------- #
def _load_proposals() -> list[dict]:
    raw = _read_json(PROPOSAL_FILE, None)
    if raw is None:
        raise SystemExit(f"Chưa có {PROPOSAL_FILE}. Hãy ghi proposal.json trước.")
    if isinstance(raw, dict):
        raw = [raw]
    st = load_state()
    out = []
    for p in raw:
        pid = int(p.get("id") or 0)
        if not pid:
            raise SystemExit("proposal.json thiếu 'id'.")
        title = str(p.get("title_new") or "").strip()
        if not title:
            raise SystemExit(f"Bài #{pid}: thiếu 'title_new'.")
        item = (st.get("items") or {}).get(str(pid), {})
        out.append(
            {
                "id": pid,
                "title_old": item.get("title_old", ""),
                "slug_old": item.get("slug_old", ""),
                "title_new": title,
                "slug_new": make_slug(title),
                "usp": str(p.get("usp") or ""),
                "note": str(p.get("note") or ""),
                "edit_url": f"{(st.get('base') or DEFAULT_BASE)}/wp-admin/post.php?post={pid}&action=edit",
            }
        )
    return out


def _review_html(rows: list[dict]) -> str:
    def badge(title: str) -> str:
        n = len(title)
        color = "#137333" if TITLE_MIN <= n <= TITLE_MAX else "#c5221f"
        return f'<span class="len" style="color:{color}">{n} ký tự</span>'

    trs = []
    for r in rows:
        trs.append(
            f"""
  <tr data-id="{r['id']}">
    <td class="pick"><input type="checkbox" class="ok" checked></td>
    <td class="tt">
      <div class="old">{html.escape(r['title_old'])}</div>
      <div class="new">{html.escape(r['title_new'])}</div>
      <div class="meta">{badge(r['title_new'])}{(' · USP: ' + html.escape(r['usp'])) if r['usp'] else ''}</div>
      {f'<div class="note">{html.escape(r["note"])}</div>' if r['note'] else ''}
    </td>
    <td class="slugcell">
      <div class="old">/{html.escape(r['slug_old'])}/</div>
      <div class="new">/{html.escape(r['slug_new'])}/</div>
    </td>
    <td class="act"><a href="{html.escape(r['edit_url'])}" target="_blank" rel="noopener">Mở bài ↗</a></td>
  </tr>"""
        )

    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<title>Duyệt title + slug — samoapumps.com</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font: 14px/1.5 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; margin: 0; background: #f6f7f9; color: #1d2327; }}
  header {{ position: sticky; top: 0; background: #fff; border-bottom: 1px solid #dcdcde; padding: 14px 20px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; z-index: 5; }}
  h1 {{ font-size: 17px; margin: 0; }}
  .hint {{ color: #646970; font-size: 12.5px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; margin: 16px 0 90px; }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid #f0f0f1; vertical-align: top; text-align: left; }}
  th {{ background: #f6f7f9; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; color: #50575e; }}
  td.pick {{ width: 46px; }}
  td.pick input {{ width: 18px; height: 18px; }}
  .old {{ color: #8c8f94; text-decoration: line-through; }}
  .new {{ font-weight: 600; color: #135e96; }}
  .meta {{ font-size: 12px; color: #50575e; margin-top: 2px; }}
  .note {{ font-size: 12.5px; color: #646970; margin-top: 4px; }}
  .len {{ font-weight: 600; }}
  td.slugcell {{ width: 34%; font-size: 12.5px; word-break: break-all; }}
  td.act {{ width: 96px; white-space: nowrap; }}
  footer {{ position: fixed; bottom: 0; left: 0; right: 0; background: #fff; border-top: 1px solid #dcdcde; padding: 12px 20px; display: flex; gap: 12px; align-items: center; justify-content: flex-end; }}
  button {{ font: inherit; padding: 9px 18px; border-radius: 6px; border: 1px solid #2271b1; background: #2271b1; color: #fff; cursor: pointer; }}
  button.ghost {{ background: #fff; color: #2271b1; }}
  button:disabled {{ opacity: .6; cursor: default; }}
  #msg {{ margin-right: auto; color: #137333; font-weight: 600; }}
  .all {{ display: flex; gap: 8px; align-items: center; }}
</style></head>
<body>
<header>
  <h1>Duyệt Title + Slug</h1>
  <span class="hint">Bỏ tick = <b>giữ nguyên</b> bài đó. Chỉ bài được tick mới ghi lên WordPress.</span>
  <span class="all"><input type="checkbox" id="pickAll" checked><label for="pickAll">Chọn tất cả</label></span>
</header>
<table>
  <thead><tr><th></th><th>Tiêu đề (cũ → mới)</th><th>Đường dẫn</th><th></th></tr></thead>
  <tbody>{''.join(trs)}</tbody>
</table>
<footer>
  <span id="msg"></span>
  <button class="ghost" id="reload">Tải lại</button>
  <button id="save">Lưu duyệt</button>
</footer>
<script>
  const all = document.getElementById('pickAll');
  all.addEventListener('change', () => {{
    document.querySelectorAll('input.ok').forEach(cb => cb.checked = all.checked);
  }});
  document.getElementById('reload').addEventListener('click', () => location.reload());
  document.getElementById('save').addEventListener('click', async () => {{
    const rows = [...document.querySelectorAll('tr[data-id]')].map(tr => ({{
      id: Number(tr.dataset.id),
      approved: tr.querySelector('input.ok').checked
    }}));
    const btn = document.getElementById('save');
    btn.disabled = true;
    document.getElementById('msg').textContent = 'Đang lưu…';
    try {{
      const res = await fetch('/save', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ rows }})
      }});
      const data = await res.json();
      document.getElementById('msg').textContent = data.message || (data.ok ? 'Đã lưu.' : 'Lỗi.');
      if (data.ok) setTimeout(() => {{ btn.textContent = 'Đã lưu ✔'; }}, 200);
    }} catch (e) {{
      document.getElementById('msg').textContent = 'Lỗi: ' + e;
      btn.disabled = false;
    }}
  }});
</script>
</body></html>"""


def cmd_review(args) -> int:
    rows = _load_proposals()
    st = load_state()
    by_id = {r["id"]: r for r in rows}
    result = {"rows": None}
    html_text = _review_html(rows)
    saved = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):      # noqa: N802
            body = html_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):     # noqa: N802
            if not self.path.startswith("/save"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self.send_error(400)
                return
            picked = [r for r in (payload.get("rows") or []) if r.get("approved")]
            for r in payload.get("rows") or []:
                pid = int(r.get("id") or 0)
                if not pid:
                    continue
                item = st["items"].setdefault(str(pid), {})
                row = by_id.get(pid) or {}
                if r.get("approved"):
                    item["status"] = "approved"
                    item["title_new"] = row.get("title_new", "")
                    item["slug_new"] = row.get("slug_new", "")
                    item["approved_at"] = datetime.now().isoformat(timespec="seconds")
                else:
                    item["status"] = "skipped"
                    item.pop("title_new", None)
                    item.pop("slug_new", None)
            save_state(st)
            _write_json(APPROVED_FILE, [by_id[r["id"]] for r in picked if r["id"] in by_id])
            result["rows"] = payload.get("rows")
            body = json.dumps(
                {
                    "ok": True,
                    "message": f"Đã lưu: {len(picked)} bài áp dụng, "
                    f"{len(payload.get('rows') or []) - len(picked)} bài bỏ qua.",
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            saved.set()

        def log_message(self, *a):      # giữ terminal sạch
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log(f"Trang duyệt: {url}")
    log("Tick bài muốn đổi rồi bấm “Lưu duyệt”. (Ctrl+C để huỷ)")
    webbrowser.open(url)
    try:
        saved.wait(timeout=args.timeout)
    except KeyboardInterrupt:
        log("Đã huỷ.")
        httpd.shutdown()
        return 130
    httpd.shutdown()
    if not saved.is_set():
        log("Hết thời gian chờ — chưa lưu gì.")
        return 1
    picked = [r for r in (result["rows"] or []) if r.get("approved")]
    log(f"Đã lưu duyệt cho {len(picked)} bài → {APPROVED_FILE}")
    log("Bước tiếp: chạy `apply` để ghi lên WordPress.")
    return 0


# --------------------------------------------------------------------------- #
# Lệnh: apply (ghi lên WordPress)
# --------------------------------------------------------------------------- #
def _backup(st: dict, rows: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"backup_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["id", "title_cu", "slug_cu", "title_moi", "slug_moi", "luc"])
        for r in rows:
            item = st["items"].get(str(r["id"]), {})
            w.writerow(
                [
                    r["id"],
                    item.get("title_old", ""),
                    item.get("slug_old", ""),
                    r["title_new"],
                    r["slug_new"],
                    datetime.now().isoformat(timespec="seconds"),
                ]
            )
    return path


def _keyword_for(pid: int, item: dict) -> str:
    """Keyword = Model (rule_seo). Lấy từ state, nếu chưa có thì đọc current_<id>.json."""
    kw = (item.get("keyword") or "").strip()
    if kw:
        return kw
    data = _read_json(OUT_DIR / f"current_{pid}.json", None)
    if isinstance(data, dict):
        for c in data.get("codes") or []:
            if c.get("from_keyword") and c.get("hits", 0) >= 2:
                return c["code"]
        codes = data.get("codes") or []
        if codes:
            return codes[0].get("code", "")
    return ""


def cmd_apply(args) -> int:
    st = load_state()
    todo = []
    for pid, item in (st.get("items") or {}).items():
        status = item.get("status")
        # "error" = lần trước lỗi -> cho thử lại (không cần duyệt lại)
        if status not in ("approved", "error"):
            continue
        if not item.get("title_new") or not item.get("slug_new"):
            continue
        if args.id and int(pid) != args.id:
            continue
        todo.append(
            {
                "id": int(pid),
                "title_new": item.get("title_new", ""),
                "slug_new": item.get("slug_new", ""),
                "keyword": _keyword_for(int(pid), item),
                "retry": status == "error",
            }
        )
    if not todo:
        log("Không có bài nào đang chờ ghi (status = approved/error).")
        return 1

    br = None
    if not args.dry_run:
        br = _browser(args)
        br.login()
        # Đọc lại title/slug THẬT trước khi backup (chỉ khi chưa có -> đỡ chậm)
        for r in todo:
            item0 = st["items"][str(r["id"])]
            if item0.get("title_old") and item0.get("slug_old"):
                continue
            try:
                cur = br.read_product(r["id"])
                item = st["items"][str(r["id"])]
                item["title_old"] = cur.get("title_old", item.get("title_old", ""))
                item["slug_old"] = cur.get("slug_old", item.get("slug_old", ""))
                save_state(st)
                log(f"  hiện tại #{r['id']}: {item['title_old']}  (/{item['slug_old']}/)")
            except Exception as exc:      # noqa: BLE001
                log(f"  ⚠ Không đọc lại được bài #{r['id']}: {str(exc).splitlines()[0][:120]}")

    backup = _backup(st, todo)
    log(f"Đã backup title/slug cũ → {backup}")
    ok_count = 0
    try:
        for r in todo:
            pid = r["id"]
            log("")
            log(f"→ #{pid}  {r['title_new']}  (/{r['slug_new']}/)" + ("  [thử lại]" if r.get("retry") else ""))
            if args.dry_run:
                log("  (chạy thử — không ghi)")
                continue
            try:
                res = br.update_post(pid, r["title_new"], r["slug_new"], r.get("keyword", ""))
            except Exception as exc:      # noqa: BLE001
                res = {"ok": False, "error": f"Lỗi khi ghi: {str(exc).splitlines()[0][:160]}"}
            item = st["items"][str(pid)]
            if (res.get("ok") and res.get("slug_ok", True) and res.get("h1_ok", True)
                    and res.get("kw_ok", True) and res.get("link_ok", True)):
                item["status"] = "applied"
                item["applied_at"] = datetime.now().isoformat(timespec="seconds")
                item["title_now"] = res.get("title_now", "")
                item["slug_now"] = res.get("slug_now", "")
                save_state(st)
                ok_count += 1
                log(f"  ✔ Đã cập nhật: title + slug + <h1> + keyword + link mã SP khớp "
                    f"({res.get('h1_state') or 'h1'}/{res.get('link_state') or 'link'}).")
            else:
                item["status"] = "error"
                item["error"] = str(res.get("error") or "Không khớp sau khi lưu")
                save_state(st)
                log(f"  ✘ Lỗi: {item['error']}")
                log(f"    hiện tại: title={res.get('title_now')!r} slug={res.get('slug_now')!r} h1={res.get('h1_now')!r} kw={res.get('kw_now')!r}")
    finally:
        if br:
            br.close()
    log("")
    if args.dry_run:
        log(f"Chạy thử: {len(todo)} bài sẽ được ghi (chưa ghi gì).")
        return 0
    log(f"Xong: {ok_count}/{len(todo)} bài cập nhật thành công.")
    return 0 if ok_count == len(todo) else 2


# --------------------------------------------------------------------------- #
# Lệnh phụ: skip / status / usp
# --------------------------------------------------------------------------- #
def cmd_keyword(args) -> int:
    """Chỉ đặt lại Focus Keyword (= mã SP) cho các bài đã xử lý (không sửa content)."""
    st = load_state()
    items = st.get("items") or {}
    if args.ids:
        ids = [int(x) for x in str(args.ids).replace(" ", "").split(",") if x]
    else:
        ids = [int(pid) for pid, it in items.items() if it.get("status") == "applied"]
    if not ids:
        log("Không có bài nào cần đặt keyword.")
        return 0
    br = _browser(args)
    br.login()
    ok = 0
    try:
        for pid in ids:
            item = items.get(str(pid), {})
            kw = _keyword_for(pid, item)
            if not kw:
                log(f"#{pid}: không xác định được mã SP — bỏ qua")
                continue
            log(f"→ #{pid}  keyword = {kw}")
            if not br._goto(br._edit_url(pid)):
                log("  ⚠ Không mở được trang sửa")
                continue
            try:
                br.page.wait_for_selector("#title, .editor-post-title__input", timeout=30000)
            except Exception:
                pass
            br._settle(1200)
            state = br._set_focus_keyword(kw)
            if state is None:
                log("  ⚠ Không có ô Focus Keyword — bỏ qua")
                continue
            res = br.update_post(pid, br.page.locator("#title").first.input_value(), br._current_slug(), kw)
            if res.get("kw_ok"):
                ok += 1
                log("  ✔ keyword đã đặt")
            else:
                log(f"  ✘ keyword chưa đúng (hiện tại: {res.get('kw_now')!r})")
    finally:
        br.close()
    log("")
    log(f"Xong: {ok}/{len(ids)} bài có keyword đúng.")
    return 0 if ok == len(ids) else 2


def cmd_skip(args) -> int:
    st = load_state()
    item = st["items"].setdefault(str(args.id), {})
    item["status"] = "skipped"
    item.pop("title_new", None)
    item.pop("slug_new", None)
    save_state(st)
    log(f"Đã bỏ qua bài #{args.id}.")
    return 0


def cmd_status(args) -> int:
    st = load_state()
    items = st.get("items") or {}
    counts: dict[str, int] = {}
    for it in items.values():
        counts[it.get("status", "new")] = counts.get(it.get("status", "new"), 0) + 1
    log(f"Tổng: {len(items)} bài | " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    for pid, it in items.items():
        if it.get("status") in ("approved", "error"):
            log(f"  #{pid} [{it.get('status')}] {it.get('title_new') or it.get('title_old')} ({it.get('slug_new') or ''})")
    return 0


def cmd_usp(args) -> int:
    for i, u in enumerate(USPS, 1):
        log(f"{i:2}. {u}  ({len(u)} ký tự)")
    return 0


# --------------------------------------------------------------------------- #
def _acquire_lock() -> bool:
    """Chỉ cho 1 tiến trình điều khiển Chrome cùng lúc (tránh ghi nhầm bài)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if LOCK_FILE.exists():
            try:
                pid = int((LOCK_FILE.read_text() or "0").strip() or 0)
            except Exception:
                pid = 0
            alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except Exception:
                    alive = False
            if alive:
                return False
            LOCK_FILE.unlink(missing_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return True


def _release_lock() -> None:
    try:
        if LOCK_FILE.exists() and (LOCK_FILE.read_text().strip() == str(os.getpid())):
            LOCK_FILE.unlink()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Tạo lại Title + Slug cho sản phẩm đã publish (chạy ngoài app).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"URL website (mặc định {DEFAULT_BASE})")
    ap.add_argument("--headless", action="store_true", help="Chạy ẩn trình duyệt (không nên dùng)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # Dùng chung cho mọi lệnh (đặt SAU tên lệnh): next --manual
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base", default=DEFAULT_BASE, help=f"URL website (mặc định {DEFAULT_BASE})")
    common.add_argument(
        "--manual",
        action="store_true",
        help="Bạn TỰ đăng nhập trong Chrome (dùng khi có captcha / không muốn lưu mật khẩu)",
    )
    common.add_argument(
        "--login-wait",
        type=int,
        default=600,
        metavar="GIAY",
        help="Số giây chờ bạn đăng nhập tay (mặc định 600)",
    )
    common.add_argument("--headless", action="store_true", help="Chạy ẩn trình duyệt (không nên dùng)")

    p = sub.add_parser("start", help="Mở Chrome 1 lần và giữ mở cho mọi bước", parents=[common])
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("stop", help="Đóng Chrome đang giữ", parents=[common])
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("login", help="Kiểm tra đăng nhập (chờ bạn tự bấm nếu có captcha)", parents=[common])
    p.add_argument("--keep-open", action="store_true")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("list", help="Lấy danh sách sản phẩm publish", parents=[common])
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("next", help="Đọc bài kế tiếp (title/slug cũ + content + mã SP)", parents=[common])
    p.add_argument("--id", type=int, default=None)
    p.add_argument("--count", type=int, default=1, help="Đọc N bài một lượt (mặc định 1)")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("review", help="Mở trang HTML duyệt title + slug", parents=[common])
    p.add_argument("--timeout", type=int, default=3600, help="Giây chờ duyệt (mặc định 3600)")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("apply", help="Ghi các bài đã duyệt lên WordPress", parents=[common])
    p.add_argument("--id", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="Chỉ in ra, không ghi")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("keyword", help="Chỉ đặt lại Focus Keyword cho bài đã xử lý", parents=[common])
    p.add_argument("--ids", default="", help="Danh sách id, cách nhau dấu phẩy (mặc định: mọi bài đã xong)")
    p.set_defaults(func=cmd_keyword)

    p = sub.add_parser("skip", help="Bỏ qua 1 bài", parents=[common])
    p.add_argument("--id", type=int, required=True)
    p.set_defaults(func=cmd_skip)

    p = sub.add_parser("status", help="Xem tiến độ", parents=[common])
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("usp", help="In danh sách USP", parents=[common])
    p.set_defaults(func=cmd_usp)

    args = ap.parse_args(argv)

    needs_browser = getattr(args, "func", None) not in (cmd_usp, cmd_status)
    if needs_browser and not _acquire_lock():
        log("⏳ Đang có tiến trình khác chạy trên Chrome — chờ nó xong rồi chạy lại.")
        return 3
    try:
        return int(args.func(args) or 0)
    finally:
        if needs_browser:
            _release_lock()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\nĐã dừng.")
        sys.exit(130)
