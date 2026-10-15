"""Màn hình 'Công việc đang làm'."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...storage.models import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_GENERATING,
    STATUS_LABELS,
    STATUS_POSTING,
    STATUS_QUEUED,
    STATUS_REVIEW,
)
from ..style import Card
from ..toast import show_toast

STATUS_OBJECTS = {
    STATUS_QUEUED: "chipGray",
    STATUS_GENERATING: "chipAmber",
    STATUS_REVIEW: "chipBlue",
    STATUS_POSTING: "chipAmber",
    STATUS_DONE: "chipGreen",
    STATUS_ERROR: "chipRed",
}


class TaskRow(QFrame):
    """1 dòng trong danh sách công việc (có nút xoá)."""

    clicked = Signal(str)
    delete = Signal(str)
    copied = Signal(str)

    def __init__(self, task, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("taskRow")
        self.task_id = task.id
        self.source_url = task.source_url or ""

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 8, 10)
        h.setSpacing(8)

        v = QVBoxLayout()
        v.setSpacing(3)

        url = QLabel(task.source_url or "(chưa có link)")
        url.setObjectName("taskTitle")
        url.setWordWrap(True)
        v.addWidget(url)

        meta = QLabel(f"{STATUS_LABELS.get(task.status, task.status)}  ·  {task.site_name}")
        meta.setObjectName("taskMeta")
        v.addWidget(meta)

        if task.status == STATUS_GENERATING:
            bar = QProgressBar()
            bar.setRange(0, 0)
            bar.setTextVisible(False)
            bar.setFixedHeight(4)
            v.addWidget(bar)

        h.addLayout(v, 1)

        self.del_btn = QPushButton("✕")
        self.del_btn.setObjectName("taskDel")
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.setToolTip("Xoá công việc này")
        self.del_btn.clicked.connect(lambda: self.delete.emit(self.task_id))
        h.addWidget(self.del_btn, 0, Qt.AlignTop)

        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.task_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        act_copy = menu.addAction("Sao chép link nguồn")
        act_copy.setEnabled(bool(self.source_url))
        act_open = menu.addAction("Mở link nguồn")
        act_open.setEnabled(bool(self.source_url))
        menu.addSeparator()
        act_del = menu.addAction("Xoá công việc")

        chosen = menu.exec(event.globalPos())
        if chosen == act_copy and self.source_url:
            QApplication.clipboard().setText(self.source_url)
            self.copied.emit(self.source_url)
        elif chosen == act_open and self.source_url:
            QDesktopServices.openUrl(QUrl(self.source_url))
        elif chosen == act_del:
            self.delete.emit(self.task_id)


class JobsPage(QWidget):
    regenerate = Signal(object, str)         # (task, field)
    regenerate_images = Signal(object, str)  # (task, footer_mode)
    post = Signal(object)                    # (task)
    create_script = Signal(object)           # (task) - tạo kịch bản (có xác nhận mật khẩu)
    stop_record = Signal()                   # dừng ghi & lưu
    delete_task = Signal(str)                # task id
    ai_edit = Signal(object, int, str)       # (task, image index, yêu cầu chỉnh sửa)

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.current = None
        self._rows: dict[str, TaskRow] = {}
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        split = QSplitter(Qt.Horizontal)

        # ---------- danh sách việc ----------
        left = Card()
        left.setMinimumWidth(300)
        left.setMaximumWidth(420)
        left.set_title("Công việc đang làm")
        self.count_badge = QLabel("0")
        self.count_badge.setObjectName("chipBlue")
        left.add_header_widget(self.count_badge)

        self.tasks_scroll = QScrollArea()
        self.tasks_scroll.setWidgetResizable(True)
        self.tasks_scroll.setFrameShape(QFrame.NoFrame)
        self.tasks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.tasks_box = QVBoxLayout(holder)
        self.tasks_box.setContentsMargins(0, 0, 0, 0)
        self.tasks_box.setSpacing(0)
        self.tasks_box.addStretch(1)
        self.tasks_scroll.setWidget(holder)
        left.body.addWidget(self.tasks_scroll, 1)
        split.addWidget(left)

        # ---------- panel kết quả ----------
        right = Card("Kết quả AI")
        self.result_card = right
        self.provider_badge = QLabel("")
        self.provider_badge.setObjectName("chipGreen")
        right.add_header_widget(self.provider_badge)

        self.stack = QStackedWidget()
        right.body.addWidget(self.stack, 1)

        # 0: chưa chọn
        self.page_empty = QLabel("Chọn 1 công việc ở bên trái để xem / duyệt kết quả.")
        self.page_empty.setAlignment(Qt.AlignCenter)
        self.page_empty.setObjectName("taskMeta")
        self.stack.addWidget(self.page_empty)

        # 1: đang chạy
        self.page_loading = QWidget()
        lv = QVBoxLayout(self.page_loading)
        lv.addStretch(1)
        self.loading_label = QLabel("Đang gọi AI tạo nội dung…")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("font-size:14px;font-weight:600;")
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedHeight(6)
        self.loading_bar.setFixedWidth(320)
        lv.addWidget(self.loading_label, alignment=Qt.AlignHCenter)
        lv.addWidget(self.loading_bar, alignment=Qt.AlignHCenter)
        self.loading_note = QLabel("")
        self.loading_note.setObjectName("taskMeta")
        self.loading_note.setAlignment(Qt.AlignCenter)
        self.loading_note.setWordWrap(True)
        lv.addWidget(self.loading_note)
        lv.addStretch(1)
        self.stack.addWidget(self.page_loading)

        # 2: lỗi
        self.page_error = QWidget()
        ev = QVBoxLayout(self.page_error)
        ev.addStretch(1)
        self.error_label = QLabel("")
        self.error_label.setObjectName("warnMsg")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        ev.addWidget(self.error_label)
        retry = QPushButton("↻ Thử tạo lại")
        retry.setProperty("class", "primary")
        retry.clicked.connect(lambda: self.current and self.regenerate.emit(self.current, ""))
        ev.addWidget(retry, alignment=Qt.AlignHCenter)
        ev.addStretch(1)
        self.stack.addWidget(self.page_error)

        # 3: kết quả
        self.editor = QWidget()
        ev2 = QVBoxLayout(self.editor)
        ev2.setContentsMargins(0, 0, 0, 0)
        ev2.setSpacing(10)

        self.title_edit = QLineEdit()
        ev2.addLayout(self._field("Tiêu đề", self.title_edit, "title"))
        self.kw_edit = QLineEdit()
        ev2.addLayout(self._field("Focus keyword", self.kw_edit, "focus_keyword"))
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setFixedHeight(62)
        ev2.addLayout(self._field("Description (mô tả SEO)", self.desc_edit, "description"))
        self.tags_edit = QLineEdit()
        ev2.addLayout(self._field("Search tags (cách nhau bởi dấu phẩy)", self.tags_edit, "tags"))
        self.content_edit = QPlainTextEdit()
        self.content_edit.setMinimumHeight(180)
        self.content_edit.setObjectName("mono")
        ev2.addLayout(self._field("Nội dung (HTML)", self.content_edit, "content_html"))

        img_head = QHBoxLayout()
        img_lab = QLabel("Ảnh (thumbnail + slider)")
        img_lab.setStyleSheet("font-weight:600;")
        img_head.addWidget(img_lab)
        img_head.addStretch(1)
        img_head.addWidget(QLabel("Thanh thông tin:"))
        self.footer_combo = QComboBox()
        self.footer_combo.addItems(["Random (mặc định)", "Chỉ dùng hình 1", "Chỉ dùng hình 2"])
        img_head.addWidget(self.footer_combo)
        regen = QPushButton("↻ Tạo lại ảnh")
        regen.setProperty("class", "ghost")
        regen.clicked.connect(self._regen_images)
        img_head.addWidget(regen)
        ev2.addLayout(img_head)

        self.images_row = QHBoxLayout()
        ev2.addLayout(self.images_row)
        ev2.addStretch(1)

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_scroll.setWidget(self.editor)
        self.stack.addWidget(self.editor_scroll)

        # thanh ghi kịch bản (hiện khi đang ghi)
        self.recording_bar = QWidget()
        rb = QHBoxLayout(self.recording_bar)
        rb.setContentsMargins(0, 6, 0, 0)
        self.rec_dot = QLabel("● Đang ghi kịch bản…")
        self.rec_dot.setStyleSheet("color:#dc2626;font-weight:700;")
        rb.addWidget(self.rec_dot)
        self.rec_note = QLabel("")
        self.rec_note.setObjectName("taskMeta")
        self.rec_note.setWordWrap(True)
        rb.addWidget(self.rec_note, 1)
        stop_rec = QPushButton("■ Dừng & Lưu kịch bản")
        stop_rec.setProperty("class", "primary")
        stop_rec.clicked.connect(self.stop_record.emit)
        rb.addWidget(stop_rec)
        right.body.addWidget(self.recording_bar)
        self.recording_bar.hide()

        # footer luôn hiện khi có kết quả
        self.footer = QWidget()
        f = QHBoxLayout(self.footer)
        f.setContentsMargins(0, 8, 0, 0)
        self.check_label = QLabel("")
        self.check_label.setObjectName("taskMeta")
        f.addWidget(self.check_label)
        f.addStretch(1)
        self.record_btn = QPushButton("● Tạo kịch bản")
        self.record_btn.setObjectName("recordBtn")
        self.record_btn.setToolTip("Mở trình duyệt và ghi lại thao tác đăng bài thành kịch bản (cần mật khẩu)")
        self.record_btn.clicked.connect(self._start_create_script)
        self.post_btn = QPushButton("OK — Đăng bài")
        self.post_btn.setProperty("class", "green")
        self.post_btn.clicked.connect(lambda: self.current and self.post.emit(self.current))
        f.addWidget(self.record_btn)
        f.addWidget(self.post_btn)
        right.body.addWidget(self.footer)
        self.footer.hide()

        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 900])
        outer.addWidget(split)

    def _field(self, label: str, widget: QWidget, field: str) -> QVBoxLayout:
        box = QVBoxLayout()
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setStyleSheet("font-weight:600;")
        row.addWidget(lab)
        row.addStretch(1)
        btn = QPushButton("↻ Random")
        btn.setProperty("class", "ghost")
        btn.clicked.connect(lambda: self.current and self.regenerate.emit(self.current, field))
        row.addWidget(btn)
        box.addLayout(row)
        box.addWidget(widget)
        return box

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        tasks = self.store.tasks
        self.count_badge.setText(str(len(tasks)))
        self._ordered = list(reversed(tasks))

        while self.tasks_box.count() > 1:
            it = self.tasks_box.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()

        for t in self._ordered:
            row = TaskRow(t)
            row.clicked.connect(self.select_task)
            row.delete.connect(self._confirm_delete)
            row.copied.connect(lambda _u: show_toast(self, "Đã sao chép link nguồn"))
            self._rows[t.id] = row
            self.tasks_box.insertWidget(self.tasks_box.count() - 1, row)

        if not self._ordered:
            self.current = None
            self._show_state()
            return

        target_id = self.current.id if self.current else None
        if not target_id or target_id not in self._rows:
            if self.current is not None:
                # vừa tạo xong -> chọn việc mới nhất
                target_id = self._ordered[0].id
            else:
                target_id = self._ordered[0].id
        self.select_task(target_id)

    def select_task(self, task_id: str) -> None:
        task = next((t for t in self.store.tasks if t.id == task_id), None)
        if not task:
            return
        self.current = task
        for tid, row in self._rows.items():
            row.set_selected(tid == task_id)
        r = task.result or {}
        self.result_card.set_title(f"Kết quả AI — {task.site_name}")
        active = self.store.ai_content.get("active", "")
        self.provider_badge.setText(f"Provider: {active}" if active else "")
        self._show_state()

    def set_loading_message(self, text: str) -> None:
        if self.current and self.current.status in (STATUS_QUEUED, STATUS_GENERATING):
            self.loading_note.setText(text)

    def set_recording(self, on: bool, note: str = "") -> None:
        self.recording_bar.setVisible(on)
        if note:
            self.rec_note.setText(note)

    # ------------------------------------------------------------------ #
    def _show_state(self) -> None:
        task = self.current
        if task is None:
            self.footer.hide()
            self.stack.setCurrentWidget(self.page_empty)
            return

        if task.status in (STATUS_QUEUED, STATUS_GENERATING):
            self.footer.hide()
            self.loading_label.setText(
                f"Đang tạo nội dung cho {task.site_name}…"
            )
            self.stack.setCurrentWidget(self.page_loading)
            return

        if task.status == STATUS_ERROR:
            self.footer.hide()
            msg = task.message or "Lỗi không xác định."
            if "giới hạn" in msg.lower():
                hint = ("Chờ tới khi lượt được làm mới, hoặc đổi provider khác "
                        "(Gemini/DeepSeek…) trong Cấu hình → AI nội dung.")
                title = "AI đang bị giới hạn."
            else:
                hint = "Kiểm tra API key / model trong Cấu hình → AI nội dung."
                title = "Không tạo được nội dung."
            self.error_label.setText(
                f"<b>{title}</b><br><br>{msg}"
                f"<br><br><span style='color:#64748b'>{hint}</span>"
            )
            self.stack.setCurrentWidget(self.page_error)
            return

        self._load(task)

    def _load(self, task) -> None:
        r = task.result or {}
        self.title_edit.setText(r.get("title", ""))
        self.kw_edit.setText(r.get("focus_keyword", ""))
        self.desc_edit.setPlainText(r.get("description", ""))
        self.tags_edit.setText(r.get("tags", ""))
        self.content_edit.setPlainText(r.get("content_html", ""))
        self.footer_combo.setCurrentIndex({"random": 0, "bar1": 1, "bar2": 2}.get(task.footer_mode, 0))

        while self.images_row.count():
            it = self.images_row.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        images = r.get("images", [])
        for i, im in enumerate(images, 1):
            self.images_row.addWidget(self._image_box(i, im))
        self.images_row.addStretch(1)

        n = len(images)
        self.check_label.setText(f"Kiểm tra: đúng format & đủ {task.image_count} ảnh (hiện có {n})")
        self.stack.setCurrentWidget(self.editor_scroll)
        self.footer.show()

    def _image_box(self, index: int, im: dict) -> QWidget:
        box = QFrame()
        box.setObjectName("imgBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(6, 6, 6, 6)
        bl.setSpacing(6)

        pic = QLabel()
        pic.setObjectName("imgThumb")
        pic.setFixedSize(160, 160)
        pic.setAlignment(Qt.AlignCenter)
        p = Path(im.get("path", ""))
        if p.exists():
            pic.setPixmap(QPixmap(str(p)).scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            pic.setText("(chưa có ảnh)")
        bl.addWidget(pic)

        bts = QHBoxLayout()
        up = QPushButton("Tải lên")
        up.setProperty("class", "ghost")
        up.clicked.connect(lambda _=False, idx=index - 1: self._upload_image(idx))
        ai = QPushButton("AI sửa")
        ai.setProperty("class", "ghost")
        ai.clicked.connect(lambda _=False, idx=index - 1: self._ai_edit(idx))
        rnd = QPushButton("↻ Random")
        rnd.setProperty("class", "ghost")
        rnd.clicked.connect(lambda: self.current and self.regenerate.emit(self.current, "images"))
        bts.addWidget(up)
        bts.addWidget(ai)
        bts.addWidget(rnd)
        bl.addLayout(bts)
        return box

    def _ai_edit(self, index: int) -> None:
        if not self.current:
            return
        prompt, ok = QInputDialog.getText(
            self, "AI sửa ảnh",
            "Mô tả yêu cầu chỉnh sửa (ví dụ: xoá nền thành trong suốt, đổi nền trắng):",
        )
        if not ok or not (prompt or "").strip():
            return
        self.ai_edit.emit(self.current, index, prompt.strip())

    # ------------------------------------------------------------------ #
    def _regen_images(self) -> None:
        if not self.current:
            return
        mode = ["random", "bar1", "bar2"][self.footer_combo.currentIndex()]
        self.current.footer_mode = mode
        self.regenerate_images.emit(self.current, mode)

    def _upload_image(self, index: int) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh", "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
        if not path or not self.current:
            return
        images = self.current.result.setdefault("images", [])
        while len(images) <= index:
            images.append({"path": "", "footer": ""})
        images[index] = {"path": path, "footer": images[index].get("footer", "")}
        self.store.upsert_task(self.current)
        self.store.save()
        self._load(self.current)

    def _start_create_script(self) -> None:
        """Xác nhận mật khẩu trước khi bắt đầu ghi kịch bản (tránh bấm nhầm)."""
        if not self.current:
            return
        pw, ok = QInputDialog.getText(
            self, "Tạo kịch bản",
            "Nhập mật khẩu để bắt đầu tạo kịch bản:",
            QLineEdit.Password,
        )
        if not ok:
            return
        if (pw or "").strip() != "admin":
            QMessageBox.warning(self, "Sai mật khẩu", "Mật khẩu không đúng. Không tạo kịch bản.")
            return
        self.create_script.emit(self.current)

    def _confirm_delete(self, task_id: str) -> None:
        ans = QMessageBox.question(
            self, "Xoá công việc", "Xoá công việc này khỏi danh sách?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if ans != QMessageBox.Yes:
            return
        if self.current and self.current.id == task_id:
            self.current = None
        self.delete_task.emit(task_id)

    def _save(self) -> None:
        if not self.current:
            return
        r = self.current.result
        r["title"] = self.title_edit.text()
        r["focus_keyword"] = self.kw_edit.text()
        r["description"] = self.desc_edit.toPlainText()
        r["tags"] = self.tags_edit.text()
        r["content_html"] = self.content_edit.toPlainText()
        self.store.upsert_task(self.current)
        self.store.save()
