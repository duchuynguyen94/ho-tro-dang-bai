"""Panel “Chèn nội dung” (Cài đặt) — khối “Đọc thêm”.

Nội dung lấy từ FILE TRÊN GITHUB (`content/readmore.html`), không nhập tay trong app.
Khối này được chèn NGAY SAU </h1> khi Auto format hoặc khi đăng bài.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..style import Card, dim_when_disabled, make_cfg_panel
from ..toast import show_toast


class ReadMorePanel(QWidget):
    """Xem nội dung “Đọc thêm” đang dùng + tải lại từ GitHub."""

    changed = Signal()

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._worker = None
        self._build()
        self.reload()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        from ...config import READMORE_PAGE_URL, READMORE_URL

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        card = Card("Chèn nội dung")
        desc = QLabel(
            "Nội dung “Đọc thêm” được chèn vào bài <b>ngay sau thẻ &lt;/h1&gt;</b> "
            "(bài không có &lt;h1&gt; thì chèn ngay đầu nội dung). "
            "Áp dụng khi bấm <b>Auto format</b> và khi <b>đăng bài</b>.<br>"
            "Nội dung lấy từ file trên GitHub — sửa file đó là mọi máy tự cập nhật; "
            "<b>không nhập tay trong app</b>."
        )
        desc.setProperty("class", "sub")
        desc.setWordWrap(True)
        card.body.addWidget(desc)

        link = QLabel(
            f'<a href="{READMORE_URL}">{READMORE_URL}</a>'
        )
        link.setOpenExternalLinks(True)
        link.setWordWrap(True)
        link.setToolTip("Bấm để mở file nội dung trên GitHub")
        card.body.addWidget(link)

        self.status = QLabel("")
        self.status.setObjectName("taskMeta")
        self.status.setWordWrap(True)
        card.body.addWidget(self.status)

        card.body.addWidget(QLabel("Nội dung đang dùng:"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)          # CHỈ XEM — sửa nội dung trên GitHub
        self.preview.setMinimumHeight(170)
        self.preview.setPlaceholderText("(chưa có nội dung — bấm “Tải lại từ GitHub”)")
        card.body.addWidget(self.preview)

        row = QHBoxLayout()
        self.fetch_btn = QPushButton("↻ Tải lại từ GitHub")
        self.fetch_btn.setProperty("class", "primary")
        self.fetch_btn.clicked.connect(self.fetch)
        row.addWidget(self.fetch_btn)
        self.open_btn = QPushButton("Mở file trên GitHub")
        self.open_btn.setProperty("class", "ghost")
        self.open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(READMORE_PAGE_URL)))
        row.addWidget(self.open_btn)
        row.addStretch(1)
        card.body.addLayout(row)

        v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(root)
        outer.addWidget(scroll, 1)
        make_cfg_panel(self)
        dim_when_disabled(self.fetch_btn)

    # ------------------------------------------------------------------ #
    def _ui(self) -> dict:
        return self.store.data.setdefault("ui", {})

    def _default_text(self) -> str:
        """Bản mặc định đóng gói kèm app (dùng khi chưa tải được từ GitHub)."""
        try:
            from ...config import default_asset

            p = default_asset("readmore.html")
            if p:
                from pathlib import Path

                return Path(p).read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:      # noqa: BLE001
            pass
        return ""

    def _current_text(self) -> tuple[str, bool]:
        """(nội dung đang dùng, đã tải từ GitHub lần nào chưa)."""
        ui = self.store.data.get("ui") or {}
        txt = str(ui.get("readmore") or "").strip()
        return (txt, bool(ui.get("readmore_synced")))

    def reload(self) -> None:
        txt, synced = self._current_text()
        if not txt and not synced:
            txt = self._default_text()
        self.preview.setPlainText(txt)
        ui = self.store.data.get("ui") or {}
        when = str(ui.get("readmore_fetched_at") or "").strip()
        n = len(txt)
        if synced and when:
            self.status.setText(f"Đang dùng bản tải từ GitHub lúc {when} · {n} ký tự")
        elif synced:
            self.status.setText(f"Đang dùng bản tải từ GitHub · {n} ký tự")
        elif n:
            self.status.setText(f"Chưa tải từ GitHub — đang dùng bản mặc định kèm app · {n} ký tự")
        else:
            self.status.setText("Chưa có nội dung — bấm “Tải lại từ GitHub”.")

    # ------------------------------------------------------------------ #
    def fetch(self) -> None:
        """Tải lại nội dung từ GitHub (chạy nền, không treo giao diện)."""
        if self._worker is not None and self._worker.isRunning():
            return
        from ...config import READMORE_URL
        from ..workers import ReadMoreFetchWorker

        w = ReadMoreFetchWorker(READMORE_URL)
        self._worker = w
        self.fetch_btn.setEnabled(False)
        self.status.setText("Đang tải nội dung từ GitHub…")
        w.ok.connect(self._on_fetched)
        w.failed.connect(self._on_failed)

        def _done() -> None:
            self.fetch_btn.setEnabled(True)
            if self._worker is w:
                self._worker = None
            try:
                w.deleteLater()
            except Exception:      # noqa: BLE001
                pass

        w.finished.connect(_done)
        w.start()

    def _on_fetched(self, text: str) -> None:
        import datetime

        ui = self._ui()
        old = str(ui.get("readmore") or "").strip()
        ui["readmore"] = str(text or "")
        ui["readmore_synced"] = True
        ui["readmore_fetched_at"] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        try:
            self.store.save()
        except Exception:      # noqa: BLE001
            pass
        self.reload()
        self.changed.emit()
        if str(text or "").strip() == old:
            show_toast(self, "Nội dung “Đọc thêm” không đổi (đã là bản mới nhất)", 2600)
        else:
            show_toast(self, "Đã cập nhật nội dung “Đọc thêm” từ GitHub", 2600)

    def _on_failed(self, err: str) -> None:
        self.reload()
        self.status.setText(
            f"Không tải được từ GitHub ({str(err)[:90]}) — vẫn dùng nội dung đang có."
        )
        show_toast(self, "Không tải được file nội dung từ GitHub", 3200, ok=False)
