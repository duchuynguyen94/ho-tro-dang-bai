"""Popup “Tìm hình” — lấy ảnh từ NHIỀU link nguồn để chèn vào canvas."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..workers import SourceImageDownloadWorker, SourceImagesFetchWorker

THUMB = 132


class _Tile(QFrame):
    """1 ảnh trong danh sách (bấm để chọn)."""

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
    """Ô link (nhiều dòng) + nút "Lấy hình" -> chọn ảnh -> "Chèn vào canvas"."""

    def __init__(self, urls: list[str] | None = None, parent=None,
                 links: list[str] | None = None, cache: dict | None = None,
                 on_save=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tìm hình")
        self.setMinimumSize(720, 620)
        self.chosen: list[str] = []
        self.chosen_nobg = False          # tick "Xoá nền" -> đánh dấu thành phần (như chuột phải)
        self.urls: list[str] = list(urls or [])
        self.links_list: list[str] = [str(u).strip() for u in (links or []) if str(u).strip()]
        self._cache: dict = cache if cache is not None else {}   # url -> bytes (nhớ ảnh đã tải)
        self._picked: list[str] = []
        self._tiles: list[_Tile] = []
        self._worker = None
        self._fetch_worker = None
        self._on_save = on_save          # callback: lưu link + tick NGAY khi thay đổi

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        lab = QLabel("Link nguồn (mỗi dòng 1 link):")
        lab.setStyleSheet("font-weight:600;")
        v.addWidget(lab)

        self.links_edit = QPlainTextEdit()
        self.links_edit.setPlaceholderText("https://…")
        self.links_edit.setFixedHeight(74)
        if self.links_list:
            self.links_edit.setPlainText("\n".join(self.links_list))
        self.links_edit.textChanged.connect(self._emit_save)
        v.addWidget(self.links_edit)

        row = QHBoxLayout()
        self.fetch_btn = QPushButton("Lấy hình")
        self.fetch_btn.setProperty("class", "primary")
        self.fetch_btn.clicked.connect(self._on_fetch)
        row.addWidget(self.fetch_btn)
        row.addStretch(1)
        v.addLayout(row)

        self.title = QLabel(f"Ảnh ({len(self.urls)})")
        self.title.setStyleSheet("font-weight:700;")
        v.addWidget(self.title)

        sub = QLabel("Bấm ảnh để CHỌN (chọn được nhiều ảnh), rồi bấm “Chèn vào canvas”.")
        sub.setProperty("class", "sub")
        v.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        self._grid = QGridLayout(holder)
        self._grid.setSpacing(10)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)

        self.status = QLabel("Gõ link rồi bấm “Lấy hình”." if not self.urls else "")
        self.status.setObjectName("taskMeta")
        v.addWidget(self.status)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.pick_all_btn = QPushButton("Chọn tất cả")
        self.pick_all_btn.setProperty("class", "ghost")
        self.pick_all_btn.clicked.connect(self._pick_all)
        foot.addWidget(self.pick_all_btn)
        cancel = QPushButton("Đóng")
        cancel.setProperty("class", "ghost")
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        self.insert_btn = QPushButton("Chèn vào canvas")
        self.insert_btn.setProperty("class", "primary")
        self.insert_btn.setEnabled(False)
        self.insert_btn.clicked.connect(self._accept)
        foot.addWidget(self.insert_btn)
        v.addLayout(foot)

        if self.urls:
            self._set_urls(self.urls)

    def _emit_save(self, *_a) -> None:
        """Lưu NGAY link + 2 tick vào job (đóng popup hay tắt app cũng không mất)."""
        try:
            self.links_list = self._links()
        except Exception:      # noqa: BLE001
            pass
        self._save_state()

    def _save_state(self) -> None:
        if self._on_save is None:
            return
        try:
            self._on_save({"links": list(self.links_list)})
        except Exception:      # noqa: BLE001
            pass

    # ---------------- lấy ảnh từ link ---------------- #
    def _links(self) -> list[str]:
        out: list[str] = []
        for line in self.links_edit.toPlainText().splitlines():
            for piece in line.replace(",", " ").split():
                t = piece.strip()
                if t and t not in out:
                    out.append(t)
        return out

    def _on_fetch(self) -> None:
        links = self._links()
        if not links:
            self.status.setText("Gõ ít nhất 1 link trước đã.")
            return
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Đang lấy…")
        self.status.setText(f"Đang lấy ảnh từ {len(links)} link…")
        worker = SourceImagesFetchWorker(links)
        worker.log.connect(self.status.setText)
        worker.ok.connect(self._on_fetch_ok)
        worker.failed.connect(self._on_fetch_failed)
        worker.finished.connect(self._on_fetch_done)
        self._fetch_worker = worker
        worker.start()

    def _on_fetch_ok(self, urls: list) -> None:
        urls = [u for u in (urls or []) if u]
        if not urls:
            self.status.setText("Không tìm thấy ảnh nào trong các link đó.")
            return
        self._cache.clear()          # lấy link mới -> danh sách MỚI (thay cũ)
        self.links_list = self._links()
        self._set_urls(urls[:80])    # tối đa 80 ảnh cho nhẹ
        self.status.setText(f"Đã lấy {len(urls)} ảnh — chọn ảnh rồi bấm “Chèn vào canvas”.")

    def _on_fetch_failed(self, err: str) -> None:
        self.status.setText(f"Lấy ảnh lỗi: {err}")

    def _on_fetch_done(self) -> None:
        self._fetch_worker = None
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Lấy hình")

    # ---------------- danh sách ảnh ---------------- #
    def _set_urls(self, urls: list[str]) -> None:
        self.urls = [u for u in (urls or []) if u]
        self._picked = []
        while self._grid.count():
            it = self._grid.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._tiles = []
        self.title.setText(f"Ảnh ({len(self.urls)})")
        self._update_buttons()

        cols = 4
        for i, url in enumerate(self.urls):
            t = _Tile(url)
            t.clicked.connect(self._select)
            self._grid.addWidget(t, i // cols, i % cols)
            self._tiles.append(t)
        self._grid.setRowStretch(len(self._tiles) // cols + 1, 1)

        if not self._tiles:
            self.status.setText("Chưa có ảnh — gõ link rồi bấm “Lấy hình”.")
            return

        try:
            if self._worker is not None:
                self._worker.stop()
        except Exception:      # noqa: BLE001
            pass
        todo: list[str] = []
        for t in self._tiles:
            data = self._cache.get(t.url)
            if data:
                t.set_image(data)
            else:
                todo.append(t.url)
        if not todo:
            self.status.setText(f"Đã có sẵn {len(self._tiles)} ảnh — chọn ảnh rồi bấm “Chèn vào canvas”.")
            return
        self.status.setText(f"Đang tải {len(todo)} ảnh…")
        self._worker = SourceImageDownloadWorker(todo)
        self._worker.done.connect(self._on_one)
        self._worker.progress.connect(self.status.setText)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_one(self, url: str, data) -> None:
        if data:
            try:
                self._cache[url] = bytes(data)     # nhớ ảnh đã tải -> mở lại popup là hiện ngay
            except Exception:      # noqa: BLE001
                pass
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
        self.status.setText(f"Đã tải {n}/{len(self._tiles)} ảnh — chọn ảnh rồi bấm “Chèn vào canvas”."
                            if n else "Không tải được ảnh nào.")

    def _select(self, url: str) -> None:
        if not url:
            return
        if url in self._picked:
            self._picked.remove(url)
        else:
            self._picked.append(url)
        for t in self._tiles:
            t.set_selected(t.url in self._picked)
        self._update_buttons()

    def _update_buttons(self) -> None:
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
        self._update_buttons()

    # ---------------- chèn ---------------- #
    def _accept(self) -> None:
        """Lưu ảnh đã chọn ra máy rồi đóng (xoá nền / trim do 2 ô tick BÊN NGOÀI quyết định)."""
        from ...source import save_image_bytes

        self.links_list = self._links()
        paths: list[str] = []
        self.status.setText("Đang lưu ảnh…")
        for t in self._tiles:
            if t.url not in self._picked or not t.data:
                continue
            try:
                p = save_image_bytes(t.url, t.data)
            except Exception:      # noqa: BLE001
                p = ""
            if not p:
                continue
            paths.append(p)
        if not paths:
            self.status.setText("Không lưu được ảnh đã chọn — thử ảnh khác.")
            return
        self.chosen = paths
        self.chosen_nobg = False     # (bỏ ô tick trong popup — dùng 2 ô tick ngoài canvas)
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.links_list = self._links()
        self._save_state()
        for w in (self._worker, self._fetch_worker):
            try:
                if w is not None:
                    w.stop()
            except Exception:      # noqa: BLE001
                pass
        super().closeEvent(event)
