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
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..workers import SourceImageDownloadWorker, SourceImageSearchWorker

THUMB = 132


class _Tile(QFrame):
    """1 ảnh trong danh sách nguồn (bấm để chọn)."""

    clicked = Signal(str)

    def __init__(self, url: str, caption: str = "", parent=None) -> None:
        super().__init__(parent)
        self.url = url
        self.data = b""          # giữ trong bộ nhớ, chưa lưu ra máy
        self.setObjectName("srcTile")
        self.setFixedSize(THUMB + 12, THUMB + 12 + 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("selected", "false")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.pic = QLabel("…")
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setFixedSize(THUMB, THUMB)
        self.pic.setObjectName("imgThumb")
        lay.addWidget(self.pic)
        # DÒNG CHỮ DƯỚI ẢNH: ảnh này thuộc mã nào
        self.cap = QLabel(str(caption or ""))
        self.cap.setWordWrap(True)
        self.cap.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.cap.setFixedHeight(28)
        self.cap.setToolTip(str(caption or ""))
        self.cap.setStyleSheet("font-size:10px;color:#475569;background:transparent;")
        lay.addWidget(self.cap)

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
    """Hiện danh sách ảnh TỰ TÌM; chọn 1 hoặc nhiều ảnh rồi bấm "Chèn vào canvas".

    - Ô nhập keyword + nút "Tìm ảnh": tìm 20 ảnh trên internet (làm lại list khác).
    - Bấm lại nút "Hình tự tìm": popup vẫn GIỮ danh sách cũ, muốn list khác thì gõ keyword mới.
    """

    def __init__(self, urls: list[str], parent=None, keyword: str = "",
                 allow_search: bool = True, cache: dict | None = None,
                 labels: dict | None = None) -> None:
        super().__init__(parent)
        self._labels: dict = dict(labels or {})     # url -> "mã sản phẩm"
        self._all_urls: list = list(urls or [])
        self.setWindowTitle("Hình tự tìm")
        self.setMinimumSize(700, 560)
        self.chosen: list[str] = []
        self.urls: list[str] = list(urls or [])
        self.keyword: str = str(keyword or "")
        self._allow_search = bool(allow_search)   # có cho tìm ảnh trên internet không
        self._cache: dict = cache if cache is not None else {}   # url -> bytes (giữ ảnh đã tải)
        self._picked: list[str] = []
        self._tiles: list[_Tile] = []
        self._worker = None
        self._search_worker = None

        v = QVBoxLayout(self)

        if not self._allow_search:
            # BỎ tìm ảnh internet -> chỉ còn ô LỌC theo mã sản phẩm
            frow = QHBoxLayout()
            flab = QLabel("Lọc theo mã")
            flab.setStyleSheet("font-weight:600;")
            frow.addWidget(flab)
            self.filter_edit = QLineEdit()
            self.filter_edit.setPlaceholderText("Gõ mã sản phẩm để lọc ảnh…")
            self.filter_edit.textChanged.connect(self._apply_filter)
            frow.addWidget(self.filter_edit, 1)
            v.addLayout(frow)
        # ô nhập keyword + nút tìm ảnh
        krow = QHBoxLayout()
        klab = QLabel("Keyword hình")
        klab.setStyleSheet("font-weight:600;")
        krow.addWidget(klab)
        self.kw_edit = QLineEdit(self.keyword)
        self.kw_edit.setPlaceholderText("Gõ keyword (ví dụ: máy bơm nước Panasonic)…")
        self.kw_edit.returnPressed.connect(self._do_search)
        krow.addWidget(self.kw_edit, 1)
        self.search_btn = QPushButton("Tìm ảnh")
        self.search_btn.setProperty("class", "primary")
        self.search_btn.setEnabled(self._allow_search)
        self.search_btn.clicked.connect(self._do_search)
        krow.addWidget(self.search_btn)
        if self._allow_search:
            v.addLayout(krow)
        else:
            klab.hide()
            self.kw_edit.hide()
            self.search_btn.hide()

        head = QHBoxLayout()
        self.title = QLabel(f"Ảnh tìm được ({len(self.urls)})")
        self.title.setStyleSheet("font-weight:700;")
        head.addWidget(self.title)
        head.addStretch(1)
        v.addLayout(head)

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

        self._set_urls(self.urls)

    # ---------------- danh sách ảnh ---------------- #
    def _set_urls(self, urls: list[str]) -> None:
        """Nạp (lại) danh sách ảnh vào popup + tải ảnh trong luồng nền."""
        self.urls = [u for u in (urls or []) if u]
        self._picked = []
        while self._grid.count():
            it = self._grid.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._tiles = []
        self.title.setText(f"Ảnh từ link nguồn ({len(self.urls)})"
                           if not self._allow_search else f"Ảnh tìm được ({len(self.urls)})")
        self._update_buttons()

        cols = 4
        for i, url in enumerate(self.urls[:60]):
            t = _Tile(url, self._labels.get(url, ""))
            t.clicked.connect(self._select)
            self._grid.addWidget(t, i // cols, i % cols)
            self._tiles.append(t)
        self._grid.setRowStretch(len(self._tiles) // cols + 1, 1)

        if not self._tiles:
            self.status.setText("Không có ảnh phù hợp." if self._all_urls
                                else "Link nguồn không có ảnh nào.")
            return
        try:
            if self._worker is not None:
                self._worker.stop()
        except Exception:
            pass
        # Ảnh ĐÃ TẢI TRƯỚC ĐÓ -> hiện NGAY (không tải lại); chỉ tải ảnh còn thiếu
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

    def _apply_filter(self) -> None:
        """Lọc ảnh theo mã sản phẩm (không phân biệt hoa thường / dấu)."""
        q = self.filter_edit.text().strip().lower() if hasattr(self, "filter_edit") else ""
        if not q:
            self._set_urls(self._all_urls)
            return
        def _norm(t: str) -> str:
            import re as _re

            t = t.lower().replace("đ", "d")
            return _re.sub(r"[^a-z0-9]+", "", t)
        nq = _norm(q)
        keep = [u for u in self._all_urls
                if nq in _norm(self._labels.get(u, "")) or nq in _norm(u)]
        self._set_urls(keep)

    def _do_search(self) -> None:
        """Tìm list ảnh MỚI theo keyword (chạy luồng riêng — không đứng giao diện)."""
        q = self.kw_edit.text().strip()
        if not q:
            self.status.setText("Gõ keyword trước đã.")
            return
        if not self._allow_search:
            return
        self.keyword = q
        self._cache.clear()          # bấm "Tìm ảnh" -> XOÁ cache ảnh cũ
        self.search_btn.setEnabled(False)
        self.status.setText("Đang tìm ảnh trên internet…")
        try:
            if self._search_worker is not None:
                self._search_worker.stop()
        except Exception:
            pass
        self._search_worker = SourceImageSearchWorker(q, limit=20)
        self._search_worker.log.connect(self.status.setText)
        self._search_worker.ok.connect(self._on_search_ok)
        self._search_worker.failed.connect(self._on_search_failed)
        self._search_worker.start()

    def _on_search_ok(self, urls: list) -> None:
        self.search_btn.setEnabled(True)
        urls = [u for u in (urls or []) if u]
        if not urls:
            self.status.setText("Không tìm được ảnh nào — thử keyword khác.")
            return
        self._set_urls(urls[:20])

    def _on_search_failed(self, err: str) -> None:
        self.search_btn.setEnabled(True)
        self.status.setText(f"Tìm ảnh lỗi: {err}")

    def _on_one(self, url: str, data) -> None:
        if data:
            try:
                self._cache[url] = bytes(data)     # nhớ ảnh đã tải -> mở lại popup là hiện ngay
            except Exception:
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
        self.status.setText(f"Đã tải {n}/{len(self._tiles)} ảnh — chọn 1 ảnh rồi bấm “Chèn vào canvas”."
                            if n else "Không tải được ảnh nào từ link nguồn.")

    def _select(self, url: str) -> None:
        """Bấm 1 ảnh = bật/tắt chọn (chọn được nhiều ảnh)."""
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

    def _accept(self) -> None:
        """Lưu (các) ảnh đã chọn ra máy rồi đóng — chỉ lưu khi bấm Chèn."""
        from ...source import save_image_bytes

        self.keyword = self.kw_edit.text().strip()      # nhớ keyword cho lần mở sau
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
            self.keyword = self.kw_edit.text().strip()
        except Exception:
            pass
        for w in (self._worker, self._search_worker):
            try:
                if w is not None:
                    w.stop()
            except Exception:
                pass
        super().closeEvent(event)
