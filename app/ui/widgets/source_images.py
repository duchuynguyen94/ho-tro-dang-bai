"""Popup chọn ảnh từ link nguồn để chèn vào canvas."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..workers import SourceImageDownloadWorker

THUMB = 132


class _Tile(QFrame):
    """1 ảnh trong danh sách nguồn (bấm để chọn)."""

    clicked = Signal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self.url = url
        self.path = ""
        self.setObjectName("srcTile")
        self.setFixedSize(THUMB + 12, THUMB + 12)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("selected", "false")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.pic = QLabel("…")
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setFixedSize(THUMB, THUMB)
        self.pic.setObjectName("imgThumb")
        lay.addWidget(self.pic)

    def set_image(self, path: str) -> None:
        self.path = path
        pm = QPixmap(path)
        if pm.isNull():
            self.pic.setText("(lỗi)")
            return
        self.pic.setPixmap(pm.scaled(THUMB, THUMB, Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation))

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.path or self.url)
        super().mousePressEvent(event)


class SourceImageDialog(QDialog):
    """Hiện danh sách ảnh lấy từ link nguồn; chọn 1 ảnh rồi bấm Chèn."""

    def __init__(self, urls: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hình từ nguồn")
        self.setMinimumSize(640, 520)
        self.chosen = ""
        self._tiles: list[_Tile] = []

        v = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel(f"Ảnh tìm thấy trên link nguồn ({len(urls)})")
        title.setStyleSheet("font-weight:700;")
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)

        sub = QLabel("Bấm 1 ảnh để chọn, rồi bấm “Chèn vào canvas”.")
        sub.setProperty("class", "sub")
        v.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(10)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)

        self.status = QLabel("Đang tải ảnh…")
        self.status.setObjectName("taskMeta")
        v.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Đóng")
        cancel.setProperty("class", "ghost")
        cancel.clicked.connect(self.reject)
        self.insert_btn = QPushButton("Chèn vào canvas")
        self.insert_btn.setProperty("class", "primary")
        self.insert_btn.setEnabled(False)
        self.insert_btn.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.insert_btn)
        v.addLayout(row)

        cols = 4
        for i, url in enumerate(urls[:40]):
            t = _Tile(url)
            t.clicked.connect(self._select)
            grid.addWidget(t, i // cols, i % cols)
            self._tiles.append(t)
        grid.setRowStretch(len(self._tiles) // cols + 1, 1)

        # tải ảnh trong luồng nền
        self._worker = SourceImageDownloadWorker(urls[:40])
        self._worker.done.connect(self._on_one)
        self._worker.progress.connect(self.status.setText)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_one(self, url: str, path: str) -> None:
        for t in self._tiles:
            if t.url == url:
                if path:
                    t.set_image(path)
                else:
                    t.setEnabled(False)
                    t.pic.setText("(không tải được)")
                break

    def _on_finished(self) -> None:
        n = sum(1 for t in self._tiles if t.path)
        self.status.setText(f"Đã tải {n}/{len(self._tiles)} ảnh — chọn 1 ảnh rồi bấm “Chèn vào canvas”."
                            if n else "Không tải được ảnh nào từ link nguồn.")

    def _select(self, val: str) -> None:
        if not val:
            return
        self.chosen = val
        for t in self._tiles:
            t.set_selected(t.path == val)
        self.insert_btn.setEnabled(True)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self._worker.stop()
        except Exception:
            pass
        super().closeEvent(event)
