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
        self.data = b""          # giữ trong bộ nhớ, chưa lưu ra máy
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

    def set_image(self, data: bytes) -> None:
        self.data = data or b""
        pm = QPixmap()
        if not pm.loadFromData(self.data):
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
        if self.data:
            self.clicked.emit(self.url)
        super().mousePressEvent(event)


class SourceImageDialog(QDialog):
    """Hiện danh sách ảnh lấy từ link nguồn; chọn 1 ảnh rồi bấm Chèn."""

    def __init__(self, urls: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hình từ nguồn")
        self.setMinimumSize(640, 520)
        self.chosen: list[str] = []
        self._picked: list[str] = []
        self._tiles: list[_Tile] = []

        v = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel(f"Ảnh tìm thấy trên link nguồn ({len(urls)})")
        title.setStyleSheet("font-weight:700;")
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)

        sub = QLabel("Bấm ảnh để CHỌN (chọn được nhiều ảnh), rồi bấm “Chèn vào canvas”.")
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
        self.pick_all_btn = QPushButton("Chọn tất cả")
        self.pick_all_btn.setProperty("class", "ghost")
        self.pick_all_btn.clicked.connect(self._pick_all)
        row.addWidget(self.pick_all_btn)
        self.insert_btn = QPushButton("Chèn vào canvas")
        self.insert_btn.setProperty("class", "primary")
        self.insert_btn.setEnabled(False)
        self.insert_btn.clicked.connect(self._accept)
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

    def _on_one(self, url: str, data) -> None:
        for t in self._tiles:
            if t.url == url:
                if data:
                    t.set_image(bytes(data))
                else:
                    t.setEnabled(False)
                    t.pic.setText("(không tải được)")
                break

    def _on_finished(self) -> None:
        n = sum(1 for t in self._tiles if t.data)
        self.status.setText(f"Đã tải {n}/{len(self._tiles)} ảnh — chọn 1 ảnh rồi bấm “Chèn vào canvas”."
                            if n else "Không tải được ảnh nào từ link nguồn.")

    def _select(self, url: str) -> None:
        """Bấm 1 ảnh = bật/tắt chọn (chọn được nhiều ảnh)."""
        if not url:
            return
        print("DEBUG select:", url[-30:], "| truoc:", len(self._picked))
        if url in self._picked:
            self._picked.remove(url)
        else:
            self._picked.append(url)
        print("DEBUG sau:", self._picked)
        for t in self._tiles:
            t.set_selected(t.url in self._picked)
        n = len(self._picked)
        self.insert_btn.setText(f"Chèn vào canvas ({n})" if n else "Chèn vào canvas")
        self.insert_btn.setEnabled(bool(n))

    def _pick_all(self) -> None:
        ready = [t.url for t in self._tiles if t.data]
        if len(self._picked) == len(ready):
            self._picked = []
        else:
            self._picked = list(ready)
        for t in self._tiles:
            t.set_selected(t.url in self._picked)
        n = len(self._picked)
        self.insert_btn.setText(f"Chèn vào canvas ({n})" if n else "Chèn vào canvas")
        self.insert_btn.setEnabled(bool(n))

    def _accept(self) -> None:
        """Lưu (các) ảnh đã chọn ra máy rồi đóng — chỉ lưu khi bấm Chèn."""
        from ...source import save_image_bytes

        paths: list[str] = []
        for t in self._tiles:
            if t.url in self._picked and t.data:
                try:
                    p = save_image_bytes(t.url, t.data)
                except Exception:
                    p = ""
                if p:
                    paths.append(p)
        if not paths:
            self.status.setText("Không lưu được ảnh đã chọn — thử ảnh khác.")
            return
        self.chosen = paths
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self._worker.stop()
        except Exception:
            pass
        super().closeEvent(event)
