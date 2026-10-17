"""Trình chỉnh sửa ảnh trực tiếp: kéo logo + ảnh sản phẩm, resize 4 góc, xoá nền."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QMenu,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...images.composer import default_product_positions, product_box
from ..style import polish_combos

CANVAS = 400          # khung chỉnh sửa (ảnh đăng bài vẫn theo Cài đặt → AI ảnh)
SRC = 1080


class DraggableImage(QLabel):
    """Ảnh kéo được + kéo 4 góc để đổi kích thước (kiểu Canva)."""

    moved = Signal()
    resized = Signal(int)
    RESIZE_ZONE = 18

    def __init__(self, parent: QWidget, dashed: bool = False, kind: str = ""):
        super().__init__(parent)
        self.kind = kind          # product | upload | logo | brand
        self.index = 0
        self.on_remove_bg = None   # callback
        self.on_remove = None      # callback
        self.on_trim = None        # callback
        self.setCursor(Qt.OpenHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if dashed:
            self.setStyleSheet("border:1px dashed rgba(37,99,235,0.8);")
        self._base_style = "border:1px dashed rgba(37,99,235,0.8);" if dashed else ""
        self._selected = False
        self._press: QPoint | None = None
        self._start: QPoint | None = None
        self._mode = ""
        self._corner = ""
        self._start_size = None
        self._src: QPixmap | None = None

        self.grips = []
        for _ in range(4):
            g = QLabel(self)
            g.setFixedSize(11, 11)
            g.setStyleSheet("background:#2563eb;border-radius:3px;")
            g.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            g.hide()
            self.grips.append(g)
        self._grips_on = False       # có cho phép hiện tay nắm không
        self._hover = False
        self.setMouseTracking(True)

    def enable_grips(self, on: bool) -> None:
        self._grips_on = bool(on)
        self._update_grips()

    def _update_grips(self) -> None:
        show = self._grips_on and (self._hover or bool(self._mode))
        for g in self.grips:
            g.setVisible(show)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self._update_grips()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._update_grips()
        super().leaveEvent(event)

    def set_source(self, pm: QPixmap) -> None:
        self._src = pm

    def set_selected(self, on: bool) -> None:
        """Viền nét đứt để biết thành phần ĐANG CHỌN (để Ctrl+C)."""
        self._selected = bool(on)
        base = getattr(self, "_base_style", "")
        if on:
            self.setStyleSheet("border:2px dashed #1d4ed8;")
        else:
            self.setStyleSheet(base)

    def resizeEvent(self, event) -> None:  # noqa: N802
        w, h = self.width(), self.height()
        for g, (x, y) in zip(self.grips, [(0, 0), (w - 11, 0), (0, h - 11), (w - 11, h - 11)]):
            g.move(max(0, x), max(0, y))
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            self._mode = ""          # tránh kẹt trạng thái kéo
            self._press = None
            self._start = None
            super().mousePressEvent(event)   # để Qt hiện menu ngữ cảnh
            return
        pos = event.position().toPoint()
        w, h, z = self.width(), self.height(), self.RESIZE_ZONE
        corner = ""
        if pos.x() <= z and pos.y() <= z:
            corner = "tl"
        elif pos.x() >= w - z and pos.y() <= z:
            corner = "tr"
        elif pos.x() <= z and pos.y() >= h - z:
            corner = "bl"
        elif pos.x() >= w - z and pos.y() >= h - z:
            corner = "br"
        self._corner = corner
        self._mode = "resize" if corner else "move"
        self._press = event.globalPosition().toPoint()
        self._start = self.pos()
        self._start_size = self.size()
        if corner in ("tl", "br"):
            self.setCursor(Qt.SizeFDiagCursor)
        elif corner in ("tr", "bl"):
            self.setCursor(Qt.SizeBDiagCursor)
        else:
            self.setCursor(Qt.ClosedHandCursor)
        self._update_grips()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._mode or self._press is None or self._start is None:
            return
        delta = event.globalPosition().toPoint() - self._press
        par = self.parentWidget()
        if self._mode == "move":
            x = max(0, min(par.width() - self.width(), self._start.x() + delta.x()))
            y = max(0, min(par.height() - self.height(), self._start.y() + delta.y()))
            self.move(x, y)
            self.moved.emit()
            return
        sw, sh = self._start_size.width(), self._start_size.height()
        dx = delta.x() if self._corner in ("tr", "br") else -delta.x()
        ratio = sh / max(1, sw)
        new_w = max(24, sw + dx)
        new_h = max(12, int(new_w * ratio))
        if self._src is not None and not self._src.isNull():
            self.setPixmap(self._src.scaled(new_w, new_h, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))
        self.setFixedSize(new_w, new_h)
        nx, ny = self._start.x(), self._start.y()
        if self._corner in ("tl", "bl"):
            nx = self._start.x() + (sw - new_w)
        if self._corner in ("tl", "tr"):
            ny = self._start.y() + (sh - new_h)
        nx = max(0, min(par.width() - new_w, nx))
        ny = max(0, min(par.height() - new_h, ny))
        self.move(nx, ny)
        self.resized.emit(new_w)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        # chỉ áp dụng cho THÀNH PHẦN SẢN PHẨM (không áp cho logo/watermark/thanh thông tin)
        if self.kind not in ("product", "upload", "brand"):
            return
        menu = QMenu(self)
        act_bg = menu.addAction("Xoá nền → trong suốt")
        act_trim = menu.addAction("✂ Trim hình (cắt viền thừa)")
        menu.addSeparator()
        act_del = menu.addAction("Xoá thành phần này")
        chosen = menu.exec(event.globalPos())
        if chosen == act_bg and self.on_remove_bg:
            self.on_remove_bg(self)
        elif chosen == act_trim and self.on_trim:
            self.on_trim(self)
        elif chosen == act_del and self.on_remove:
            self.on_remove(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._mode = ""
        self._corner = ""
        self._press = None
        self._start = None
        self.setCursor(Qt.OpenHandCursor)
        self._update_grips()
        self.moved.emit()


class ImageEditorPanel(QFrame):
    """Panel chỉnh sửa ảnh: canvas (logo + ảnh sản phẩm) + điều khiển."""

    apply_opts = Signal(dict)
    changed = Signal()            # báo "canvas vừa đổi" -> cập nhật preview trong list ngay (0.2s)
    footer_changed = Signal(str)  # người dùng đổi select "thanh thông tin" -> dựng lại nền canvas NGAY
    request_upload = Signal()
    request_ai_edit = Signal()
    request_refetch = Signal()
    request_export = Signal()
    request_source_picker = Signal()
    request_trim = Signal(str, int)     # (loại thành phần, chỉ số)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("imgEditor")
        self._opts: dict = {}
        self._preview: dict = {}
        self._product_items: list[DraggableImage] = []
        self._upload_items: list[DraggableImage] = []
        self.wm_label = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        self.title = QLabel("Trình sửa ảnh trực tiếp")
        self.title.setStyleSheet("font-weight:700;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.hint = QLabel("Kéo ảnh để di chuyển · kéo 4 góc để đổi kích thước")
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
        self.canvas.setFocusPolicy(Qt.ClickFocus)      # bấm vào canvas -> nhận con trỏ (để dán ảnh)
        self.canvas.installEventFilter(self)           # bấm vào thành phần -> biết đang CHỌN cái nào
        self._sel_item = None
        left.addWidget(self.canvas)

        self.logo_item = DraggableImage(self.canvas, dashed=True, kind="logo")
        self.brand_item = DraggableImage(self.canvas, kind="brand")
        self.logo_item.moved.connect(self._on_moved)
        self.brand_item.moved.connect(self._on_moved)
        self.logo_item.resized.connect(lambda w: self._on_resized("logo", w))
        self.brand_item.resized.connect(lambda w: self._on_resized("brand", w))
        for it in (self.logo_item, self.brand_item):
            it.hide()
        body.addLayout(left)

        # ---------- điều khiển ----------
        right = QVBoxLayout()
        right.setSpacing(8)

        # hàng nút thao tác ảnh (3 nút cũ chuyển vào đây)
        tools = QHBoxLayout()
        up = QPushButton("Tải lên")
        up.setProperty("class", "ghost")
        up.clicked.connect(self.request_upload.emit)
        ai = QPushButton("Sửa bằng AI")
        ai.setProperty("class", "ghost")
        ai.clicked.connect(self.request_ai_edit.emit)
        self.ai_btn = ai
        src_btn = QPushButton("Hình tự tìm")
        src_btn.setProperty("class", "ghost")
        src_btn.setToolTip("Hiện danh sách ảnh lấy từ link nguồn — chọn 1 ảnh để chèn vào canvas")
        src_btn.clicked.connect(self.request_source_picker.emit)
        exp = QPushButton("Xuất hình")
        exp.setProperty("class", "ghost")
        exp.setToolTip("Xuất ảnh vào thư mục bài (theo Rule ảnh) và MỞ THƯ MỤC đó")
        exp.clicked.connect(self.request_export.emit)
        tools.addWidget(up)
        tools.addWidget(ai)
        tools.addWidget(src_btn)
        tools.addWidget(exp)
        reset = QPushButton("Đặt lại")
        reset.setProperty("class", "ghost")
        reset.clicked.connect(self._reset)
        tools.addWidget(reset)          # nằm ngay cạnh "Xuất hình"
        tools.addStretch(1)
        right.addLayout(tools)

        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        self.s_logo = self._slider(grid, 0, "Logo website — kích thước", 50, 300, 180)
        self.s_wm = self._slider(grid, 1, "Watermark — độ mờ", 0, 100, 15)
        self.s_wm_size = self._slider(grid, 2, "Watermark — kích thước", 50, 200, 85)
        self.s_wm_rot = self._slider(grid, 3, "Watermark — góc xoay", 0, 90, 50, suffix="°")
        right.addLayout(grid)

        foot_row = QHBoxLayout()
        foot_row.addWidget(QLabel("Thanh thông tin:"))
        self.footer_combo = QComboBox()
        self.footer_combo.addItems(["Hình 1", "Hình 2"])
        foot_row.addWidget(self.footer_combo, 1)
        right.addLayout(foot_row)

        right.addStretch(1)
        body.addLayout(right, 1)

        self.s_logo.valueChanged.connect(lambda _v: self._layout_items())

        # tự động lưu sau khi ngừng thao tác
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(500)       # chờ người dùng NGỪNG chỉnh 0.5s mới ghép lại
        self._quick = QTimer(self)            # cập nhật preview trong list sau 0.2s
        self._quick.setSingleShot(True)
        self._quick.setInterval(200)
        self._quick.timeout.connect(self.changed.emit)
        self._autosave.timeout.connect(self._emit_opts)
        for w in (self.s_logo, self.s_wm, self.s_wm_size, self.s_wm_rot):
            w.valueChanged.connect(self._schedule_save)
        # vẽ lại canvas NGAY khi kéo 3 thanh watermark (độ mờ / kích thước / góc xoay)
        for w in (self.s_wm, self.s_wm_size, self.s_wm_rot):
            w.valueChanged.connect(lambda _v: self._layout_watermark())
        self.footer_combo.currentIndexChanged.connect(self._on_footer_changed)
        polish_combos(self)

    def _on_footer_changed(self, _index: int) -> None:
        """Đổi select "thanh thông tin": dựng lại NỀN canvas NGAY, rồi mới tới preview."""
        if getattr(self, "_loading", False):
            return
        self._schedule_save()          # 0.2s -> preview trong list · 0.5s -> ghép file thật
        self.footer_changed.emit(["bar1", "bar2"][max(0, min(1, self.footer_combo.currentIndex()))])

    def eventFilter(self, obj, event):  # noqa: N802
        """Bấm vào thành phần trên canvas -> đánh dấu ĐANG CHỌN (để Ctrl+C copy)."""
        try:
            if obj is self.canvas and event.type() == QEvent.MouseButtonPress:
                w = self.canvas.childAt(event.pos())
                while w is not None and not isinstance(w, DraggableImage):
                    w = w.parentWidget()
                self._set_sel_item(w if isinstance(w, DraggableImage) else None)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _set_sel_item(self, item) -> None:
        old = getattr(self, "_sel_item", None)
        if old is item:
            return
        for it in (old, item):
            if it is not None:
                try:
                    it.set_selected(it is item)
                except Exception:
                    pass
        self._sel_item = item

    def copy_selected(self) -> dict | None:
        """Lấy thông tin thành phần ĐANG CHỌN để dán sang ảnh khác (Ctrl+C).

        Chỉ hỗ trợ "đối tượng hình ảnh" (ảnh chèn/dán hoặc ảnh nguồn).
        """
        it = getattr(self, "_sel_item", None)
        if it is None:
            return None
        kind = getattr(it, "kind", "")
        idx = int(getattr(it, "index", 0) or 0)
        if kind == "upload":
            ups = list(self._opts.get("uploads") or [])
            if idx < len(ups) and isinstance(ups[idx], dict):
                up = ups[idx]
                return {"path": up.get("path", ""), "scale": float(up.get("scale", 1.0) or 1.0),
                        "nobg": bool(up.get("nobg"))}
        elif kind == "product":
            prods = list(self._preview.get("products") or [])
            scales = list(self._opts.get("product_scales") or [])
            nobg = list(self._opts.get("product_nobg") or [])
            if idx < len(prods):
                return {"path": prods[idx],
                        "scale": float(scales[idx]) if idx < len(scales) else 1.0,
                        "nobg": bool(nobg[idx]) if idx < len(nobg) else False}
        return None

    def flush(self) -> None:
        """CHỐT NGAY phần vừa sửa (dùng trước khi đổi ảnh / đổi job).

        Trả về True nếu có thay đổi chưa ghép -> phát tín hiệu để ghép cho ĐÚNG ảnh đó.
        """
        if getattr(self, "_loading", False):
            return False
        pending = self._autosave.isActive() or self._quick.isActive()
        self._autosave.stop()
        self._quick.stop()
        if pending:
            self._emit_opts()
        return pending

    # ------------------------------------------------------------------ #
    def set_ai_enabled(self, on: bool) -> None:
        """Ẩn nút "AI sửa" khi cấu hình đang TẮT AI chỉnh ảnh."""
        self.ai_btn.setVisible(bool(on))

    # ------------------------------------------------------------------ #
    def _schedule_save(self, *_a) -> None:
        if getattr(self, "_emitting", False) or getattr(self, "_loading", False):
            return
        self._autosave.start()
        try:
            self._quick.start()          # 0.2s -> cập nhật preview trong list
        except Exception:
            pass

    def _slider(self, grid: QGridLayout, row: int, label: str,
                lo: int, hi: int, value: int, suffix: str = "%") -> QSlider:
        lab = QLabel(label)
        val = QLabel(f"{value}{suffix}")
        val.setObjectName("taskMeta")
        val.setFixedWidth(46)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(value)
        sl.valueChanged.connect(lambda v, l=val, su=suffix: l.setText(f"{v}{su}"))
        grid.addWidget(lab, row, 0)
        grid.addWidget(sl, row, 1)
        grid.addWidget(val, row, 2)
        return sl

    # ------------------------------------------------------------------ #
    def set_background(self, path: str) -> None:
        """Chỉ cập nhật ẢNH NỀN của canvas (không nạp lại toàn bộ trình sửa)."""
        bg = Path(str(path or ""))
        if bg.exists():
            self.canvas.setPixmap(
                QPixmap(str(bg)).scaled(CANVAS, CANVAS, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._preview["background"] = str(bg)

    def load(self, preview: dict, opts: dict | None = None,
             footer_mode: str = "random", title: str = "") -> None:
        self._preview = dict(preview or {})
        self._opts = dict(opts or {})
        if title:
            self.title.setText(f"Trình sửa ảnh trực tiếp — {title}")

        bg = Path(self._preview.get("background", ""))
        if bg.exists():
            self.canvas.setPixmap(
                QPixmap(str(bg)).scaled(CANVAS, CANVAS, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self.canvas.clear()
            self.canvas.setText("(chưa có ảnh)")

        # Chỉ NẠP giá trị — không tự động lưu/ghép lại ảnh khi mới chọn ảnh
        self._loading = True
        try:
            self.s_logo.setValue(int(float(self._opts.get("logo_scale", 1.8) or 1.8) * 100))
            self.s_wm.setValue(int(self._opts.get("watermark_opacity", 15) or 0))
            self.s_wm_size.setValue(int(float(self._opts.get("watermark_size", 0.85) or 0.85) * 100))
            self.s_wm_rot.setValue(int(float(self._opts.get("watermark_rotate", 50) or 50)))
            mode = self._opts.get("footer_mode") or footer_mode or "bar1"
            self.footer_combo.setCurrentIndex({"bar1": 0, "bar2": 1}.get(mode, 0))
        finally:
            self._loading = False
        self._layout_items()
        self._layout_products()
        self._layout_uploads()
        self._layout_watermark()

    # ---------------- logo ---------------- #
    @staticmethod
    def _fit_size(iw: int, ih: int, max_w: int, max_h: int) -> tuple[int, int]:
        """Giống composer._fit: vừa trong max_w × max_h (cho phép phóng to)."""
        if iw <= 0 or ih <= 0:
            return 0, 0
        ratio = min(max_w / iw, max_h / ih)
        return max(1, int(iw * ratio)), max(1, int(ih * ratio))

    def _composed_size(self, path: str, base_w: float, base_h: float,
                       scale: float) -> tuple[int, int]:
        p = Path(path or "")
        if not p.exists():
            return 0, 0
        src = QPixmap(str(p))
        if src.isNull():
            return 0, 0
        return self._fit_size(src.width(), src.height(),
                              int(SRC * base_w * scale), int(SRC * base_h * scale))

    def _pixmap_for(self, path: str, base_w: float, base_h: float, scale: float,
                    src: QPixmap | None = None) -> tuple[QPixmap, int, int]:
        if src is None:
            p = Path(path or "")
            if not p.exists():
                return QPixmap(), 0, 0
            src = QPixmap(str(p))
        if src is None or src.isNull():
            return QPixmap(), 0, 0
        cw, ch = self._fit_size(src.width(), src.height(),
                                int(SRC * base_w * scale), int(SRC * base_h * scale))
        if cw <= 0:
            return QPixmap(), 0, 0
        disp_w = max(8, int(cw * CANVAS / SRC))
        disp_h = max(8, int(ch * CANVAS / SRC))
        return src.scaled(disp_w, disp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation), disp_w, disp_h

    def _layout_items(self) -> None:
        logo_pm, lw, lh = self._pixmap_for(self._preview.get("logo", ""), 0.26, 0.12,
                                           self.s_logo.value() / 100.0)
        brand_path = self._preview.get("brand", "")
        brand_src = None
        if self._opts.get("brand_nobg") and brand_path:
            pm_nb = self._display_pixmap(brand_path, True)
            if pm_nb is not None and not pm_nb.isNull():
                brand_src = pm_nb
        brand_pm, bw, bh = self._pixmap_for(brand_path, 0.34, 0.13,
                                            float(self._opts.get("brand_scale", 1.0) or 1.0),
                                            brand_src)
        if self._opts.get("brand_hidden"):
            brand_pm, bw, bh = QPixmap(), 0, 0
        for item, pm, w, h in ((self.logo_item, logo_pm, lw, lh),
                               (self.brand_item, brand_pm, bw, bh)):
            item.setPixmap(pm)
            item.set_source(pm)
            item.setFixedSize(max(1, w), max(1, h))
            item.setVisible(not pm.isNull())
            item.enable_grips(not pm.isNull())
            item.on_remove_bg = self._ctx_remove_bg
            item.on_remove = self._ctx_remove_component
            item.on_trim = self._ctx_trim

        lp = self._opts.get("logo_pos") or [0.025, 0.018]
        bp = self._opts.get("brand_pos") or [0.955, 0.032]
        self.logo_item.move(int(lp[0] * CANVAS), int(lp[1] * CANVAS))
        self.brand_item.move(
            max(0, min(CANVAS - self.brand_item.width(), int(bp[0] * CANVAS) - self.brand_item.width())),
            int(bp[1] * CANVAS),
        )

    # ---------------- sản phẩm ---------------- #
    def _display_pixmap(self, path: str, nobg: bool):
        """QPixmap để hiển thị (xoá nền nếu cần) — có cache."""
        cache = getattr(self, "_nobg_cache", None)
        if cache is None:
            cache = self._nobg_cache = {}
        key = (path, bool(nobg))
        if key in cache:
            return cache[key]
        pm = QPixmap(path) if Path(path).exists() else QPixmap()
        if not pm.isNull() and nobg:
            try:
                from PIL import Image as _Img

                from ...images.composer import remove_background_auto

                img = _Img.open(path).convert("RGBA")
                img = remove_background_auto(img, 42)
                buf = str(Path(path).with_suffix("")) + "_nobg.png"
                img.save(buf)
                pm2 = QPixmap(buf)
                if not pm2.isNull():
                    pm = pm2
            except Exception:
                pass
        cache[key] = pm
        return pm

    def _raise_watermark(self) -> None:
        """Watermark luôn nằm TRÊN mọi thành phần khác."""
        if self.wm_label is not None:
            self.wm_label.raise_()

    def _layout_products(self) -> None:
        all_paths = list(self._preview.get("products") or [])
        hidden = set(self._opts.get("product_hidden") or [])
        keep = [k for k in range(len(all_paths)) if k not in hidden][:3]
        paths = [all_paths[k] for k in keep]
        nobg = list(self._opts.get("product_nobg") or [])
        for it in self._product_items:
            it.setParent(None)
            it.deleteLater()
        self._product_items = []

        if not paths:
            self._raise_watermark()
            return
        scale = 1.0
        scales = list(self._opts.get("product_scales") or [])
        positions = list(self._opts.get("product_pos") or [])
        if len(positions) < len(paths):
            positions += default_product_positions(len(paths), SRC, scale)[len(positions):]

        for i, path in enumerate(paths):
            sc = float(scales[i]) if i < len(scales) else scale
            box_i = product_box(SRC, sc)
            it = DraggableImage(self.canvas)
            it.index = i
            orig = keep[i] if i < len(keep) else i
            pm = self._display_pixmap(path, bool(nobg[orig]) if orig < len(nobg) else False)
            if pm.isNull():
                it.deleteLater()
                continue
            cw, ch = self._fit_size(pm.width(), pm.height(), box_i, box_i)
            dw = max(8, int(cw * CANVAS / SRC))
            dh = max(8, int(ch * CANVAS / SRC))
            pm = pm.scaled(dw, dh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            it.setPixmap(pm)
            it.set_source(pm)
            it.setFixedSize(pm.size())
            it.kind = "product"
            it.index = orig
            it.on_remove_bg = self._ctx_remove_bg
            it.on_remove = self._ctx_remove_component
            it.on_trim = self._ctx_trim
            it.show()
            it.enable_grips(True)
            it.moved.connect(self._on_product_moved)
            it.resized.connect(lambda w, idx=i: self._on_product_resized(idx, w))
            fx, fy = positions[i]
            it.move(max(0, min(CANVAS - it.width(), int(fx * CANVAS))),
                    max(0, min(CANVAS - it.height(), int(fy * CANVAS))))
            self._product_items.append(it)
        self._raise_watermark()

    # ---------------- thành phần tải lên (per-image) ---------------- #
    def _layout_uploads(self) -> None:
        ups = list(self._opts.get("uploads") or [])
        for it in self._upload_items:
            it.setParent(None)
            it.deleteLater()
        self._upload_items = []

        scale = 1.0
        for i, up in enumerate(ups):
            sc = float(up.get("scale", scale)) if isinstance(up, dict) else scale
            box_i = product_box(SRC, sc)
            path = up.get("path") if isinstance(up, dict) else str(up)
            pos = (up.get("pos") if isinstance(up, dict) else None) or [0.5, 0.5]
            it = DraggableImage(self.canvas)
            it.index = i
            pm = self._display_pixmap(path, bool(up.get("nobg")) if isinstance(up, dict) else False)
            if pm.isNull():
                it.deleteLater()
                continue
            cw, ch = self._fit_size(pm.width(), pm.height(), box_i, box_i)
            dw = max(8, int(cw * CANVAS / SRC))
            dh = max(8, int(ch * CANVAS / SRC))
            pm = pm.scaled(dw, dh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            it.setPixmap(pm)
            it.set_source(pm)
            it.setFixedSize(pm.size())
            it.kind = "upload"
            it.on_remove_bg = self._ctx_remove_bg
            it.on_remove = self._ctx_remove_component
            it.on_trim = self._ctx_trim
            it.show()
            it.enable_grips(True)
            it.moved.connect(self._on_upload_moved)
            it.resized.connect(lambda w, idx=i: self._on_upload_resized(idx, w))
            it.move(max(0, min(CANVAS - it.width(), int(pos[0] * CANVAS - it.width() / 2))),
                    max(0, min(CANVAS - it.height(), int(pos[1] * CANVAS - it.height() / 2))))
            it.raise_()
            self._upload_items.append(it)
        self._raise_watermark()

    def _on_upload_moved(self) -> None:  # noqa: D401
        ups = list(self._opts.get("uploads") or [])
        for i, it in enumerate(self._upload_items):
            if i < len(ups) and isinstance(ups[i], dict):
                ups[i]["pos"] = [round((it.x() + it.width() / 2) / CANVAS, 4),
                                 round((it.y() + it.height() / 2) / CANVAS, 4)]
        self._opts["uploads"] = ups
        self._schedule_save()

    def _on_upload_resized(self, index: int, width: int) -> None:
        ups0 = list(self._opts.get("uploads") or [])
        path = ""
        if index < len(ups0) and isinstance(ups0[index], dict):
            path = ups0[index].get("path", "")
        disp1 = self._disp_width_at_scale1(path)
        scale = max(0.3, min(2.5, width / max(1.0, disp1)))
        ups = list(self._opts.get("uploads") or [])
        if index < len(ups) and isinstance(ups[index], dict):
            ups[index]["scale"] = round(scale, 3)
        self._opts["uploads"] = ups
        self._on_upload_moved()

    # ---------------- watermark nằm TRÊN các thành phần ---------------- #
    def _layout_watermark(self) -> None:
        text = (self._preview.get("watermark") or "").strip()
        if self.wm_label is not None:
            self.wm_label.setParent(None)
            self.wm_label.deleteLater()
            self.wm_label = None
        if not text:
            return
        pm = QPixmap(CANVAS, CANVAS)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont()
        try:
            font.setFamilies(["Canva Sans", "Avenir Next", "Avenir", "Futura",
                              "Century Gothic", "Montserrat", "Arial", "Helvetica"])
        except Exception:
            font.setFamily("Arial")
        font.setBold(True)
        font.setPixelSize(max(6, int(60 * (self.s_wm_size.value() / 100) * CANVAS / SRC)))
        painter.setFont(font)
        alpha = max(0, min(255, int(self.s_wm.value() * 255 / 100)))
        painter.setPen(QColor(15, 23, 42, alpha))
        font.setPixelSize(max(6, int(60 * (self.s_wm_size.value() / 100) * CANVAS / SRC)))
        painter.setFont(font)
        painter.translate(CANVAS / 2, CANVAS / 2)
        painter.rotate(-self.s_wm_rot.value())    # góc xoay theo thanh điều khiển
        w = painter.fontMetrics().horizontalAdvance(text)
        painter.drawText(int(-w / 2), 0, text)
        painter.end()

        lab = QLabel(self.canvas)
        lab.setPixmap(pm)
        lab.setFixedSize(CANVAS, CANVAS)
        lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lab.move(0, 0)
        lab.show()
        lab.raise_()
        self.wm_label = lab

    def _ctx_remove_bg(self, item) -> None:
        """Xoá nền cho ĐÚNG thành phần đó."""
        if item.kind == "product":
            nobg = list(self._opts.get("product_nobg") or [])
            while len(nobg) <= item.index:
                nobg.append(False)
            nobg[item.index] = True
            self._opts["product_nobg"] = nobg
            self._layout_products()
        elif item.kind == "upload":
            ups = list(self._opts.get("uploads") or [])
            if item.index < len(ups) and isinstance(ups[item.index], dict):
                ups[item.index]["nobg"] = True
                self._opts["uploads"] = ups
                self._layout_uploads()
        elif item.kind == "brand":
            self._opts["brand_nobg"] = True
            self._layout_items()
        self._schedule_save()

    def _ctx_remove_component(self, item) -> None:
        """Xoá thành phần khỏi ảnh đang sửa."""
        if item.kind == "product":
            hidden = list(self._opts.get("product_hidden") or [])
            if item.index not in hidden:
                hidden.append(item.index)
            self._opts["product_hidden"] = hidden
            self._layout_products()
        elif item.kind == "upload":
            ups = list(self._opts.get("uploads") or [])
            if item.index < len(ups):
                ups.pop(item.index)
            self._opts["uploads"] = ups
            self._layout_uploads()
        elif item.kind == "brand":
            self._opts["brand_hidden"] = True
            self._layout_items()
        self._schedule_save()

    def _ctx_trim(self, item) -> None:
        """Cắt viền thừa của ảnh thành phần (trim)."""
        from ...images.composer import trim_borders

        if item.kind == "upload":
            ups = list(self._opts.get("uploads") or [])
            if item.index < len(ups) and isinstance(ups[item.index], dict):
                old = ups[item.index].get("path", "")
                new = trim_borders(old)
                if new and new != old:
                    ups[item.index]["path"] = new
                    self._opts["uploads"] = ups
                    self._layout_uploads()
                    self._schedule_save()
            return
        # sản phẩm / logo brand: báo lên trang để lưu vào kết quả công việc
        self.request_trim.emit(item.kind, int(item.index))

    def _on_product_moved(self) -> None:  # noqa: D401
        self._opts["product_pos"] = [
            [round(it.x() / CANVAS, 4), round(it.y() / CANVAS, 4)] for it in self._product_items
        ]
        self._schedule_save()

    def _disp_width_at_scale1(self, path: str) -> int:
        p = Path(path or "")
        if not p.exists():
            return 0
        src = QPixmap(str(p))
        if src.isNull():
            return 0
        cw, _ch = self._fit_size(src.width(), src.height(), product_box(SRC, 1.0),
                                 product_box(SRC, 1.0))
        return max(1, int(cw * CANVAS / SRC))

    def _on_product_resized(self, index: int, width: int) -> None:
        paths = list(self._preview.get("products") or [])
        disp1 = self._disp_width_at_scale1(paths[index] if index < len(paths) else "")
        scale = max(0.3, min(2.5, width / max(1.0, disp1)))
        scales = list(self._opts.get("product_scales") or [])
        while len(scales) < index + 1:
            scales.append(1.0)
        scales[index] = round(scale, 3)
        self._opts["product_scales"] = scales
        self._on_product_moved()

    # ---------------- chung ---------------- #
    def _on_resized(self, which: str, width: int) -> None:
        bw, bh = (0.26, 0.12) if which == "logo" else (0.34, 0.13)
        path = self._preview.get("logo" if which == "logo" else "brand", "")
        w1, _h1 = self._composed_size(path, bw, bh, 1.0)
        disp1 = max(1, int(w1 * CANVAS / SRC))
        hi = 3.0 if which == "logo" else 2.5
        scale = max(0.3, min(hi, width / max(1.0, disp1)))
        if which == "logo":
            self.s_logo.blockSignals(True)
            self.s_logo.setValue(int(scale * 100))
            self.s_logo.blockSignals(False)
        self._opts["logo_scale" if which == "logo" else "brand_scale"] = round(scale, 3)
        self._schedule_save()

    def _on_moved(self) -> None:  # noqa: D401
        lp = self.logo_item.pos()
        bp = self.brand_item.pos()
        self._opts["logo_pos"] = [round(lp.x() / CANVAS, 4), round(lp.y() / CANVAS, 4)]
        self._opts["brand_pos"] = [
            round((bp.x() + self.brand_item.width()) / CANVAS, 4),
            round(bp.y() / CANVAS, 4),
        ]
        self._schedule_save()

    def _reset(self) -> None:
        self._opts = {}
        self.s_logo.setValue(180)
        self.s_wm.setValue(15)
        self.s_wm_size.setValue(85)
        self.s_wm_rot.setValue(50)
        self._layout_items()
        self._layout_products()
        self._layout_uploads()
        self._layout_watermark()

    def _emit_opts(self) -> None:
        self._emitting = True
        self._on_moved()
        self._on_product_moved()
        self._on_upload_moved()
        opts = dict(self._opts)
        opts.update({
            "logo_scale": self.s_logo.value() / 100.0,
            "watermark_opacity": self.s_wm.value(),
            "watermark_size": self.s_wm_size.value() / 100.0,
            "watermark_rotate": self.s_wm_rot.value(),
            "footer_mode": ["bar1", "bar2"][self.footer_combo.currentIndex()],
        })
        self._opts = opts
        self.apply_opts.emit(opts)
        self._emitting = False

    def _apply(self) -> None:
        self._on_moved()
        self._on_product_moved()
        opts = dict(self._opts)
        opts.update({
            "logo_scale": self.s_logo.value() / 100.0,
            "watermark_opacity": self.s_wm.value(),
            "watermark_size": self.s_wm_size.value() / 100.0,
            "watermark_rotate": self.s_wm_rot.value(),
            "footer_mode": ["bar1", "bar2"][self.footer_combo.currentIndex()],
        })
        self._opts = opts
        self.apply_opts.emit(opts)
