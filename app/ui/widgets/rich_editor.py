"""Trình soạn thảo nội dung trực tiếp (kiểu TinyMCE thu gọn)."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextListFormat
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class RichEditor(QWidget):
    """Soạn thảo HTML trực quan + chế độ xem/sửa HTML nguồn."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ---------------- thanh công cụ ----------------
        bar = QWidget()
        bar.setObjectName("rteBar")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(6, 6, 6, 6)
        tb.setSpacing(2)

        tb.addWidget(self._btn("H2", self._heading, "Tiêu đề mục"))
        tb.addWidget(self._sep())
        tb.addWidget(self._btn("B", self._bold, "Đậm", bold=True))
        tb.addWidget(self._btn("I", self._italic, "Nghiêng", italic=True))
        tb.addWidget(self._btn("U", self._underline, "Gạch chân", underline=True))
        tb.addWidget(self._sep())
        tb.addWidget(self._btn("• Danh sách", lambda: self._list(QTextListFormat.ListDisc), "Danh sách chấm"))
        tb.addWidget(self._btn("1. Danh sách", lambda: self._list(QTextListFormat.ListDecimal), "Danh sách số"))
        tb.addWidget(self._sep())
        tb.addWidget(self._btn("Chèn link", self._insert_link, "Chèn liên kết"))
        tb.addWidget(self._btn("Chèn ảnh", self._insert_image, "Chèn ảnh (src)"))
        tb.addStretch(1)
        self.html_btn = self._btn("</> HTML", self._toggle_html, "Xem / sửa HTML")
        self.html_btn.setObjectName("tbBtnHtml")
        tb.addWidget(self.html_btn)
        v.addWidget(bar)

        # ---------------- vùng soạn thảo ----------------
        self.edit = QTextEdit()
        self.edit.setObjectName("rteEdit")
        self.edit.setAcceptRichText(True)
        self.edit.setMinimumHeight(200)
        self.edit.textChanged.connect(self._update_status)

        self.source = QPlainTextEdit()
        self.source.setObjectName("rteSource")
        self.source.setMinimumHeight(200)
        self.source.textChanged.connect(self._update_status)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.edit)
        self.stack.addWidget(self.source)
        v.addWidget(self.stack)

        # ---------------- thanh trạng thái ----------------
        self.status = QLabel("")
        self.status.setObjectName("rteStatus")
        v.addWidget(self.status)
        self._update_status()

    # ------------------------------------------------------------------ #
    def _btn(self, text: str, slot, tip: str = "", bold=False, italic=False, underline=False) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("tbBtn")
        b.setToolTip(tip or text)
        b.setCursor(Qt.PointingHandCursor)
        if bold:
            b.setStyleSheet("font-weight:800;")
        elif italic:
            b.setStyleSheet("font-style:italic;")
        elif underline:
            b.setStyleSheet("text-decoration:underline;")
        b.clicked.connect(slot)
        return b

    def _sep(self) -> QLabel:
        s = QLabel()
        s.setObjectName("tbSep")
        s.setFixedWidth(1)
        s.setFixedHeight(20)
        return s

    # ------------------------------------------------------------------ #
    def _focus_rich(self) -> None:
        if self.stack.currentWidget() is not self.edit:
            self._toggle_html()

    def _bold(self) -> None:
        self._focus_rich()
        fmt = self.edit.currentCharFormat()
        self.edit.setFontWeight(QFont.Normal if fmt.fontWeight() > QFont.Normal else QFont.Bold)

    def _italic(self) -> None:
        self._focus_rich()
        self.edit.setFontItalic(not self.edit.currentCharFormat().fontItalic())

    def _underline(self) -> None:
        self._focus_rich()
        self.edit.setFontUnderline(not self.edit.currentCharFormat().fontUnderline())

    def _heading(self) -> None:
        self._focus_rich()
        cursor = self.edit.textCursor()
        cursor.insertHtml("<h2>Tiêu đề mục</h2><p><br/></p>")

    def _list(self, style) -> None:
        self._focus_rich()
        cursor = self.edit.textCursor()
        cursor.beginEditBlock()
        fmt = QTextListFormat()
        fmt.setStyle(style)
        cursor.createList(fmt)
        cursor.endEditBlock()

    def _insert_link(self) -> None:
        self._focus_rich()
        url, ok = QInputDialog.getText(self, "Chèn link", "Địa chỉ (URL):")
        if not ok or not url.strip():
            return
        url = url.strip()
        text, ok2 = QInputDialog.getText(self, "Chèn link", "Chữ hiển thị:", text=url)
        label = (text or url).strip() if ok2 else url
        self.edit.insertHtml(f'<a href="{url}">{label}</a>')

    def _insert_image(self) -> None:
        self._focus_rich()
        path, _ = QFileDialog.getOpenFileName(
            self, "Chèn ảnh", "", "Ảnh (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if path:
            self.edit.insertHtml(f'<img src="{path}" width="520" />')

    def _toggle_html(self) -> None:
        if self.stack.currentWidget() is self.edit:
            self.source.setPlainText(self.get_html())
            self.stack.setCurrentWidget(self.source)
            self.html_btn.setText("WYSIWYG")
        else:
            self.edit.setHtml(self.source.toPlainText())
            self.stack.setCurrentWidget(self.edit)
            self.html_btn.setText("</> HTML")

    # ------------------------------------------------------------------ #
    def _update_status(self) -> None:
        text = self.get_text()
        self.status.setText(f"{len(text)} ký tự · {len(text.split())} từ")

    def get_html(self) -> str:
        if self.stack.currentWidget() is self.source:
            return self.source.toPlainText().strip()
        raw = self.edit.toHtml()
        m = re.search(r"<body[^>]*>(.*?)</body>", raw, re.S | re.I)
        return (m.group(1) if m else raw).strip()

    def get_text(self) -> str:
        if self.stack.currentWidget() is self.source:
            return self.source.toPlainText()
        return self.edit.toPlainText()

    def set_html(self, html_text: str) -> None:
        self.edit.setHtml(html_text or "")
        self.source.setPlainText(self.get_html())
        self.stack.setCurrentWidget(self.edit)
        self.html_btn.setText("</> HTML")
        self._update_status()
