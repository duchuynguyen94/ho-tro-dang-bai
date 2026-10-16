"""Popup "Model Extractor": nhập danh sách link nguồn -> trích xuất product models."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..style import dim_when_disabled
from ..workers import ModelExtractorWorker


class ModelExtractorDialog(QDialog):
    """Nhập list link nguồn (mỗi link 1 dòng) -> bấm Tạo -> hiện product models."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Model Extractor")
        self.setMinimumSize(820, 640)
        self.worker: ModelExtractorWorker | None = None

        v = QVBoxLayout(self)
        v.setSpacing(8)

        title = QLabel("Model Extractor — trích xuất Product Models từ link nguồn")
        title.setStyleSheet("font-weight:700;font-size:14px;")
        v.addWidget(title)

        is_chatgpt = (store.ai_content.get("active") or "") == "chatgpt"
        if is_chatgpt:
            sub = QLabel(
                "Provider đang dùng: <b>ChatGPT</b> — sẽ trích xuất theo file "
                "<b>Rule_Model_Extractor.pdf</b> trong Project."
            )
        else:
            sub = QLabel(
                f"Provider đang dùng: <b>{store.ai_content.get('active', '')}</b> — "
                "sẽ trích xuất theo file <b>Rule Model Extractor</b> trong Cài đặt → Format Rule."
            )
        sub.setProperty("class", "sub")
        sub.setWordWrap(True)
        v.addWidget(sub)

        v.addWidget(QLabel("Danh sách link nguồn (mỗi link 1 dòng):"))
        self.links_edit = QPlainTextEdit()
        self.links_edit.setPlaceholderText(
            "https://vidu.com/san-pham-1\nhttps://vidu.com/san-pham-2"
        )
        self.links_edit.setFixedHeight(150)
        v.addWidget(self.links_edit)

        row = QHBoxLayout()
        self.show_browser = None
        if is_chatgpt:
            self.show_browser = QCheckBox("Hiện cửa sổ Chrome khi chạy")
            self.show_browser.setChecked(
                bool((store.ai_content.get("providers") or {}).get("chatgpt", {}).get("show_browser", False))
            )
            row.addWidget(self.show_browser)
        row.addStretch(1)
        self.create_btn = QPushButton("Tạo")
        self.create_btn.setProperty("class", "primary")
        self.create_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("■ Dừng")
        self.stop_btn.setProperty("class", "danger")
        self.stop_btn.setEnabled(False)
        dim_when_disabled(self.stop_btn)          # mờ hẳn khi không có gì để dừng
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.stop_btn)
        row.addWidget(self.create_btn)
        v.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("taskMeta")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        v.addWidget(QLabel("Kết quả (Product Models):"))
        self.result_edit = QPlainTextEdit()
        self.result_edit.setPlaceholderText("Kết quả sẽ hiện ở đây…")
        v.addWidget(self.result_edit, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        copy_btn = QPushButton("Sao chép kết quả")
        copy_btn.setProperty("class", "ghost")
        copy_btn.clicked.connect(self._copy)
        close_btn = QPushButton("Đóng")
        close_btn.setProperty("class", "ghost")
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(copy_btn)
        bottom.addWidget(close_btn)
        v.addLayout(bottom)

    # ------------------------------------------------------------------ #
    def _start(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        links = [l.strip() for l in self.links_edit.toPlainText().splitlines() if l.strip()]
        if not links:
            self.status.setText("⚠️ Chưa nhập link nguồn nào.")
            return
        self.result_edit.setPlainText("")
        self.status.setText(f"Đang xử lý {len(links)} link…")
        self.create_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        show = bool(self.show_browser.isChecked()) if self.show_browser is not None else False
        w = ModelExtractorWorker(self.store, links, show_browser=show)
        self.worker = w
        w.log.connect(lambda m: self.status.setText(m))
        w.partial.connect(self.result_edit.setPlainText)
        w.ok.connect(self._done)
        w.failed.connect(self._failed)
        w.finished.connect(lambda: self._finish())
        w.start()

    def _stop(self) -> None:
        if self.worker and self.worker.isRunning():
            self.status.setText("Đang dừng…")
            self.worker.stop()

    def _finish(self) -> None:
        self.create_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _done(self, text: str) -> None:
        self.create_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)      # chạy xong -> khoá nút Dừng
        self.result_edit.setPlainText(text)
        n = len([l for l in text.splitlines() if l.strip()])
        self.status.setText(f"✓ Xong — {n} dòng kết quả.")

    def _failed(self, err: str) -> None:
        self.create_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)      # lỗi -> khoá nút Dừng
        self.status.setText("✗ Lỗi: " + str(err)[:300])

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.result_edit.toPlainText())
        self.status.setText("Đã sao chép kết quả.")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        super().closeEvent(event)
