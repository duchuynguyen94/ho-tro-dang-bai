"""Trình soạn thảo nội dung trực tiếp (kiểu TinyMCE thu gọn)."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCharFormat, QTextListFormat
from PySide6.QtWidgets import (
    QComboBox,
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


# Style Qt tự thêm khi serialize DOM -> bỏ đi, chỉ giữ định dạng NGƯỜI DÙNG đặt
_KEEP_STYLE = ("color", "background", "text-decoration", "font-style", "text-align",
               "vertical-align", "list-style")


def _clean_qt_html(html: str) -> str:
    """Bỏ rác do Qt tự thêm vào HTML (class/dir/lang + style mặc định của DOM)."""
    if not html:
        return html
    html = re.sub(r'\s(?:class|dir|lang|xmlns)="[^"]*"', "", html, flags=re.I)

    def _fix(m: re.Match) -> str:
        props = [p.strip() for p in m.group(1).split(";") if p.strip()]
        keep = [p for p in props if p.split(":")[0].strip() in _KEEP_STYLE]
        for p in props:
            name, _, val = p.partition(":")
            name, val = name.strip(), val.strip().lower()
            if name == "font-weight" and not re.match(r"(400|normal)", val):
                keep.append(p)                      # giữ đậm
            elif name == "font-size" and "medium" not in val:
                keep.append(p)                      # giữ cỡ chữ người dùng chọn
        return f' style="{"; ".join(dict.fromkeys(keep))}"' if keep else ""

    return re.sub(r'\sstyle="([^"]*)"', _fix, html)


class RichEditor(QWidget):
    """Soạn thảo HTML trực quan + chế độ xem/sửa HTML nguồn."""

    changed = Signal()          # nội dung đổi (để hiện/ẩn nút "Tạo JSON SEO")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("rteBar")
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(6, 6, 6, 6)
        tb.setSpacing(2)

        # hoàn tác / làm lại
        tb.addWidget(self._btn("↶", self._undo, "Hoàn tác"))
        tb.addWidget(self._btn("↷", self._redo, "Làm lại"))
        tb.addWidget(self._sep())

        # kiểu đoạn
        self.heading = QComboBox()
        self.heading.setObjectName("rteCombo")
        self.heading.addItems(["Đoạn", "Tiêu đề 1", "Tiêu đề 2", "Tiêu đề 3"])
        self.heading.setFixedWidth(104)
        self.heading.currentIndexChanged.connect(self._heading_changed)
        tb.addWidget(self.heading)
        from ..style import polish_combo

        polish_combo(self.heading)
        tb.addWidget(self._sep())

        # định dạng chữ
        tb.addWidget(self._btn("B", self._bold, "Đậm", bold=True))
        tb.addWidget(self._btn("I", self._italic, "Nghiêng", italic=True))
        tb.addWidget(self._btn("U", self._underline, "Gạch chân", underline=True))
        tb.addWidget(self._btn("S", self._strike, "Gạch ngang", strike=True))
        tb.addWidget(self._btn("⌫", self._clear_format, "Bỏ định dạng"))
        tb.addWidget(self._sep())

        # danh sách
        tb.addWidget(self._btn("•", lambda: self._list(QTextListFormat.ListDisc), "Danh sách chấm"))
        tb.addWidget(self._btn("1.", lambda: self._list(QTextListFormat.ListDecimal), "Danh sách số"))
        tb.addWidget(self._btn("⇤", lambda: self._indent(-1), "Giảm thụt lề"))
        tb.addWidget(self._btn("⇥", lambda: self._indent(1), "Tăng thụt lề"))
        tb.addWidget(self._sep())

        # căn lề
        tb.addWidget(self._btn("⬅", lambda: self._align(Qt.AlignLeft), "Căn trái"))
        tb.addWidget(self._btn("↔", lambda: self._align(Qt.AlignHCenter), "Căn giữa"))
        tb.addWidget(self._btn("➡", lambda: self._align(Qt.AlignRight), "Căn phải"))
        tb.addWidget(self._btn("☰", lambda: self._align(Qt.AlignJustify), "Căn đều"))
        tb.addWidget(self._sep())

        # chèn
        tb.addWidget(self._btn("Link", self._insert_link, "Chèn liên kết"))
        tb.addWidget(self._btn("Ảnh", self._insert_image, "Chèn ảnh (src)"))
        tb.addWidget(self._btn("Bảng", self._insert_table, "Chèn bảng"))
        tb.addWidget(self._btn("―", lambda: self.edit.insertHtml("<hr>"), "Đường kẻ ngang"))
        tb.addStretch(1)

        self.html_btn = self._btn("</> HTML", self._toggle_html, "Xem / sửa HTML")
        self.html_btn.setObjectName("tbBtnHtml")
        tb.addWidget(self.html_btn)
        v.addWidget(bar)

        # vùng soạn thảo
        self.edit = QTextEdit()
        self.edit.setObjectName("rteEdit")
        self.edit.setAcceptRichText(True)
        self.edit.setMinimumHeight(220)
        self.edit.textChanged.connect(self._update_status)
        self.edit.textChanged.connect(self.changed.emit)

        self.source = QPlainTextEdit()
        self.source.setObjectName("rteSource")
        self.source.setMinimumHeight(220)
        self.source.textChanged.connect(self._update_status)
        self.source.textChanged.connect(self.changed.emit)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.edit)
        self.stack.addWidget(self.source)
        v.addWidget(self.stack)

        self.status = QLabel("")
        self.status.setObjectName("rteStatus")
        v.addWidget(self.status)
        self._raw_html = ""          # HTML gốc (không qua Qt serialize)
        self._update_status()

    # ------------------------------------------------------------------ #
    def _btn(self, text: str, slot, tip: str = "", bold=False, italic=False,
             underline=False, strike=False) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("tbBtn")
        b.setToolTip(tip or text)
        b.setCursor(Qt.PointingHandCursor)
        style = ""
        if bold:
            style = "font-weight:800;"
        elif italic:
            style = "font-style:italic;"
        elif underline:
            style = "text-decoration:underline;"
        elif strike:
            style = "text-decoration:line-through;"
        if style:
            b.setStyleSheet(style)
        b.clicked.connect(slot)
        return b

    def _sep(self) -> QLabel:
        s = QLabel()
        s.setObjectName("tbSep")
        s.setFixedWidth(1)
        s.setFixedHeight(20)
        return s

    def _focus_rich(self) -> None:
        if self.stack.currentWidget() is not self.edit:
            self._toggle_html()

    # ---------------- hành động ---------------- #
    def _undo(self) -> None:
        self._focus_rich()
        self.edit.undo()

    def _redo(self) -> None:
        self._focus_rich()
        self.edit.redo()

    def _heading_changed(self, idx: int) -> None:
        if self.stack.currentWidget() is not self.edit:
            return
        cursor = self.edit.textCursor()
        cursor.beginEditBlock()
        fmt = cursor.blockFormat()
        fmt.setHeadingLevel(max(0, idx))
        cursor.setBlockFormat(fmt)
        cursor.endEditBlock()

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

    def _strike(self) -> None:
        self._focus_rich()
        cf = QTextCharFormat()
        cf.setFontStrikeOut(not self.edit.currentCharFormat().fontStrikeOut())
        self.edit.mergeCurrentCharFormat(cf)

    def _clear_format(self) -> None:
        self._focus_rich()
        self.edit.setCurrentCharFormat(QTextCharFormat())

    def _list(self, style) -> None:
        self._focus_rich()
        cursor = self.edit.textCursor()
        cursor.beginEditBlock()
        fmt = QTextListFormat()
        fmt.setStyle(style)
        cursor.createList(fmt)
        cursor.endEditBlock()

    def _indent(self, delta: int) -> None:
        self._focus_rich()
        cursor = self.edit.textCursor()
        cursor.beginEditBlock()
        fmt = cursor.blockFormat()
        fmt.setIndent(max(0, fmt.indent() + delta))
        cursor.setBlockFormat(fmt)
        cursor.endEditBlock()

    def _align(self, align) -> None:
        self._focus_rich()
        self.edit.setAlignment(align)

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

    def _insert_table(self) -> None:
        self._focus_rich()
        cursor = self.edit.textCursor()
        cursor.beginEditBlock()
        cursor.insertTable(3, 3)
        cursor.endEditBlock()

    def _toggle_html(self) -> None:
        if self.stack.currentWidget() is self.edit:
            # Nếu người dùng CHƯA sửa gì trong chế độ trực quan thì hiện ĐÚNG HTML gốc
            # (tránh Qt tự thêm style/font vào DOM khi serialize)
            if self.edit.document().isModified():
                self.source.setPlainText(self.get_html())
            else:
                self.source.setPlainText(self._raw_html)
            self.stack.setCurrentWidget(self.source)
            self.html_btn.setText("WYSIWYG")
        else:
            text = self.source.toPlainText()
            self._raw_html = text
            self.edit.setHtml(text)
            self.edit.document().setModified(False)
            self.stack.setCurrentWidget(self.edit)
            self.html_btn.setText("</> HTML")

    # ------------------------------------------------------------------ #
    def _update_status(self) -> None:
        text = self.get_text()
        self.status.setText(f"{len(text)} ký tự · {len(text.split())} từ")

    def get_html(self) -> str:
        if self.stack.currentWidget() is self.source:
            return self.source.toPlainText().strip()
        # Chưa sửa gì trong chế độ trực quan -> trả ĐÚNG HTML NGUYÊN BẢN (không serialize lại)
        if not self.edit.document().isModified():
            return self._raw_html.strip()
        raw = self.edit.toHtml()
        m = re.search(r"<body[^>]*>(.*?)</body>", raw, re.S | re.I)
        return _clean_qt_html((m.group(1) if m else raw).strip())

    def get_text(self) -> str:
        if self.stack.currentWidget() is self.source:
            return self.source.toPlainText()
        return self.edit.toPlainText()

    def set_html(self, html_text: str) -> None:
        self._raw_html = html_text or ""
        self.edit.setHtml(self._raw_html)
        self.edit.document().setModified(False)     # đánh dấu "chưa sửa" -> giữ HTML gốc
        self.source.setPlainText(self._raw_html)
        self.stack.setCurrentWidget(self.edit)
        self.html_btn.setText("</> HTML")
        self._update_status()
