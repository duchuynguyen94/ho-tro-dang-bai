"""Các luồng chạy nền (tạo nội dung, đăng bài, ghi kịch bản)."""
from __future__ import annotations

import random
import traceback

from PySide6.QtCore import QThread, Signal

from .. import source as src
from ..ai import generate_content
from ..ai.manager import autolink_html, extract_product_name
from ..config import output_dir
from ..images import compose, save_composed


def _remove_bg_opts(store) -> tuple[bool, int]:
    cfg = (store.ai_image or {}).get("remove_bg") or {}
    enabled = cfg.get("mode", "off") != "off"
    try:
        thresh = max(10, int(float(cfg.get("threshold", 0.5)) * 100))
    except (TypeError, ValueError):
        thresh = 42
    return enabled, thresh


def pick_footer(site, mode: str = "") -> str:
    bars = [b for b in (site.footer_bars or []) if b]
    if not bars:
        return ""
    mode = mode or site.footer_mode or "random"
    if mode == "bar1":
        return bars[0]
    if mode == "bar2":
        return bars[1] if len(bars) > 1 else bars[0]
    return random.choice(bars)


def build_template_images(site, task, brand_logo: str, product_paths: list[str],
                          footer_mode: str = "", log=None, rules: list[str] | None = None,
                          remove_bg: bool = False, remove_bg_thresh: int = 42) -> list[dict]:
    """Ghép ảnh theo mẫu (dùng cho cả tạo mới và tạo lại ảnh)."""
    import re as _re

    from ..wp import render_value

    images: list[dict] = []
    count = max(1, int(task.image_count or 3))
    mode = footer_mode or task.footer_mode or "random"
    result = task.result or {}
    ctx = {
        "title": result.get("title", ""),
        "focus_keyword": result.get("focus_keyword", ""),
        "keyword": result.get("focus_keyword", ""),
        "site": task.site_name,
        "description": result.get("description", ""),
    }
    rules = list(rules or [])

    for i in range(count):
        footer = pick_footer(site, mode)
        prods = product_paths[i:] + product_paths[:i] if product_paths else []
        img = compose(
            size=1080,
            site_logo=site.logo_path,
            brand_logo=brand_logo,
            products=prods[:3],
            footer_bar=footer,
            frame=site.frame_path,
            watermark=site.watermark_text,
            remove_bg=remove_bg,
            remove_bg_thresh=remove_bg_thresh,
        )
        # Rule đặt tên ảnh (nếu có)
        rule = (rules[i] if i < len(rules) else "").strip()
        name = ""
        if rule:
            name = _re.sub(r"[^\w\-\. ]+", "", render_value(rule, {**ctx, "index": i + 1})).strip()
        fname = f"{name.replace(' ', '-')[:80]}_{i + 1}.png" if name else f"{task.id}_{i + 1}.png"
        out = output_dir() / fname
        save_composed(img, str(out))
        images.append({"path": str(out), "footer": footer})
    if log:
        log(f"Đã ghép {len(images)} ảnh.")
    return images


class ContentWorker(QThread):
    """Đọc link nguồn -> AI viết -> ghép ảnh."""

    log = Signal(str)
    progress = Signal(int)
    ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, store, task, site) -> None:
        super().__init__()
        self.store = store
        self.task = task
        self.site = site

    def run(self) -> None:
        t, site = self.task, self.site
        try:
            self.progress.emit(5)
            self.log.emit("Đang đọc link nguồn…")
            page = src.fetch_source(t.source_url)
            self.progress.emit(25)

            product_urls = page.get("images", [])[:3]
            self.log.emit(f"Tìm thấy {len(page.get('images', []))} ảnh; tải {len(product_urls)} ảnh sản phẩm.")
            product_paths: list[str] = []
            for u in product_urls:
                try:
                    product_paths.append(src.download_image(u))
                except Exception as exc:
                    self.log.emit(f"  bỏ qua 1 ảnh: {exc}")
            self.progress.emit(45)

            data = generate_content(self.store, page, log=self.log.emit)
            # chèn 1 link external vào tên sản phẩm + link cho tên miền www.
            pname = extract_product_name(
                data.get("raw_content", ""), page.get("title", "") or data.get("title", "")
            )
            data["content_html"] = autolink_html(
                data.get("content_html", ""), site.url or "", site.name or "", pname
            )
            self.progress.emit(70)

            # Logo thương hiệu: ưu tiên file dự phòng, nếu trống thì thử tìm trên trang nguồn.
            brand_logo = t.brand_logo_fallback or ""
            if not brand_logo:
                cand = src.find_brand_logo(t.source_url)
                if cand:
                    try:
                        brand_logo = src.download_image(cand, prefix="brand")
                        self.log.emit("Đã tự tìm được logo thương hiệu từ trang nguồn.")
                    except Exception:
                        brand_logo = ""
            if not brand_logo:
                self.log.emit("Không tìm được logo thương hiệu — bỏ qua (có thể thêm ở Cấu hình).")

            # Ghép ảnh theo mẫu
            self.log.emit(f"Đang ghép {t.image_count} ảnh theo mẫu…")
            rb, th = _remove_bg_opts(self.store)
            images = build_template_images(site, t, brand_logo, product_paths,
                                           t.footer_mode, log=self.log.emit,
                                           rules=self.store.image_rules,
                                           remove_bg=rb, remove_bg_thresh=th)
            self.progress.emit(100)

            result = dict(data)
            result.update(
                {
                    "images": images,
                    "brand_logo": brand_logo,
                    "product_images": product_paths,
                    "source_title": page.get("title", ""),
                }
            )
            self.ok.emit(result)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class FieldWorker(QThread):
    """Tạo lại 1 trường duy nhất (nút Random riêng từng phần)."""

    log = Signal(str)
    ok = Signal(str, str)      # (field, value)
    failed = Signal(str)

    def __init__(self, store, site, task, field: str, current: str = "") -> None:
        super().__init__()
        self.store = store
        self.site = site
        self.task = task
        self.field = field
        self.current = current

    def run(self) -> None:
        from ..ai.manager import generate_field

        try:
            self.log.emit(f"Đang tạo lại: {self.field}…")
            page = src.fetch_source(self.task.source_url)
            value = generate_field(self.store, page, self.field, self.current, log=self.log.emit)
            self.ok.emit(self.field, value)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class ImagesWorker(QThread):
    """Tạo lại ảnh theo mẫu (đổi thanh thông tin) mà không cần gọi lại AI."""

    log = Signal(str)
    ok = Signal(list)
    failed = Signal(str)

    def __init__(self, store, site, task, footer_mode: str = "") -> None:
        super().__init__()
        self.store = store
        self.site = site
        self.task = task
        self.footer_mode = footer_mode

    def run(self) -> None:
        try:
            r = self.task.result or {}
            rb, th = _remove_bg_opts(self.store)
            images = build_template_images(
                self.site, self.task,
                r.get("brand_logo", ""), list(r.get("product_images") or []),
                self.footer_mode, log=self.log.emit,
                rules=self.store.image_rules,
                remove_bg=rb, remove_bg_thresh=th,
            )
            self.ok.emit(images)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class PostWorker(QThread):
    """Mở trình duyệt -> tự đăng nhập -> phát lại kịch bản (điền form)."""

    log = Signal(str)
    ok = Signal(str)
    failed = Signal(str)

    def __init__(self, site, result: dict) -> None:
        super().__init__()
        self.site = site
        self.result = result

    def run(self) -> None:
        from ..wp import WPBrowser, play_script

        site = self.site
        try:
            self.log.emit("Mở trình duyệt…")
            br = WPBrowser(headless=False, site_id=site.id)
            page = br.open()
            self.log.emit(f"Trình duyệt: {br.channel_used}")

            self.log.emit("Đăng nhập WordPress…")
            if site.username or site.get_password():
                ok = br.login(site)
                self.log.emit("Đã đăng nhập." if ok else "Không đăng nhập được (tiếp tục với session hiện có).")

            if site.script and site.script.steps:
                self.log.emit("Phát lại kịch bản…")
                ctx = {
                    "title": self.result.get("title", ""),
                    "content_html": self.result.get("content_html", ""),
                    "content": self.result.get("content_html", ""),
                    "focus_keyword": self.result.get("focus_keyword", ""),
                    "description": self.result.get("description", ""),
                    "tags": self.result.get("tags", ""),
                    "__upload_files": [im["path"] for im in self.result.get("images", [])],
                }
                play_script(page, site.script, ctx, log=self.log.emit)
            else:
                self.log.emit("Website chưa có kịch bản — mở trang tạo bài để bạn tự thao tác.")
                if site.new_post_url:
                    page.goto(site.new_post_url, wait_until="domcontentloaded")

            self.log.emit("Đã điền xong. Bạn kiểm tra rồi bấm Đăng trên WordPress.")
            self.ok.emit(page.url)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class OpenLoginWorker(QThread):
    """Mở trình duyệt riêng để người dùng đăng nhập 1 dịch vụ (ví dụ ChatGPT)."""

    log = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, profile_id: str, title: str = "") -> None:
        super().__init__()
        self.url = url
        self.profile_id = profile_id
        self.title = title or url
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        from ..wp import WPBrowser

        br = None
        try:
            br = WPBrowser(headless=False, site_id=self.profile_id)
            page = br.open()
            page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
            self.log.emit(f"Đã mở {self.title}. Hãy đăng nhập, rồi đóng trình duyệt.")
            while self._running:
                try:
                    if page.is_closed():
                        break
                    page.wait_for_timeout(300)
                except Exception:
                    break
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))
        finally:
            try:
                if br:
                    br.close()
            except Exception:
                pass


class LoginWorker(QThread):
    """Mở trình duyệt (có hiển thị) để đăng nhập và cho người dùng xem."""

    log = Signal(str)
    ok = Signal(bool)
    failed = Signal(str)

    def __init__(self, site, keep_open_seconds: int = 180) -> None:
        super().__init__()
        self.site = site
        self.keep_open = keep_open_seconds
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from ..wp import WPBrowser

        site = self.site
        try:
            self.log.emit("Đang mở trình duyệt…")
            br = WPBrowser(headless=False, site_id=site.id)
            page = br.open()
            self.log.emit(f"Trình duyệt đã mở ({br.channel_used}). Đang đăng nhập…")

            logged = br.login(site)
            if logged:
                self.log.emit("Đăng nhập thành công — bạn xem trang quản trị WordPress.")
                if site.new_post_url:
                    try:
                        page.goto(site.new_post_url, wait_until="domcontentloaded")
                    except Exception:
                        pass
            else:
                self.log.emit("Chưa đăng nhập tự động được — bạn thử đăng nhập trực tiếp trên cửa sổ trình duyệt.")
            self.ok.emit(logged)

            # Giữ cửa sổ mở cho người dùng xem cho tới khi họ đóng trình duyệt.
            waited = 0
            limit = self.keep_open * 5  # 200ms * 5 = 1s
            while not self._stop and waited < limit:
                try:
                    if page.is_closed():
                        break
                    page.wait_for_timeout(200)
                except Exception:
                    break
                waited += 1
            try:
                br.close()
            except Exception:
                pass
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class ImageEditWorker(QThread):
    """Sửa 1 ảnh bằng AI theo yêu cầu người dùng."""

    log = Signal(str)
    ok = Signal(str)          # đường dẫn ảnh mới
    failed = Signal(str)

    def __init__(self, store, task, index: int, prompt: str) -> None:
        super().__init__()
        self.store = store
        self.task = task
        self.index = index
        self.prompt = prompt

    def run(self) -> None:
        from ..images.aiedit import edit_image

        try:
            images = (self.task.result or {}).get("images") or []
            if self.index >= len(images):
                raise RuntimeError("Không tìm thấy ảnh để sửa.")
            src = images[self.index].get("path", "")
            path = edit_image(self.store, src, self.prompt, log=self.log.emit)
            self.ok.emit(path)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class PostRecordWorker(QThread):
    """Mở trình duyệt để đăng bài bằng tay, đồng thời GHI lại kịch bản."""

    log = Signal(str)
    step = Signal(dict)
    ok = Signal(list)          # danh sách bước ghi được
    failed = Signal(str)

    def __init__(self, site, task=None) -> None:
        super().__init__()
        self.site = site
        self.task = task
        self._running = True
        self.steps: list[dict] = []

    def stop(self) -> None:
        self._running = False

    def _on_step(self, _source, payload: dict) -> None:
        if self.steps and self.steps[-1].get("selector") == payload.get("selector") \
                and self.steps[-1].get("value") == payload.get("value"):
            return
        self.steps.append(payload)
        self.step.emit(payload)

    def run(self) -> None:
        from ..wp import WPBrowser
        from ..wp import recorder

        br = None
        try:
            br = WPBrowser(headless=False, site_id=self.site.id)
            page = br.open()
            page.expose_binding("__wpRecordStep", self._on_step)
            page.add_init_script(recorder.RECORDER_JS)

            self.log.emit("Đang đăng nhập WordPress…")
            try:
                br.login(self.site)
            except Exception:
                pass

            target = self.site.new_post_url or self.site.url
            if target:
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=25000)
                except Exception as exc:
                    self.log.emit(f"Không mở được địa chỉ đã cấu hình ({str(exc)[:80]}).")
            self.log.emit("● Đang ghi: thao tác trên trình duyệt rồi bấm “Dừng & Lưu kịch bản”.")

            while self._running:
                try:
                    if page.is_closed():
                        break
                    page.wait_for_timeout(300)
                except Exception:
                    break
            self.ok.emit(list(self.steps))
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))
        finally:
            try:
                if br:
                    br.close()
            except Exception:
                pass


class RecordWorker(QThread):
    """Ghi lại thao tác người dùng thành các bước kịch bản."""

    step = Signal(dict)
    log = Signal(str)
    failed = Signal(str)

    def __init__(self, site, start_url: str = "") -> None:
        super().__init__()
        self.site = site
        self.start_url = start_url or site.new_post_url or site.url
        self._running = True
        self.steps: list[dict] = []

    def stop(self) -> None:
        self._running = False

    def _on_step(self, _source, payload: dict) -> None:
        # lọc trùng liên tiếp
        if self.steps and self.steps[-1].get("selector") == payload.get("selector") \
                and self.steps[-1].get("value") == payload.get("value"):
            return
        self.steps.append(payload)
        self.step.emit(payload)

    def run(self) -> None:
        from ..wp import WPBrowser
        from ..wp import recorder

        br = None
        try:
            br = WPBrowser(headless=False, site_id=self.site.id)
            page = br.open()
            page.expose_binding("__wpRecordStep", self._on_step)
            page.add_init_script(recorder.RECORDER_JS)
            self.log.emit("Đã mở trình duyệt. Thao tác trên trình duyệt rồi bấm Dừng ghi.")

            if self.start_url:
                try:
                    page.goto(self.start_url, wait_until="domcontentloaded", timeout=25000)
                except Exception as exc:
                    self.log.emit(
                        "Không mở được địa chỉ đã cấu hình — bạn có thể tự nhập địa chỉ trên trình duyệt. "
                        f"({str(exc)[:100]})"
                    )

            while self._running:
                try:
                    if page.is_closed():
                        break
                    page.wait_for_timeout(300)
                except Exception:
                    break
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))
        finally:
            try:
                if br:
                    br.close()
            except Exception:
                pass
            self.log.emit("Đã đóng trình duyệt ghi.")
