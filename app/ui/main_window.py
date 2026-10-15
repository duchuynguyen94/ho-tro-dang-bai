"""Cửa sổ chính."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..storage.models import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_GENERATING,
    STATUS_POSTING,
    STATUS_REVIEW,
    Script,
    ScriptStep,
)
from ..storage.store import Store
from .pages.config_page import ConfigPage
from .pages.error_log_page import ErrorLogPage
from .pages.history_page import HistoryPage
from .pages.jobs_page import JobsPage
from .pages.post_page import PostPage
from .style import app_font
from .workers import (
    ContentWorker,
    FieldWorker,
    ImageEditWorker,
    ImagesWorker,
    PostRecordWorker,
    PostWorker,
)

NAV = ["Đăng bài", "Cấu hình", "Công việc đang làm", "Lịch sử", "Log lỗi"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = Store()
        self.setWindowTitle("Hỗ Trợ Đăng Bài — WordPress")
        self.resize(1240, 820)
        self.setFont(app_font())
        self._workers: list = []
        self.record_worker = None
        self._build()

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
        self.status_pill = QLabel("Sẵn sàng")
        self.status_pill.setStyleSheet(
            "color:#4ade80;background:rgba(22,163,74,.15);border:1px solid rgba(74,222,128,.35);"
            "border-radius:10px;padding:3px 10px;font-size:11px;"
        )
        tl.addWidget(self.status_pill)
        v.addWidget(titlebar)

        # thanh điều hướng
        nav = QFrame()
        nav.setObjectName("navBar")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(10, 0, 10, 0)
        nl.setSpacing(0)
        self.nav_buttons: list[QPushButton] = []
        for i, text in enumerate(NAV):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _=False, idx=i: self._go(idx))
            nl.addWidget(b)
            self.nav_buttons.append(b)
        nl.addStretch(1)
        v.addWidget(nav)

        # nội dung
        self.stack = QStackedWidget()
        self.post_page = PostPage(self.store)
        self.config_page = ConfigPage(self.store)
        self.jobs_page = JobsPage(self.store)
        self.history_page = HistoryPage(self.store)
        self.error_log_page = ErrorLogPage(self.store)
        for page in (self.post_page, self.config_page, self.jobs_page,
                     self.history_page, self.error_log_page):
            self.stack.addWidget(page)
        v.addWidget(self.stack, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())

        # signals
        self.post_page.create_task.connect(self._on_create_task)
        self.jobs_page.regenerate.connect(self._on_regenerate)
        self.jobs_page.regenerate_images.connect(self._on_regenerate_images)
        self.jobs_page.delete_task.connect(self._on_delete_task)
        self.jobs_page.post.connect(self._on_post_task)
        self.jobs_page.create_script.connect(self._on_create_script)
        self.jobs_page.stop_record.connect(self._on_stop_record)
        self.jobs_page.ai_edit.connect(self._on_ai_edit)
        self.config_page.changed.connect(self._on_config_changed)

        self._refresh_count()
        self._check_env()

    # ------------------------------------------------------------------ #
    def _check_env(self) -> None:
        if not self.store.sites:
            self.status("Chưa có website — vào tab Cấu hình để thêm.")

    def status(self, text: str) -> None:
        """Chỉ hiển thị việc ĐANG LÀM (không dùng cho báo lỗi)."""
        self.statusBar().showMessage(text)
        self.status_pill.setText(text[:44] if text else "Sẵn sàng")

    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == index)
        if index == 2:
            self.jobs_page.refresh()
        elif index == 3:
            self.history_page.refresh()
        elif index == 4:
            self.error_log_page.refresh()
        elif index == 0:
            self.post_page.reload_sites()

    def _refresh_count(self) -> None:
        self.nav_buttons[2].setText(f"Công việc đang làm ({len(self.store.tasks)})")

    def _on_config_changed(self) -> None:
        self.post_page.reload_sites()

    # ------------------------------------------------------------------ #
    def _on_create_task(self, task) -> None:
        site = self.store.get_site(task.site_id)
        if not site:
            return
        task.status = STATUS_GENERATING
        task.progress = 10
        task.message = ""
        self.store.upsert_task(task)
        self.store.save()

        # Chuyển ngay sang tab "Công việc đang làm" và chọn việc mới
        self._go(2)
        self.jobs_page.refresh()
        self.jobs_page.select_task(task.id)
        self._refresh_count()

        worker = ContentWorker(self.store, task, site)
        worker.log.connect(self._on_worker_log)
        worker.ok.connect(lambda res: self._on_content_ok(task, res))
        worker.failed.connect(lambda err: self._on_content_failed(task, err))
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        worker.start()
        self.status(f"Đang tạo nội dung cho {site.name}…")

    def _on_worker_log(self, msg: str) -> None:
        self.status(msg)
        self.jobs_page.set_loading_message(msg)

    def _on_content_ok(self, task, result: dict) -> None:
        from ..storage.models import Task

        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.result = result
        fresh.status = STATUS_REVIEW
        fresh.progress = 100
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.refresh()
        self._refresh_count()
        self.status("Xong — vào tab Công việc đang làm để duyệt.")

    def _on_content_failed(self, task, err: str) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.status = STATUS_ERROR
        fresh.message = err
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.refresh()
        self.jobs_page.select_task(fresh.id)
        self._refresh_count()
        self._log_err("Tạo nội dung", err)
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

        worker = ImagesWorker(self.store, site, task, footer_mode)
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda images: self._on_images_ok(task, images))
        worker.failed.connect(lambda err: (self._log_err("Tạo ảnh", err), self.status("Sẵn sàng")))
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        worker.start()
        self.status("Đang tạo lại ảnh…")

    def _on_images_ok(self, task, images: list) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.result["images"] = images
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.current = fresh
        self.jobs_page._load(fresh)
        self.status("Đã tạo lại ảnh.")

    def _on_regenerate(self, task, field: str) -> None:
        site = self.store.get_site(task.site_id)
        if not site:
            return
        # Ghi lại các trường đã sửa trước khi tạo lại
        self.jobs_page._save()

        if field == "images" or not field:
            # ảnh / toàn bộ -> chạy lại quy trình đầy đủ
            self._on_create_task(task)
            return

        value_map = {
            "title": self.jobs_page.title_edit,
            "focus_keyword": self.jobs_page.kw_edit,
            "description": self.jobs_page.desc_edit,
            "tags": self.jobs_page.tags_edit,
            "content_html": self.jobs_page.content_edit,
        }
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
        site = self.store.get_site(task.site_id)
        if not site:
            return
        self.jobs_page._save()

        if not (site.script and site.script.steps):
            ans = QMessageBox.question(
                self,
                "Chưa có kịch bản",
                "Website này chưa có kịch bản đăng bài.\nBạn muốn tạo kịch bản ngay bây giờ?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ans == QMessageBox.Yes:
                self._on_create_script(task)
                return

        task.status = STATUS_POSTING
        self.store.upsert_task(task)
        self.store.save()
        self.jobs_page.refresh()

        worker = PostWorker(site, task.result or {})
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda url: self._on_post_ok(task, url))
        worker.failed.connect(lambda err: self._on_post_failed(task, err))
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        worker.start()

    def _on_post_ok(self, task, url: str) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.result["result_url"] = url
        fresh.status = STATUS_DONE
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.refresh()
        self._refresh_count()
        self.status("Đã mở trình duyệt và điền thông tin — bạn tự bấm Đăng trên WordPress.")
        self._maybe_sheets(fresh)

    def _on_post_failed(self, task, err: str) -> None:
        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.status = STATUS_ERROR
        fresh.message = err
        self.store.upsert_task(fresh)
        self.store.save()
        self._log_err("Đăng bài", err)
        self.jobs_page.refresh()
        self.status("Sẵn sàng")

    def _maybe_sheets(self, task) -> None:
        cfg = self.store.sheets
        if not cfg.get("enabled"):
            return
        try:
            from ..sheets import append_row

            append_row(cfg, task.source_url, task.result.get("result_url", ""), task.site_name)
            self.status("Đã ghi kết quả vào Google Sheets.")
        except Exception as exc:
            self._log_err("Google Sheets", str(exc))

    # ------------------------------------------------------------------ #
    def _log_err(self, source: str, message: str) -> None:
        self.store.log_error(source, message)
        self.error_log_page.refresh()

    def _on_create_script(self, task) -> None:
        site = self.store.get_site(task.site_id)
        if not site:
            return
        self.jobs_page._save()
        if self.record_worker and self.record_worker.isRunning():
            self.status("Đang ghi kịch bản rồi…")
            return

        worker = PostRecordWorker(site, task)
        self.record_worker = worker
        worker.log.connect(lambda m: (self.status(m), self.jobs_page.set_recording(True, m)))
        worker.step.connect(
            lambda _s: self.jobs_page.set_recording(True, f"Đã ghi {len(worker.steps)} bước…")
        )
        worker.ok.connect(lambda steps: self._on_record_done(site, steps))
        worker.failed.connect(self._on_record_failed)
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        self.jobs_page.set_recording(True, "Đang mở trình duyệt…")
        worker.start()

    def _on_stop_record(self) -> None:
        if self.record_worker:
            self.status("Đang dừng ghi…")
            self.record_worker.stop()

    def _on_record_done(self, site, steps) -> None:
        self.jobs_page.set_recording(False)
        self.record_worker = None
        if not steps:
            self.status("Không ghi được bước nào — kịch bản giữ nguyên.")
            return
        site.script = Script(steps=[ScriptStep.from_dict(s) for s in steps])
        self.store.upsert_site(site)
        self.store.save()
        self.status(f"Đã lưu kịch bản ({len(steps)} bước) cho {site.name}.")
        QMessageBox.information(
            self, "Đã lưu kịch bản",
            f"Đã ghi và lưu {len(steps)} bước vào cấu hình của {site.name}.",
        )

    def _on_record_failed(self, err: str) -> None:
        self.jobs_page.set_recording(False)
        self.record_worker = None
        self._log_err("Ghi kịch bản", err)
        self.status("Sẵn sàng")

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

    def closeEvent(self, event) -> None:  # noqa: N802
        for w in list(self._workers):
            try:
                if hasattr(w, "stop"):
                    w.stop()
            except Exception:
                pass
        self.store.save()
        super().closeEvent(event)
