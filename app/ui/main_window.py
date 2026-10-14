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
)
from ..storage.store import Store
from .pages.config_page import ConfigPage
from .pages.history_page import HistoryPage
from .pages.jobs_page import JobsPage
from .pages.post_page import PostPage
from .style import app_font
from .workers import ContentWorker, FieldWorker, ImagesWorker, PostWorker

NAV = ["Đăng bài", "Cấu hình", "Công việc đang làm", "Lịch sử"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = Store()
        self.setWindowTitle("Hỗ Trợ Đăng Bài — WordPress")
        self.resize(1240, 820)
        self.setFont(app_font())
        self._workers: list = []
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
        self.status_pill = QLabel("● Sẵn sàng")
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
        for page in (self.post_page, self.config_page, self.jobs_page, self.history_page):
            self.stack.addWidget(page)
        v.addWidget(self.stack, 1)

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())

        # signals
        self.post_page.create_task.connect(self._on_create_task)
        self.jobs_page.regenerate.connect(self._on_regenerate)
        self.jobs_page.regenerate_images.connect(self._on_regenerate_images)
        self.jobs_page.post.connect(self._on_post_task)
        self.config_page.changed.connect(self._on_config_changed)

        self._refresh_count()
        self._check_env()

    # ------------------------------------------------------------------ #
    def _check_env(self) -> None:
        if not self.store.sites:
            self.status("Chưa có website — vào tab Cấu hình để thêm.")

    def status(self, text: str) -> None:
        self.statusBar().showMessage(text)
        self.status_pill.setText("● " + text[:40])

    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == index)
        if index == 2:
            self.jobs_page.refresh()
        elif index == 3:
            self.history_page.refresh()
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
        self.store.upsert_task(task)
        self.store.save()
        self._refresh_count()
        self.jobs_page.refresh()

        worker = ContentWorker(self.store, task, site)
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda res: self._on_content_ok(task, res))
        worker.failed.connect(lambda err: self._on_content_failed(task, err))
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        worker.start()
        self.status(f"Đang tạo nội dung cho {site.name}…")

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
        from ..storage.models import Task

        fresh = next((t for t in self.store.tasks if t.id == task.id), task)
        fresh.status = STATUS_ERROR
        fresh.message = err
        self.store.upsert_task(fresh)
        self.store.save()
        self.jobs_page.refresh()
        self.status("Lỗi tạo nội dung: " + err[:80])
        QMessageBox.warning(self, "Lỗi tạo nội dung", err)

    # ------------------------------------------------------------------ #
    def _on_regenerate_images(self, task, footer_mode: str) -> None:
        site = self.store.get_site(task.site_id)
        if not site:
            return
        self.jobs_page._save()
        task.footer_mode = footer_mode
        self.store.upsert_task(task)
        self.store.save()

        worker = ImagesWorker(site, task, footer_mode)
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda images: self._on_images_ok(task, images))
        worker.failed.connect(lambda err: self.status("Lỗi tạo ảnh: " + err[:80]))
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
        worker.log.connect(lambda m: self.status(m))
        worker.ok.connect(lambda f, v: self._on_field_ok(task, f, v))
        worker.failed.connect(lambda err: self.status("Lỗi: " + err[:80]))
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
        self.jobs_page.refresh()
        QMessageBox.warning(self, "Lỗi đăng bài", err)

    def _maybe_sheets(self, task) -> None:
        cfg = self.store.sheets
        if not cfg.get("enabled"):
            return
        try:
            from ..sheets import append_row

            append_row(cfg, task.source_url, task.result.get("result_url", ""), task.site_name)
            self.status("Đã ghi kết quả vào Google Sheets.")
        except Exception as exc:
            self.status(f"Không ghi được Google Sheets: {exc}")

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
