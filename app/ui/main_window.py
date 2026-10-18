"""Cửa sổ chính."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
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

from ..storage.models import (
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
from .workers import (
    ContentWorker,
    export_post_images,
    ImageRefetchWorker,
    _opts_list_of,
    FieldWorker,
    ImageEditWorker,
    ImagesWorker,
    PostWorker,
    SeoJsonWorker,
    SplitWorker,
    shutdown_all_threads,
)

# (chữ trên tab, chỉ số trang trong stack) — "Cài đặt" đã chuyển thành nút ⚙ góc phải trên
NAV = [("Đăng bài", 1), ("Công việc đang làm", 2), ("Log lỗi", 3)]
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
        self._post_workers: dict = {}        # task_id -> luồng đăng bài
        self._post_started: dict = {}        # task_id -> thời điểm bắt đầu đăng (giây)
        self._start_post_watchdog()          # lưới an toàn: Chrome tắt -> mở khoá nút
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
        self.config_page = ConfigPage(self.store)
        self.jobs_page = JobsPage(self.store)
        self.error_log_page = ErrorLogPage(self.store)
        for page in (self.config_page, self.post_page, self.jobs_page,
                     self.error_log_page):
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
        self.jobs_page.change_site.connect(self._on_change_site)
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
        elif index == 3:
            self.error_log_page.refresh()
        elif index == 1:
            self.post_page.reload_sites()      # tab "Đăng bài"

    def _refresh_count(self) -> None:
        for b in self.nav_buttons:
            if int(b.property("pageIndex") or -1) == 2:
                b.setText(f"Công việc đang làm ({len(self.store.tasks)})")
                break

    def _on_config_changed(self) -> None:
        self.post_page.reload_sites()

    # ------------------------------------------------------------------ #
    def _on_create_task(self, task) -> None:
        """Việc mới: đưa vào HÀNG ĐỢI (queued) rồi để bộ điều phối chạy khi tới lượt."""
        site = self.store.get_site(task.site_id)
        if not site:
            return
        if (getattr(task, "kind", "") or "") == "blank":
            # JOB TRỐNG: không chạy AI -> mở thẳng panel kết quả, các ô để trống
            task.status = STATUS_FINISH
            task.progress = 100
            task.message = ""
            task.error_stage = ""
            # tạo sẵn ĐÚNG số ô ảnh đã chọn (để trống, chờ tải ảnh lên)
            slots = [{"path": "", "footer": ""} for _ in range(max(1, int(task.image_count or 3)))]
            task.result = {"title": "", "focus_keyword": "", "description": "",
                           "tags": "", "content_html": "",
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
            site = self.store.get_site(task.site_id)
            if not site:
                return
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
                                   "tags", "content_html")})
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
        site = self.store.get_site(task.site_id)
        if not site:
            return
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
        try:
            idx = self.jobs_page._sel_index
            imgs = fresh.result.get("images") or []
            if 0 <= idx < len(imgs):
                # dựng lại ảnh nền "SẠCH" ở LUỒNG RIÊNG (không đứng giao diện)
                self.jobs_page._request_canvas_bg(fresh, idx)
        except Exception:
            pass
        self.status("Đã tạo lại ảnh.")

    def _on_change_site(self, task, site_id: str) -> None:
        """Đổi website cho job THƯỜNG: giữ nội dung, hỏi có ghép lại ảnh theo site mới không."""
        if getattr(self.jobs_page, "_busy", False):
            show_toast(self, "Đang có tiến trình chạy — chờ xong đã", 2800, ok=False)
            return
        new_site = self.store.get_site(site_id)
        if not new_site:
            return
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        if fresh.site_id == site_id:
            return
        if not (getattr(new_site, "script", None) and getattr(new_site.script, "steps", None)):
            show_toast(self, f"Website “{new_site.name}” chưa có kịch bản đăng bài", 3000, ok=False)
            return
        self.jobs_page._save()               # lưu nội dung đang gõ trước khi đổi
        old = self.store.get_site(fresh.site_id)
        fresh.site_id = new_site.id
        fresh.site_name = new_site.name
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.current = fresh
        try:
            self._refresh_jobs_keep(fresh)
        except Exception:      # noqa: BLE001
            traceback.print_exc()
        # sửa link TIÊU ĐỀ ĐẦU của nội dung -> website MỚI
        try:
            from ..ai.manager import set_first_title_link

            r2 = fresh.result = dict(fresh.result or {})
            html2 = str(r2.get("content_html") or "")
            if html2:
                r2["content_html"] = set_first_title_link(html2, new_site.url or "")
                self.store.upsert_task(fresh)
                self.store.save()
                self.jobs_page._load(fresh)      # cập nhật lại panel (editor thấy link mới)
        except Exception:      # noqa: BLE001
            traceback.print_exc()
        self.status(f"Đã đổi website: {old.name if old else '?'} → {new_site.name}")
        # luôn GHÉP LẠI ẢNH theo website mới (logo site / watermark / thanh thông tin của site mới)
        self._start_images_worker(fresh, None, None, "Đang ghép lại ảnh theo website mới…")
        show_toast(self, f"Đã đổi sang “{new_site.name}” — đang ghép lại ảnh theo website mới…", 2800)

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
        sites = [x for x in self.store.sites
                 if getattr(x, "script", None) and getattr(x.script, "steps", None)]
        if not sites:
            show_toast(self, "Chưa có website nào có kịch bản đăng bài", 3200, ok=False)
            return
        try:
            self.post_page.set_splitting(True, n)
        except Exception:      # noqa: BLE001
            pass
        worker = SplitWorker(self.store, link, n)
        worker.log.connect(self._on_worker_log)
        worker.ok.connect(lambda arts: self._on_split_ok(task, arts, sites))
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

    def _on_split_ok(self, task, arts: list, sites: list) -> None:
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
            site = sites[(i - 1) % len(sites)]      # TUẦN TỰ, cho phép trùng
            t = Task(
                site_id=site.id,
                site_name=site.name,
                source_url=link,
                source_urls=[link],
                split_no=i,
                kind="blank",
                brand_logo_fallback=brand,
                image_count=count,
                status=STATUS_FINISH,
            )
            slots = [{"path": "", "footer": ""} for _ in range(count)]
            # link TIÊU ĐỀ ĐẦU = website mà job này SẼ ĐĂNG
            try:
                from ..ai.manager import set_first_title_link as _set_first

                content = _set_first(content, site.url or "")
            except Exception:      # noqa: BLE001
                pass
            t.result = {"title": "", "focus_keyword": "", "description": "", "tags": "",
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
        for t in made:      # tự ghép ảnh theo website được chia
            self._start_images_worker(t, None, None, "Đang ghép ảnh…")
        show_toast(self, f"Đã tạo {len(made)} job trống (Bài 1 → Bài {len(made)})", 3600)

    def _on_split_failed(self, err: str) -> None:
        try:
            self.post_page.set_splitting(False, 0)
        except Exception:      # noqa: BLE001
            pass
        self._log_err("Chia nhiều bài", err)
        show_toast(self, f"Chia bài lỗi: {str(err)[:80]}", 4000, ok=False)

    def _on_seo_json(self, task) -> None:
        """Nút "Tạo JSON SEO" (job trống): gọi AI tạo SEO từ NỘI DUNG đang soạn."""
        site = self.store.get_site(task.site_id)
        if not site:
            return
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
        for k in ("title", "description", "focus_keyword", "tags"):
            v = str((seo or {}).get(k, "") or "").strip()
            if v:
                r[k] = v
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.set_seo_busy(False)
        self.jobs_page.current = fresh
        self.jobs_page._load(fresh)         # điền vào các ô
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
        site = self.store.get_site(task.site_id)
        if not site:
            return
        # Ghi lại các trường đã sửa trước khi tạo lại
        self.jobs_page._save()

        if field == "images" or not field:
            if not field:
                # "Random lại": CHỈ tạo lại NỘI DUNG — nếu job đã có ảnh thì GIỮ NGUYÊN ảnh
                r = task.result or {}
                if list(r.get("images") or []):
                    self._content_only_ids.add(task.id)
            self._on_create_task(task)
            return

        value_map = {
            "title": self.jobs_page.title_edit,
            "focus_keyword": self.jobs_page.kw_edit,
            "description": self.jobs_page.desc_edit,
            "tags": self.jobs_page.tags_edit,
            "content_html": self.jobs_page.content_edit,
        }
        if field == "content_html":
            current = self.jobs_page.content_edit.get_text()
        else:
            widget = value_map.get(field)
            current = (
                widget.toPlainText() if hasattr(widget, "toPlainText") else widget.text()
            ) if widget else ""

        worker = FieldWorker(self.store, site, task, field, current)
        worker.log.connect(self._on_worker_log)
        worker.ok.connect(lambda f, v: self._on_field_ok(task, f, v))
        worker.failed.connect(lambda err: (self._log_err("Tạo nội dung", err), self.status("Sẵn sàng")))
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        worker.start()
        self.status(f"Đang tạo lại {field}…")

    def _on_field_ok(self, task, field: str, value: str) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.result[field] = value
        self.store.upsert_task(fresh)
        self.store.save()
        self.current_task = fresh
        self.jobs_page.current = fresh
        self.jobs_page._load(fresh)
        self.status("Đã tạo lại xong.")

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
        site = self.store.get_site(task.site_id)
        if not site:
            return
        self.jobs_page.set_posting(task.id, True)      # khoá + mờ nút Đăng bài
        self.jobs_page._save()

        if not (site.script and site.script.steps):
            self.jobs_page.set_posting(task.id, False)  # mở lại nút nếu không chạy được
            QMessageBox.warning(
                self,
                "Chưa có kịch bản",
                f"Website “{site.name}” chưa có kịch bản đăng bài.\n\n"
                "Vào Cài đặt → website → Kịch bản đăng bài để dán/import kịch bản.",
            )
            return

        # lưu 3 ảnh vào thư mục tên = ID công việc (để upload lên website)
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        try:
            paths = export_post_images(self.store, fresh)
            if paths:
                fresh.result = dict(fresh.result or {})
                fresh.result["post_images"] = paths
                self.store.upsert_task(fresh)
                self.store.save()
                task = fresh
                self.status(f"Đã lưu {len(paths)} ảnh vào thư mục {fresh.id[:8]}…")
        except Exception as exc:
            self._log_err("Lưu ảnh đăng bài", str(exc))

        self.store.upsert_task(task)
        self.store.save()
        self.jobs_page.refresh()

        self.jobs_page.set_posting_locked(True)      # khoá nút OK — Đăng bài của mọi job
        worker = PostWorker(site, task.result or {})
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
            self._cleanup(worker)

        worker.finished.connect(_post_done)
        self._workers.append(worker)
        worker.start()

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
                task = next((t for t in self.store.tasks if t.id == tid), None)
                site = self.store.get_site(task.site_id) if task is not None else None
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
                changed = True
                self._log_err("Đăng bài", "Chrome đã tắt — app tự mở khoá nút “OK — Đăng bài”.")
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
        # KHÔNG mở lại nút ở đây: chờ người dùng đóng trình duyệt (xem _on_post_closed)
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.result["result_url"] = url
        fresh.status = STATUS_FINISH
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.refresh()
        self._refresh_count()
        self.status("Đã mở trình duyệt và điền thông tin — bạn tự bấm Đăng trên WordPress.")

    def _on_post_failed(self, task, err: str) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        r = fresh.result or {}
        has_content = bool(r.get("content_html") or r.get("title"))
        # Nội dung đã có -> GIỮ NGUYÊN "Chờ đăng", KHÔNG chuyển sang trang tạo lại
        fresh.status = STATUS_FINISH if has_content else STATUS_ERROR
        fresh.message = err
        fresh.error_stage = "post" if has_content else "content"
        self.store.upsert_task(fresh)
        self.store.save()
        self._log_err("Đăng bài", err)
        try:
            self._refresh_jobs_keep(fresh)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self._log_err("Hiển thị kết quả", str(exc))
        self._refresh_count()
        # KHÔNG hiện cảnh báo "không đăng được bài" (việc đăng do người dùng tự bấm trên
        # WordPress). Lỗi vẫn được ghi vào tab Log lỗi để tra khi cần.
        self.status("")          # xoá message ở thanh dưới

    def _log_err(self, source: str, message: str) -> None:
        self.store.log_error(source, message)
        self.error_log_page.refresh()

    def _start_images_worker(self, task, opts: dict | None, only_index: int | None,
                             status_msg: str) -> None:
        """Chỉ chạy 1 luồng ghép ảnh cho mỗi công việc (tránh dồn luồng → crash khi thoát).

        Nếu việc đó ĐANG ghép ảnh -> xếp hàng chờ (KHÔNG giết việc đang chạy) để
        không mất ảnh vừa yêu cầu ghép lại.
        """
        site = self.store.get_site(task.site_id)
        if not site:
            return
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
        site = self.store.get_site(task.site_id)
        if not site:
            return
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
        """Xuất ảnh vào thư mục bài (posts/<ID>) rồi MỞ THƯ MỤC cho người dùng."""
        self.jobs_page._save()
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        try:
            paths = export_post_images(self.store, fresh)
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
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception:
            pass
        show_toast(self, f"Đã xuất {len(paths)} ảnh — đã mở thư mục bài", 3000)

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
        site = self.store.get_site(task.site_id)
        if not site:
            return
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
        if not self.store.get_site(task.site_id):
            return
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
        self.shutdown_workers()
        try:
            self.store.save()
        except Exception:
            pass
        super().closeEvent(event)
