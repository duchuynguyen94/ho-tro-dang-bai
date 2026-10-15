"""Giao diện: màu sắc, style chung."""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
GREEN = "#16a34a"
RED = "#dc2626"
AMBER = "#b45309"
PANEL = "#111827"
BG = "#f8fafc"
LINE = "#e5e7eb"
MUTED = "#6b7280"
TEXT = "#111827"


def app_font() -> QFont:
    for name in ("Segoe UI", "Helvetica Neue", "Helvetica", "Arial"):
        if name in QFontDatabase.families():
            return QFont(name, 10)
    return QFont()


def _ensure_arrow() -> str:
    """Tạo mũi tên cho QComboBox (Qt QSS cần file ảnh)."""
    from PIL import Image, ImageDraw

    from ..config import app_data_dir

    d = app_data_dir() / "assets"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "arrow_down.png"
    if not p.exists():
        size = 48
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        dr.line([(12, 18), (24, 30), (36, 18)], fill=(51, 65, 85, 255), width=6, joint="curve")
        img.save(p)
    return p.as_posix()


ARROW = _ensure_arrow()


QSS = f"""
QWidget {{ color: {TEXT}; font-size: 13px; }}
QMainWindow, #contentRoot {{ background: {BG}; }}

#titleBar {{ background: #111827; }}
#titleBar QLabel {{ color: #e5e7eb; font-weight: 600; }}

#navBar {{ background: {PANEL}; }}
#navBar QPushButton {{
    background: transparent; color: #9ca3af; border: none;
    border-bottom: 3px solid transparent; padding: 12px 18px; font-weight: 600;
}}
#navBar QPushButton:hover {{ color: #e5e7eb; }}
#navBar QPushButton:checked {{ color: #ffffff; border-bottom: 3px solid {ACCENT}; }}

#card {{ background: #ffffff; border: 1px solid {LINE}; border-radius: 10px; }}
#cardHeader {{ border-bottom: 1px solid {LINE}; }}
#cardHeader QLabel {{ font-weight: 700; font-size: 13px; }}
#cardBody {{ background: #ffffff; }}

QLabel.hint {{ color: {MUTED}; font-size: 11px; }}
QLabel.h2 {{ font-size: 18px; font-weight: 700; }}
QLabel.sub {{ color: {MUTED}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background: #ffffff; border: 1px solid #cbd5e1; border-radius: 7px; padding: 7px 9px;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}

QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
    width: 26px; border: none; background: transparent; }}
QComboBox::down-arrow {{ image: url("{ARROW}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;
    padding: 4px; outline: none; selection-background-color: #eff6ff; selection-color: {ACCENT_DARK}; }}
QComboBox QAbstractItemView::item {{ padding: 6px 8px; border-radius: 6px; }}

QFrame#siteRow {{ background: #ffffff; border: 1px solid {LINE}; border-radius: 9px; }}
QFrame#siteRow[selected="true"] {{ background: #eff6ff; border: 1px solid {ACCENT}; }}
QLabel#rowTitle {{ font-weight: 600; font-size: 13px; }}
QLabel#chipGreen, QLabel#chipRed, QLabel#chipAmber, QLabel#chipGray, QLabel#chipBlue {{
    border-radius: 9px; padding: 1px 8px; font-size: 11px;
}}
QLabel#chipGreen {{ color: #047857; background: #ecfdf5; border: 1px solid #a7f3d0; }}
QLabel#chipRed   {{ color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; }}
QLabel#chipAmber {{ color: #b45309; background: #fff7ed; border: 1px solid #fed7aa; }}
QLabel#chipGray  {{ color: #475569; background: #f1f5f9; border: 1px solid #e2e8f0; }}
QLabel#chipBlue  {{ color: {ACCENT_DARK}; background: #eff6ff; border: 1px solid #bfdbfe; }}
QLabel#metaText  {{ color: {MUTED}; font-size: 11px; }}
QFrame#imgBox {{ background: #ffffff; border: 1px solid {LINE}; border-radius: 9px; }}
#rteBar {{ background: #f8fafc; border: 1px solid #cbd5e1; border-bottom: none;
    border-top-left-radius: 8px; border-top-right-radius: 8px; }}
QPushButton#tbBtn {{ background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 4px 9px; font-size: 12.5px; color: #334155; }}
QPushButton#tbBtn:hover {{ background: #e2e8f0; }}
QPushButton#tbBtnHtml {{ color: {ACCENT_DARK}; border-color: #bfdbfe; background: #eff6ff; font-weight: 700; }}
QLabel#tbSep {{ background: {LINE}; }}
QLabel#rteStatus {{ background: #f8fafc; border: 1px solid #cbd5e1; border-top: none;
    border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; padding: 4px 8px;
    color: {MUTED}; font-size: 11px; }}
QTextEdit#rteEdit, QPlainTextEdit#rteSource {{ border: 1px solid #cbd5e1; border-top: none;
    border-bottom: none; border-radius: 0; }}
QPlainTextEdit#rteSource {{ font-family: Menlo, Consolas, monospace; font-size: 12px; }}
QLabel#imgThumb {{ background: #f1f5f9; border-radius: 6px; color: #94a3b8; }}

/* Danh sách công việc */
QFrame#taskRow {{ background: transparent; border: none; border-bottom: 1px solid {LINE}; }}
QFrame#taskRow:hover {{ background: #f8fafc; }}
QFrame#taskRow[selected="true"] {{ background: #eff6ff; }}
QLabel#taskTitle {{ font-weight: 600; font-size: 12.5px; }}
QLabel#taskMeta {{ color: {MUTED}; font-size: 11px; }}
QLabel#taskUrl {{ color: #94a3b8; font-size: 10.5px; }}
QPushButton#taskDel {{ background: transparent; border: none; color: #94a3b8; font-weight: 700; }}
QPushButton#taskDel:hover {{ color: {RED}; background: #fef2f2; border-radius: 5px; }}
QLabel#warnMsg {{ color: {RED}; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 14px; }}
QPlainTextEdit#mono {{ font-family: Menlo, Consolas, monospace; font-size: 12px; }}
QProgressBar {{ background: #e2e8f0; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QPushButton.primary {{ background: {ACCENT}; color: #ffffff; border: none; border-radius: 7px; padding: 8px 14px; font-weight: 600; }}
QPushButton.primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton.primary:disabled {{ background: #e2e8f0; color: #94a3b8; }}
QPushButton.ghost {{ background: #ffffff; color: #334155; border: 1px solid #cbd5e1; border-radius: 7px; padding: 8px 12px; }}
QPushButton.ghost:hover {{ background: #f1f5f9; }}
QPushButton.green {{ background: {GREEN}; color: #ffffff; border: none; border-radius: 7px; padding: 8px 14px; font-weight: 600; }}
QPushButton.green:hover {{ background: #15803d; }}
QPushButton.danger {{ background: #ffffff; color: {RED}; border: 1px solid #fecaca; border-radius: 7px; padding: 8px 12px; }}
QPushButton.danger:hover {{ background: #fef2f2; }}
QPushButton#recordBtn {{ background: {RED}; color: #ffffff; border: none; border-radius: 7px; padding: 8px 14px; font-weight: 600; }}
QPushButton#recordBtn:hover {{ background: #b91c1c; }}

QListWidget {{ background: #ffffff; border: 1px solid {LINE}; border-radius: 10px; padding: 6px; }}
QListWidget::item {{ padding: 9px 10px; border-radius: 7px; }}
QListWidget::item:selected {{ background: #eff6ff; color: {ACCENT_DARK}; }}

#sideBar {{ background: #ffffff; border-right: 1px solid {LINE}; }}
#sideBar QPushButton {{ text-align: left; background: transparent; border: none; border-radius: 7px; padding: 8px 10px; }}
#sideBar QPushButton:hover {{ background: #f1f5f9; }}
#sideBar QPushButton:checked {{ background: #eff6ff; color: {ACCENT_DARK}; font-weight: 600; }}
#sideBar QLabel.section {{ color: #94a3b8; font-size: 10px; font-weight: 700; padding: 10px 8px 4px 8px; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: #64748b; padding: 8px 14px; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}

QStatusBar {{ background: #ffffff; color: {MUTED}; }}
QLabel.badge {{ border-radius: 9px; padding: 2px 8px; font-size: 11px; font-weight: 700; }}
QLabel.warn {{ color: {RED}; background: #fef2f2; border: 1px solid #fecaca; border-radius: 7px; padding: 8px 10px; }}
QLabel.notice {{ color: {ACCENT_DARK}; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 7px; padding: 8px 10px; }}
"""


class Card(QFrame):
    """Khung nội dung có tiêu đề (giống card trong mockup)."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("cardHeader")
        self.header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(14, 11, 14, 11)
        self.header_label = QLabel(title)
        hl.addWidget(self.header_label)
        hl.addStretch(1)
        self.header_layout = hl
        self._outer.addWidget(self.header)
        self.header.setVisible(bool(title))

        body = QWidget()
        body.setObjectName("cardBody")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(14, 14, 14, 14)
        self.body.setSpacing(10)
        self._outer.addWidget(body, 1)
        self._body_widget = body

    def set_title(self, text: str) -> None:
        self.header_label.setText(text)
        self.header.setVisible(True)

    def add_header_widget(self, w: QWidget) -> None:
        self.header_layout.addWidget(w)
