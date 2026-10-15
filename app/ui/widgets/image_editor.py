"""Trình chỉnh sửa ảnh trực tiếp (kéo logo, chỉnh kích thước, xoá nền…)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

CANVAS = 380


class DragMarker(QLabel):
    """Ô đánh dấu kéo được trên canvas."""

    moved = Signal()

    def __init__(self, text: str, parent: QWidget, color: str, width: int = 64, height: int = 24):
        super().__init__(text, parent)
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.OpenHandCursor)
        self.setStyleSheet(
            f"background:rgba(255,255,255,0.75); border:2px dashed {color};"
            f"border-radius:5px; color:{color}; font-size:10px; font-weight:700;"
        )
        self._press: QPoint | None = None
        self._start: QPoint | None = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._start = self.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None or self._start is None:
            return
        delta = event.globalPosition().toPoint() - self._press
        pos = self._start + delta
        par = self.parentWidget()
        x = max(0, min(par.width() - self.width(), pos.x()))
        y = max(0, min(par.height() - self.height(), pos.y()))
        self.move(x, y)
        self.moved.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press = None
        self._start = None
        self.setCursor(Qt.OpenHandCursor)


class ImageEditorPanel(QFrame):
    """Panel chỉnh sửa ảnh: canvas + điều khiển."""

    apply_opts = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("imgEditor")
        self._opts: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        head = QLabel("Trình sửa ảnh trực tiếp")
        head.setStyleSheet("font-weight:700;")
        root.addWidget(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body)

        # ---------- canvas ----------
        left = QVBoxLayout()
        self.canvas = QLabel()
        self.canvas.setObjectName("imgCanvas")
        self.canvas.setFixedSize(CANVAS, CANVAS)
        self.canvas.setAlignment(Qt.AlignCenter)
        left.addWidget(self.canvas)

        self.logo_marker = DragMarker("Logo site", self.canvas, "#2563eb")
        self.brand_marker = DragMarker("Logo brand", self.canvas, "#16a34a", 76, 24)
        self.logo_marker.moved.connect(self._on_marker_moved)
        self.brand_marker.moved.connect(self._on_marker_moved)

        note = QLabel("Kéo ô xanh để đổi vị trí logo. Bấm “Lưu & áp dụng” để ghép lại ảnh.")
        note.setObjectName("taskMeta")
        note.setWordWrap(True)
        left.addWidget(note)
        body.addLayout(left)

        # ---------- điều khiển ----------
        right = QVBoxLayout()
        right.setSpacing(8)
        grid = QGridLayout()
        grid.setVerticalSpacing(10)

        self.s_product = self._slider(grid, 0, "Ảnh sản phẩm — kích thước", 50, 180, 100)
        self.s_logo = self._slider(grid, 1, "Logo website — kích thước", 50, 180, 100)
        self.s_brand = self._slider(grid, 2, "Logo thương hiệu — kích thước", 50, 180, 100)
        self.s_wm = self._slider(grid, 3, "Watermark — độ mờ", 0, 40, 18)
        right.addLayout(grid)

        self.remove_bg = QCheckBox("Xoá nền ảnh sản phẩm → trong suốt")
        right.addWidget(self.remove_bg)

        foot_row = QHBoxLayout()
        foot_row.addWidget(QLabel("Thanh thông tin:"))
        self.footer_combo = QComboBox()
        self.footer_combo.addItems(["Random (mặc định)", "Chỉ dùng hình 1", "Chỉ dùng hình 2"])
        foot_row.addWidget(self.footer_combo, 1)
        right.addLayout(foot_row)

        right.addStretch(1)
        actions = QHBoxLayout()
        reset = QPushButton("Đặt lại")
        reset.setProperty("class", "ghost")
        reset.clicked.connect(self._reset)
        apply_btn = QPushButton("Lưu && áp dụng")
        apply_btn.setProperty("class", "primary")
        apply_btn.clicked.connect(self._apply)
        actions.addWidget(reset)
        actions.addStretch(1)
        actions.addWidget(apply_btn)
        right.addLayout(actions)
        body.addLayout(right, 1)

        self._image_path = ""

    # ------------------------------------------------------------------ #
    def _slider(self, grid: QGridLayout, row: int, label: str,
                lo: int, hi: int, value: int) -> QSlider:
        lab = QLabel(label)
        val = QLabel(f"{value}%")
        val.setObjectName("taskMeta")
        val.setFixedWidth(46)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(value)
        sl.valueChanged.connect(lambda v, l=val: l.setText(f"{v}%"))
        grid.addWidget(lab, row, 0)
        grid.addWidget(sl, row, 1)
        grid.addWidget(val, row, 2)
        return sl

    # ------------------------------------------------------------------ #
    def load(self, image_path: str, opts: dict | None = None, footer_mode: str = "random") -> None:
        self._image_path = image_path or ""
        self._opts = dict(opts or {})
        self._show_image()
        self._apply_opts_to_widgets(footer_mode)

    def _apply_opts_to_widgets(self, footer_mode: str = "random") -> None:
        o = self._opts
        self.s_product.setValue(int(float(o.get("product_scale", 1.0)) * 100))
        self.s_logo.setValue(int(float(o.get("logo_scale", 1.0)) * 100))
        self.s_brand.setValue(int(float(o.get("brand_scale", 1.0)) * 100))
        self.s_wm.setValue(int(o.get("watermark_opacity", 18) or 18))
        self.remove_bg.setChecked(bool(o.get("remove_bg", False)))
        mode = o.get("footer_mode") or footer_mode or "random"
        self.footer_combo.setCurrentIndex({"random": 0, "bar1": 1, "bar2": 2}.get(mode, 0))
        self._place_markers()

    def _place_markers(self) -> None:
        lp = self._opts.get("logo_pos") or [0.035, 0.035]
        bp = self._opts.get("brand_pos") or [0.965, 0.035]
        self.logo_marker.move(int(lp[0] * CANVAS), int(lp[1] * CANVAS))
        self.brand_marker.move(
            max(0, int(bp[0] * CANVAS) - self.brand_marker.width()), int(bp[1] * CANVAS)
        )

    def _on_marker_moved(self) -> None:
        lp = self.logo_marker.pos()
        bp = self.brand_marker.pos()
        self._opts["logo_pos"] = [round(lp.x() / CANVAS, 4), round(lp.y() / CANVAS, 4)]
        self._opts["brand_pos"] = [
            round((bp.x() + self.brand_marker.width()) / CANVAS, 4),
            round(bp.y() / CANVAS, 4),
        ]

    def _show_image(self) -> None:
        p = Path(self._image_path)
        if p.exists():
            pm = QPixmap(str(p)).scaled(CANVAS, CANVAS, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.canvas.setPixmap(pm)
        else:
            self.canvas.setPixmap(QPixmap())
            self.canvas.setText("(chưa có ảnh)")

    # ------------------------------------------------------------------ #
    def _reset(self) -> None:
        self._opts = {}
        self._apply_opts_to_widgets()

    def _apply(self) -> None:
        self._on_marker_moved()
        opts = dict(self._opts)
        opts.update({
            "product_scale": self.s_product.value() / 100.0,
            "logo_scale": self.s_logo.value() / 100.0,
            "brand_scale": self.s_brand.value() / 100.0,
            "watermark_opacity": self.s_wm.value(),
            "remove_bg": self.remove_bg.isChecked(),
            "footer_mode": ["random", "bar1", "bar2"][self.footer_combo.currentIndex()],
        })
        self._opts = opts
        self.apply_opts.emit(opts)
