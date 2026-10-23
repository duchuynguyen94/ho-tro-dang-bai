"""Popup “Công cụ ảnh”: Trim / Xoá BG / Xoá BG + Trim cho nhiều ảnh."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPlainTextEdit,
                               QProgressBar, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..toast import show_toast
from ..workers import ImageToolsWorker

MODES = [
    ("trim", "Trim Ảnh",
     "Cắt viền thừa quanh đối tượng. Kết quả: <tên>_trim"),
    ("nobg", "Xoá BG ảnh",
     "Xoá nền thành trong suốt (PNG). Kết quả: <tên>_nobg"),
    ("nobg_trim", "Xoá BG + Trim",
     "Xoá nền TRƯỚC, rồi cắt viền. Kết quả: <tên>_nobg_trim"),
]
IMG_FILTER = "Ảnh (*.png *.jpg *.jpeg *.webp *.bmp)"


class ImageToolsDialog(QDialog):
    """Chọn tab (kiểu menu) + chọn nhiều ảnh -> xử lý -> lưu vào thư mục đã chọn."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.files: list[str] = []
        self.worker = None
        self.setWindowTitle("Công cụ ảnh")
        self.setMinimumSize(760, 560)
        self._build()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # menu trái
        self.menu = QListWidget()
        self.menu.setFixedWidth(190)
        for _key, title, _desc in MODES:
            self.menu.addItem(title)
        self.menu.setCurrentRow(0)
        self.menu.currentRowChanged.connect(self._on_mode_changed)
        root.addWidget(self.menu)

        # nội dung phải
        right = QVBoxLayout()
        right.setSpacing(8)
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight:700;font-size:15px;")
        right.addWidget(self.title)
        self.desc = QLabel("")
        self.desc.setProperty("class", "sub")
        self.desc.setWordWrap(True)
        right.addWidget(self.desc)

        row = QHBoxLayout()
        self.pick_btn = QPushButton("Chọn ảnh…")
        self.pick_btn.setProperty("class", "primary")
        self.pick_btn.clicked.connect(self._pick_files)
        row.addWidget(self.pick_btn)
        self.clear_btn = QPushButton("Bỏ chọn")
        self.clear_btn.setProperty("class", "ghost")
        self.clear_btn.clicked.connect(self._clear_files)
        row.addWidget(self.clear_btn)
        self.count_lab = QLabel("Chưa chọn ảnh")
        self.count_lab.setObjectName("taskMeta")
        row.addWidget(self.count_lab, 1)
        right.addLayout(row)

        orow = QHBoxLayout()
        orow.addWidget(QLabel("Thư mục lưu:"))
        self.out_edit = QLineEdit(self._saved_dir())
        self.out_edit.setPlaceholderText("Chọn thư mục lưu ảnh đã xử lý…")
        orow.addWidget(self.out_edit, 1)
        self.out_btn = QPushButton("Chọn…")
        self.out_btn.setProperty("class", "ghost")
        self.out_btn.clicked.connect(self._pick_dir)
        orow.addWidget(self.out_btn)
        right.addLayout(orow)

        self.start_btn = QPushButton("Bắt đầu")
        self.start_btn.setProperty("class", "green")
        self.start_btn.clicked.connect(self._start)
        right.addWidget(self.start_btn, alignment=Qt.AlignLeft)

        self.bar = QProgressBar()
        self.bar.setValue(0)
        right.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Nhật ký xử lý…")
        right.addWidget(self.log, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.close_btn = QPushButton("Đóng")
        self.close_btn.setProperty("class", "ghost")
        self.close_btn.clicked.connect(self.reject)
        foot.addWidget(self.close_btn)
        right.addLayout(foot)

        root.addLayout(right, 1)
        self._on_mode_changed(0)

    # ------------------------------------------------------------------ #
    def _saved_dir(self) -> str:
        try:
            return str(((self.store.data.get("ui") or {}).get("tools_out_dir") or "")).strip()
        except Exception:      # noqa: BLE001
            return ""

    def _save_dir(self, path: str) -> None:
        try:
            self.store.data.setdefault("ui", {})["tools_out_dir"] = str(path)
            self.store.save()
        except Exception:      # noqa: BLE001
            pass

    def _mode(self) -> str:
        row = self.menu.currentRow()
        return MODES[row][0] if 0 <= row < len(MODES) else "trim"

    def _on_mode_changed(self, row: int) -> None:
        if not (0 <= row < len(MODES)):
            return
        _key, title, desc = MODES[row]
        self.title.setText(title)
        self.desc.setText(desc)

    def _pick_files(self) -> None:
        from ..filepick import open_files

        paths = open_files(self.store, self, "Chọn ảnh cần xử lý", IMG_FILTER)
        if not paths:
            return
        for p in paths:
            if p not in self.files:
                self.files.append(p)
        self._refresh_count()

    def _clear_files(self) -> None:
        self.files = []
        self._refresh_count()

    def _refresh_count(self) -> None:
        n = len(self.files)
        self.count_lab.setText(f"Đã chọn {n} ảnh" if n else "Chưa chọn ảnh")

    def _pick_dir(self) -> None:
        start = self.out_edit.text().strip() or self._saved_dir()
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu ảnh", start,
                                             QFileDialog.ShowDirsOnly)
        if d:
            self.out_edit.setText(d)
            self._save_dir(d)

    # ------------------------------------------------------------------ #
    def _start(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        if not self.files:
            show_toast(self, "Chọn ít nhất 1 ảnh", 2600, ok=False)
            return
        out = self.out_edit.text().strip()
        if not out:
            show_toast(self, "Chọn thư mục lưu trước", 2600, ok=False)
            return
        try:
            Path(out).mkdir(parents=True, exist_ok=True)
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Không tạo được thư mục: {str(exc)[:60]}", 3600, ok=False)
            return
        self._save_dir(out)
        self.log.clear()
        self.bar.setValue(0)
        self.bar.setMaximum(max(1, len(self.files)))
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Đang xử lý…")

        worker = ImageToolsWorker(self.files, self._mode(), out)
        worker.log.connect(self.log.appendPlainText)
        worker.progress.connect(lambda i, t: self.bar.setValue(i))
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self.worker = worker
        worker.start()

    def _on_done(self, ok: int, total: int, out: str) -> None:
        self.log.appendPlainText(f"Xong: {ok}/{total} ảnh -> {out}")
        show_toast(self, f"Đã xử lý {ok}/{total} ảnh", 3000)

    def _on_failed(self, err: str) -> None:
        self.log.appendPlainText(f"Lỗi: {err}")
        show_toast(self, str(err)[:120], 3600, ok=False)

    def _on_finished(self) -> None:
        self.worker = None
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Bắt đầu")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            show_toast(self, "Đang xử lý — vui lòng chờ xong", 2600, ok=False)
            event.ignore()
            return
        super().closeEvent(event)
