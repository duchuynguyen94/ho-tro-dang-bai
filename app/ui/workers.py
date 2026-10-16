"""Các luồng chạy nền (tạo nội dung, đăng bài, ghi kịch bản)."""
from __future__ import annotations

import random
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .. import source as src
from ..ai import generate_content
from ..ai.manager import extract_product_name, insert_external_links, linkify_site
from ..config import output_dir
from ..images import compose, save_composed


ACTIVE_THREADS: set = set()


class TrackedThread(QThread):
    """QThread tự đăng ký vào ACTIVE_THREADS để lúc thoát app chờ hết (tránh crash)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        ACTIVE_THREADS.add(self)
        self.finished.connect(lambda: ACTIVE_THREADS.discard(self))


def shutdown_all_threads(timeout: int = 6000) -> None:
    """Dừng + CHỜ mọi luồng nền đang chạy kết thúc."""
    for w in list(ACTIVE_THREADS):
        try:
            if hasattr(w, "stop"):
                w.stop()
        except Exception:      # noqa: BLE001
            pass
    for w in list(ACTIVE_THREADS):
        try:
            if w.isRunning():
                w.wait(timeout)
        except Exception:      # noqa: BLE001
            pass


class _Cancelled(Exception):
    """Người dùng bấm Dừng."""


def render_rule(rule: str, ctx: dict) -> str:
    """Thay biến trong Rule ảnh: hỗ trợ cả {title} và {{title}}."""
    import re as _re

    def repl(m):
        return str(ctx.get(m.group(1), m.group(0)))

    return _re.sub(r"\{\{?\s*(\w+)\s*\}\}?", repl, rule or "")


def _image_stem(rule: str, ctx: dict, index: int) -> str:
    """Tên ảnh theo Rule ảnh (CHỈ tên, KHÔNG kèm đuôi file).

    Đuôi file (.png/.jpg) do cấu hình AI ảnh → "Định dạng xuất" quyết định.
    """
    import re as _re

    name = ""
    if rule:
        name = render_rule(rule, {**ctx, "index": index + 1}).strip()
        name = _re.sub(r'[\\/:*?"<>|]+', "-", name)      # bỏ ký tự cấm trong tên file
        name = _re.sub(r"\s+", " ", name).strip()[:100]
    # bỏ đuôi cũ nếu người dùng có gõ kèm trong Rule ảnh
    name = _re.sub(r"\.(png|jpe?g|webp)$", "", name, flags=_re.I).strip()
    if not name:
        name = f"anh-{index + 1}"
    return name


def export_post_images(store, task) -> list[str]:
    """Lưu ảnh vào thư mục tên = ID công việc (để upload lên website).

    - Tên file: theo Rule ảnh (chỉ tên) + đuôi theo cấu hình AI ảnh.
    - Định dạng (PNG/JPG) và kích thước lấy từ Cấu hình → AI ảnh → Xử lý ảnh cục bộ.
    - Xuất TẤT CẢ ảnh đang có (kể cả ảnh thêm bằng nút "+ Thêm hình").
    """
    from PIL import Image as _Img

    from ..config import posts_dir

    r = task.result or {}
    images = r.get("images") or []
    if not images:
        return []
    base = posts_dir() / task.id
    base.mkdir(parents=True, exist_ok=True)
    rules = list(store.image_rules or [])
    pillow = ((store.ai_image or {}).get("pillow") or {})
    fmt = str(pillow.get("output_format", "PNG") or "PNG").upper()
    ext = ".jpg" if fmt == "JPG" else ".png"
    try:
        quality = max(50, min(100, int(pillow.get("jpg_quality", 90) or 90)))
    except (TypeError, ValueError):
        quality = 90
    try:
        out_size = int(pillow.get("size", 1080) or 0)      # 0 = giữ nguyên
    except (TypeError, ValueError):
        out_size = 1080
    ctx = {
        "title": r.get("title", ""),
        "focus_keyword": r.get("focus_keyword", ""),
        "keyword": r.get("focus_keyword", ""),
        "site": task.site_name,
        "description": r.get("description", ""),
    }
    out: list[str] = []
    for i, im in enumerate(images):
        src = Path(im.get("path", ""))
        if not src.exists():
            continue
        dest = base / f"{_image_stem(rules[i] if i < len(rules) else '', ctx, i)}{ext}"
        try:
            img = _Img.open(src)
            if out_size > 0 and (img.width != out_size or img.height != out_size):
                img = img.resize((out_size, out_size), _Img.LANCZOS)
            if ext == ".jpg":
                img.convert("RGB").save(dest, "JPEG", quality=quality)
            else:
                img.convert("RGBA").save(dest, "PNG")
            out.append(str(dest))
        except OSError:
            continue
    return out


def _remove_bg_opts(store) -> tuple[bool, int]:
    """Xoá nền TOÀN CỤC đã bỏ — giờ chỉ xoá nền theo từng thành phần (chuột phải)."""
    return False, 42


def pick_footer(site, mode: str = "") -> str:
    bars = [b for b in (site.footer_bars or []) if b]
    if not bars:
        return ""
    mode = mode or site.footer_mode or "bar1"
    if mode == "bar1":
        return bars[0]
    if mode == "bar2":
        return bars[1] if len(bars) > 1 else bars[0]
    return random.choice(bars)


def pick_footer_by_index(site, index: int, mode: str = "") -> str:
    """Luân phiên 1 -> 2 -> 1 -> 2 (trừ khi người dùng chọn cứng)."""
    bars = [b for b in (site.footer_bars or []) if b]
    if not bars:
        return ""
    mode = mode or site.footer_mode or ""
    if mode == "bar1":
        return bars[0]
    if mode == "bar2":
        return bars[1] if len(bars) > 1 else bars[0]
    return bars[index % len(bars)]


def _opts_list_of(result: dict) -> list[dict]:
    """Chuyển image_opts (cũ) -> danh sách tuỳ chọn theo từng ảnh."""
    lst = result.get("image_opts_list")
    if isinstance(lst, list):
        return [dict(x or {}) for x in lst]
    old = result.get("image_opts")
    if isinstance(old, dict) and old:
        return [dict(old)]
    return []


def build_template_images(site, task, brand_logo: str, product_paths: list[str],
                          footer_mode: str = "", log=None, rules: list[str] | None = None,
                          remove_bg: bool = False, remove_bg_thresh: int = 42,
                          opts: dict | None = None, only_index: int | None = None,
                          should_stop=None) -> list[dict]:
    """Ghép ảnh theo mẫu (dùng cho cả tạo mới và tạo lại ảnh)."""
    import re as _re

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
    opts_list = _opts_list_of(result)
    indices = [only_index] if only_index is not None else list(range(count))

    for i in indices:
        if should_stop is not None and should_stop():
            break
        o = dict(opts or {})
        if only_index is None and i < len(opts_list):
            o = dict(opts_list[i])
        elif only_index is not None and i < len(opts_list):
            o = {**opts_list[i], **o}
        logo_pos = tuple(o.get("logo_pos") or (0.015, 0.0))
        brand_pos = tuple(o.get("brand_pos") or (0.965, 0.035))
        logo_scale = float(o.get("logo_scale", 1.8) or 1.8)
        brand_scale = float(o.get("brand_scale", 1.0) or 1.0)
        brand_nobg = bool(o.get("brand_nobg", False))
        brand_hidden = bool(o.get("brand_hidden", False))
        product_scale = float(o.get("product_scale", 1.0) or 1.0)
        uploads = o.get("uploads") or None
        product_positions = o.get("product_pos") or None
        if product_positions:
            product_positions = [tuple(p) for p in product_positions]
        wm_opacity = int(o.get("watermark_opacity", 10) or 0)
        wm_size = float(o.get("watermark_size", 1.0) or 1.0)
        product_scales = o.get("product_scales") or None
        product_nobg = o.get("product_nobg") or None
        hidden = set(o.get("product_hidden") or [])
        rb = remove_bg if o.get("remove_bg") is None else bool(o["remove_bg"])
        mode_i = o.get("footer_mode") or footer_mode or mode
        footer = pick_footer_by_index(site, i, mode_i)
        keep = [k for k in range(len(product_paths or [])) if k not in hidden]
        prods = [product_paths[k] for k in keep]
        if o.get("no_products"):
            # ảnh mới thêm bằng "+ Thêm hình": để TRỐNG, chỉ có khung mẫu
            prods = []
        if product_scales:
            product_scales = [product_scales[k] for k in keep if k < len(product_scales)]
        if product_positions:
            product_positions = [product_positions[k] for k in keep
                                 if k < len(product_positions)]
        if product_nobg:
            product_nobg = [product_nobg[k] for k in keep if k < len(product_nobg)]
        img = compose(
            size=1080,
            site_logo=site.logo_path,
            brand_logo=brand_logo,
            products=prods[:3],
            footer_bar=footer,
            frame=site.frame_path,
            watermark=site.watermark_text,
            watermark_opacity=wm_opacity,
            watermark_size=wm_size,
            remove_bg=rb,
            remove_bg_thresh=remove_bg_thresh,
            logo_pos=logo_pos,
            brand_pos=brand_pos,
            logo_scale=logo_scale,
            brand_scale=brand_scale,
            brand_nobg=brand_nobg,
            brand_hidden=brand_hidden,
            product_scale=product_scale,
            product_positions=product_positions,
            product_scales=product_scales,
            product_nobg=product_nobg,
            uploads=uploads,
        )
        # Rule đặt tên ảnh (nếu có)
        rule = (rules[i] if i < len(rules) else "").strip()
        name = ""
        if rule:
            name = _re.sub(r"[^\w\-\. ]+", "", render_rule(rule, {**ctx, "index": i + 1})).strip()
        fname = f"{name.replace(' ', '-')[:80]}_{i + 1}.png" if name else f"{task.id}_{i + 1}.png"
        out = output_dir() / fname
        save_composed(img, str(out))
        images.append({"index": i, "path": str(out), "footer": footer})
    if log:
        log(f"Đã ghép {len(images)} ảnh.")
    return images


class ContentWorker(TrackedThread):
    """Đọc link nguồn -> AI viết -> ghép ảnh."""

    log = Signal(str)
    progress = Signal(int)
    ok = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, store, task, site) -> None:
        super().__init__()
        self.store = store
        self.task = task
        self.site = site
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _stopped(self) -> bool:
        return self._cancel

    def run(self) -> None:
        t, site = self.task, self.site
        try:
            self.progress.emit(5)
            if self._stopped():
                raise _Cancelled()
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

            if self._stopped():
                raise _Cancelled()
            data = generate_content(self.store, page, log=self.log.emit,
                                     should_stop=self._stopped)
            if self._stopped():
                raise _Cancelled()
            # 1) link nội bộ: mọi chỗ có tên miền của CHÍNH website này -> URL website
            raw_html = data.get("content_html", "")
            html_out = linkify_site(raw_html, site.url or "", site.name or "")

            # 2) link NGOÀI: mỗi site khác trong danh sách chèn 1 lần vào heading (h2..h5)
            others = [(x.url or "", x.name or "") for x in self.store.sites
                      if x.id != site.id and (x.url or "").strip()]
            if others:
                pname = extract_product_name(
                    raw_html, page.get("title", "") or data.get("title", "")
                )
                html_out = insert_external_links(
                    html_out, others,
                    [pname, data.get("focus_keyword", ""), data.get("title", ""),
                     page.get("title", "")],
                )
                self.log.emit(f"Chèn {len(others)} liên kết ngoài vào tiêu đề mục.")
            else:
                self.log.emit("Chỉ có 1 website trong danh sách — không chèn liên kết ngoài.")
            data["content_html"] = html_out
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

            if self._stopped():
                raise _Cancelled()
            # Ghép ảnh theo mẫu
            self.log.emit(f"Đang ghép {t.image_count} ảnh theo mẫu…")
            rb, th = _remove_bg_opts(self.store)
            images = build_template_images(site, t, brand_logo, product_paths,
                                           t.footer_mode, log=self.log.emit,
                                           rules=self.store.image_rules,
                                           remove_bg=rb, remove_bg_thresh=th)
            self.progress.emit(100)
            self.log.emit("Đang hiển thị kết quả…")

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
        except _Cancelled:
            self.log.emit("Đã dừng theo yêu cầu.")
            self.cancelled.emit()
        except Exception as exc:
            if self._cancel or "Đã dừng" in str(exc):
                self.log.emit("Đã dừng theo yêu cầu.")
                self.cancelled.emit()
                return
            traceback.print_exc()
            self.failed.emit(str(exc))


class FieldWorker(TrackedThread):
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


class ImagesWorker(TrackedThread):
    """Tạo lại ảnh theo mẫu (đổi thanh thông tin) mà không cần gọi lại AI."""

    log = Signal(str)
    ok = Signal(list)
    failed = Signal(str)

    def __init__(self, store, site, task, footer_mode: str = "",
                 opts: dict | None = None, only_index: int | None = None) -> None:
        super().__init__()
        self.store = store
        self.site = site
        self.task = task
        self.footer_mode = footer_mode
        self.opts = dict(opts or {})
        self.only_index = only_index
        self._cancel = False

    def stop(self) -> None:
        self._cancel = True

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
                opts=self.opts,
                only_index=self.only_index,
                should_stop=lambda: self._cancel,
            )
            if not self._cancel:
                self.ok.emit(images)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class PostWorker(TrackedThread):
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
        from ..wp.player import make_slug, show_page_notice, wait_editor_ready

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
                # LUÔN mở trang tạo bài trước khi phát lại kịch bản (bỏ qua nếu đang ở đó rồi)
                if site.new_post_url and "post-new.php" not in page.url:
                    self.log.emit("Mở trang tạo bài viết…")
                    page.goto(site.new_post_url, wait_until="domcontentloaded")
                wait_editor_ready(page, log=self.log.emit)
                # Hộp thoại (alert/confirm) của web: ghi log + chọn "Hủy bỏ" để KHÔNG xoá gì
                try:
                    page.on("dialog", lambda d: (
                        self.log.emit(f"  (web hỏi: {str(d.message)[:80]}…)"),
                        d.dismiss(),
                    ))
                except Exception:
                    pass
                self.log.emit("Phát lại kịch bản…")
                uploads = (self.result.get("post_images")
                           or [im["path"] for im in self.result.get("images", [])])
                ctx = {
                    "title": self.result.get("title", ""),
                    "content_html": self.result.get("content_html", ""),
                    "content": self.result.get("content_html", ""),
                    "focus_keyword": self.result.get("focus_keyword", ""),
                    "description": self.result.get("description", ""),
                    "tags": self.result.get("tags", ""),
                    "__upload_files": uploads,
                }
                # cho phép kịch bản dùng {{image_1}}, {{image_2}}… để tải từng ảnh
                for _n, _p in enumerate(uploads, 1):
                    ctx[f"image_{_n}"] = _p
                ctx["image"] = uploads[0] if uploads else ""
                # đường dẫn (slug) tạo từ tiêu đề, tối đa 60 ký tự
                ctx["slug"] = make_slug(ctx["title"], 65)
                try:
                    play_script(page, site.script, ctx, log=self.log.emit)
                except Exception as exc:
                    show_page_notice(
                        page,
                        "⚠️ Kịch bản DỪNG giữa đường\n"
                        f"{str(exc).splitlines()[0][:180]}\n"
                        "Bạn tự điền nốt phần còn lại rồi bấm Đăng.",
                        ok=False,
                    )
                    raise
            else:
                self.log.emit("Website chưa có kịch bản — mở trang tạo bài để bạn tự thao tác.")
                if site.new_post_url:
                    page.goto(site.new_post_url, wait_until="domcontentloaded")

            self.log.emit("Đã điền xong. Bạn kiểm tra rồi bấm Đăng trên WordPress.")
            show_page_notice(
                page,
                "✅ ĐÃ ĐIỀN XONG TỰ ĐỘNG\n"
                "Kiểm tra lại nội dung rồi bấm Đăng trên WordPress.",
                ok=True,
            )
            self.ok.emit(page.url)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class OpenLoginWorker(TrackedThread):
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


class LoginWorker(TrackedThread):
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


class ImageRefetchWorker(TrackedThread):
    """Crawl lại ảnh sản phẩm từ link nguồn và ghép lại 1 ảnh."""

    log = Signal(str)
    ok = Signal(list)
    failed = Signal(str)

    def __init__(self, store, site, task, index: int) -> None:
        super().__init__()
        self.store = store
        self.site = site
        self.task = task
        self.index = index

    def run(self) -> None:
        try:
            self.log.emit("Đang lấy ảnh sản phẩm từ link nguồn…")
            page = src.fetch_source(self.task.source_url)
            urls = list(page.get("images", []) or [])[:3]
            paths: list[str] = []
            for u in urls:
                try:
                    paths.append(src.download_image(u))
                except Exception:
                    continue

            if not paths:
                raise RuntimeError(
                    "Link nguồn không có ảnh sản phẩm nào để lấy."
                )
            r = self.task.result or {}
            r["product_images"] = paths
            rb, th = _remove_bg_opts(self.store)
            images = build_template_images(
                self.site, self.task, r.get("brand_logo", ""), paths,
                self.task.footer_mode, log=self.log.emit,
                rules=self.store.image_rules,
                remove_bg=rb, remove_bg_thresh=th,
                only_index=self.index,
            )
            self.ok.emit(images)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class ImageEditWorker(TrackedThread):
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

