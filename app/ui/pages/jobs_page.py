"""Màn hình 'Công việc đang làm'."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
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

STATUS_COLORS = {
    STATUS_QUEUED: "#64748b",
    STATUS_GENERATING: "#b45309",
    STATUS_REVIEW: "#1d4ed8",
    STATUS_POSTING: "#6d28d9",
    STATUS_DONE: "#047857",
    STATUS_ERROR: "#b91c1c",
}


class JobsPage(QWidget):
    regenerate = Signal(object, str)   # (task, field)  field="" -> toàn bộ
    post = Signal(object)              # (task)

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.current = None
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        split = QSplitter(Qt.Horizontal)

        # ---- danh sách việc ----
        left = Card()
        left.setMinimumWidth(320)
        left.set_title("Công việc đang làm")
        self.count_badge = QLabel("0")
        self.count_badge.setStyleSheet(
            "background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;border-radius:9px;padding:2px 8px;font-size:11px;font-weight:700;"
        )
        left.add_header_widget(self.count_badge)
        self.task_list = QListWidget()
        self.task_list.currentItemChanged.connect(self._on_select)
        left.body.addWidget(self.task_list)
        split.addWidget(left)

        # ---- kết quả ----
        right = Card("Kết quả AI — chờ duyệt")
        self.result_root = right
        self.empty = QLabel("Chọn 1 công việc ở bên trái để xem / duyệt kết quả.")
        self.empty.setProperty("class", "hint")
        right.body.addWidget(self.empty)

        self.editor = QWidget()
        ev = QVBoxLayout(self.editor)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(10)

        # Tiêu đề
        self.title_edit = QLineEdit()
        ev.addLayout(self._field("Tiêu đề", self.title_edit, "title"))
        # Focus keyword
        self.kw_edit = QLineEdit()
        ev.addLayout(self._field("Focus keyword", self.kw_edit, "focus_keyword"))
        # Description
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setFixedHeight(64)
        ev.addLayout(self._field("Description (mô tả SEO)", self.desc_edit, "description"))
        # Tags
        self.tags_edit = QLineEdit()
        ev.addLayout(self._field("Search tags (cách nhau bởi dấu phẩy)", self.tags_edit, "tags"))
        # Nội dung
        self.content_edit = QPlainTextEdit()
        self.content_edit.setMinimumHeight(200)
        self.content_edit.setStyleSheet("font-family: Menlo, Consolas, monospace; font-size: 12px;")
        ev.addLayout(self._field("Nội dung (HTML)", self.content_edit, "content_html"))

        # Ảnh
        ev.addWidget(QLabel("Ảnh (thumbnail + slider)"))
        self.images_row = QHBoxLayout()
        ev.addLayout(self.images_row)

        hint = QLabel(
            "Bấm <b>Đăng bài</b> → phần mềm mở trình duyệt và <b>điền sẵn theo kịch bản</b>. "
            "Bạn tự kiểm tra rồi bấm nút Đăng trên WordPress."
        )
        hint.setProperty("class", "hint")
        hint.setWordWrap(True)
        ev.addWidget(hint)

        foot = QHBoxLayout()
        foot.addStretch(1)
        save = QPushButton("Lưu nháp")
        save.setProperty("class", "ghost")
        save.clicked.connect(self._save)
        self.post_btn = QPushButton("OK — Đăng bài")
        self.post_btn.setProperty("class", "green")
        self.post_btn.clicked.connect(lambda: self.current and self.post.emit(self.current))
        foot.addWidget(save)
        foot.addWidget(self.post_btn)
        ev.addLayout(foot)

        right.body.addWidget(self.editor)
        self.editor.hide()
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        outer.addWidget(split)

    def _field(self, label: str, widget: QWidget, field: str) -> QHBoxLayout:
        """1 hàng: label + nút Random; widget ở dưới (dùng VBox ngoài)."""
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
        wrapper = QVBoxLayout()
        wrapper.addLayout(box)
        return wrapper

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        tasks = self.store.tasks
        self.count_badge.setText(str(len(tasks)))
        self._ordered = list(reversed(tasks))  # mới nhất lên đầu

        self.task_list.blockSignals(True)
        self.task_list.clear()
        for t in self._ordered:
            label = (
                f"{(t.result.get('title') or t.source_url)[:42]}\n"
                f"{STATUS_LABELS.get(t.status, t.status)} · {t.site_name}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, t.id)
            self.task_list.addItem(item)
        self.task_list.blockSignals(False)

        if not self._ordered:
            self.current = None
            self.editor.hide()
            self.empty.show()
            return

        target_id = self.current.id if self.current else None
        if not target_id or not any(t.id == target_id for t in self._ordered):
            pick = next((i for i, t in enumerate(self._ordered) if t.result.get("images")), 0)
            target_id = self._ordered[pick].id
        for i, t in enumerate(self._ordered):
            if t.id == target_id:
                self.task_list.setCurrentRow(i)
                break

    def _on_select(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        tid = item.data(Qt.UserRole)
        task = next((t for t in self.store.tasks if t.id == tid), None)
        if not task:
            return
        self.current = task
        self._load(task)

    def _load(self, task) -> None:
        self.empty.hide()
        self.editor.show()
        r = task.result or {}
        self.result_root.set_title(f"Kết quả AI — {task.site_name}")
        self.title_edit.setText(r.get("title", ""))
        self.kw_edit.setText(r.get("focus_keyword", ""))
        self.desc_edit.setPlainText(r.get("description", ""))
        self.tags_edit.setText(r.get("tags", ""))
        self.content_edit.setPlainText(r.get("content_html", ""))

        while self.images_row.count():
            it = self.images_row.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        for i, im in enumerate(r.get("images", []), 1):
            box = QFrame()
            box.setStyleSheet("QFrame{border:1px solid #e5e7eb;border-radius:8px;}")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(6, 6, 6, 6)
            pic = QLabel()
            pic.setFixedSize(150, 150)
            pic.setStyleSheet("background:#f1f5f9;border-radius:6px;")
            pic.setAlignment(Qt.AlignCenter)
            p = Path(im.get("path", ""))
            if p.exists():
                pm = QPixmap(str(p)).scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pic.setPixmap(pm)
            else:
                pic.setText("(chưa có ảnh)")
            bl.addWidget(pic)
            bts = QHBoxLayout()
            up = QPushButton("Tải lên")
            up.setProperty("class", "ghost")
            up.clicked.connect(lambda _=False, idx=i - 1: self._upload_image(idx))
            rnd = QPushButton("↻ Random")
            rnd.setProperty("class", "ghost")
            rnd.clicked.connect(lambda: self.current and self.regenerate.emit(self.current, "images"))
            bts.addWidget(up)
            bts.addWidget(rnd)
            bl.addLayout(bts)
            self.images_row.addWidget(box)
        self.images_row.addStretch(1)

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
