"""Cửa sổ chính."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..storage.models import (
    Site,
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_QUEUED,
    STATUS_GENERATING,
    STATUS_FINISH,
    Task,
)
from ..storage.store import Store
from .pages.config_page import ConfigPage
from .pages.error_log_page import ErrorLogPage
from .pages.jobs_page import JobsPage
from .pages.post_page import PostPage
from .style import app_font, register_bundled_fonts
from .toast import show_toast
from .widgets.seo_progress import SeoProgressOverlay
from .workers import (
    ContentWorker,
    export_post_images,
    ImageRefetchWorker,
    _opts_list_of,
    ImageEditWorker,
    ImagesWorker,
    PostWorker,
    SeoJsonWorker,
    SplitSeoWorker,
    SplitWorker,
    shutdown_all_threads,
)

# (chữ trên tab, chỉ số trang trong stack) — "Cài đặt" đã chuyển thành nút ⚙ góc phải trên
NAV = [("Đăng bài", 1), ("Công việc đang làm", 2)]      # Log lỗi đã chuyển vào Cài đặt
GEAR_PAGE = 0      # trang "Cài đặt"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = Store()
        self.store.reset_stale_tasks()
        self.setWindowTitle("Hỗ Trợ Đăng Bài — WordPress")
        self.resize(1240, 820)
        try:                      # nạp font đóng gói kèm app (Canva Sans) — dùng cho watermark
            register_bundled_fonts()
        except Exception:
            pass
        self.setFont(app_font())
        self._workers: list = []
        self._content_workers: dict = {}
        self._img_workers: dict = {}
        self._img_queue: dict = {}        # việc ghép ảnh đang chờ (task_id -> [(opts, index, msg)])
        self._content_only_ids: set = set()  # "Random lại" -> chỉ tạo lại NỘI DUNG, giữ nguyên ảnh
        self._seo_worker = None              # luồng tạo JSON SEO (job trống)
        self._split_worker = None            # luồng chia 1 link thành N bài
        self._split_seo_worker = None         # luồng tạo JSON SEO cho từng bài đã chia
        self._split_seo_overlay = None        # popup phủ toàn app báo tiến trình lấy JSON SEO
        self._split_seo_cancelled = False     # người dùng đã bấm "Dừng và đóng"
        self._post_workers: dict = {}        # task_id -> luồng đăng bài
        self._post_sites: dict = {}           # task_id -> website đang đăng (chọn lúc bấm Đăng)
        self._post_started: dict = {}        # task_id -> thời điểm bắt đầu đăng (giây)
        self._start_post_watchdog()          # lưới an toàn: Chrome tắt -> mở khoá nút
        self._start_update_watch()           # kiểm tra cập nhật (chỉ Windows)
        self._build()
        try:                       # mở app là vào thẳng tab "Đăng bài"
            self._go(1)
        except Exception:
            pass
        try:                       # nút bị khoá -> mờ đi (mọi nút trong cửa sổ)
            from .style import dim_all_buttons

            dim_all_buttons(self)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # thanh tiêu đề
        titlebar = QFrame()
        titlebar.setObjectName("titleBar")
        tl = QHBoxLayout(titlebar)
        tl.setContentsMargins(16, 10, 16, 10)
        name = QLabel("WP Multi Poster")
        tl.addWidget(name)
        tl.addStretch(1)
        # nút CÀI ĐẶT (icon răng cửa) ở GÓC PHẢI TRÊN
        self.gear_btn = QPushButton()
        self.gear_btn.setObjectName("gearBtn")
        self.gear_btn.setCheckable(True)
        self.gear_btn.setToolTip("Cài đặt")
        self.gear_btn.setCursor(Qt.PointingHandCursor)
        try:
            from ..config import default_asset_path

            icon_path = default_asset_path("icons/gear.svg")
            if icon_path:
                self.gear_btn.setIcon(QIcon(icon_path))
                self.gear_btn.setIconSize(QSize(20, 20))
        except Exception:      # noqa: BLE001
            traceback.print_exc()
        self.gear_btn.clicked.connect(lambda: self._go(GEAR_PAGE))
        tl.addWidget(self.gear_btn)
        v.addWidget(titlebar)

        # thanh điều hướng
        nav = QFrame()
        nav.setObjectName("navBar")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(10, 0, 10, 0)
        nl.setSpacing(0)
        self.nav_buttons: list[QPushButton] = []
        for text, page_idx in NAV:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("pageIndex", page_idx)
            b.setChecked(page_idx == 1)   # mặc định mở tab "Đăng bài"
            b.clicked.connect(lambda _=False, idx=page_idx: self._go(idx))
            nl.addWidget(b)
            self.nav_buttons.append(b)
        nl.addStretch(1)
        v.addWidget(nav)

        # nội dung
        self.stack = QStackedWidget()
        self.post_page = PostPage(self.store)
        self.error_log_page = ErrorLogPage(self.store)     # nằm trong Cài đặt (sidebar)
        self.config_page = ConfigPage(self.store, self.error_log_page,
                                      on_cache_cleared=self._on_cache_cleared)
        self.jobs_page = JobsPage(self.store)
        self.jobs_page._post_sites = self._post_sites    # job chưa lưu website -> dùng chung
        for page in (self.config_page, self.post_page, self.jobs_page):
            self.stack.addWidget(page)
        v.addWidget(self.stack, 1)

        self.setCentralWidget(root)
        # KHÔNG dùng thanh dưới (status bar) nữa — mọi thông báo nằm ở item / Log lỗi / nút

        # signals
        self.post_page.create_task.connect(self._on_create_task)
        self.post_page.split_task.connect(self._on_split_task)
        self.jobs_page.regenerate.connect(self._on_regenerate)
        self.jobs_page.regenerate_images.connect(self._on_regenerate_images)
        self.jobs_page.delete_task.connect(self._on_delete_task)
        self.jobs_page.post.connect(self._on_post_task)
        self.jobs_page.ai_edit.connect(self._on_ai_edit)
        self.jobs_page.refetch_image.connect(self._on_refetch_image)
        self.jobs_page.recompose_image.connect(self._on_recompose_image)
        self.jobs_page.recompose_all.connect(self._on_recompose_all)
        self.jobs_page.export_images.connect(self._on_export_images)
        self.jobs_page.trim_component.connect(self._on_trim_component)
        self.jobs_page.stop_all.connect(self._on_stop_all)
        self.jobs_page.apply_image_opts.connect(self._on_apply_image_opts)
        self.jobs_page.cancel_task.connect(self._on_cancel_task)
        self.jobs_page.status_msg.connect(self.status)
        self.jobs_page.seo_json.connect(self._on_seo_json)
        self.jobs_page.models_extract.connect(self._on_models_extract)
        self.config_page.changed.connect(self._on_config_changed)

        self._refresh_count()
        self._check_env()

    # ------------------------------------------------------------------ #
    def _check_env(self) -> None:
        if not self.store.sites:
            self.status("Chưa có website — vào tab Cài đặt để thêm.")

    def status(self, text: str) -> None:
        """Đã BỎ thanh dưới -> không hiện message nữa (giữ hàm để không phải sửa 38 chỗ gọi)."""
        return

    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for b in self.nav_buttons:
            try:
                b.setChecked(int(b.property("pageIndex") or -1) == index)
            except Exception:      # noqa: BLE001
                pass
        try:
            self.gear_btn.setChecked(index == GEAR_PAGE)
        except Exception:      # noqa: BLE001
            pass
        if index == 2:
            self.jobs_page.refresh()
        elif index == 1:
            self.post_page.reload_sites()      # tab "Đăng bài"

    def _refresh_count(self) -> None:
        for b in self.nav_buttons:
            if int(b.property("pageIndex") or -1) == 2:
                b.setText(f"Công việc đang làm ({len(self.store.tasks)})")
                break

    def _on_cache_cleared(self) -> None:
        """Vừa xoá cache: bỏ cache ảnh trong RAM + nạp lại danh sách job (đã trống)."""
        try:
            self.jobs_page._img_cache.clear()
        except Exception:      # noqa: BLE001
            pass
        try:
            self.jobs_page.current = None
            self.jobs_page.refresh()
            self._refresh_count()
        except Exception:      # noqa: BLE001
            pass
        show_toast(self, "Đã xoá cache — toàn bộ job và ảnh đã xoá", 3200)

    def _on_config_changed(self) -> None:
        self.post_page.reload_sites()

    # ------------------------------------------------------------------ #
    def _on_create_task(self, task) -> None:
        """Việc mới: đưa vào HÀNG ĐỢI (queued) rồi để bộ điều phối chạy khi tới lượt."""
        site = self._site_of(task)
        if (getattr(task, "kind", "") or "") == "blank":
            # JOB TRỐNG: không chạy AI -> mở thẳng panel kết quả, các ô để trống
            task.status = STATUS_FINISH
            task.progress = 100
            task.message = ""
            task.error_stage = ""
            # tạo sẵn ĐÚNG số ô ảnh đã chọn (để trống, chờ tải ảnh lên)
            slots = [{"path": "", "footer": ""} for _ in range(max(1, int(task.image_count or 3)))]
            task.result = {"title": "", "focus_keyword": "", "description": "",
                           "tags": "", "category_name": "", "brand_name": "",
                           "ma_san_pham": "",
                           "content_html": "",
                           "images": slots, "image_opts_list": [{} for _ in slots],
                           "product_images": []}
            self.store.upsert_task(task)
            self.store.save()
            self._go(2)
            self.jobs_page.refresh()
            self.jobs_page.select_task(task.id)
            self._refresh_count()
            self.status(f"Đã tạo job trống cho {site.name} — đang ghép ảnh…")
            # TỰ GHÉP ẢNH ngay (logo site + thanh thông tin + watermark + logo thương hiệu nếu có;
            # KHÔNG có ảnh sản phẩm — người dùng tự thêm sau)
            self._start_images_worker(task, None, None, "Đang ghép ảnh…")
            return
        task.status = STATUS_QUEUED
        task.progress = 0
        task.message = ""
        task.error_stage = ""
        self.store.upsert_task(task)
        self.store.save()

        # Chuyển ngay sang tab "Công việc đang làm" và chọn việc mới
        self._go(2)
        self.jobs_page.refresh()
        self.jobs_page.select_task(task.id)
        self._refresh_count()
        self._start_next_content()

    def _running_content_id(self) -> str:
        """Id của việc ĐANG tạo nội dung (rỗng nếu không có)."""
        return next(iter(self._content_workers), "")

    def _start_next_content(self) -> None:
        """Bộ điều phối: mỗi lúc CHỈ 1 việc tạo nội dung; chọn việc cũ nhất đang chờ."""
        try:
            if self._running_content_id():
                self._update_ai_busy()
                return
            queued = [t for t in self.store.tasks if t.status == STATUS_QUEUED]
            if not queued:
                self._update_ai_busy()
                return
            task = queued[0]                      # job cũ nhất chạy trước
            site = self._site_of(task)
            task.status = STATUS_GENERATING
            task.progress = 10
            task.message = ""
            task.error_stage = ""
            self.store.upsert_task(task)
            self.store.save()
            self._spawn_content_worker(task, site)
            self.jobs_page.refresh()
            self._refresh_count()
            self._update_ai_busy()
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Hàng đợi tạo nội dung", str(exc))

    def _spawn_content_worker(self, task, site) -> None:
        content_only = task.id in self._content_only_ids
        worker = ContentWorker(self.store, task, site, content_only=content_only)
        self._content_workers[task.id] = worker
        worker.log.connect(self._on_worker_log)
        worker.ok.connect(lambda res: self._on_content_ok(task, res))
        worker.failed.connect(lambda err: self._on_content_failed(task, err))
        worker.cancelled.connect(lambda: self._on_content_cancelled(task))
        worker.finished.connect(lambda: (self._content_workers.pop(task.id, None),
                                         self._content_only_ids.discard(task.id),
                                         self._cleanup(worker),
                                         self._start_next_content()))
        self._workers.append(worker)
        worker.start()
        self._update_ai_busy()
        self.status(f"Đang tạo nội dung cho {site.name}…")

    def _update_ai_busy(self) -> None:
        """ChatGPT đang chạy việc nào -> khoá nút gọi AI ở mọi việc (provider API thì không)."""
        try:
            busy = bool(self._content_workers)      # mọi provider đều chạy tuần tự
            self.jobs_page.set_ai_busy(busy)
        except Exception:
            pass

    def _on_worker_log(self, msg: str) -> None:
        """Log của worker: chỉ cập nhật panel nếu panel đang xem ĐÚNG việc đó."""
        try:
            w = self.sender()
            tid = next((k for k, v in self._content_workers.items() if v is w), "")
        except Exception:
            tid = ""
        self.status(msg)
        # chỉ ghi message vào panel khi đang xem đúng công việc đang chạy
        try:
            cur = getattr(self.jobs_page, "current", None)
            if tid and cur is not None and getattr(cur, "id", "") == tid:
                self.jobs_page.set_loading_message(msg)
        except Exception:
            pass

    def _on_content_ok(self, task, result: dict) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        content_only = task.id in self._content_only_ids
        try:
            if content_only:
                # chỉ thay NỘI DUNG, giữ nguyên ảnh + tuỳ chọn ảnh đang có
                r = dict(fresh.result or {})
                r.update({k: v for k, v in (result or {}).items()
                          if k in ("title", "focus_keyword", "description",
                                   "tags", "category_name", "brand_name",
                                   "ma_san_pham", "content_html")})
                fresh.result = r
            else:
                fresh.result = result
            fresh.status = STATUS_FINISH
            fresh.progress = 100
            fresh.error_stage = ""
            self.store.upsert_task(fresh)
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Lưu kết quả AI", str(exc))
            self.status("Lỗi khi lưu kết quả — xem tab Log lỗi.")
            return
        try:
            self._refresh_jobs_keep(fresh)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Hiển thị kết quả AI", str(exc))
            self.status("Lỗi khi hiển thị kết quả — xem tab Log lỗi.")
            return
        self._refresh_count()
        self.status("Xong — vào tab Công việc đang làm để duyệt.")
        self._prefetch_source_images(fresh)      # tự lấy sẵn ảnh từ link nguồn

    def _prefetch_source_images(self, task, targets: list | None = None) -> None:
        """Job vừa TẠO XONG NỘI DUNG -> tự lấy ảnh từ ĐÚNG link nguồn (chạy nền).

        Ảnh lưu sẵn vào job -> mở "Tìm hình" là có ngay, không phải bấm "Lấy hình".
        """
        try:
            if task is None:
                return
            kind = str(getattr(task, "kind", "") or "")
            if kind == "blank" and not int(getattr(task, "split_no", 0) or 0):
                return                       # job trống (không có link nguồn)
            r = task.result or {}
            if [u for u in (r.get("source_images") or []) if u]:
                return                       # đã có ảnh -> không lấy lại
            links = [u for u in (r.get("image_links") or []) if u]
            if not links:
                links = list(getattr(task, "source_urls", []) or [])
            if not links and str(getattr(task, "source_url", "") or "").strip():
                links = [task.source_url]
            links = [str(u).strip() for u in links if str(u).strip()]
            if not links:
                return
            ids = [str(x) for x in (targets or [task.id])]
            from .workers import SourceImagesFetchWorker

            worker = SourceImagesFetchWorker(links)
            self.status("Đang lấy sẵn ảnh từ link nguồn…")

            def _ok(urls) -> None:
                urls = [u for u in (urls or []) if u]
                if not urls:
                    return
                for tid in ids:
                    fresh = next((t for t in self.store.tasks if t.id == tid), None)
                    if fresh is None:
                        continue
                    rr = fresh.result = dict(fresh.result or {})
                    if [u for u in (rr.get("source_images") or []) if u]:
                        continue             # đã có -> giữ nguyên
                    rr["source_images"] = list(urls)
                    if not [u for u in (rr.get("image_links") or []) if u]:
                        rr["image_links"] = list(links)
                    self.store.upsert_task(fresh)
                self.store.save()
                if getattr(self.jobs_page.current, "id", "") in ids:
                    fresh = next((t for t in self.store.tasks
                                  if t.id == self.jobs_page.current.id), None)
                    if fresh is not None:
                        self.jobs_page.current = fresh
                self.status(f"Đã lấy sẵn {len(urls)} ảnh từ link nguồn.")

            worker.ok.connect(_ok)
            worker.failed.connect(lambda _e: self.status("Không lấy được ảnh từ link nguồn."))
            worker.finished.connect(lambda: self._cleanup(worker))
            self._workers.append(worker)
            worker.start()
        except Exception:      # noqa: BLE001
            traceback.print_exc()

    def _on_cancel_task(self, task) -> None:
        worker = self._content_workers.get(task.id)
        if worker and worker.isRunning():
            worker.cancel()
            self.status("Đang dừng…")
            # provider ChatGPT -> đóng NGAY cửa sổ Chrome (khỏi chờ worker thoát)
            try:
                active = str(self.store.ai_content.get("active") or "")
                if active == "chatgpt":
                    from ..wp.browser import _kill_profile_browsers, _user_data_dir

                    d = _user_data_dir("chatgpt")
                    _kill_profile_browsers(d)
                    self.status("Đã đóng Chrome ChatGPT — đang dừng…")
            except Exception:
                pass
        else:
            self.status("Sẵn sàng")

    def _refresh_jobs_keep(self, task) -> None:
        """Refresh danh sách nhưng GIỮ đúng việc người dùng đang xem."""
        try:
            cur = getattr(self.jobs_page, "current", None)
            keep = getattr(cur, "id", "") or ""
            self.jobs_page.refresh()
            if keep:
                self.jobs_page.select_task(keep)
            else:
                self.jobs_page.select_task(getattr(task, "id", ""))
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Hiển thị kết quả", str(exc))

    def _on_content_cancelled(self, task) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.status = STATUS_CANCELLED
        fresh.message = "Đã dừng theo yêu cầu"
        self.store.upsert_task(fresh)
        self.store.save()
        try:
            self._refresh_jobs_keep(fresh)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Hiển thị kết quả", str(exc))
        self.status("Đã dừng tạo nội dung.")

    def _on_content_failed(self, task, err: str) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        r = fresh.result or {}
        has_result = bool(str(r.get("title") or "").strip()
                          or str(r.get("content_html") or "").strip()
                          or list(r.get("images") or []))
        if has_result:
            # Job ĐÃ CÓ kết quả -> tạo lại lỗi thì BỎ QUA: giữ nguyên nội dung + ảnh cũ,
            # không đổi trạng thái, không hiện màn hình lỗi (chỉ ghi vào Log lỗi).
            fresh.status = STATUS_FINISH
            fresh.message = ""
            fresh.error_stage = ""
            self.store.upsert_task(fresh)
            self.store.save()
            self._log_err("Tạo lại nội dung (bỏ qua — giữ kết quả cũ)", err)
            try:
                self._refresh_jobs_keep(fresh)
            except Exception as exc:      # noqa: BLE001
                traceback.print_exc()
                self._log_err("Hiển thị lỗi", str(exc))
            self._refresh_count()
            self.status("Tạo lại lỗi — đã bỏ qua, giữ nguyên nội dung cũ.")
            return
        fresh.status = STATUS_ERROR
        fresh.message = err
        fresh.error_stage = "content"
        self.store.upsert_task(fresh)
        self.store.save()
        self._log_err("Tạo nội dung", err)
        try:
            self._refresh_jobs_keep(fresh)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Hiển thị lỗi", str(exc))
        self._refresh_count()
        self.status("Sẵn sàng")

    def _on_delete_task(self, task_id: str) -> None:
        self.store.set_tasks([t for t in self.store.tasks if t.id != task_id])
        self.store.save()
        self.jobs_page.refresh()
        self._refresh_count()

    # ------------------------------------------------------------------ #
    def _on_regenerate_images(self, task, footer_mode: str) -> None:
        site = self._site_of(task)
        self.jobs_page._save()
        task.footer_mode = footer_mode
        self.store.upsert_task(task)
        self.store.save()
        # đi qua cùng hàng đợi -> mỗi việc chỉ 1 luồng ghép ảnh (không ghi đè lẫn nhau)
        self._start_images_worker(task, None, None, "Đang tạo lại ảnh…")

    def _on_images_ok(self, task, images: list) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        cur = list(fresh.result.get("images") or [])
        if images and all("index" in im for im in images) and len(images) == 1:
            idx = images[0]["index"]
            while len(cur) <= idx:
                cur.append({"path": "", "footer": ""})
            cur[idx] = {"path": images[0]["path"], "footer": images[0].get("footer", "")}
            fresh.result["images"] = cur
        else:
            fresh.result["images"] = [
                {"path": im.get("path", ""), "footer": im.get("footer", "")} for im in images
            ]
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.current = fresh
        # CHỈ cập nhật thumbnail + ảnh nền của trình sửa (KHÔNG nạp lại panel -> không đóng menu chuột phải)
        self.jobs_page.reload_thumbs()
        self.jobs_page.refresh_info()        # ảnh xong -> cập nhật "Thông tin đã đầy đủ"
        try:
            idx = self.jobs_page._sel_index
            imgs = fresh.result.get("images") or []
            if 0 <= idx < len(imgs):
                # dựng lại ảnh nền "SẠCH" ở LUỒNG RIÊNG (không đứng giao diện)
                self.jobs_page._request_canvas_bg(fresh, idx)
        except Exception:
            pass
        self.status("Đã tạo lại ảnh.")

    def _on_split_task(self, task, n: int) -> None:
        """Chia 1 link nguồn thành N bài -> tạo N JOB TRỐNG (website chia TUẦN TỰ)."""
        if self._split_worker is not None and self._split_worker.isRunning():
            return
        if getattr(self.jobs_page, "_busy", False):
            show_toast(self, "Đang có tiến trình chạy — chờ xong đã", 2800, ok=False)
            return
        link = str(getattr(task, "source_url", "") or "").strip()
        if not link:
            return
        try:
            self.post_page.set_splitting(True, n)
        except Exception:      # noqa: BLE001
            pass
        worker = SplitWorker(self.store, link, n)
        worker.log.connect(self._on_worker_log)
        worker.ok.connect(lambda arts: self._on_split_ok(task, arts))
        worker.failed.connect(self._on_split_failed)

        def _done() -> None:
            if self._split_worker is worker:
                self._split_worker = None
            self._cleanup(worker)

        worker.finished.connect(_done)
        self._split_worker = worker
        self._workers.append(worker)
        worker.start()
        show_toast(self, f"Đang chia link nguồn thành {n} bài…", 3200)

    def _on_split_ok(self, task, arts: list) -> None:
        """Provider trả về các content -> tạo N job TRỐNG (mỗi job 1 content)."""
        try:
            self.post_page.set_splitting(False, 0)
        except Exception:      # noqa: BLE001
            pass
        arts = [str(a) for a in (arts or []) if str(a).strip()]
        if not arts:
            show_toast(self, "Không chia được bài nào", 3200, ok=False)
            return
        link = str(getattr(task, "source_url", "") or "")
        brand = str(getattr(task, "brand_logo_fallback", "") or "")
        count = max(1, int(getattr(task, "image_count", 3) or 3))
        made: list = []
        for i, content in enumerate(arts, 1):
            t = Task(
                source_url=link,
                source_urls=[link],
                split_no=i,
                kind="blank",
                brand_logo_fallback=brand,
                image_count=count,
                status=STATUS_FINISH,
            )
            slots = [{"path": "", "footer": ""} for _ in range(count)]
            # link TIÊU ĐỀ ĐẦU: tạm dùng link mặc định -> khi bấm Đăng mới đổi theo website
            try:
                from ..ai.manager import set_first_title_link as _set_first

                content = _set_first(content, self.store.title_link_first or "")
            except Exception:      # noqa: BLE001
                pass
            t.result = {"title": "", "focus_keyword": "", "description": "", "tags": "",
                        "category_name": "", "brand_name": "", "ma_san_pham": "",
                        "content_html": content, "images": slots,
                        "image_opts_list": [{} for _ in slots], "product_images": []}
            self.store.upsert_task(t)
            made.append(t)
        self.store.save()
        self.jobs_page.refresh()
        self._refresh_count()
        self._go(2)
        if made:
            self.jobs_page.select_task(made[0].id)
        for t in made:      # ghép ảnh bằng logo/thanh thông tin MẶC ĐỊNH (chưa chọn website)
            self._start_images_worker(t, None, None, "Đang ghép ảnh…")
        show_toast(self, f"Đã tạo {len(made)} job trống (Bài 1 → Bài {len(made)})", 3600)
        if made:
            self._prefetch_source_images(made[0], targets=[x.id for x in made])
        self._start_split_seo(made)      # tự lấy JSON SEO cho TỪNG bài (popup phủ toàn app)

    # ------------------------------------------------------------------ #
    # JSON SEO cho từng bài của "chia bài" (popup phủ toàn app, chạy tuần tự)
    # ------------------------------------------------------------------ #
    def _start_split_seo(self, made: list) -> None:
        """Sau khi chia bài: hiện popup + tự tạo JSON SEO lần lượt cho từng bài."""
        items = []
        for i, t in enumerate(made, 1):
            html = str((t.result or {}).get("content_html") or "")
            if not html.strip():
                continue
            items.append((t.id, html, f"Bài {i}"))
        if not items:
            return
        self._split_seo_cancelled = False
        try:
            overlay = SeoProgressOverlay(self)
            overlay.cancelled.connect(self._stop_split_seo)
            self._split_seo_overlay = overlay
            overlay.start(len(items))
        except Exception:      # noqa: BLE001
            traceback.print_exc()
            self._split_seo_overlay = None
        worker = SplitSeoWorker(self.store, items)
        worker.log.connect(self._on_worker_log)
        worker.progress.connect(self._on_split_seo_progress)
        worker.done.connect(self._on_split_seo_done)
        worker.finished_all.connect(self._on_split_seo_finished)

        def _done() -> None:
            if self._split_seo_worker is worker:
                self._split_seo_worker = None
            self._cleanup(worker)

        worker.finished.connect(_done)
        self._split_seo_worker = worker
        self._workers.append(worker)
        self.jobs_page.set_seo_busy(True)
        worker.start()
        self.status(f"Đang lấy JSON SEO cho {len(items)} bài (tuần tự)…")

    def _on_split_seo_progress(self, i: int, total: int, label: str) -> None:
        ov = self._split_seo_overlay
        if ov is not None:
            try:
                ov.set_step(i, total, label)
            except Exception:      # noqa: BLE001
                pass
        self.status(f"Đang lấy JSON SEO cho {label} ({i}/{total})…")

    def _on_split_seo_done(self, i: int, total: int, task_id: str, seo: dict) -> None:
        """1 bài đã có JSON SEO -> điền Title / Description / Focus keyword / Tags."""
        self._apply_split_seo(task_id, seo)
        ov = self._split_seo_overlay
        if ov is not None:
            try:
                ov.set_done(i, total)
            except Exception:      # noqa: BLE001
                pass

    def _apply_split_seo(self, task_id: str, seo: dict) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task_id), None)
        if fresh is None:
            return
        r = fresh.result = dict(fresh.result or {})
        for k in ("title", "description", "focus_keyword", "tags",
                  "category_name", "brand_name", "ma_san_pham"):
            v = str((seo or {}).get(k, "") or "").strip()
            if v:
                r[k] = v
        self.store.upsert_task(fresh)
        self.store.save()
        try:      # nếu đang mở đúng job đó -> điền luôn vào các ô
            if getattr(self.jobs_page.current, "id", "") == task_id:
                self.jobs_page.current = fresh
                self.jobs_page._load(fresh)
        except Exception:      # noqa: BLE001
            pass
        self.jobs_page.refresh_info()
        self._refresh_count()

    def _on_split_seo_finished(self, ok: int, total: int) -> None:
        """Chạy xong HẾT -> tự đóng popup + báo tổng kết."""
        self._close_split_seo_overlay()
        self.jobs_page.set_seo_busy(False)
        if self._split_seo_cancelled:
            return                      # người dùng đã dừng -> không báo "xong"
        self.status(f"Đã tạo JSON SEO cho {ok}/{total} bài.")
        show_toast(self, f"Đã tạo JSON SEO cho {ok}/{total} bài", 3600,
                   ok=(ok >= total))

    def _stop_split_seo(self) -> None:
        """Bấm "Dừng và đóng" / X / Esc -> DỪNG lấy JSON SEO ngay."""
        if self._split_seo_cancelled and self._split_seo_overlay is None:
            return                      # đã dừng rồi -> không báo lại
        self._split_seo_cancelled = True
        w = self._split_seo_worker
        if w is not None:
            try:
                w.stop()
            except Exception:      # noqa: BLE001
                pass
        self._close_split_seo_overlay()
        self.jobs_page.set_seo_busy(False)
        self.status("Đã dừng lấy JSON SEO — các bài chưa xong bạn bấm “Tạo JSON SEO” sau.")
        show_toast(self, "Đã dừng lấy JSON SEO", 3000, ok=False)

    def _close_split_seo_overlay(self) -> None:
        ov = self._split_seo_overlay
        self._split_seo_overlay = None
        if ov is not None:
            try:
                ov.hide()
                ov.deleteLater()
            except Exception:      # noqa: BLE001
                pass

    def _on_split_failed(self, err: str) -> None:
        try:
            self.post_page.set_splitting(False, 0)
        except Exception:      # noqa: BLE001
            pass
        self._log_err("Chia nhiều bài", err)
        show_toast(self, f"Chia bài lỗi: {str(err)[:80]}", 4000, ok=False)

    def _on_models_extract(self) -> None:
        """Nút "Product Models" -> popup trích xuất Product Models (ChatGPT Project)."""
        from .widgets.models_dialog import ModelsDialog

        task = getattr(self.jobs_page, "current", None)
        if task is None:
            show_toast(self, "Chưa mở công việc nào", 2400, ok=False)
            return
        self.jobs_page._save()               # chốt nội dung đang gõ
        task_id = task.id

        def _content() -> str:
            fresh = next((t for t in self.store.tasks if t.id == task_id), None)
            return str(((fresh.result if fresh else None) or {}).get("content_html") or "")

        r0 = next((t for t in self.store.tasks if t.id == task_id), task).result or {}
        ModelsDialog(self.store, task_id, get_content=_content,
                     apply_content=self._apply_models_content, parent=self,
                     brand=str(r0.get("brand_name") or "")).exec()

    def _apply_models_content(self, task_id: str, new_html: str) -> None:
        """Ghi nội dung mới (đã chèn Product Models) vào công việc + cập nhật ô Nội dung."""
        fresh = next((t for t in self.store.tasks if t.id == task_id), None)
        if fresh is None:
            return
        r = fresh.result = dict(fresh.result or {})
        r["content_html"] = str(new_html or "")
        self.store.upsert_task(fresh)
        self.store.save()
        if getattr(self.jobs_page.current, "id", "") == task_id:
            self.jobs_page.current = fresh
            try:
                self.jobs_page.content_edit.set_html(r["content_html"])
            except Exception:      # noqa: BLE001
                pass

    def _on_seo_json(self, task) -> None:
        """Nút "Tạo JSON SEO" (job trống): gọi AI tạo SEO từ NỘI DUNG đang soạn."""
        if self._seo_worker is not None and self._seo_worker.isRunning():
            return
        self.jobs_page._save()              # lưu nội dung đang gõ
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        content = str((fresh.result or {}).get("content_html") or "")
        if not content.strip():
            show_toast(self, "Ô Nội dung đang trống", 2600, ok=False)
            return
        self.jobs_page.set_seo_busy(True)
        worker = SeoJsonWorker(self.store, content)
        worker.log.connect(self._on_worker_log)
        worker.ok.connect(lambda seo: self._on_seo_json_ok(fresh, seo))
        worker.failed.connect(self._on_seo_json_failed)

        def _done() -> None:
            if self._seo_worker is worker:
                self._seo_worker = None
            self._cleanup(worker)

        worker.finished.connect(_done)
        self._seo_worker = worker
        self._workers.append(worker)
        worker.start()
        self.status("Đang tạo JSON SEO từ nội dung…")

    def _on_seo_json_ok(self, task, seo: dict) -> None:
        """Có JSON SEO -> điền vào Title / Description / Focus keyword / Tags."""
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        r = fresh.result = dict(fresh.result or {})
        for k in ("title", "description", "focus_keyword", "tags",
                  "category_name", "brand_name", "ma_san_pham"):
            v = str((seo or {}).get(k, "") or "").strip()
            if v:
                r[k] = v
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.set_seo_busy(False)
        self.jobs_page.current = fresh
        self.jobs_page._load(fresh)         # điền vào các ô
        self.jobs_page.refresh_info()       # có JSON SEO -> cập nhật "Thông tin đã đầy đủ"
        self._refresh_count()
        self.status("Đã tạo JSON SEO — đã điền Title / Description / Focus keyword / Tags.")

    def _on_seo_json_failed(self, err: str) -> None:
        """Lỗi -> GIỮ NGUYÊN các ô đang có, chỉ ghi Log lỗi."""
        self.jobs_page.set_seo_busy(False)
        self._log_err("Tạo JSON SEO", err)
        self.status("Tạo JSON SEO lỗi — giữ nguyên các ô đang có (xem tab Log lỗi).")

    def _on_regenerate(self, task, field: str) -> None:
        # đang có việc tạo nội dung -> không cho tạo lại (chạy tuần tự)
        if self._content_workers:
            self.status("Đang có 1 công việc tạo nội dung — chờ xong rồi hãy tạo lại.")
            return
        # Ghi lại các trường đã sửa trước khi tạo lại
        self.jobs_page._save()

        # "Random lại" / "Thử tạo lại": tạo lại TOÀN BỘ nội dung
        # (nếu job đã có ảnh thì GIỮ NGUYÊN ảnh đang có)
        r = task.result or {}
        if list(r.get("images") or []):
            self._content_only_ids.add(task.id)
        self._on_create_task(task)

    def _on_post_task(self, task) -> None:
        # Mỗi công việc chỉ mở 1 Chrome: nếu đang đăng thì bỏ qua lần bấm sau
        if self.jobs_page.is_posting(task.id):
            return
        # CHỈ 1 việc đăng bài tại 1 thời điểm
        other = [tid for tid, busy in self.jobs_page._posting.items()
                 if busy and tid != task.id]
        if other:
            show_toast(self, "Đang có 1 việc đăng bài — chờ việc đó xong đã", 3200, ok=False)
            return
        # CHỌN WEBSITE ĐỂ ĐĂNG (popup chọn sẵn website đã lưu của job; chỉ web có kịch bản)
        self.jobs_page._save()                          # chốt nội dung đang gõ trước khi hỏi
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        # CHỤP LẠI thông tin text NGAY LÚC BẤM ĐĂNG: đổi sang job khác giữa lúc ghép ảnh
        # cũng KHÔNG làm Chrome điền nhầm dữ liệu của job khác
        import copy as _copy1

        snap = _copy1.deepcopy(fresh.result or {})
        prev_site_id = str(getattr(fresh, "site_id", "") or "")
        site = self._choose_post_site(fresh)
        if site is None:
            return                                     # người dùng huỷ -> không đăng
        self.jobs_page.set_posting(task.id, True)      # khoá + mờ nút Đăng bài
        self.jobs_page.set_posting_locked(True)        # khoá nút của MỌI job (đang chuẩn bị đăng)
        import time as _time0

        self._post_started[task.id] = _time0.time()    # mốc để watchdog không mở khoá sớm
        self._post_sites[task.id] = site
        # LƯU website vào job (lần sau popup chọn sẵn website này)
        fresh.site_id = site.id
        fresh.site_name = site.name or site.url
        self.store.upsert_task(fresh)
        self.store.save()
        # 1) AUTO FORMAT LẠI 1 LẦN + link tiêu đề ĐẦU = website vừa chọn
        self._format_content_for_site(fresh, site)
        # 2) ẢNH: chỉ GHÉP LẠI khi ĐỔI website (hoặc chưa có ảnh) -> chờ xong mới mở Chrome
        cur_imgs = (fresh.result or {}).get("images") or []
        have_img = bool(cur_imgs and any(str(im.get("path") or "") for im in cur_imgs))
        if (site.id != prev_site_id) or not have_img:
            if not self._compose_images_for_site(fresh, site):
                self.jobs_page.set_posting(task.id, False)
                self.jobs_page.set_posting_locked(False)
                self._post_sites.pop(task.id, None)
                self._post_started.pop(task.id, None)
                return
        fresh = next((t for t in self.store.tasks if t.id == task.id), fresh)
        try:
            paths = export_post_images(self.store, fresh)
            if paths:
                fresh.result = dict(fresh.result or {})
                # CHỈ dùng trong bộ nhớ để kịch bản upload ảnh — KHÔNG lưu vào job
                fresh.result["post_images"] = paths
                task = fresh
                self.status(f"Đã lưu {len(paths)} ảnh vào thư mục {fresh.id[:8]}…")
        except Exception:      # noqa: BLE001
            traceback.print_exc()

        payload = dict(task.result or {})
        for _k in ("title", "focus_keyword", "description", "tags",
                   "category_name", "brand_name", "ma_san_pham"):
            if str(snap.get(_k) or "").strip():
                payload[_k] = snap.get(_k)
        worker = PostWorker(site, payload)
        import time as _time

        self._post_workers[task.id] = worker
        self._post_started[task.id] = _time.time()
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda url: self._on_post_ok(task, url))
        worker.failed.connect(lambda err: self._on_post_failed(task, err))
        worker.closed.connect(lambda _u: (self.jobs_page.set_posting(task.id, False),
                                          self._on_post_closed(task)))
        def _post_done() -> None:
            self._post_workers.pop(task.id, None)
            self._post_started.pop(task.id, None)
            self._post_sites.pop(task.id, None)
            self._cleanup(worker)

        worker.finished.connect(_post_done)
        self._workers.append(worker)
        worker.start()

    # ---------------- kiểm tra cập nhật (CHỈ Windows) ---------------- #
    def _start_update_watch(self) -> None:
        """Tự kiểm tra bản mới: sau 5 giây + mỗi 10 phút (chỉ bản Windows)."""
        try:
            from .. import update as upd

            if not upd.is_windows():
                return
        except Exception:      # noqa: BLE001
            return
        self._update_asked: set[str] = set()
        self._update_worker = None
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(10 * 60 * 1000)        # 10 phút
        self._update_timer.timeout.connect(self._check_update_quiet)
        QTimer.singleShot(5000, self._check_update_quiet)     # sau 5 giây
        self._update_timer.start()

    def _check_update_quiet(self) -> None:
        try:
            if getattr(self, "_update_worker", None) is not None and self._update_worker.isRunning():
                return
            w = UpdateWorker()
        except Exception:      # noqa: BLE001
            return
        self._update_worker = w
        w.checked.connect(self._on_update_checked)
        w.failed.connect(lambda _e: None)                     # mất mạng -> im lặng

        def _done() -> None:
            if getattr(self, "_update_worker", None) is w:
                self._update_worker = None
            self._cleanup(w)

        w.finished.connect(_done)
        self._workers.append(w)
        w.start()

    def _on_update_checked(self, info: dict) -> None:
        """Có bản mới -> hỏi Có/Không (mỗi phiên bản chỉ hỏi 1 lần)."""
        try:
            from .. import update as upd

            ver = str((info or {}).get("version") or "").strip()
            if not ver or not upd.is_newer(ver):
                return
            asked = getattr(self, "_update_asked", set())
            if ver in asked:
                return
            asked.add(ver)
            self._update_asked = asked
            notes = str((info or {}).get("notes") or "").strip()
            msg = (f"🎉 Có bản cập nhật mới!\n\n"
                   f"Đang dùng:  {__version__}\n"
                   f"Bản mới:    {ver}\n")
            if notes:
                msg += f"\n{notes[:800]}\n"
            msg += "\nBạn có muốn cài đặt ngay không?"
            ans = QMessageBox.question(self, "Cập nhật phần mềm", msg,
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ans == QMessageBox.Yes:
                self._apply_update(info or {})
        except Exception:      # noqa: BLE001
            traceback.print_exc()

    def _apply_update(self, info: dict) -> None:
        """Tải + cài bản mới rồi tắt app để hoàn tất."""
        try:
            w = UpdateWorker(apply_url=str(info.get("url") or ""))
        except Exception:      # noqa: BLE001
            return
        w.log.connect(self.status)
        w.applied.connect(self._on_update_applied)
        w.failed.connect(lambda e: show_toast(self, f"Cập nhật lỗi: {str(e)[:120]}", 4000, ok=False))
        w.finished.connect(lambda: self._cleanup(w))
        self._workers.append(w)
        w.start()
        show_toast(self, "Đang tải bản cập nhật…", 3000)

    def _on_update_applied(self, _tmp: str) -> None:
        show_toast(self, "Đang khởi động lại phần mềm để hoàn tất cập nhật…", 3000)
        QTimer.singleShot(1200, self.close)

    # ---------------- lưới an toàn cho nút "OK — Đăng bài" ---------------- #
    def _start_post_watchdog(self) -> None:
        """Mỗi 3 giây: job đang đăng mà KHÔNG còn Chrome -> tự mở khoá nút."""
        self._post_watchdog = QTimer(self)
        self._post_watchdog.setInterval(3000)
        self._post_watchdog.timeout.connect(self._check_posting_alive)
        self._post_watchdog.start()

    def _check_posting_alive(self) -> None:
        try:
            busy = dict(getattr(self.jobs_page, "_posting", {}) or {})
            if not busy:
                return
            import time as _time

            from ..wp.browser import _pids_using_profile, _user_data_dir

            changed = False
            for tid in list(busy.keys()):
                started = float(self._post_started.get(tid, 0) or 0)
                if started and (_time.time() - started) < 12:
                    continue                 # đang mở trình duyệt -> chưa kiểm tra
                site = self._post_sites.get(tid)          # website chọn lúc bấm Đăng
                if site is None:
                    self.jobs_page.set_posting(tid, False)
                    changed = True
                    continue
                try:
                    alive = bool(_pids_using_profile(_user_data_dir(site.id)))
                except Exception:      # noqa: BLE001
                    alive = True
                if alive:
                    continue
                # Chrome đã tắt mà nút chưa mở khoá -> mở khoá ngay + dừng luồng kẹt
                self.jobs_page.set_posting(tid, False)
                self._stop_post_worker(tid)
                changed = True      # Chrome đã tắt -> tự mở khoá (không ghi Log lỗi)
            if changed and not any(getattr(self.jobs_page, "_posting", {}).values()):
                self.jobs_page.set_posting_locked(False)
        except Exception:      # noqa: BLE001
            traceback.print_exc()

    def _stop_post_worker(self, task_id: str) -> None:
        """Dừng luồng đăng bài đang kẹt (giải phóng profile cho lần sau)."""
        w = self._post_workers.get(task_id)
        if w is None:
            return
        try:
            w.stop()
        except Exception:      # noqa: BLE001
            pass
        self._post_workers.pop(task_id, None)
        self._post_started.pop(task_id, None)

    def _on_post_closed(self, task) -> None:
        self.jobs_page.set_posting_locked(False)     # đã đóng Chrome -> mở khoá lại
        self.status("")                              # xoá message ở thanh dưới

    def _on_post_ok(self, task, url: str) -> None:
        # ĐĂNG BÀI: KHÔNG đụng gì vào job (không đổi trạng thái, KHÔNG lưu link kết quả, không ghi Log lỗi).
        # KHÔNG mở lại nút ở đây: chờ người dùng đóng trình duyệt (xem _on_post_closed)
        self.status("Đã mở trình duyệt và điền thông tin — bạn tự bấm Đăng trên WordPress.")

    def _on_post_failed(self, task, err: str) -> None:
        # KỊCH BẢN DỪNG GIỮA ĐƯỜNG: KHÔNG đụng gì vào job (không đổi trạng thái, không ghi Log lỗi,
        # không hiện cảnh báo) — bạn tự điền nốt phần còn lại rồi bấm Đăng trên WordPress.
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        try:
            self._refresh_jobs_keep(fresh)
        except Exception:      # noqa: BLE001
            traceback.print_exc()
        self.status("Kịch bản dừng giữa đường — bạn tự điền nốt rồi bấm Đăng trên WordPress.")

    def _log_err(self, source: str, message: str) -> None:
        self.store.log_error(source, message)
        self.error_log_page.refresh()

    def _start_images_worker(self, task, opts: dict | None, only_index: int | None,
                             status_msg: str) -> None:
        """Chỉ chạy 1 luồng ghép ảnh cho mỗi công việc (tránh dồn luồng → crash khi thoát).

        Nếu việc đó ĐANG ghép ảnh -> xếp hàng chờ (KHÔNG giết việc đang chạy) để
        không mất ảnh vừa yêu cầu ghép lại.
        """
        # Job CHƯA chọn website -> ghép bằng MẶC ĐỊNH của phần mềm
        # (logo mặc định + thanh thông tin 1/2 mặc định + watermark mặc định).
        site = self._site_of(task)
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        old = self._img_workers.get(fresh.id)
        if old is not None and old.isRunning():
            q = self._img_queue.setdefault(fresh.id, [])
            q[:] = [x for x in q if x[1] != only_index]     # mỗi ảnh giữ yêu cầu MỚI NHẤT
            q.append((dict(opts or {}), only_index, status_msg))
            self.status("Đang ghép ảnh — yêu cầu mới sẽ ghép ngay sau khi xong…")
            return
        worker = ImagesWorker(self.store, site, fresh, fresh.footer_mode, opts,
                              only_index=only_index)
        self._img_workers[fresh.id] = worker
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda images: self._on_images_ok(fresh, images))
        worker.failed.connect(lambda err: (self._log_err("Ghép ảnh", err),
                                           self.status("Sẵn sàng")))

        def _done() -> None:
            if self._img_workers.get(fresh.id) is worker:
                self._img_workers.pop(fresh.id, None)
            self._cleanup(worker)
            # còn yêu cầu đang chờ -> ghép tiếp cho ĐÚNG ảnh đó
            rest = self._img_queue.get(fresh.id) or []
            if rest:
                o, idx, msg = rest.pop(0)
                if not rest:
                    self._img_queue.pop(fresh.id, None)
                t2 = next((t for t in self.store.tasks if t.id == fresh.id), fresh)
                self._start_images_worker(t2, o, idx, msg)

        worker.finished.connect(_done)
        self._workers.append(worker)
        worker.start()
        self.status(status_msg)

    def _on_apply_image_opts(self, task, index: int, opts: dict) -> None:
        site = self._site_of(task)
        self.jobs_page._save()
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        lst = _opts_list_of(fresh.result)
        while len(lst) <= index:
            lst.append({})
        lst[index] = {**lst[index], **opts}
        fresh.result["image_opts_list"] = lst
        self.store.upsert_task(fresh)
        self.store.save()
        self._start_images_worker(fresh, opts, index, "Đang ghép lại ảnh theo thiết lập…")

    def _on_recompose_image(self, task, index: int) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        lst = _opts_list_of(fresh.result)
        opts = dict(lst[index]) if index < len(lst) else {}
        self._start_images_worker(fresh, opts, index, f"Đang ghép lại Ảnh {index + 1}…")

    def _on_recompose_all(self, task) -> None:
        """Ghép lại TOÀN BỘ ảnh (sau khi thêm / xoá / sắp xếp ảnh)."""
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        self._start_images_worker(fresh, None, None, "Đang ghép lại toàn bộ ảnh…")

    def _on_export_images(self, task) -> None:
        """Hỏi THƯ MỤC xuất ảnh -> xuất thẳng vào đó (KHÔNG tự mở thư mục)."""
        self.jobs_page._save()
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        # hỏi nơi xuất (nhớ thư mục đã chọn, lưu trong config.json -> nhớ cả khi tắt app)
        start = str(((self.store.data.get("ui") or {}).get("export_dir") or "")).strip()
        if not start:
            try:
                start = str(Path.home())
            except Exception:      # noqa: BLE001
                start = ""
        try:
            chosen = QFileDialog.getExistingDirectory(
                self, "Chọn thư mục xuất ảnh", start,
                QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
            )
        except Exception:      # noqa: BLE001
            traceback.print_exc()
            return
        if not chosen:                        # Huỷ -> KHÔNG xuất
            return
        self._export_dir = chosen
        try:                                  # lưu lại để lần sau (kể cả sau khi tắt app) mở sẵn
            self.store.data.setdefault("ui", {})["export_dir"] = chosen
            self.store.save()
        except Exception:      # noqa: BLE001
            traceback.print_exc()
        try:
            paths = export_post_images(self.store, fresh, dest_dir=chosen)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Xuất ảnh", str(exc))
            show_toast(self, f"Xuất ảnh lỗi: {exc}", 3600, ok=False)
            return
        if not paths:
            show_toast(self, "Không có ảnh để xuất", 3000, ok=False)
            return
        fresh.result = dict(fresh.result or {})
        fresh.result["post_images"] = paths
        self.store.upsert_task(fresh)
        self.store.save()
        folder = Path(paths[0]).parent
        show_toast(self, f"Đã xuất {len(paths)} ảnh vào {folder.name}/", 3200)

    # ------------------------------------------------------------------ #
    # Chọn website lúc ĐĂNG BÀI + format lại nội dung + ghép lại ảnh
    # ------------------------------------------------------------------ #
    def _site_of(self, task):
        """Website của job: đã chọn lúc Đăng -> hoặc MẶC ĐỊNH (job chưa chọn website)."""
        return (self.store.get_site(getattr(task, "site_id", ""))
                or self._post_sites.get(getattr(task, "id", ""))
                or Site())

    def _choose_post_site(self, task=None):
        """Popup chọn website để ĐĂNG (chỉ website CÓ KỊCH BẢN). None nếu người dùng huỷ.

        Job đã lưu website -> CHỌN SẴN website đó (bấm OK là đăng luôn).
        """
        sites = [x for x in self.store.sites
                 if getattr(x, "script", None) and getattr(x.script, "steps", None)]
        if not sites:
            QMessageBox.warning(
                self,
                "Chưa có kịch bản",
                "Chưa có website nào có kịch bản đăng bài.\n\n"
                "Vào Cài đặt → website → Kịch bản đăng bài để dán/import kịch bản.",
            )
            return None
        names = [x.name or x.url for x in sites]
        cur = str(getattr(task, "site_id", "") or "") if task is not None else ""
        # ƯU TIÊN: website DÙNG GẦN NHẤT (nhớ toàn app) -> mọi job đều chọn sẵn web đó
        last = str(((self.store.data.get("ui") or {}).get("last_post_site") or ""))
        start = next((i for i, x in enumerate(sites) if x.id == last), -1)
        if start < 0:                 # chưa có / website đã bị xoá -> dùng website của job
            start = next((i for i, x in enumerate(sites) if x.id == cur), 0)
        name, ok = QInputDialog.getItem(
            self, "Chọn website để đăng", "Website sẽ đăng bài này:", names, start, False
        )
        if not ok or not name:
            return None
        idx = names.index(name) if name in names else start
        site = sites[idx]
        try:      # NHỚ website vừa chọn cho LẦN SAU (dùng chung mọi job)
            self.store.data.setdefault("ui", {})["last_post_site"] = site.id
            self.store.save()
        except Exception:      # noqa: BLE001
            pass
        return site

    def _format_content_for_site(self, task, site) -> None:
        """Auto format LẠI 1 lần + đặt link tiêu đề ĐẦU = website sẽ đăng."""
        try:
            from ..ai.manager import (apply_template_icons, clean_content_html,
                                      extract_product_name, insert_readmore,
                                      insert_title_links, linkify_domains,
                                      mark_auto_formatted, readmore_from_store,
                                      set_first_title_link)

            r = task.result = dict(task.result or {})
            html = str(r.get("content_html") or "")
            if not html.strip():
                return
            site_url = str(getattr(site, "url", "") or "")
            from ..ai.manager import already_auto_formatted

            if already_auto_formatted(html):
                # đã format rồi -> chỉ sửa link tiêu đề đầu cho đúng website
                out = set_first_title_link(html, site_url)
                out = insert_readmore(out, readmore_from_store(self.store))
            else:
                out = clean_content_html(html)
                out = apply_template_icons(out)
                all_sites = [(x.url or "", x.name or "") for x in self.store.sites]
                out = linkify_domains(out, all_sites)
                out = insert_title_links(
                    out, site_url, list(self.store.title_links),
                    [extract_product_name(out, ""), str(r.get("focus_keyword") or ""),
                     str(r.get("title") or ""), ""],
                )
                out = set_first_title_link(out, site_url)
                out = insert_readmore(out, readmore_from_store(self.store))
                out = mark_auto_formatted(out)
            r["content_html"] = out
            self.store.upsert_task(task)
            self.store.save()
            # Nạp lại ô Nội dung (nếu đang mở đúng job) -> lần tự lưu sau không ghi đè bản CŨ
            try:
                if getattr(self.jobs_page.current, "id", "") == getattr(task, "id", ""):
                    self.jobs_page.content_edit.set_html(out)
            except Exception:      # noqa: BLE001
                pass
            self.status(f"Đã auto format lại nội dung + link tiêu đề đầu → {site.name or site_url}")
        except Exception:      # noqa: BLE001
            traceback.print_exc()          # không ghi Log lỗi (việc đăng không đụng vào job)

    def _compose_images_for_site(self, task, site, timeout_ms: int = 180000) -> bool:
        """Ghép LẠI ảnh theo website vừa chọn rồi CHỜ xong mới cho mở Chrome đăng."""
        from PySide6.QtCore import QEventLoop

        loop = QEventLoop(self)
        state = {"ok": False, "err": ""}
        try:
            worker = ImagesWorker(self.store, site, task, task.footer_mode, None)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            show_toast(self, f"Ghép ảnh lỗi: {exc}", 4200, ok=False)   # báo lỗi, KHÔNG mở Chrome
            return False
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda images: (self._on_images_ok(task, images),
                                          state.update(ok=True), loop.quit()))
        worker.failed.connect(lambda err: (state.update(err=str(err)), loop.quit()))
        self._workers.append(worker)
        self.status(f"Đang ghép lại ảnh theo {site.name}… (xong mới mở Chrome)")
        worker.start()
        QTimer.singleShot(max(5000, int(timeout_ms)), loop.quit)     # lưới an toàn
        loop.exec()
        try:
            if worker.isRunning():
                worker.wait(2000)
        except Exception:      # noqa: BLE001
            pass
        self._cleanup(worker)
        if state["ok"]:
            return True
        # LỖI GHÉP ẢNH -> DỪNG, KHÔNG mở Chrome; báo alert cho người dùng
        show_toast(self, f"Ghép ảnh lỗi — không đăng: {state['err'][:90] or 'quá lâu'}",
                   5000, ok=False)
        return False

    def _on_stop_all(self) -> None:
        """Dừng TẤT CẢ: mọi việc đang chờ / đang tạo -> cancelled ("chưa tạo")."""
        try:
            n = 0
            for t in self.store.tasks:
                if t.status in (STATUS_QUEUED, STATUS_GENERATING):
                    t.status = STATUS_CANCELLED
                    t.message = ""
                    t.progress = 0
                    self.store.upsert_task(t)
                    n += 1
            self.store.save()
            # dừng các worker đang chạy
            for w in list(self._content_workers.values()):
                try:
                    if hasattr(w, "cancel"):
                        w.cancel()
                except Exception:
                    pass
            self.jobs_page.refresh()
            self._refresh_count()
            self._update_ai_busy()
            if n:
                show_toast(self, f"Đã dừng tất cả ({n} việc) → chưa tạo", 3000)
            self.status("Đã dừng tất cả việc đang chờ / đang tạo.")
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Dừng tất cả", str(exc))

    def _on_trim_component(self, task, kind: str, index: int) -> None:
        """Cắt viền thừa (trim) cho ảnh sản phẩm / logo brand rồi ghép lại ảnh."""
        from ..images.composer import trim_borders

        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        r = fresh.result = dict(fresh.result or {})
        changed = False
        if kind == "brand":
            old = r.get("brand_logo", "")
            new = trim_borders(old)
            if new and new != old:
                r["brand_logo"] = new
                changed = True
        elif kind == "product":
            prods = list(r.get("product_images") or [])
            if 0 <= index < len(prods):
                old = prods[index]
                new = trim_borders(old)
                if new and new != old:
                    prods[index] = new
                    r["product_images"] = prods
                    changed = True
        if not changed:
            show_toast(self, "Ảnh này không có viền thừa để cắt", 2600, ok=False)
            return
        self.store.upsert_task(fresh)
        self.store.save()
        idx = getattr(self.jobs_page, "_sel_index", 0)
        self._start_images_worker(fresh, None, idx, "Đang ghép lại ảnh sau khi trim…")
        show_toast(self, "Đã cắt viền ảnh", 2200)

    def _on_refetch_image(self, task, index: int) -> None:
        site = self._site_of(task)
        self.jobs_page._save()
        worker = ImageRefetchWorker(self.store, site, task, index)
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda images: self._on_images_ok(task, images))
        worker.failed.connect(lambda err: (self._log_err("Lấy đối tượng hình ảnh", err),
                                           self.status("Sẵn sàng")))
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        worker.start()
        self.status(f"Đang lấy ảnh cho Ảnh {index + 1}…")

    def _on_ai_edit(self, task, index: int, prompt: str) -> None:
        worker = ImageEditWorker(self.store, task, index, prompt)
        worker.log.connect(self.status)
        worker.ok.connect(lambda path: self._on_ai_edit_ok(task, index, path))
        worker.failed.connect(self._on_ai_edit_failed)
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        worker.start()
        self.status("Đang sửa ảnh bằng AI…")

    def _on_ai_edit_failed(self, err: str) -> None:
        self._log_err("AI sửa ảnh", err)
        self.status("Sẵn sàng")

    def _on_ai_edit_ok(self, task, index: int, path: str) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        images = fresh.result.setdefault("images", [])
        while len(images) <= index:
            images.append({"path": "", "footer": ""})
        images[index] = {**images[index], "path": path}
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.current = fresh
        self.jobs_page._load(fresh)
        self.status("Đã sửa ảnh bằng AI.")

    # ------------------------------------------------------------------ #
    def _cleanup(self, worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)

    def shutdown_workers(self, timeout: int = 15000) -> None:
        """Dừng & CHỜ mọi luồng nền kết thúc (tránh crash 'QThread destroyed while running').

        Dừng CẢ `cancel()` (worker nội dung dùng tên này) — không chỉ `stop()`.
        """
        for w in list(self._workers):
            for name in ("stop", "cancel"):
                try:
                    fn = getattr(w, name, None)
                    if callable(fn):
                        fn()
                except Exception:      # noqa: BLE001
                    pass
        for w in list(self._workers):
            try:
                if w.isRunning():
                    w.wait(timeout)
            except Exception:      # noqa: BLE001
                pass
        try:
            shutdown_all_threads(timeout)
        except Exception:      # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.jobs_page._save()      # lưu nốt thông tin đang gõ trước khi tắt app
        except Exception:      # noqa: BLE001
            pass
        self.shutdown_workers()
        try:
            self.store.save()
        except Exception:
            pass
        super().closeEvent(event)
