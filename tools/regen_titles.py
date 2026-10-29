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
  usp              in danh sách USP + độ dài (để chọn vừa 55–60 ký tự)

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

DEFAULT_BASE = "https://samoapumps.com"
LIST_PATH = "/wp-admin/edit.php?post_status=publish&post_type=product"
TITLE_MIN, TITLE_MAX = 55, 60

# USP: danh sách người dùng chốt + chuẩn rule_seo.pdf + gợi ý thêm.
# Mỗi title chỉ dùng 1 USP (chọn ngẫu nhiên, ưu tiên vừa 55–60 ký tự).
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
    "Miễn phí vận chuyển",
    "Kỹ sư tư vấn",
    "Đổi trả 1-1",
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


def make_slug(text: str, max_len: int = 60) -> str:
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

    # -- vòng đời -- #
    def open(self):
        if self.page:
            return self.page
        from playwright.sync_api import sync_playwright

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
            self.page.set_default_timeout(60000)
            self.page.set_default_navigation_timeout(120000)
        except Exception:
            pass
        return self.page

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
        page.goto(self.base + "/wp-login.php", wait_until="domcontentloaded")
        self._wait_login_done()
        try:
            page.goto(self.base + LIST_PATH, wait_until="domcontentloaded")
            time.sleep(0.5)
        except Exception:
            pass

    def login(self) -> None:
        page = self.open()
        target = self.base + LIST_PATH
        page.goto(target, wait_until="domcontentloaded")
        time.sleep(0.6)
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

    # -- đọc dữ liệu -- #
    def list_products(self) -> list[dict]:
        page = self.open()
        url = self.base + LIST_PATH
        products: list[dict] = []
        seen: set[int] = set()
        for _ in range(200):
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector("#the-list, .wp-list-table", timeout=60000)
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

    def read_product(self, pid: int) -> dict:
        page = self.open()
        edit_url = f"{self.base}/wp-admin/post.php?post={pid}&action=edit"
        page.goto(edit_url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("#title, .editor-post-title__input, [aria-label*='tiêu đề' i]", timeout=60000)
        except Exception:
            pass
        time.sleep(0.6)

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

        slug = ""
        try:
            permalink = page.eval_on_selector(
                "#sample-permalink, #editable-post-name-full",
                "el => el ? (el.innerText || el.textContent || '').trim() : ''",
            )
            if permalink:
                if "://" in permalink:
                    parts = [p for p in permalink.split("?")[0].split("/") if p]
                    slug = parts[-1] if parts else ""
                else:
                    slug = permalink.strip()
        except Exception:
            pass

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

        text = html_to_text(content_html)
        return {
            "id": pid,
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
    def set_slug(self, slug: str) -> bool:
        page = self.open()
        current = ""
        try:
            cur = page.eval_on_selector(
                "#sample-permalink, #editable-post-name-full",
                "el => el ? (el.innerText || el.textContent || '').trim() : ''",
            )
            if cur:
                current = cur.rstrip("/").split("/")[-1]
        except Exception:
            pass
        if current == slug:
            return True
        try:
            link = page.locator("#edit-slug-buttons a.edit-slug, a.edit-slug")
            if not link.count():
                box = page.locator("#edit-slug-box")
                if box.count():
                    box.first.click()
            if link.count():
                link.first.click(force=True)
            inp = page.locator("#new-post-slug")
            inp.wait_for(state="visible", timeout=10000)
            inp.fill(slug)
            save = page.locator("#edit-slug-buttons button.save, button.save")
            if save.count():
                save.first.click()
            else:
                inp.press("Enter")
            page.wait_for_timeout(900)
            return True
        except Exception as exc:      # noqa: BLE001
            log(f"  ⚠ Không sửa được slug: {str(exc).splitlines()[0][:160]}")
            return False

    def update_post(self, pid: int, title_new: str, slug_new: str) -> dict:
        page = self.open()
        page.goto(f"{self.base}/wp-admin/post.php?post={pid}&action=edit", wait_until="domcontentloaded")
        try:
            page.wait_for_selector("#title, .editor-post-title__input", timeout=60000)
        except Exception:
            pass
        time.sleep(0.4)
        if page.locator("#title").count():
            page.locator("#title").first.fill(title_new)
        elif page.locator(".editor-post-title__input").count():
            page.locator(".editor-post-title__input").first.click()
            page.keyboard.press("Meta+A" if sys.platform == "darwin" else "Control+A")
            page.keyboard.type(title_new)
        else:
            return {"ok": False, "error": "Không thấy ô tiêu đề (#title)"}

        slug_ok = self.set_slug(slug_new)

        try:
            btn = page.locator("#publish, .editor-post-publish-button, button.editor-post-publish-button__button")
            btn.first.click()
            page.wait_for_function(
                """() => {
                    const b = document.querySelector('#publish');
                    const notice = document.querySelector('#message.updated, #message.notice-success, .notice-success');
                    return (b && !b.disabled && /cập nhật|update/i.test(b.value || b.innerText || '')) || !!notice;
                }""",
                timeout=180000,
            )
            page.wait_for_timeout(1200)
        except Exception as exc:      # noqa: BLE001
            return {"ok": False, "error": f"Bấm Cập nhật lỗi: {str(exc).splitlines()[0][:160]}"}

        after = self.read_product(pid)
        return {
            "ok": after.get("title_old", "").strip() == title_new.strip(),
            "slug_ok": (after.get("slug_old", "") == slug_new) if slug_ok else False,
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


def _next_pending(st: dict, only_id: int | None = None) -> int | None:
    done = {"applied", "skipped"}
    if only_id is not None:
        return only_id
    for pid in st.get("queue", []):
        item = st["items"].get(str(pid)) or {}
        if item.get("status") in done:
            continue
        return int(pid)
    for pid, item in st["items"].items():
        if item.get("status") not in done:
            return int(pid)
    return None


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

        pid = _next_pending(st, args.id)
        if pid is None:
            log("Đã xử lý HẾT sản phẩm trong danh sách.")
            log("Muốn làm lại từ đầu: xoá tools/out/state.json rồi chạy `list`.")
            return 0
        log(f"Đang đọc bài #{pid}…")
        data = br.read_product(pid)
    finally:
        br.close()

    item = st["items"].setdefault(str(pid), {})
    item.update(
        {
            "title_old": data["title_old"],
            "slug_old": data["slug_old"],
            "status": "fetched",
            "fetched_at": data["fetched_at"],
        }
    )
    save_state(st)
    _write_json(CURRENT_FILE, data)

    log("")
    log("=" * 78)
    log(f"#{pid}  {data['title_old']}  ({len(data['title_old'])} ký tự)")
    log(f"Slug cũ : {data['slug_old']}")
    log(f"Danh mục/Thương hiệu: {', '.join(data['taxonomies']) or '—'}")
    log(f"SKU     : {data['sku'] or '—'}")
    log("Mã SP dò được trong content:")
    if data["codes"]:
        for c in data["codes"][:6]:
            star = "★" if c["from_keyword"] else " "
            log(f"  {star} {c['code']}  (xuất hiện {c['hits']} lần)")
    else:
        log("  (không thấy — cần đọc content để chọn mã)")
    log(f"Content: {len(data['content_text'])} ký tự (xem đầy đủ trong tools/out/current.json)")
    log("=" * 78)
    log("")
    log("Bước tiếp: ghi tools/out/proposal.json rồi chạy `review`.")
    log('  {"id": %d, "title_new": "...", "usp": "...", "note": "..."}' % pid)
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


def cmd_apply(args) -> int:
    st = load_state()
    todo = []
    for pid, item in (st.get("items") or {}).items():
        if item.get("status") != "approved":
            continue
        if args.id and int(pid) != args.id:
            continue
        todo.append({"id": int(pid), "title_new": item.get("title_new", ""), "slug_new": item.get("slug_new", "")})
    if not todo:
        log("Không có bài nào đang chờ ghi (status = approved).")
        return 1

    backup = _backup(st, todo)
    log(f"Đã backup title/slug cũ → {backup}")

    br = None
    if not args.dry_run:
        br = _browser(args)
        br.login()
    ok_count = 0
    try:
        for r in todo:
            pid = r["id"]
            log("")
            log(f"→ #{pid}  {r['title_new']}  (/{r['slug_new']}/)")
            if args.dry_run:
                log("  (chạy thử — không ghi)")
                continue
            res = br.update_post(pid, r["title_new"], r["slug_new"])
            item = st["items"][str(pid)]
            if res.get("ok") and res.get("slug_ok", True):
                item["status"] = "applied"
                item["applied_at"] = datetime.now().isoformat(timespec="seconds")
                item["title_now"] = res.get("title_now", "")
                item["slug_now"] = res.get("slug_now", "")
                save_state(st)
                ok_count += 1
                log("  ✔ Đã cập nhật (title + slug khớp).")
            else:
                item["status"] = "error"
                item["error"] = str(res.get("error") or "Không khớp sau khi lưu")
                save_state(st)
                log(f"  ✘ Lỗi: {item['error']}")
                log(f"    hiện tại: title={res.get('title_now')!r} slug={res.get('slug_now')!r}")
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

    p = sub.add_parser("login", help="Kiểm tra đăng nhập (chờ bạn tự bấm nếu có captcha)", parents=[common])
    p.add_argument("--keep-open", action="store_true")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("list", help="Lấy danh sách sản phẩm publish", parents=[common])
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("next", help="Đọc bài kế tiếp (title/slug cũ + content + mã SP)", parents=[common])
    p.add_argument("--id", type=int, default=None)
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("review", help="Mở trang HTML duyệt title + slug", parents=[common])
    p.add_argument("--timeout", type=int, default=3600, help="Giây chờ duyệt (mặc định 3600)")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("apply", help="Ghi các bài đã duyệt lên WordPress", parents=[common])
    p.add_argument("--id", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="Chỉ in ra, không ghi")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("skip", help="Bỏ qua 1 bài", parents=[common])
    p.add_argument("--id", type=int, required=True)
    p.set_defaults(func=cmd_skip)

    p = sub.add_parser("status", help="Xem tiến độ", parents=[common])
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("usp", help="In danh sách USP", parents=[common])
    p.set_defaults(func=cmd_usp)

    args = ap.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\nĐã dừng.")
        sys.exit(130)
