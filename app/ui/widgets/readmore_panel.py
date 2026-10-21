"""Panel “Chèn nội dung” (Cài đặt) — cấu hình khối “Đọc thêm”.

Khối này được chèn NGAY TRƯỚC <h2> ĐẦU TIÊN khi Auto format hoặc khi đăng bài.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..style import Card, dim_when_disabled, make_cfg_panel
from ..toast import show_toast


class ReadMorePanel(QWidget):
    """Ô textarea “Đọc thêm” + nút Lưu (lưu trong config.json -> ui.readmore)."""

    changed = Signal()

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._build()
        self.reload()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
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
            "Nội dung “Đọc thêm” sẽ được chèn vào bài <b>ngay sau thẻ &lt;/h1&gt;</b> "
            "(bài không có &lt;h1&gt; thì chèn ngay đầu nội dung).<br>"
            "Áp dụng khi bấm <b>Auto format</b> và khi <b>đăng bài</b>. "
            "Để trống = không chèn (và tự gỡ khối cũ)."
        )
        desc.setProperty("class", "sub")
        desc.setWordWrap(True)
        card.body.addWidget(desc)

        card.body.addWidget(QLabel("Nội dung “Đọc thêm”:"))
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(
            '<p>Đọc thêm về sản phẩm: <a href="https://…">tại đây</a></p>'
        )
        self.edit.setMinimumHeight(160)
        card.body.addWidget(self.edit)

        row = QHBoxLayout()
        self.save_btn = QPushButton("Lưu")
        self.save_btn.setProperty("class", "primary")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        self.reset_btn = QPushButton("Khôi phục đã lưu")
        self.reset_btn.setProperty("class", "ghost")
        self.reset_btn.clicked.connect(self.reload)
        row.addWidget(self.reset_btn)
        row.addStretch(1)
        card.body.addLayout(row)

        v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(root)
        outer.addWidget(scroll, 1)
        make_cfg_panel(self)
        dim_when_disabled(self.save_btn)

    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        try:
            txt = str(((self.store.data.get("ui") or {}).get("readmore") or ""))
        except Exception:      # noqa: BLE001
            txt = ""
        self.edit.setPlainText(txt)

    def _save(self) -> None:
        try:
            ui = self.store.data.setdefault("ui", {})
            ui["readmore"] = self.edit.toPlainText()
            self.store.save()
            self.changed.emit()
            show_toast(self, "Đã lưu nội dung “Đọc thêm”", 2200)
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Lỗi lưu: {str(exc)[:80]}", 3200, ok=False)
