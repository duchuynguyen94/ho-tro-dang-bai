"""Trình chỉnh sửa ảnh trực tiếp: kéo trực tiếp logo thật, chỉnh kích thước, xoá nền."""
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
SRC = 1080


class DraggableImage(QLabel):
    """Ảnh (logo) kéo được + kéo góc để đổi kích thước (kiểu Canva)."""

    moved = Signal()
    resized = Signal(int)
    RESIZE_ZONE = 18

    def __init__(self, parent: QWidget, dashed: bool = False):
        super().__init__(parent)
        self.setCursor(Qt.OpenHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if dashed:
            self.setStyleSheet("border:1px dashed rgba(37,99,235,0.8);")
        self._press: QPoint | None = None
        self._start: QPoint | None = None
        self._mode = ""
        self._start_size = None
        self._src: QPixmap | None = None

        self.grip = QLabel(self)
        self.grip.setFixedSize(11, 11)
        self.grip.setStyleSheet("background:#2563eb;border-radius:3px;")
        self.grip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.grip.hide()

    def set_source(self, pm: QPixmap) -> None:
        self._src = pm

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.grip.move(max(0, self.width() - 11), max(0, self.height() - 11))
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        near = (pos.x() >= self.width() - self.RESIZE_ZONE
                and pos.y() >= self.height() - self.RESIZE_ZONE)
        self._mode = "resize" if near else "move"
        self._press = event.globalPosition().toPoint()
        self._start = self.pos()
        self._start_size = self.size()
        self.setCursor(Qt.SizeFDiagCursor if near else Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._mode or self._press is None or self._start is None:
            return
        delta = event.globalPosition().toPoint() - self._press
        if self._mode == "move":
            par = self.parentWidget()
            x = max(0, min(par.width() - self.width(), self._start.x() + delta.x()))
            y = max(0, min(par.height() - self.height(), self._start.y() + delta.y()))
            self.move(x, y)
            self.moved.emit()
            return
        # resize giữ tỉ lệ
        new_w = max(24, self._start_size.width() + delta.x())
        ratio = self._start_size.height() / max(1, self._start_size.width())
        new_h = max(12, int(new_w * ratio))
        self.setFixedSize(new_w, new_h)
        if self._src is not None and not self._src.isNull():
            self.setPixmap(self._src.scaled(new_w, new_h, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))
        self.move(self._start)
        self.resized.emit(new_w)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._mode = ""
        self._press = None
        self._start = None
        self.setCursor(Qt.OpenHandCursor)
        self.moved.emit()


class ImageEditorPanel(QFrame):
    """Panel chỉnh sửa ảnh: canvas (kéo logo thật) + điều khiển."""

    apply_opts = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("imgEditor")
        self._opts: dict = {}
        self._preview: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        self.title = QLabel("Trình sửa ảnh trực tiếp")
        self.title.setStyleSheet("font-weight:700;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.hint = QLabel("Kéo trực tiếp logo trên ảnh để đổi vị trí")
        self.hint.setObjectName("taskMeta")
        head.addWidget(self.hint)
        root.addLayout(head)

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

        self.logo_item = DraggableImage(self.canvas, dashed=True)
        self.brand_item = DraggableImage(self.canvas)
        self.logo_item.moved.connect(self._on_moved)
        self.brand_item.moved.connect(self._on_moved)
        self.logo_item.resized.connect(lambda w: self._on_resized("logo", w))
        self.brand_item.resized.connect(lambda w: self._on_resized("brand", w))
        self.logo_item.hide()
        self.brand_item.hide()
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
        self.footer_combo.addItems(["Hình 1", "Hình 2"])
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

        # cập nhật preview khi kéo size
        self.s_logo.valueChanged.connect(lambda _v: self._layout_items())
        self.s_brand.valueChanged.connect(lambda _v: self._layout_items())

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
    def load(self, preview: dict, opts: dict | None = None,
             footer_mode: str = "random", title: str = "") -> None:
        """preview = {background, logo, brand}; opts = tuỳ chọn hiện tại."""
        self._preview = dict(preview or {})
        self._opts = dict(opts or {})
        if title:
            self.title.setText(f"Trình sửa ảnh trực tiếp — {title}")

        # ảnh nền (đã ghép, KHÔNG có logo)
        bg = Path(self._preview.get("background", ""))
        if bg.exists():
            self.canvas.setPixmap(
                QPixmap(str(bg)).scaled(CANVAS, CANVAS, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self.canvas.setText("(chưa có ảnh)")

        self.s_product.setValue(int(float(self._opts.get("product_scale", 1.0)) * 100))
        self.s_logo.setValue(int(float(self._opts.get("logo_scale", 1.0)) * 100))
        self.s_brand.setValue(int(float(self._opts.get("brand_scale", 1.0)) * 100))
        self.s_wm.setValue(int(self._opts.get("watermark_opacity", 18) or 18))
        self.remove_bg.setChecked(bool(self._opts.get("remove_bg", False)))
        mode = self._opts.get("footer_mode") or footer_mode or "bar1"
        self.footer_combo.setCurrentIndex({"bar1": 0, "bar2": 1}.get(mode, 0))
        self._layout_items()

    def _logo_pixmap(self, path: str, base_w: float, scale: float) -> tuple[QPixmap, int, int]:
        p = Path(path or "")
        if not p.exists():
            return QPixmap(), 0, 0
        src = QPixmap(str(p))
        if src.isNull():
            return QPixmap(), 0, 0
        target_w = max(20, int(SRC * base_w * scale))
        disp_w = max(16, int(target_w * CANVAS / SRC))
        disp_h = max(10, int(disp_w * src.height() / max(1, src.width())))
        return src.scaled(disp_w, disp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation), disp_w, disp_h

    def _layout_items(self) -> None:
        logo_pm, lw, lh = self._logo_pixmap(
            self._preview.get("logo", ""), 0.26, self.s_logo.value() / 100.0)
        brand_pm, bw, bh = self._logo_pixmap(
            self._preview.get("brand", ""), 0.34, self.s_brand.value() / 100.0)

        for item, pm, w, h in ((self.logo_item, logo_pm, lw, lh),
                               (self.brand_item, brand_pm, bw, bh)):
            item.setPixmap(pm)
            item.set_source(pm)
            item.setFixedSize(max(1, w), max(1, h))
            item.setVisible(not pm.isNull())
            item.grip.setVisible(not pm.isNull())

        lp = self._opts.get("logo_pos") or [0.035, 0.035]
        bp = self._opts.get("brand_pos") or [0.965, 0.035]
        self.logo_item.move(int(lp[0] * CANVAS), int(lp[1] * CANVAS))
        self.brand_item.move(
            max(0, min(CANVAS - self.brand_item.width(), int(bp[0] * CANVAS) - self.brand_item.width())),
            int(bp[1] * CANVAS),
        )

    def _on_resized(self, which: str, width: int) -> None:
        base = (0.26 if which == "logo" else 0.34) * CANVAS
        scale = max(0.5, min(1.8, width / max(1.0, base)))
        slider = self.s_logo if which == "logo" else self.s_brand
        slider.blockSignals(True)
        slider.setValue(int(scale * 100))
        slider.blockSignals(False)
        self._opts["logo_scale" if which == "logo" else "brand_scale"] = round(scale, 3)

    def _on_moved(self) -> None:
        lp = self.logo_item.pos()
        bp = self.brand_item.pos()
        self._opts["logo_pos"] = [round(lp.x() / CANVAS, 4), round(lp.y() / CANVAS, 4)]
        self._opts["brand_pos"] = [
            round((bp.x() + self.brand_item.width()) / CANVAS, 4),
            round(bp.y() / CANVAS, 4),
        ]

    # ------------------------------------------------------------------ #
    def _reset(self) -> None:
        self._opts = {}
        self.s_product.setValue(100)
        self.s_logo.setValue(100)
        self.s_brand.setValue(100)
        self.s_wm.setValue(18)
        self.remove_bg.setChecked(False)
        self._layout_items()

    def _apply(self) -> None:
        self._on_moved()
        opts = dict(self._opts)
        opts.update({
            "product_scale": self.s_product.value() / 100.0,
            "logo_scale": self.s_logo.value() / 100.0,
            "brand_scale": self.s_brand.value() / 100.0,
            "watermark_opacity": self.s_wm.value(),
            "remove_bg": self.remove_bg.isChecked(),
            "footer_mode": ["bar1", "bar2"][self.footer_combo.currentIndex()],
        })
        self._opts = opts
        self.apply_opts.emit(opts)
