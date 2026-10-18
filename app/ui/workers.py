"""Các luồng chạy nền (tạo nội dung, đăng bài, ghi kịch bản)."""
from __future__ import annotations

import random
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .. import source as src
from ..ai import generate_content
from ..ai.manager import (apply_template_icons, extract_product_name,
                             insert_title_links, linkify_domains)
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
    - Định dạng (PNG/JPG) và kích thước lấy từ Cài đặt → AI ảnh → Xử lý ảnh cục bộ.
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


def _site_bars(site) -> list[str]:
    """Thanh thông tin: file riêng của website -> nếu trống thì dùng MẶC ĐỊNH của phần mềm."""
    from ..config import default_asset

    bars = [b for b in (site.footer_bars or []) if b]
    if bars:
        return bars
    return [x for x in (default_asset("bar1.png"), default_asset("bar2.png")) if x]


def pick_footer(site, mode: str = "") -> str:
    bars = _site_bars(site)
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
    bars = _site_bars(site)
    if not bars:
        return ""
    mode = mode or site.footer_mode or ""
    if mode == "bar1":
        return bars[0]
    if mode == "bar2":
        return bars[1] if len(bars) > 1 else bars[0]
    # mặc định: hình ĐẦU dùng thanh 1, các hình sau dùng thanh 2
    return bars[0] if index == 0 else (bars[1] if len(bars) > 1 else bars[0])


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
        logo_pos = tuple(o.get("logo_pos") or (0.025, 0.018))
        brand_pos = tuple(o.get("brand_pos") or (0.955, 0.032))
        logo_scale = float(o.get("logo_scale", 1.8) or 1.8)
        brand_scale = float(o.get("brand_scale", 1.0) or 1.0)
        brand_nobg = bool(o.get("brand_nobg", False))
        brand_hidden = bool(o.get("brand_hidden", False))
        product_scale = float(o.get("product_scale", 1.0) or 1.0)
        uploads = o.get("uploads") or None
        product_positions = o.get("product_pos") or None
        if product_positions:
            product_positions = [tuple(p) for p in product_positions]
        wm_opacity = int(o.get("watermark_opacity", 50) or 0)
        wm_size = float(o.get("watermark_size", 1.0) or 1.0)
        wm_rot = float(o.get("watermark_rotate", 50) or 50)
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
        from ..config import default_asset

        img = compose(
            size=1080,
            site_logo=site.logo_path or default_asset("logo.png"),
            brand_logo=brand_logo,
            products=prods[:3],
            footer_bar=footer,
            frame="",                      # khung viền: đã bỏ, không dùng nữa
            watermark=site.watermark_text,
            watermark_opacity=wm_opacity,
            watermark_size=wm_size,
            watermark_rotate=wm_rot,
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


def merge_sources(pages: list[dict], urls: list[str]) -> dict:
    """Gộp NHIỀU trang nguồn thành 1 nguồn (nhiều link -> 1 bài viết)."""
    pages = [p for p in (pages or []) if isinstance(p, dict)]
    if not pages:
        return {}
    if len(pages) == 1:
        p = dict(pages[0])
        p["urls"] = list(urls or [p.get("url", "")])
        return p
    imgs: list[str] = []
    texts: list[str] = []
    for i, pg in enumerate(pages, 1):
        u = str(pg.get("url") or (urls[i - 1] if i - 1 < len(urls) else ""))
        texts.append(f"=== NGUỒN {i}: {u} ===\n{str(pg.get('text') or '').strip()}")
        for im in (pg.get("images") or []):
            if im and im not in imgs:
                imgs.append(im)
    return {
        "url": (urls[0] if urls else str(pages[0].get("url") or "")),
        "urls": list(urls),
        "title": str(pages[0].get("title") or ""),
        "text": "\n\n".join(texts)[:18000],
        "images": imgs,
    }


class ContentWorker(TrackedThread):
    """Đọc link nguồn -> AI viết -> ghép ảnh."""

    log = Signal(str)
    progress = Signal(int)
    ok = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, store, task, site, content_only: bool = False) -> None:
        super().__init__()
        self.store = store
        self.task = task
        self.site = site
        self.content_only = bool(content_only)   # CHỈ tạo lại NỘI DUNG -> không đụng tới ảnh
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
            urls = [u for u in (getattr(t, "source_urls", None) or []) if str(u).strip()]
            if not urls and t.source_url:
                urls = [t.source_url]
            self.log.emit("Đang đọc link nguồn…" if len(urls) <= 1
                          else f"Đang đọc {len(urls)} link nguồn…")
            pages: list[dict] = []
            for i, u in enumerate(urls, 1):
                if self._stopped():
                    raise _Cancelled()
                if len(urls) > 1:
                    self.log.emit(f"  nguồn {i}/{len(urls)}: {u}")
                try:
                    pages.append(src.fetch_source(u))
                except Exception as exc:      # noqa: BLE001
                    self.log.emit(f"  (bỏ qua nguồn {i}: {str(exc)[:80]})")
            if not pages:
                raise RuntimeError("Không đọc được link nguồn nào.")
            page = merge_sources(pages, urls)
            if len(urls) > 1:
                self.log.emit(f"Đã gộp {len(pages)}/{len(urls)} nguồn thành 1 bài viết.")
            self.progress.emit(25)

            # KHÔNG tự tải/chèn ảnh nữa: chỉ lưu danh sách ảnh nguồn để người dùng chọn
            source_images = [u for u in (page.get("images") or []) if u]
            self.log.emit(f"Tìm thấy {len(source_images)} ảnh trên trang nguồn "
                          "(chọn trong trình sửa ảnh → “Hình từ nguồn”).")
            product_paths: list[str] = []
            self.progress.emit(45)

            if self._stopped():
                raise _Cancelled()
            data = generate_content(self.store, page, log=self.log.emit,
                                     should_stop=self._stopped)
            if self._stopped():
                raise _Cancelled()
            # 0) icon đầu mục + icon dòng liên hệ cho ĐÚNG template (Rule_Content mục 5)
            raw_html = data.get("content_html", "")
            html_out = apply_template_icons(raw_html)

            # 1) mọi chỗ có "www.<tên-miền>" -> link về ĐÚNG tên miền đó (bỏ www)
            all_sites = [(x.url or "", x.name or "") for x in self.store.sites]
            html_out = linkify_domains(html_out, all_sites)

            # 2) link vào TIÊU ĐỀ MỤC: h2 đầu = website đang đăng; từ h2 thứ 2 = link trong cấu hình
            title_links = list(self.store.title_links)
            pname = extract_product_name(
                raw_html, page.get("title", "") or data.get("title", "")
            )
            html_out = insert_title_links(
                html_out, self.store.title_link_first, title_links,
                [pname, data.get("focus_keyword", ""), data.get("title", ""),
                 page.get("title", "")],
            )
            self.log.emit(
                f"Chèn link tiêu đề: h1/h2 đầu → {self.store.title_link_first or '(trống)'}, "
                f"{len(title_links)} link cấu hình cho các mục sau."
            )
            data["content_html"] = html_out
            self.progress.emit(70)

            if self.content_only:
                # "Random lại" -> CHỈ tạo lại nội dung, GIỮ NGUYÊN ảnh đang có
                self.progress.emit(100)
                self.log.emit("Chỉ tạo lại nội dung — giữ nguyên ảnh đang có.")
                self.ok.emit(dict(data))
                return

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
                self.log.emit("Không tìm được logo thương hiệu — bỏ qua (có thể thêm ở Cài đặt).")

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
                    "source_images": source_images,
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
                (r.get("brand_logo")
                 or str(getattr(self.task, "brand_logo_fallback", "") or "")),
                list(r.get("product_images") or []),
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
    """Mở trình duyệt -> tự đăng nhập -> phát lại kịch bản (điền form).

    Sau khi điền xong, luồng này CHỜ người dùng đóng trình duyệt rồi mới phát
    tín hiệu `closed` — dùng để mở lại nút "Đăng bài" (mỗi việc chỉ 1 Chrome).
    """

    log = Signal(str)
    ok = Signal(str)
    failed = Signal(str)
    closed = Signal(str)          # người dùng đã đóng trình duyệt

    def __init__(self, site, result: dict) -> None:
        super().__init__()
        self.site = site
        self.result = result
        self._running = True

    def stop(self) -> None:
        self._running = False

    def _wait_closed(self, page, br, timeout: int = 7200) -> None:
        """Chờ người dùng đóng cửa sổ Chrome (tối đa 2 giờ).

        Kiểm tra bằng DANH SÁCH TIẾN TRÌNH của profile (không hỏi Playwright — Playwright
        vẫn báo "chưa đóng" sau khi người dùng tắt Chrome, phải chờ ~1 phút mới biết).
        """
        import time

        from ..wp.browser import _pids_using_profile, _user_data_dir

        try:
            profile = _user_data_dir(getattr(self.site, "id", "") or "default")
        except Exception:      # noqa: BLE001
            profile = ""
        deadline = time.time() + timeout
        while self._running and time.time() < deadline:
            time.sleep(2)
            if profile:
                try:
                    if not _pids_using_profile(profile):
                        break                    # Chrome đã tắt hẳn -> mở khoá ngay
                except Exception:      # noqa: BLE001
                    pass
                continue
            try:                                 # dự phòng khi không lấy được profile
                if page.is_closed():
                    break
            except Exception:      # noqa: BLE001
                break
        try:
            if br:
                br.close()
        except Exception:
            pass

    def run(self) -> None:
        from ..wp import WPBrowser, play_script
        from ..wp.player import make_slug, show_page_notice, wait_editor_ready

        site = self.site
        br = None
        page = None
        _on_dialog = None
        try:
            self.log.emit("Mở trình duyệt…")
            br = WPBrowser(headless=False, site_id=site.id, log=self.log.emit)
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
                def _on_dialog(d) -> None:      # noqa: ANN001
                    try:
                        self.log.emit(f"  (web hỏi: {str(d.message)[:80]}…)")
                        d.dismiss()
                    except Exception:
                        pass

                try:
                    page.on("dialog", _on_dialog)
                except Exception:
                    _on_dialog = None
                # chỉ tắt cảnh báo "rời trang" của web (KHÔNG chặn các hộp thoại khác)
                try:
                    page.evaluate(
                        "() => { window.onbeforeunload = null;"
                        " window.addEventListener('beforeunload',"
                        " (e) => { e.stopImmediatePropagation(); }, true); }"
                    )
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
                    ctx[f"image_name_{_n}"] = Path(_p).stem      # tên ảnh (không đuôi)
                ctx["image"] = uploads[0] if uploads else ""
                ctx["image_name"] = Path(uploads[0]).stem if uploads else ""
                # đường dẫn (slug) tạo từ tiêu đề, tối đa 60 ký tự
                ctx["slug"] = make_slug(ctx["title"], 59)
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
        finally:
            # Kịch bản XONG hoặc LỖI -> DỪNG ĐIỀU KHIỂN CHROME: gỡ bộ bắt hộp thoại,
            # từ đây app không can thiệp vào trang nữa (bạn tự do bấm/kiểm tra).
            if _on_dialog is not None and page is not None:
                try:
                    page.remove_listener("dialog", _on_dialog)
                    self.log.emit("Đã dừng điều khiển Chrome — bạn tự do thao tác trên trang.")
                except Exception:      # noqa: BLE001
                    pass
            # Nút "Đăng bài" chỉ mở lại khi NGƯỜI DÙNG đóng trình duyệt
            if page is not None:
                try:
                    if not page.is_closed():
                        self.log.emit("Bạn tự kiểm tra rồi bấm Đăng; đóng trình duyệt khi xong.")
                except Exception:      # noqa: BLE001
                    pass
                self._wait_closed(page, br)
            self.closed.emit("")


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
            self.log.emit("Đang lấy đối tượng hình ảnh từ link nguồn…")
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
                    "Link nguồn không có đối tượng hình ảnh nào để lấy."
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


class SourceImageDownloadWorker(TrackedThread):
    """Tải danh sách ảnh từ link nguồn về máy (để hiện trong popup chọn ảnh)."""

    done = Signal(str, object)     # (url, bytes) — giữ trong bộ nhớ, KHÔNG lưu ra máy
    progress = Signal(str)

    def __init__(self, urls: list[str]) -> None:
        super().__init__()
        self.urls = list(urls)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        import httpx

        from ..source import UA

        total = len(self.urls)
        for i, url in enumerate(self.urls, 1):
            if self._stop:
                break
            self.progress.emit(f"Đang tải ảnh {i}/{total}…")
            data = b""
            try:
                r = httpx.get(url, headers=UA, follow_redirects=True, timeout=60)
                r.raise_for_status()
                data = r.content
            except Exception:
                data = b""
            self.done.emit(url, data)
        self.progress.emit("")


class SplitWorker(TrackedThread):
    """Chia 1 link nguồn thành N bài viết (CHỈ content, KHÔNG JSON SEO)."""

    log = Signal(str)
    ok = Signal(list)          # danh sách content HTML
    failed = Signal(str)

    def __init__(self, store, link: str, n: int) -> None:
        super().__init__()
        self.store = store
        self.link = str(link or "")
        self.n = max(2, int(n or 2))

    def run(self) -> None:
        try:
            from ..ai.manager import (_call_ai, apply_template_icons,
                                      build_split_prompt, clean_content_html,
                                      linkify_domains, parse_split_articles)

            self.log.emit(f"Đang đọc link nguồn rồi chia thành {self.n} bài…")
            page = src.fetch_source(self.link)
            full = build_split_prompt(self.store.formats, page, self.n, with_rule=True)
            short = build_split_prompt(self.store.formats, page, self.n, with_rule=False)
            raw = _call_ai(self.store, full, short, self.log.emit)
            # LƯU câu trả lời THÔ để soi khi cần
            try:
                from ..config import output_dir

                (output_dir() / "last_split_reply.txt").write_text(str(raw or ""), encoding="utf-8")
            except Exception:      # noqa: BLE001
                pass
            arts = parse_split_articles(raw, self.n)
            self.log.emit(f"AI trả về {len(str(raw or ''))} ký tự — tách được {len(arts)} bài.")
            all_sites = [(x.url or "", x.name or "") for x in self.store.sites]
            out: list[str] = []
            for a in arts:
                if len(str(a).strip()) < 300:      # bài rỗng/quá ngắn -> bỏ (tránh tạo job rác)
                    continue
                # DỌN RÁC HTML ở đầu/cuối (```html, <!DOCTYPE>, <html>, <head>, <body>, chữ "html")
                html = clean_content_html(a)
                html = apply_template_icons(html)
                html = linkify_domains(html, all_sites)
                if html.strip():
                    out.append(html)
            if not out:
                raise RuntimeError(
                    "AI không trả về BÀI VIẾT nào (chỉ có dòng ngăn cách hoặc bài quá ngắn). "
                    "Xem câu trả lời thô ở output/last_split_reply.txt"
                )
            self.log.emit(f"Đã chia được {len(out)}/{self.n} bài.")
            self.ok.emit(out)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(exc))


class CanvasPreviewWorker(TrackedThread):
    """Dựng ẢNH NỀN cho canvas (nền + thanh thông tin) ở LUỒNG RIÊNG -> app không bị đứng."""

    ok = Signal(str)          # đường dẫn file ảnh nền
    failed = Signal(str)

    def __init__(self, params: dict) -> None:
        super().__init__()
        self.params = dict(params or {})

    def run(self) -> None:
        try:
            p = self.params
            base = compose(
                size=1080,
                site_logo="", brand_logo="", products=[],
                footer_bar=str(p.get("footer", "") or ""),
                frame="",
                watermark="",            # watermark vẽ riêng trên canvas
                watermark_opacity=0,
                remove_bg=bool(p.get("remove_bg", False)),
                remove_bg_thresh=int(p.get("remove_bg_thresh", 42) or 42),
                product_scale=float(p.get("product_scale", 1.0) or 1.0),
            )
            out = str(p.get("out", "") or "")
            if not out:
                raise RuntimeError("thiếu đường dẫn ảnh nền")
            save_composed(base, out)
            self.ok.emit(out)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(exc))


class SeoJsonWorker(TrackedThread):
    """Tạo JSON SEO (title / description / focus_keyword / tags) từ NỘI DUNG đã có."""

    log = Signal(str)
    ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, store, content_html: str) -> None:
        super().__init__()
        self.store = store
        self.content_html = str(content_html or "")

    def run(self) -> None:
        try:
            from ..ai.manager import generate_seo_json

            seo = generate_seo_json(self.store, self.content_html, log=self.log.emit)
            self.ok.emit(dict(seo or {}))
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(exc))


class SourceImageSearchWorker(TrackedThread):
    """Tìm ảnh trên internet theo keyword (dùng trong popup "Hình tự tìm")."""

    log = Signal(str)
    ok = Signal(list)          # danh sách URL ảnh
    failed = Signal(str)

    def __init__(self, query: str, limit: int = 20) -> None:
        super().__init__()
        self.query = str(query or "")
        self.limit = max(1, int(limit or 20))

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from ..source import search_images

        try:
            urls = search_images(self.query, limit=self.limit, log=self.log.emit)
            self.ok.emit(list(urls or []))
        except Exception as exc:      # noqa: BLE001
            self.failed.emit(str(exc))


class UpdateWorker(TrackedThread):
    """Kiểm tra / tải & áp dụng bản cập nhật phần mềm."""

    log = Signal(str)
    checked = Signal(dict)     # {"version", "url", "notes"}
    applied = Signal(str)      # thư mục tạm của bộ cài
    failed = Signal(str)

    def __init__(self, apply_url: str = "") -> None:
        super().__init__()
        self.apply_url = apply_url

    def run(self) -> None:
        from .. import update

        try:
            if self.apply_url:
                tmp = update.apply_update(self.apply_url, log=self.log.emit)
                self.applied.emit(str(tmp))
                return
            self.checked.emit(update.check_update())
        except Exception as exc:      # noqa: BLE001 (lỗi mạng là bình thường)
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

