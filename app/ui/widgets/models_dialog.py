"""Popup “Product Models” — trích xuất Product Models từ link/file bằng ChatGPT."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QVBoxLayout)

from ...ai.manager import build_models_prompt
from ..toast import show_toast
from ..workers import ModelsWorker

FILE_FILTER = ("Tài liệu (*.pdf *.docx *.doc *.txt *.png *.jpg *.jpeg *.webp);;"
               "Tất cả tệp (*)")


class ModelsDialog(QDialog):
    """Ô link + ô chọn file -> nút Xuất -> hiện danh sách Product Models."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.file_path = ""
        self._worker = None

        self.setWindowTitle("Product Models")
        self.setMinimumWidth(660)
        self.resize(700, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        title = QLabel("Trích xuất Product Models từ link hoặc file")
        title.setStyleSheet("font-weight:700;font-size:15px;")
        root.addWidget(title)

        root.addWidget(QLabel("Link nguồn (mỗi dòng 1 link):"))
        self.links = QPlainTextEdit()
        self.links.setPlaceholderText("https://…")
        self.links.setFixedHeight(76)
        root.addWidget(self.links)

        row = QHBoxLayout()
        self.pick_btn = QPushButton("Chọn file…")
        self.pick_btn.setProperty("class", "ghost")
        self.pick_btn.clicked.connect(self._pick_file)
        row.addWidget(self.pick_btn)
        self.file_lab = QLabel("(chưa chọn file)")
        self.file_lab.setObjectName("taskMeta")
        self.file_lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.file_lab, 1)
        self.clear_btn = QPushButton("✕")
        self.clear_btn.setProperty("class", "ghost")
        self.clear_btn.setFixedWidth(34)
        self.clear_btn.setToolTip("Bỏ file đã chọn")
        self.clear_btn.clicked.connect(self._clear_file)
        self.clear_btn.hide()
        row.addWidget(self.clear_btn)
        root.addLayout(row)

        self.export_btn = QPushButton("Xuất")
        self.export_btn.setProperty("class", "green")
        self.export_btn.clicked.connect(self._on_export)
        root.addWidget(self.export_btn, alignment=Qt.AlignLeft)

        self.status = QLabel("")
        self.status.setObjectName("taskMeta")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        root.addWidget(QLabel("Kết quả (mỗi Product Model 1 dòng):"))
        self.out = QPlainTextEdit()
        self.out.setPlaceholderText("Kết quả sẽ hiện ở đây…")
        root.addWidget(self.out, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.copy_btn = QPushButton("Sao chép")
        self.copy_btn.setProperty("class", "ghost")
        self.copy_btn.clicked.connect(self._copy)
        foot.addWidget(self.copy_btn)
        self.close_btn = QPushButton("Đóng")
        self.close_btn.clicked.connect(self.reject)
        foot.addWidget(self.close_btn)
        root.addLayout(foot)

    # ------------------------------------------------------------------ #
    def _pick_file(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Chọn file nguồn", "", FILE_FILTER)
        if not p:
            return
        self.file_path = p
        self.file_lab.setText(Path(p).name)
        self.clear_btn.show()

    def _clear_file(self) -> None:
        self.file_path = ""
        self.file_lab.setText("(chưa chọn file)")
        self.clear_btn.hide()

    def _links(self) -> list[str]:
        out: list[str] = []
        for line in self.links.toPlainText().splitlines():
            for piece in line.replace(",", " ").split():
                t = piece.strip()
                if t and t not in out:
                    out.append(t)
        return out

    def _on_export(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        links = self._links()
        files = [self.file_path] if self.file_path else []
        if not links and not files:
            show_toast(self, "Nhập link hoặc chọn file trước", 2600, ok=False)
            return
        prompt = build_models_prompt(links, bool(files))

        self.export_btn.setEnabled(False)
        self.export_btn.setText("Đang xuất…")
        self.out.setPlainText("")
        self.status.setText("Đang mở ChatGPT (Project)…")

        worker = ModelsWorker(self.store, prompt, files)
        worker.log.connect(self._on_log)
        worker.ok.connect(self._on_ok)
        worker.failed.connect(self._on_fail)
        worker.finished.connect(self._on_done)
        self._worker = worker
        worker.start()

    def _on_log(self, text: str) -> None:
        self.status.setText(str(text or ""))

    def _on_ok(self, text: str) -> None:
        rows = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
        self.out.setPlainText("\n".join(rows))
        self.status.setText(f"Xong — {len(rows)} Product Models")
        show_toast(self, f"Đã trích xuất {len(rows)} Product Models", 2600)

    def _on_fail(self, err: str) -> None:
        self.status.setText("")
        show_toast(self, str(err)[:160] or "Không trích xuất được", 4200, ok=False)

    def _on_done(self) -> None:
        self._worker = None
        self.export_btn.setEnabled(True)
        self.export_btn.setText("Xuất")

    def _copy(self) -> None:
        text = self.out.toPlainText().strip()
        if not text:
            show_toast(self, "Chưa có kết quả để sao chép", 2200, ok=False)
            return
        QApplication.clipboard().setText(text)
        show_toast(self, "Đã sao chép", 1800)

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:      # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            show_toast(self, "Đang xuất — vui lòng chờ xong", 2600, ok=False)
            event.ignore()
            return
        super().closeEvent(event)
