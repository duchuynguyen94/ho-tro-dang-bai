"""Giao diện: màu sắc, style chung."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

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


def register_bundled_fonts() -> list[str]:
    """Nạp font đóng gói kèm app (Canva Sans) vào Qt. Trả về tên font đã nạp."""
    names: list[str] = []
    try:
        from ..config import app_assets_dir

        d = app_assets_dir() / "fonts"
        if not d.exists():
            return names
        for f in sorted(d.glob("*.ttf")) + sorted(d.glob("*.otf")):
            fid = QFontDatabase.addApplicationFont(str(f))
            if fid >= 0:
                names += QFontDatabase.applicationFontFamilies(fid)
    except Exception:
        pass
    return names


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
/* Menu chuột phải: mục KHÔNG chọn được -> xám mờ */
QMenu {{ background: #ffffff; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px 6px 14px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: #eff6ff; color: {ACCENT_DARK}; }}
QMenu::item:disabled {{ color: #b8c0cc; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
QMainWindow, #contentRoot {{ background: {BG}; }}

#titleBar {{ background: #111827; }}
#titleBar QLabel {{ color: #e5e7eb; font-weight: 600; }}

/* nút Cài đặt (răng cửa) ở góc phải trên thanh tiêu đề */
#gearBtn {{ background: transparent; border: none; border-radius: 8px; padding: 4px 6px; }}
#gearBtn:hover {{ background: rgba(255,255,255,0.12); }}
#gearBtn:checked {{ background: rgba(37,99,235,0.35); }}
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
#cardBody {{ background: #ffffff; border-radius: 10px; }}
/* Panel Cài đặt (AI nội dung, AI ảnh, Format Rule, Link tiêu đề, Cập nhật): nền #f1f5f9 */
QWidget#cfgPanel, QScrollArea#cfgPanel {{ background: #e8edf3; }}
QScrollArea#cfgPanel > QWidget {{ background: transparent; }}
QWidget#cfgInner {{ background: transparent; }}
/* vùng cuộn con bên trong: trong suốt (bỏ màu xám mặc định của Qt) */
QScrollArea#cfgScroll, QScrollArea#cfgScroll > QWidget,
QScrollArea#cfgScroll > QWidget > QWidget {{ background: transparent; }}

/* vùng cuộn panel kết quả: nền trong suốt (bỏ màu xám mặc định của Qt) */
QScrollArea#resultScroll, QScrollArea#resultScroll > QWidget,
QScrollArea#resultScroll > QWidget > QWidget {{ background: transparent; }}

QLabel.hint {{ color: {MUTED}; font-size: 11px; }}
QLabel.h2 {{ font-size: 18px; font-weight: 700; }}
QLabel.sub {{ color: {MUTED}; }}
/* Thanh cuộn: dễ nhận thấy (rãnh xám + con trượt đậm) */
QScrollBar:vertical {{ background: #e2e8f0; width: 10px; margin: 0; border: none; border-radius: 5px; }}
QScrollBar::handle:vertical {{ background: #94a3b8; min-height: 32px; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: #64748b; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; background: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background: #e2e8f0; height: 10px; margin: 0; border: none; border-radius: 5px; }}
QScrollBar::handle:horizontal {{ background: #94a3b8; min-width: 32px; border-radius: 5px; }}
QScrollBar::handle:horizontal:hover {{ background: #64748b; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; background: none; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ô tick cách chữ 8px (trước đây dính sát) */
QCheckBox {{ spacing: 5px; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background: #ffffff; border: 1px solid #cbd5e1; border-radius: 7px; padding: 7px 9px;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}

QComboBox {{ padding: 7px 30px 7px 10px; }}
QComboBox:hover {{ border: 1px solid #94a3b8; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
    width: 28px; border: none; background: transparent; }}
QComboBox::down-arrow {{ image: url("{ARROW}"); width: 11px; height: 11px; }}

/* Danh sách xổ xuống: nền trắng bo góc, item có hover + đang chọn rõ ràng */
QComboBox QAbstractItemView {{ background: #ffffff; border: 1px solid #cbd5e1;
    border-radius: 12px; padding: 7px; outline: none;
    selection-color: {ACCENT_DARK}; }}
QComboBox QAbstractItemView::item {{ padding: 9px 12px; border-radius: 8px;
    min-height: 22px; color: #1f2937; }}
QComboBox QAbstractItemView::item:hover {{ background: #f1f5f9; }}
QComboBox QAbstractItemView::item:selected {{ background: #eff6ff; color: {ACCENT_DARK}; font-weight: 600; }}

/* Khung popup (window riêng) — trong suốt để thấy viền bo của phần view */
#comboPopup {{ background: transparent; border: none; }}
#comboView {{ background: #ffffff; border: 1px solid #cbd5e1; border-radius: 12px;
    padding: 7px; outline: none; }}
#comboView::item {{ padding: 9px 12px; border-radius: 8px; min-height: 22px; color: #1f2937; }}
#comboView::item:hover {{ background: #f1f5f9; }}
#comboView::item:selected {{ background: #eff6ff; color: {ACCENT_DARK}; font-weight: 600; }}

/* Thanh cuộn trong danh sách xổ xuống (mảnh, bo tròn, không dùng thanh mặc định) */
QComboBox QAbstractItemView QScrollBar:vertical {{ background: transparent; width: 8px;
    margin: 4px 2px 4px 0; border: none; }}
QComboBox QAbstractItemView QScrollBar::handle:vertical {{ background: #cbd5e1;
    border-radius: 4px; min-height: 24px; }}
QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {{ background: #94a3b8; }}
QComboBox QAbstractItemView QScrollBar::add-line:vertical,
QComboBox QAbstractItemView QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
QComboBox QAbstractItemView QScrollBar::add-page:vertical,
QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{ background: transparent; }}

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
QFrame#imgBox {{ background: #ffffff; border: 1px solid {LINE}; border-radius: 0; }}
QFrame#imgBox[selected="true"] {{ border: 3px solid {ACCENT_DARK}; background: #dbeafe; }}
QFrame#srcTile {{ background: #ffffff; border: 1px solid {LINE}; border-radius: 8px; }}
QFrame#srcTile[selected="true"] {{ border: 2px solid {ACCENT}; background: #eff6ff; }}
QFrame#srcTile:disabled {{ background: #f8fafc; }}
QFrame#imgEditor {{ background: #f8fafc; border: 1px solid {LINE}; border-radius: 9px; }}
QLabel#imgCanvas {{ background: #ffffff; border: 1px dashed #b6c2d1; border-radius: 0; color: #94a3b8; }}
#rteBar {{ background: #f8fafc; border: 1px solid #cbd5e1; border-bottom: none;
    border-top-left-radius: 8px; border-top-right-radius: 8px; }}
QPushButton#tbBtn {{ background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 3px 7px; font-size: 12.5px; color: #334155; }}
QPushButton#tbBtn:hover {{ background: #e2e8f0; }}
QPushButton#tbBtnHtml {{ color: {ACCENT_DARK}; border-color: #bfdbfe; background: #eff6ff; font-weight: 700; }}
QComboBox#rteCombo {{ padding: 3px 22px 3px 8px; font-size: 12.5px; border-radius: 6px; }}
QComboBox#rteCombo::drop-down {{ width: 20px; }}
QComboBox#rteCombo::down-arrow {{ width: 10px; height: 10px; }}
QLabel#tbSep {{ background: {LINE}; }}
QLabel#rteStatus {{ background: #f8fafc; border: 1px solid #cbd5e1; border-top: none;
    border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; padding: 4px 8px;
    color: {MUTED}; font-size: 11px; }}
QTextEdit#rteEdit, QPlainTextEdit#rteSource {{ border: 1px solid #cbd5e1; border-top: none;
    border-bottom: none; border-radius: 0; }}
QPlainTextEdit#rteSource {{ font-family: Menlo, Consolas, monospace; font-size: 12px; }}
QLabel#imgThumb {{ background: #ffffff; border-radius: 0; color: #94a3b8; }}
QPushButton#imgDel {{ background: transparent; border: none; color: #94a3b8; font-weight: 700;
    font-size: 12px; }}
QPushButton#imgDel:hover {{ color: {RED}; background: #fef2f2; border-radius: 5px; }}
QPushButton#imgDel:disabled {{ color: #cbd5e1; }}

/* Danh sách công việc */
QFrame#taskRow {{ background: transparent; border: none; border-bottom: 1px solid {LINE};
    border-left: 3px solid transparent; }}
QFrame#taskRow:hover, QFrame#taskRow[hover="true"] {{ background: #eef2f7; }}
QFrame#taskRow[selected="true"] {{ background: #eff6ff; border-left: 3px solid {ACCENT}; }}
QFrame#taskRow[selected="true"]:hover,
QFrame#taskRow[selected="true"][hover="true"] {{ background: #e6efff; }}
QLabel#taskTitle {{ font-weight: 600; font-size: 12.5px; }}
QLabel#taskTitleBlank {{ font-weight: 600; font-size: 12.5px; color: #7c3aed; }}
QLabel#taskMeta {{ color: {MUTED}; font-size: 11px; }}
QLabel#taskDone {{ color: {GREEN}; font-size: 11px; font-weight: 700; }}
QLabel#taskInfoOk {{ color: {GREEN}; font-size: 11px; font-weight: 700; }}
QLabel#taskInfoMissing {{ color: {AMBER}; font-size: 11px; font-weight: 700; }}
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
/* nút bị khoá: làm mờ rõ ràng */
QPushButton:disabled {{ color: #b8c0cc; }}
QPushButton.ghost:disabled {{ background: #f8fafc; color: #b8c0cc; border-color: #e5e7eb; }}
QPushButton.green:disabled {{ background: #e2e8f0; color: #94a3b8; }}
QPushButton.danger:disabled {{ background: #f8fafc; color: #cbd5e1; border-color: #eef1f5; }}
QPushButton.primary:disabled {{ background: #eef1f5; color: #b8c0cc; }}
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

/* Trang Cài đặt → website: nền panel nhạt, vùng nội dung tab là khối TRẮNG bo 15px */
QWidget#sitePanel {{ background: #e8edf3; }}
QTabWidget::pane {{ border: none; background: #e8edf3; }}
QTabWidget > QStackedWidget {{ background: #e8edf3; }}
QScrollArea#siteTabScroll {{
    background: #ffffff; border: 1px solid {LINE}; border-radius: 15px;
}}
QScrollArea#siteTabScroll > QWidget,
QScrollArea#siteTabScroll > QWidget > QWidget {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: #64748b; padding: 8px 14px; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}

QLabel.badge {{ border-radius: 9px; padding: 2px 8px; font-size: 11px; font-weight: 700; }}
QLabel.warn {{ color: {RED}; background: #fef2f2; border: 1px solid #fecaca; border-radius: 7px; padding: 8px 10px; }}
QLabel.notice {{ color: {ACCENT_DARK}; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 7px; padding: 8px 10px; }}
"""


class _PopupWidthFilter(QObject):
    """Giữ bề rộng danh sách xổ xuống tối đa `max_w` (gọn như menu, không kéo dài hết ô)."""

    def __init__(self, parent, max_w: int = 420) -> None:
        super().__init__(parent)
        self.max_w = int(max_w)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        try:
            if event.type() in (QEvent.Show, QEvent.Resize) and obj.width() > self.max_w:
                obj.setFixedWidth(self.max_w)
        except Exception:      # noqa: BLE001
            pass
        return False


def polish_combo(combo) -> None:
    """Bo tròn + làm đẹp danh sách xổ xuống của QComboBox.

    Trên macOS khung popup là 1 cửa sổ riêng nên QSS không bo góc được —
    phải set cờ cửa sổ trong suốt cho popup.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox

    if not isinstance(combo, QComboBox):
        return
    try:
        view = combo.view()
        if view is None:
            return
        view.setObjectName("comboView")
        fm = combo.fontMetrics()
        longest = max([fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())] or [0])
        # GỌN: bề rộng vừa đủ theo mục dài nhất, tối đa 420px (không kéo dài hết ô)
        want = max(longest + 60, 200)
        view.setMinimumWidth(min(want, 420))
        try:
            view.setMaximumWidth(420)
        except Exception:      # noqa: BLE001
            pass
        frame = view.parentWidget()
        win = view.window()
        if frame is not None and frame is not win:
            frame.setObjectName("comboPopup")
            try:      # chừa lề để vẽ bóng đổ
                lay = frame.layout()
                if lay is not None:
                    lay.setContentsMargins(12, 12, 12, 12)
            except Exception:      # noqa: BLE001
                pass
        if win is not None:
            win.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            win.setAttribute(Qt.WA_TranslucentBackground, True)
        try:      # giới hạn bề rộng popup (Qt tự nới bằng bề rộng ô -> kéo lại 420px)
            target = frame if frame is not None else win
            if target is not None:
                flt = _PopupWidthFilter(combo, 420)
                target.installEventFilter(flt)
                combo._popup_filter = flt        # giữ tham chiếu
        except Exception:      # noqa: BLE001
            pass
        try:      # bóng đổ nhẹ cho danh sách xổ xuống
            from PySide6.QtGui import QColor
            from PySide6.QtWidgets import QGraphicsDropShadowEffect

            eff = QGraphicsDropShadowEffect(view)
            eff.setBlurRadius(20)
            eff.setOffset(0, 5)
            eff.setColor(QColor(15, 23, 42, 70))
            view.setGraphicsEffect(eff)
        except Exception:      # noqa: BLE001
            pass
        combo.setMaxVisibleItems(12)
    except Exception:
        pass


def polish_combos(root) -> None:
    """Áp polish_combo cho mọi QComboBox trong `root`."""
    from PySide6.QtWidgets import QComboBox

    if root is None:
        return
    for c in root.findChildren(QComboBox):
        polish_combo(c)


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
        hl.setContentsMargins(14, 11, 24, 11)      # lề phải: widget ở header thẳng hàng nội dung
        self.header_label = QLabel(title)
        hl.addWidget(self.header_label)
        hl.addStretch(1)
        self.header_layout = hl
        self._outer.addWidget(self.header)
        self.header.setVisible(bool(title))

        body = QWidget()
        body.setObjectName("cardBody")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(14, 6, 14, 14)      # padding-top body = 6px
        self.body.setSpacing(10)
        self._outer.addWidget(body, 1)
        self._body_widget = body

    def set_title(self, text: str) -> None:
        self.header_label.setText(text)
        self.header.setVisible(True)

    def add_header_widget(self, w: QWidget) -> None:
        self.header_layout.addWidget(w)


class _DimOnDisable(QObject):
    """Giữ nút ở trạng thái MỜ khi bị disabled (QSS không hỗ trợ opacity)."""

    def __init__(self, btn, opacity: float = 0.45) -> None:
        super().__init__(btn)
        self.btn = btn
        self.opacity = opacity
        self.eff = QGraphicsOpacityEffect(btn)
        self.eff.setOpacity(1.0)
        btn.setGraphicsEffect(self.eff)
        btn.installEventFilter(self)
        self._sync()

    def _sync(self) -> None:
        try:
            self.eff.setOpacity(self.opacity if not self.btn.isEnabled() else 1.0)
        except RuntimeError:
            pass

    def eventFilter(self, obj, ev):      # noqa: N802
        if ev.type() == QEvent.EnabledChange:
            self._sync()
        return False


def dim_when_disabled(btn, opacity: float = 0.45) -> None:
    """Nút sẽ MỜ đi khi bị disabled, sáng lại khi bật."""
    _DimOnDisable(btn, opacity)


def dim_all_buttons(root, opacity: float = 0.45) -> None:
    """Áp dụng cho mọi QPushButton trong 1 widget (dùng sau khi dựng UI)."""
    from PySide6.QtWidgets import QPushButton

    for b in root.findChildren(QPushButton):
        dim_when_disabled(b, opacity)

def make_cfg_panel(panel) -> None:
    """Panel Cài đặt: nền #f1f5f9 + mọi vùng cuộn bên trong trong suốt (hết #eeeeee)."""
    from PySide6.QtWidgets import QScrollArea

    try:
        panel.setAttribute(Qt.WA_StyledBackground, True)
    except Exception:
        pass
    panel.setObjectName("cfgPanel")
    if isinstance(panel, QScrollArea):
        # panel LÀ vùng cuộn (Format Rule / Sheets): widget con phải trong suốt
        inner = panel.widget()
        if inner is not None:
            inner.setAutoFillBackground(False)
            inner.setObjectName("cfgInner")
    else:
        for sa in panel.findChildren(QScrollArea):
            sa.setObjectName("cfgScroll")
