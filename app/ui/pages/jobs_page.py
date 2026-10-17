"""Màn hình 'Công việc đang làm'."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QPixmapCache, QDesktopServices, QDrag, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...storage.models import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_GENERATING,
    STATUS_LABELS,
    STATUS_QUEUED,
    STATUS_FINISH,
)
from ...config import output_dir
from ...images import compose, save_composed
from ..style import Card, polish_combos
from ..workers import _remove_bg_opts
from ..widgets.image_editor import ImageEditorPanel
from ..widgets.rich_editor import RichEditor
from ..toast import show_toast

STATUS_OBJECTS = {
    STATUS_QUEUED: "chipGray",
    STATUS_GENERATING: "chipAmber",
    STATUS_FINISH: "chipGreen",
    STATUS_ERROR: "chipRed",
}

MAX_IMAGES = 8      # số ảnh tối đa cho 1 bài (nút "+ Thêm hình")
THUMB_W = 152       # bề rộng mỗi khung ảnh (cố định, không giãn ra)
THUMB_H = 152

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")


def clipboard_image_path() -> str:
    """Lấy ảnh từ clipboard (ảnh copy từ web / máy tính) -> lưu vào media, trả về đường dẫn."""
    from datetime import datetime

    from ...config import media_dir

    cb = QApplication.clipboard()
    md = cb.mimeData()
    if md is None:
        return ""
    if md.hasImage():
        img = cb.image()
        if not img.isNull():
            d = media_dir()
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"dan_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            if img.save(str(p), "PNG"):
                return str(p)
    if md.hasUrls():
        for u in md.urls():
            lp = u.toLocalFile()
            if lp and Path(lp).suffix.lower() in IMAGE_EXTS:
                return lp
    return ""


class ThumbImage(QLabel):
    """Ảnh thumbnail: tự phóng đầy khung (cắt cạnh thừa)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("imgThumb")
        self.setMinimumWidth(80)
        self.setMinimumHeight(118)
        self.setAlignment(Qt.AlignCenter)
        self._src = None
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return max(80, w)      # ảnh vuông 1:1

    def set_source(self, pm) -> None:
        self._src = pm
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._rescale()
        super().resizeEvent(event)

    def _rescale(self) -> None:
        if self._src is None or self._src.isNull() or self.width() < 2 or self.height() < 2:
            return
        scaled = self._src.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                                  Qt.SmoothTransformation)
        x = max(0, (scaled.width() - self.width()) // 2)
        y = max(0, (scaled.height() - self.height()) // 2)
        self.setPixmap(scaled.copy(x, y, self.width(), self.height()))


class ThumbBox(QFrame):
    """Thumbnail ảnh: bấm để chọn sửa, KÉO để đổi thứ tự."""

    clicked = Signal(int)

    def __init__(self, index: int, parent=None) -> None:
        super().__init__(parent)
        self.index = index
        self.setObjectName("imgBox")
        self.setMinimumWidth(108)
        self.pic = None
        self._press = None
        self.setToolTip("Bấm để chỉnh sửa · kéo sang trái/phải để đổi thứ tự")

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.index))
        drag.setMimeData(mime)
        pm = self.grab()
        drag.setPixmap(pm.scaled(max(40, pm.width() // 2), max(40, pm.height() // 2),
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation))
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._press is not None:
            self._press = None
            self.clicked.emit(self.index)
        super().mouseReleaseEvent(event)


class ImagesBox(QWidget):
    """Hàng thumbnail ảnh — nhận kéo-thả để sắp xếp lại."""

    reordered = Signal(int, int)      # (từ vị trí, đến vị trí)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def _boxes(self) -> list[ThumbBox]:
        lay = self.layout()
        out: list[ThumbBox] = []
        if lay is None:
            return out
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, ThumbBox):
                out.append(w)
        return out

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        try:
            frm = int(event.mimeData().text())
        except (TypeError, ValueError):
            return
        boxes = self._boxes()
        if not boxes:
            return
        x = event.position().toPoint().x()
        to = len(boxes)
        for i, b in enumerate(boxes):
            if x < b.x() + b.width() / 2:
                to = i
                break
        if to > frm:
            to -= 1
        if 0 <= to < len(boxes) and to != frm:
            self.reordered.emit(frm, to)
        event.acceptProposedAction()


class TaskRow(QFrame):
    """1 dòng trong danh sách công việc (có nút xoá)."""

    clicked = Signal(str)
    delete = Signal(str)
    copied = Signal(str)

    def __init__(self, task, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("taskRow")
        self.task_id = task.id
        self.source_url = task.source_url or ""

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 8, 10)
        h.setSpacing(8)

        v = QVBoxLayout()
        v.setSpacing(3)

        is_blank = (getattr(task, "kind", "") or "") == "blank"
        url = QLabel(task.site_name if is_blank else (task.source_url or "(chưa có link)"))
        url.setObjectName("taskTitleDone" if task.status == STATUS_FINISH else "taskTitle")
        url.setWordWrap(True)
        v.addWidget(url)

        if not is_blank:                     # job trống: ẩn phần trạng thái
            label = STATUS_LABELS.get(task.status, task.status)
            if task.status == STATUS_ERROR and (task.message or "").strip():
                label = f"lỗi: {str(task.message).splitlines()[0][:70]}"   # hiện nội dung lỗi để soi
            meta = QLabel(f"{label}  ·  {task.site_name}")
            meta.setObjectName("taskMeta")
            v.addWidget(meta)

        if task.status == STATUS_GENERATING:
            bar = QProgressBar()
            bar.setRange(0, 0)
            bar.setTextVisible(False)
            bar.setFixedHeight(4)
            v.addWidget(bar)

        h.addLayout(v, 1)

        self.del_btn = QPushButton("✕")
        self.del_btn.setObjectName("taskDel")
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.setToolTip("Xoá công việc này")
        self.del_btn.clicked.connect(lambda: self.delete.emit(self.task_id))
        h.addWidget(self.del_btn, 0, Qt.AlignTop)

        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.task_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        act_copy = menu.addAction("Sao chép link nguồn")
        act_copy.setEnabled(bool(self.source_url))
        act_open = menu.addAction("Mở link nguồn")
        act_open.setEnabled(bool(self.source_url))
        menu.addSeparator()
        act_del = menu.addAction("Xoá công việc")

        chosen = menu.exec(event.globalPos())
        if chosen == act_copy and self.source_url:
            QApplication.clipboard().setText(self.source_url)
            self.copied.emit(self.source_url)
        elif chosen == act_open and self.source_url:
            QDesktopServices.openUrl(QUrl(self.source_url))
        elif chosen == act_del:
            self.delete.emit(self.task_id)


class JobsPage(QWidget):
    regenerate = Signal(object, str)         # (task, field)
    regenerate_images = Signal(object, str)  # (task, footer_mode)
    post = Signal(object)                    # (task)
    delete_task = Signal(str)                # task id
    ai_edit = Signal(object, int, str)       # (task, image index, yêu cầu chỉnh sửa)
    refetch_image = Signal(object, int)      # (task, image index) lấy lại ảnh sản phẩm
    recompose_image = Signal(object, int)    # (task, image index) ghép lại 1 ảnh
    recompose_all = Signal(object)           # (task) ghép lại TOÀN BỘ ảnh (sau thêm/xoá/sắp xếp)
    export_images = Signal(object)           # (task) xuất ảnh vào thư mục bài + mở thư mục
    trim_component = Signal(object, str, int)  # (task, loại thành phần, chỉ số) cắt viền ảnh
    stop_all = Signal()                        # dừng TẤT CẢ việc đang chờ / đang tạo
    apply_image_opts = Signal(object, int, dict)  # (task, chỉ số ảnh, tuỳ chọn)
    cancel_task = Signal(object)             # (task) dừng đang tạo

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.current = None
        self._posting: dict[str, bool] = {}      # task_id -> đang mở Chrome để đăng
        self._field_btns: list = []              # các nút "↻ Random" từng trường
        self._ai_busy = False
        self._posting_locked = False      # task_id -> đang mở Chrome để đăng
        self._rows: dict[str, TaskRow] = {}
        self._thumbs: list = []
        self._sel_index = 0
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        split = QSplitter(Qt.Horizontal)

        # ---------- danh sách việc ----------
        left = Card()
        left.setMinimumWidth(300)
        left.setMaximumWidth(420)
        left.set_title("Công việc đang làm")
        self.stop_all_btn = QPushButton("■ Dừng tất cả")
        self.stop_all_btn.setProperty("class", "danger")
        self.stop_all_btn.setToolTip("Dừng mọi việc đang chờ / đang tạo → chuyển thành \"chưa tạo\"")
        self.stop_all_btn.clicked.connect(self.stop_all.emit)
        left.add_header_widget(self.stop_all_btn)
        self.count_badge = QLabel("0")
        self.count_badge.setObjectName("chipBlue")
        left.add_header_widget(self.count_badge)

        self.tasks_scroll = QScrollArea()
        self.tasks_scroll.setWidgetResizable(True)
        self.tasks_scroll.setFrameShape(QFrame.NoFrame)
        self.tasks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.tasks_box = QVBoxLayout(holder)
        self.tasks_box.setContentsMargins(0, 0, 0, 0)
        self.tasks_box.setSpacing(0)
        self.tasks_box.addStretch(1)
        self.tasks_scroll.setWidget(holder)
        left.body.addWidget(self.tasks_scroll, 1)
        split.addWidget(left)

        # ---------- panel kết quả ----------
        right = Card("Kết quả AI")
        self.result_card = right
        self.provider_badge = QLabel("")
        self.provider_badge.setObjectName("chipGreen")
        right.add_header_widget(self.provider_badge)
        self.stack = QStackedWidget()
        right.body.addWidget(self.stack, 1)

        # 0: chưa chọn
        self.page_empty = QLabel("Chọn 1 công việc ở bên trái để xem / duyệt kết quả.")
        self.page_empty.setAlignment(Qt.AlignCenter)
        self.page_empty.setObjectName("taskMeta")
        self.stack.addWidget(self.page_empty)

        # 1: đang chạy
        self.page_loading = QWidget()
        lv = QVBoxLayout(self.page_loading)
        lv.addStretch(1)
        self.loading_label = QLabel("Đang gọi AI tạo nội dung…")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("font-size:14px;font-weight:600;")
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedHeight(6)
        self.loading_bar.setFixedWidth(320)
        lv.addWidget(self.loading_label, alignment=Qt.AlignHCenter)
        lv.addWidget(self.loading_bar, alignment=Qt.AlignHCenter)
        self.loading_note = QLabel("")
        self.loading_note.setObjectName("taskMeta")
        self.loading_note.setAlignment(Qt.AlignCenter)
        self.loading_note.setWordWrap(True)
        lv.addWidget(self.loading_note)
        self.stop_btn = QPushButton("■ Dừng")
        self.stop_btn.setProperty("class", "danger")
        self.stop_btn.clicked.connect(lambda: self.current and self.cancel_task.emit(self.current))
        lv.addWidget(self.stop_btn, alignment=Qt.AlignHCenter)
        lv.addStretch(1)
        self.stack.addWidget(self.page_loading)

        # 2: lỗi
        self.page_error = QWidget()
        ev = QVBoxLayout(self.page_error)
        ev.addStretch(1)
        self.error_label = QLabel("")
        self.error_label.setObjectName("warnMsg")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        ev.addWidget(self.error_label)
        retry = QPushButton("↻ Tạo lại")
        retry.setProperty("class", "primary")
        retry.setToolTip("Tạo lại nội dung bằng AI")
        retry.clicked.connect(self._on_retry)
        self.retry_btn = retry
        ev.addWidget(retry, alignment=Qt.AlignHCenter)
        ev.addStretch(1)
        self.stack.addWidget(self.page_error)

        # 3: kết quả
        self.editor = QWidget()
        self.editor.setObjectName("resultScrollInner")
        ev2 = QVBoxLayout(self.editor)
        ev2.setContentsMargins(0, 0, 0, 0)
        ev2.setSpacing(10)

        self.title_edit = QLineEdit()
        ev2.addLayout(self._field("Tiêu đề", self.title_edit))
        self.kw_edit = QLineEdit()
        ev2.addLayout(self._field("Focus keyword", self.kw_edit))
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setFixedHeight(62)
        ev2.addLayout(self._field("Description (mô tả SEO)", self.desc_edit))
        self.tags_edit = QLineEdit()
        ev2.addLayout(self._field("Search tags (cách nhau bởi dấu phẩy)", self.tags_edit))
        self.content_edit = RichEditor()
        ev2.addLayout(self._field("Nội dung (soạn thảo trực tiếp — chèn được link/ảnh & sửa HTML)",
                                  self.content_edit))

        img_head = QHBoxLayout()
        img_lab = QLabel("Ảnh")
        img_lab.setStyleSheet("font-weight:600;")
        img_head.addWidget(img_lab)
        img_head.addStretch(1)
        ev2.addLayout(img_head)

        self.images_box = ImagesBox()
        self.images_row = QHBoxLayout(self.images_box)
        self.images_row.setContentsMargins(0, 0, 0, 0)
        self.images_row.setSpacing(8)
        self.images_scroll = QScrollArea()
        self.images_scroll.setWidgetResizable(False)   # giữ đúng bề rộng khung -> cuộn ngang khi nhiều ảnh
        self.images_scroll.setFrameShape(QFrame.NoFrame)
        self.images_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.images_scroll.setFixedHeight(THUMB_H + 34)
        self.images_scroll.setWidget(self.images_box)
        ev2.addWidget(self.images_scroll)
        self.images_box.reordered.connect(self._reorder_images)

        self.add_img_btn = QPushButton("+ Thêm hình")
        self.add_img_btn.setProperty("class", "ghost")
        self.add_img_btn.setToolTip(
            "Thêm 1 ảnh TRỐNG (chỉ có logo site, logo brand, watermark, thanh thông tin).\n"
            "Bạn tự tải ảnh sản phẩm lên cho ảnh đó."
        )
        self.add_img_btn.clicked.connect(self._add_image)

        self.img_editor = ImageEditorPanel()
        self.img_editor.apply_opts.connect(self._apply_image_opts)
        self.img_editor.changed.connect(self._sync_thumb_from_canvas)
        self.img_editor.footer_changed.connect(self._on_footer_changed)
        self.img_editor.request_upload.connect(
            lambda: self._upload_image(getattr(self, "_sel_index", 0)))
        self.img_editor.request_ai_edit.connect(
            lambda: self._ai_edit(getattr(self, "_sel_index", 0)))
        self.img_editor.request_refetch.connect(
            lambda: self.current and self.refetch_image.emit(self.current,
                                                             getattr(self, "_sel_index", 0)))
        self.img_editor.request_export.connect(
            lambda: self.current and self.export_images.emit(self.current))
        self.img_editor.request_source_picker.connect(self._pick_source_image)
        self.img_editor.request_trim.connect(
            lambda kind, idx: self.current and self.trim_component.emit(self.current, kind, idx))
        ev2.addWidget(self.img_editor)

        # Ctrl/Cmd + V: dán ảnh (copy từ web hoặc máy tính) vào canvas
        # (dùng event filter toàn app để chắc chắn bắt được phím, không phụ thuộc focus)
        QApplication.instance().installEventFilter(self)

        ev2.addStretch(1)

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setObjectName("resultScroll")     # nền trong suốt (xem style.py)
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_scroll.setWidget(self.editor)
        self.stack.addWidget(self.editor_scroll)

        # footer luôn hiện khi có kết quả
        self.footer = QWidget()
        f = QHBoxLayout(self.footer)
        f.setContentsMargins(0, 8, 0, 0)
        self.regen_all_btn = QPushButton("↻ Random lại")
        self.regen_all_btn.setProperty("class", "ghost")
        self.regen_all_btn.setToolTip("Tạo lại toàn bộ nội dung (tiêu đề, từ khóa, mô tả, tags, nội dung)")
        self.regen_all_btn.clicked.connect(
            lambda: self.current and self.regenerate.emit(self.current, "")
        )
        f.addWidget(self.regen_all_btn)          # sát TRÁI (left = 0)
        self.check_label = QLabel("")
        self.check_label.setObjectName("taskMeta")
        f.addWidget(self.check_label)
        f.addStretch(1)                          # đẩy 2 nút kia sang PHẢI (right = 0)
        self.post_btn = QPushButton("OK — Đăng bài")
        self.post_btn.setProperty("class", "green")
        self.post_btn.clicked.connect(self._emit_post)
        f.addWidget(self.post_btn)
        right.body.addWidget(self.footer)
        self.footer.hide()

        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 900])
        outer.addWidget(split)
        polish_combos(self)

    def _field(self, label: str, widget: QWidget, field: str | None = None) -> QVBoxLayout:
        box = QVBoxLayout()
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setStyleSheet("font-weight:600;")
        row.addWidget(lab)
        row.addStretch(1)
        if field:
            btn = QPushButton("↻ Random")
            btn.setProperty("class", "ghost")
            btn.clicked.connect(lambda: self.current and self.regenerate.emit(self.current, field))
            row.addWidget(btn)
            self._field_btns.append(btn)      # để khoá khi ChatGPT đang bận
        box.addLayout(row)
        box.addWidget(widget)
        return box

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        tasks = self.store.tasks
        self.count_badge.setText(str(len(tasks)))
        busy = any(t.status in (STATUS_QUEUED, STATUS_GENERATING) for t in tasks)
        self.stop_all_btn.setEnabled(busy)
        self._ordered = list(reversed(tasks))

        while self.tasks_box.count() > 1:
            it = self.tasks_box.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()

        for t in self._ordered:
            row = TaskRow(t)
            row.clicked.connect(self.select_task)
            row.delete.connect(self._confirm_delete)
            row.copied.connect(lambda _u: show_toast(self, "Đã sao chép link nguồn"))
            self._rows[t.id] = row
            self.tasks_box.insertWidget(self.tasks_box.count() - 1, row)

        if not self._ordered:
            self.current = None
            self._show_state()
            return

        target_id = self.current.id if self.current else None
        if not target_id or target_id not in self._rows:
            if self.current is not None:
                # vừa tạo xong -> chọn việc mới nhất
                target_id = self._ordered[0].id
            else:
                target_id = self._ordered[0].id
        self.select_task(target_id)

    # ------------------------------------------------------------------ #
    # Đăng bài: mỗi công việc chỉ mở 1 Chrome, khoá nút để tránh bấm nhiều lần
    # ------------------------------------------------------------------ #
    def _emit_post(self) -> None:
        task = self.current
        if not task or self._posting.get(task.id):
            return                      # đang đăng rồi -> bỏ qua
        self.post.emit(task)

    def set_posting(self, task_id: str, busy: bool) -> None:
        """Đánh dấu công việc đang mở Chrome để đăng -> khoá + mờ nút."""
        if busy:
            self._posting[task_id] = True
        else:
            self._posting.pop(task_id, None)
        self._sync_post_btn()

    def is_posting(self, task_id: str) -> bool:
        return bool(self._posting.get(task_id))

    def _sync_post_btn(self) -> None:
        cur = getattr(self.current, "id", None)
        busy = bool(cur and self._posting.get(cur)) or bool(self._posting_locked)
        self.post_btn.setEnabled(not busy)
        self.post_btn.setText("Đang mở trình duyệt…" if busy else "OK — Đăng bài")

    def select_task(self, task_id: str) -> None:
        task = next((t for t in self.store.tasks if t.id == task_id), None)
        if not task:
            return
        self.current = task
        for tid, row in self._rows.items():
            row.set_selected(tid == task_id)
        self.result_card.set_title(f"Kết quả AI — {task.site_name}")
        active = self.store.ai_content.get("active", "")
        self.provider_badge.setText(f"Provider: {active}" if active else "")
        self._show_state()
        self._sync_post_btn()

    # chữ gốc / chữ khi ChatGPT đang bận
    _BUSY_TEXT = {
        "retry_btn": ("↻ Tạo lại", "có 1 công việc khác đang làm"),
        "regen_all_btn": ("↻ Random lại", "Random - có 1 công việc khác đang làm"),
    }

    def set_posting_locked(self, locked: bool) -> None:
        """Có 1 việc đang đăng bài -> khoá nút "OK — Đăng bài" của mọi job."""
        self._posting_locked = bool(locked)
        self.post_btn.setEnabled(not locked)
        if locked:
            self.post_btn.setToolTip("Đang có 1 việc đăng bài — chờ việc đó xong đã")
        else:
            self.post_btn.setToolTip("")

    def set_ai_busy(self, busy: bool) -> None:
        """ChatGPT đang chạy 1 việc -> khoá + đổi chữ các nút gọi AI (tạo lại / random)."""
        busy = bool(busy)
        self._ai_busy = busy
        tip = "Đang chạy 1 việc bằng ChatGPT — chờ việc đó xong đã" if busy else ""
        names = list(self._BUSY_TEXT.keys()) + ["_field_btns"]
        for name in names:
            if name == "_field_btns":
                btns = list(getattr(self, "_field_btns", []))
                for b in btns:
                    b.setEnabled(not busy)
                    if busy:
                        b.setToolTip(tip)
                continue
            b = getattr(self, name, None)
            if b is None:
                continue
            normal, busy_text = self._BUSY_TEXT[name]
            b.setText(busy_text if busy else normal)
            b.setEnabled(not busy)
            b.setToolTip(tip if busy else "")
        # nút "Đăng bài" không liên quan AI -> không đụng

    def set_loading_message(self, text: str) -> None:
        if self.current and self.current.status in (STATUS_QUEUED, STATUS_GENERATING):
            self.loading_note.setText(text)


    # ------------------------------------------------------------------ #
    def _show_state(self) -> None:
        task = self.current
        # mỗi lần hiển thị 1 job: xoá sạch message cũ (không để lẫn của job khác)
        self.loading_note.setText("")
        if task is None:
            self.footer.hide()
            self.stack.setCurrentWidget(self.page_empty)
            return

        if task.status == STATUS_QUEUED:
            # đang chờ tới lượt: KHÔNG có nút nào, KHÔNG hiện message của việc khác
            self.footer.hide()
            self.loading_label.setText(f"đang chờ tới lượt · {task.site_name}")
            self.loading_note.setText("")
            self.loading_bar.setVisible(False)
            self.stop_btn.setVisible(False)
            self.stack.setCurrentWidget(self.page_loading)
            return

        if task.status == STATUS_GENERATING:
            self.footer.hide()
            self.loading_label.setText(
                f"Đang tạo nội dung cho {task.site_name}…"
            )
            self.loading_bar.setVisible(True)
            self.stop_btn.setVisible(True)
            self.stack.setCurrentWidget(self.page_loading)
            return

        if task.status == STATUS_CANCELLED:
            self.footer.hide()
            self.error_label.setText(
                "<b>Đã dừng tạo nội dung.</b><br><br>"
                "<span style='color:#64748b'>Bấm “Thử tạo lại” nếu muốn chạy lại.</span>"
            )
            self.stack.setCurrentWidget(self.page_error)
            return

        if task.status == STATUS_ERROR:
            self.footer.hide()
            msg = task.message or "Lỗi không xác định."
            r = task.result or {}
            has_content = bool(r.get("content_html") or r.get("title"))
            stage = getattr(task, "error_stage", "") or ("post" if has_content else "content")
            low = msg.lower()
            missing_key = "thiếu api key" in low or ("api key" in low and "thiếu" in low)

            if stage == "post":
                # Lỗi ở bước ĐĂNG BÀI: việc đăng do người dùng tự bấm trên WordPress,
                # nên KHÔNG báo lỗi — vẫn hiện panel kết quả bình thường để họ tự kiểm tra.
                self.footer.show()
                self._load(task)
                return
            title = "Không tạo được nội dung."

            body = f"<b>{title}</b><br><br>{str(msg).replace(chr(10), '<br>')}"
            # CHỈ gợi ý khi provider thiếu API key; các lỗi khác chỉ báo lý do (đã lưu vào Log lỗi)
            if missing_key:
                body += ("<br><br><span style='color:#64748b'>Provider này chưa có API key — "
                         "vào Cài đặt → AI nội dung để dán key.</span>")
            self.error_label.setText(body)
            self.stack.setCurrentWidget(self.page_error)
            return

        self._load(task)

    def _on_retry(self) -> None:
        """Nút "Tạo lại": CHỈ tạo lại nội dung (không liên quan đăng bài)."""
        if not self.current:
            return
        self.regenerate.emit(self.current, "")

    def _load(self, task) -> None:
        """Hiển thị kết quả — có chốt an toàn: lỗi thì báo rõ, KHÔNG kẹt ở màn hình chờ."""
        try:
            self._load_inner(task)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            self.error_label.setText(
                "<b>Không hiển thị được kết quả.</b><br><br>"
                f"{type(exc).__name__}: {exc}"
                "<br><br><span style='color:#64748b'>Bấm “Thử tạo lại”, hoặc xem tab Log lỗi.</span>"
            )
            self.stack.setCurrentWidget(self.page_error)
            self.footer.show()

    def _load_inner(self, task) -> None:
        r = task.result or {}
        self.title_edit.setText(r.get("title", ""))
        self.kw_edit.setText(r.get("focus_keyword", ""))
        self.desc_edit.setPlainText(r.get("description", ""))
        self.tags_edit.setText(r.get("tags", ""))
        self.content_edit.set_html(r.get("content_html", ""))

        while self.images_row.count():
            it = self.images_row.takeAt(0)
            w = it.widget()
            if w is self.add_img_btn:
                continue                      # GIỮ LẠI nút "+ Thêm hình" (không xoá)
            if w:
                w.deleteLater()

        # xoá cache pixmap -> thumbnail đọc lại file ảnh MỚI từ đĩa (tránh ảnh cũ bị cache)
        try:
            QPixmapCache.clear()
        except Exception:
            pass

        images = r.get("images", [])
        self._thumbs = []
        for i, im in enumerate(images, 1):
            box = self._image_box(i, im, len(images) > 1)
            box.setFixedWidth(THUMB_W)
            self.images_row.addWidget(box, 0, Qt.AlignTop)
            self._thumbs.append(box)
        self.images_row.addStretch(1)
        self.images_row.addWidget(self.add_img_btn, 0, Qt.AlignTop)
        self.add_img_btn.setEnabled(len(images) < MAX_IMAGES)
        # giữ ĐÚNG bề rộng nội dung -> ít ảnh thì khung nhỏ gọn, nhiều ảnh thì cuộn ngang
        need_w = len(images) * (THUMB_W + 8) + 150 + 16
        self.images_box.setFixedWidth(max(260, need_w))
        self.images_box.setFixedHeight(THUMB_H + 34)

        if getattr(self, "_sel_index", 0) >= len(images):
            self._sel_index = 0
        self._refresh_preview(task)

        self.stack.setCurrentWidget(self.editor_scroll)
        self.footer.show()

    def _image_box(self, index: int, im: dict, can_delete: bool = True) -> ThumbBox:
        box = ThumbBox(index - 1)
        box.clicked.connect(self._select_image)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        pic = ThumbImage()
        box.pic = pic
        p = Path(im.get("path", ""))
        if p.exists():
            pm = QPixmap()
            try:                     # đọc lại bytes -> chắc chắn là ảnh MỚI
                pm.loadFromData(p.read_bytes())
            except Exception:
                pm = QPixmap(str(p))
            pic.set_source(pm)
        else:
            pic.setText("(chưa có ảnh)")
        bl.addWidget(pic)

        pad = QVBoxLayout()
        pad.setContentsMargins(8, 6, 8, 8)
        pad.setSpacing(6)
        bl.addLayout(pad)

        footer = im.get("footer") or ""
        tag = "#1" if "bar_1" in footer else ("#2" if "bar_2" in footer else "")
        cap_row = QHBoxLayout()
        cap_row.setContentsMargins(0, 0, 0, 0)
        cap_row.setSpacing(4)
        cap = QLabel(f"Ảnh {index}" + (f" · thanh TT {tag}" if tag else ""))
        cap.setObjectName("taskMeta")
        cap_row.addWidget(cap, 1)
        del_btn = QPushButton("✕")
        del_btn.setObjectName("imgDel")
        del_btn.setFixedSize(20, 20)
        del_btn.setToolTip("Xoá ảnh này")
        del_btn.setEnabled(bool(can_delete))
        del_btn.clicked.connect(lambda _=False, i=index - 1: self._delete_image(i))
        cap_row.addWidget(del_btn)
        pad.addLayout(cap_row)

        return box

    # ---------------- thêm / xoá / sắp xếp ảnh ---------------- #
    def _sync_image_meta(self, task) -> None:
        """Cập nhật số ảnh cho lần ghép lại — KHÔNG tự đổi thanh thông tin."""
        r = task.result or {}
        images = r.get("images") or []
        lst = list(r.get("image_opts_list") or [])
        while len(lst) < len(images):
            lst.append({})
        r["image_opts_list"] = lst
        task.image_count = max(1, len(images))

    def _footer_mode_of(self, task, index: int) -> str:
        """Thanh thông tin (bar1/bar2) ảnh ở vị trí `index` đang dùng.

        Thứ tự ưu tiên:
        1. Ảnh CÓ CHỌN THANH ở panel phải -> dùng ĐÚNG lựa chọn đó (cao nhất).
        2. Ảnh ĐÃ ghép -> theo thanh thật đang có trong ảnh (khớp với preview).
        3. Ảnh mới "+ Thêm hình" -> mặc định thanh 2.
        4. Còn lại -> quy tắc 1, 2, 2, 2, 2 (ảnh đầu thanh 1, các ảnh sau thanh 2).
        """
        from ..workers import _site_bars

        r = task.result or {}
        # 1) LỰA CHỌN Ở PANEL PHẢI = ưu tiên CAO NHẤT
        lst = r.get("image_opts_list") or []
        if 0 <= index < len(lst) and isinstance(lst[index], dict):
            m = lst[index].get("footer_mode")
            if m in ("bar1", "bar2"):
                return m
        # 2) ảnh đã ghép -> theo thanh thật trong ảnh
        site = self.store.get_site(task.site_id)
        bars = _site_bars(site) if site else []
        images = r.get("images") or []
        cur = str(images[index].get("footer", "") or "") if 0 <= index < len(images) else ""
        if cur:
            if len(bars) > 1 and cur == bars[1]:
                return "bar2"
            if bars and cur == bars[0]:
                return "bar1"
        # 3+4) mặc định: ảnh đầu thanh 1, các ảnh sau thanh 2
        return "bar1" if index == 0 else "bar2"

    def _add_image(self) -> None:
        if not self.current:
            return
        self._save()
        r = self.current.result
        images = list(r.get("images") or [])
        if len(images) >= MAX_IMAGES:
            show_toast(self, f"Tối đa {MAX_IMAGES} ảnh", 2200, ok=False)
            return
        # quy luật thanh thông tin: ảnh ĐẦU = thanh 1, các ảnh sau = thanh 2
        new_mode = "bar2" if images else "bar1"
        images.append({"path": "", "footer": ""})
        r["images"] = images
        lst = list(r.get("image_opts_list") or [])
        while len(lst) < len(images):
            lst.append({})
        # ảnh mới: ĐỂ TRỐNG (chỉ khung mẫu) — chờ người dùng tải ảnh lên
        lst[len(images) - 1] = {**lst[len(images) - 1],
                                "no_products": True, "footer_mode": new_mode}
        r["image_opts_list"] = lst
        self._sync_image_meta(self.current)
        self.store.upsert_task(self.current)
        self.store.save()
        self._sel_index = len(images) - 1
        self._load(self.current)
        self.recompose_all.emit(self.current)

    def _delete_image(self, index: int) -> None:
        if not self.current:
            return
        images = list((self.current.result or {}).get("images") or [])
        if len(images) <= 1:
            show_toast(self, "Phải giữ lại ít nhất 1 ảnh", 2200, ok=False)
            return
        if not (0 <= index < len(images)):
            return
        ans = QMessageBox.question(
            self, "Xoá ảnh", f"Xoá Ảnh {index + 1}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,        # Enter = Yes
        )
        if ans != QMessageBox.Yes:
            return
        self._save()
        r = self.current.result
        images = list(r.get("images") or [])
        if not (0 <= index < len(images)):
            return
        images.pop(index)
        r["images"] = images
        lst = list(r.get("image_opts_list") or [])
        if index < len(lst):
            lst.pop(index)
        r["image_opts_list"] = lst
        self._sync_image_meta(self.current)
        self.store.upsert_task(self.current)
        self.store.save()
        self._sel_index = max(0, min(self._sel_index, len(images) - 1))
        self._load(self.current)
        self.recompose_all.emit(self.current)

    def _reorder_images(self, frm: int, to: int) -> None:
        if not self.current or frm == to:
            return
        self._save()
        r = self.current.result
        images = list(r.get("images") or [])
        lst = list(r.get("image_opts_list") or [])
        while len(lst) < len(images):
            lst.append({})
        if not (0 <= frm < len(images)) or not (0 <= to < len(images)):
            return
        images.insert(to, images.pop(frm))
        lst.insert(to, lst.pop(frm))
        r["images"] = images
        r["image_opts_list"] = lst
        self._sync_image_meta(self.current)
        self.store.upsert_task(self.current)
        self.store.save()
        self._sel_index = to
        self._load(self.current)
        self.recompose_all.emit(self.current)

    def _ai_edit(self, index: int) -> None:
        if not self.current:
            return
        prompt, ok = QInputDialog.getText(
            self, "AI sửa ảnh",
            "Mô tả yêu cầu chỉnh sửa (ví dụ: xoá nền thành trong suốt, đổi nền trắng):",
        )
        if not ok or not (prompt or "").strip():
            return
        self.ai_edit.emit(self.current, index, prompt.strip())

    # ------------------------------------------------------------------ #
    def reload_thumbs(self) -> None:
        """Chỉ dựng lại DANH SÁCH ẢNH (thumbnail) — không nạp lại cả panel/trình sửa."""
        try:
            task = self.current
            if task is None:
                return
            r = task.result or {}
            images = r.get("images") or []
            if not images:
                return
            try:
                QPixmapCache.clear()
            except Exception:
                pass
            while self.images_row.count():
                it = self.images_row.takeAt(0)
                wd = it.widget()
                if wd is self.add_img_btn:
                    continue
                if wd:
                    wd.deleteLater()
            self._thumbs = []
            for i, im in enumerate(images, 1):
                box = self._image_box(i, im, len(images) > 1)
                box.setFixedWidth(THUMB_W)
                self.images_row.addWidget(box, 0, Qt.AlignTop)
                self._thumbs.append(box)
            self.images_row.addStretch(1)
            self.images_row.addWidget(self.add_img_btn, 0, Qt.AlignTop)
            self.add_img_btn.setEnabled(len(images) < MAX_IMAGES)
        except Exception:
            traceback.print_exc()

    def _select_image(self, index: int) -> None:
        self._sel_index = index
        if self.current:
            self._refresh_preview(self.current)

    def _build_preview(self, task, index: int, mode_override: str = "") -> dict:
        site = self.store.get_site(task.site_id)
        r = task.result or {}
        images = r.get("images") or []
        footer = str(images[index].get("footer", "") or "") if index < len(images) else ""
        lst = r.get("image_opts_list") or []
        opts = dict(lst[index]) if index < len(lst) else (r.get("image_opts") or {})
        # Lựa chọn ở PANEL PHẢI (hoặc vừa đổi) = ưu tiên CAO NHẤT -> dựng nền theo lựa chọn đó
        explicit = mode_override or (opts.get("footer_mode")
                                     if opts.get("footer_mode") in ("bar1", "bar2") else "")
        if explicit:
            footer = ""
        if not footer and site:
            # ảnh chưa có thanh thông tin -> dùng thanh theo QUY TẮC (ảnh 1 -> thanh 1, sau -> thanh 2)
            from ..workers import _site_bars
            bars = _site_bars(site)
            mode = explicit or self._footer_mode_of(task, index)
            if bars:
                footer = bars[1] if (mode == "bar2" and len(bars) > 1) else bars[0]
        remove_bg, th = _remove_bg_opts(self.store)
        from ...config import default_asset

        base = compose(
            size=1080,
            site_logo="", brand_logo="",
            products=[],
            footer_bar=footer,
            frame="",
            watermark="",     # watermark vẽ riêng để luôn nằm trên thành phần
            watermark_opacity=0,
            remove_bg=remove_bg,
            remove_bg_thresh=th,
            product_scale=float(opts.get("product_scale", 1.0) or 1.0),
        )
        out = output_dir() / f"preview_{task.id}_{index + 1}.png"
        save_composed(base, str(out))
        return {
            "background": str(out),
            "logo": (site.logo_path or default_asset("logo.png")) if site else "",
            "brand": (r.get("brand_logo")
                      or str(getattr(task, "brand_logo_fallback", "") or "")),
            "products": [] if opts.get("no_products") else
                        [p for p in (r.get("product_images") or []) if p],
            "watermark": (site.watermark_text if site else ""),
        }

    def _refresh_preview(self, task) -> None:
        r = task.result or {}
        images = r.get("images") or []
        idx = getattr(self, "_sel_index", 0)
        for box in getattr(self, "_thumbs", []):
            box.set_selected(box.index == idx)
        title = f"Ảnh {idx + 1}" if images else ""
        lst = r.get("image_opts_list") or []
        opts_i = dict(lst[idx]) if idx < len(lst) else (r.get("image_opts") or {})
        preview = self._build_preview(task, idx) if images and self.store.get_site(task.site_id) else {}
        self.img_editor.set_ai_enabled((self.store.ai_image or {}).get("active") != "off")
        # thanh thông tin: select phản ánh ĐÚNG thanh đang có trong ảnh
        # job trống: không chạy AI -> ẩn nút Random lại
        self.regen_all_btn.setVisible((getattr(task, "kind", "") or "") != "blank")
        self.img_editor.load(preview, opts_i, self._footer_mode_of(task, idx), title)

    def _on_footer_changed(self, mode: str) -> None:
        """Đổi select "thanh thông tin": lưu lựa chọn + dựng lại NỀN canvas NGAY.

        Thứ tự: canvas đổi TRƯỚC -> 0.2s sau preview trong danh sách -> 2s sau ghép file ảnh thật.
        """
        if not self.current:
            return
        idx = getattr(self, "_sel_index", 0)
        r = self.current.result if isinstance(self.current.result, dict) else {}
        lst = list(r.get("image_opts_list") or [])
        while len(lst) <= idx:
            lst.append({})
        if isinstance(lst[idx], dict):
            lst[idx] = {**lst[idx], "footer_mode": mode}
        r["image_opts_list"] = lst
        try:
            self.store.upsert_task(self.current)   # lưu ngay -> nạp lại panel vẫn giữ lựa chọn
            self.store.save()
        except Exception:
            pass
        try:
            prev = self._build_preview(self.current, idx, mode)
            if prev.get("background"):
                self.img_editor.set_background(prev["background"])
        except Exception:
            pass

    def _sync_thumb_from_canvas(self) -> None:
        """Chụp canvas -> cập nhật preview trong danh sách ảnh (nhanh, không cần worker)."""
        try:
            idx = self._sel_index
            if not (0 <= idx < len(self._thumbs)):
                return
            pm = self.img_editor.canvas.grab()
            box = self._thumbs[idx]
            pic = getattr(box, "pic", None)
            if pic is not None and not pm.isNull():
                pic.set_source(pm)
        except Exception:
            pass

    def _apply_image_opts(self, opts: dict) -> None:
        if self.current:
            self.apply_image_opts.emit(self.current, getattr(self, "_sel_index", 0), opts)

    def _regen_images(self) -> None:
        if not self.current:
            return
        mode = ["random", "bar1", "bar2"][self.footer_combo.currentIndex()]
        self.current.footer_mode = mode
        self.regenerate_images.emit(self.current, mode)

    def _upload_image(self, index: int) -> None:
        """Chọn NHIỀU ảnh từ máy -> thêm vào canvas thành các thành phần."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Chọn ảnh (chọn được nhiều ảnh)", "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
        if not paths:
            return
        self._add_upload_components(paths, index)

    def _paste_clipboard_image(self) -> None:
        """Ctrl/Cmd + V: dán ảnh copy từ web/máy tính vào canvas như thành phần tải lên."""
        if not self.isVisible() or not self.current:
            return
        path = clipboard_image_path()
        if not path:
            show_toast(self, "Clipboard không có ảnh", 2400, ok=False)
            return
        self._add_upload_component(path, getattr(self, "_sel_index", 0))
        show_toast(self, "Đã dán ảnh vào canvas", 1800)

    @staticmethod
    def _is_text_widget(w) -> bool:
        if isinstance(w, (QLineEdit, QPlainTextEdit)):
            return True
        return w is not None and w.inherits("QTextEdit")

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Ctrl/Cmd+V: dán ảnh vào canvas của hình ĐANG CHỌN để chỉnh sửa.

        Ở ô nhập liệu (Tiêu đề / Nội dung…) thì để widget tự dán text như bình thường.
        """
        try:
            if event.type() == QEvent.KeyPress and event.matches(QKeySequence.Paste):
                fw = QApplication.focusWidget()
                if self._is_text_widget(fw):
                    return False
                if self.isVisible() and self.current:
                    if clipboard_image_path():
                        self._paste_clipboard_image()
                        return True
        except Exception:      # noqa: BLE001
            traceback.print_exc()
        return super().eventFilter(obj, event)

    def _pick_source_image(self) -> None:
        """Popup: chọn 1 ảnh từ link nguồn để chèn vào canvas (hình đang sửa)."""
        if not self.current:
            return
        r0 = self.current.result or {}
        urls = [u for u in (r0.get("source_images") or []) if u]
        if not urls:
            # chưa có -> đọc lại link nguồn
            src_url = (self.current.source_url or "").strip()
            if src_url:
                from PySide6.QtCore import Qt as _Qt

                from ...source import fetch_source

                QApplication.setOverrideCursor(_Qt.WaitCursor)
                try:
                    page = fetch_source(src_url)
                    urls = [u for u in (page.get("images") or []) if u]
                except Exception:
                    urls = []
                finally:
                    QApplication.restoreOverrideCursor()
                if urls:
                    r = self.current.result = dict(r0)
                    r["source_images"] = urls
                    self.store.upsert_task(self.current)
                    self.store.save()
        if not urls:
            # vẫn không có -> TÌM TRÊN INTERNET theo mã sản phẩm (tối đa 10 ảnh)
            query = (r0.get("focus_keyword") or "").strip() or (r0.get("title") or "").strip()
            if not query:
                show_toast(self, "Không có mã sản phẩm để tìm ảnh", 3200, ok=False)
                return
            from PySide6.QtCore import Qt as _Qt

            from ...source import search_images

            self.status("Đang tìm ảnh trên internet…")
            show_toast(self, f"Đang tìm ảnh trên internet theo mã: {query}", 3000)
            QApplication.setOverrideCursor(_Qt.WaitCursor)
            try:
                urls = search_images(query, limit=10, log=self.status)
            except Exception:
                urls = []
            finally:
                QApplication.restoreOverrideCursor()
            if not urls:
                show_toast(self, "Không tìm được ảnh nào từ internet", 3200, ok=False)
                return
            r = self.current.result = dict(r0)
            r["source_images"] = urls
            self.store.upsert_task(self.current)
            self.store.save()

        from ..widgets.source_images import SourceImageDialog

        dlg = SourceImageDialog(urls, self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            self._add_upload_components(list(dlg.chosen), getattr(self, "_sel_index", 0))

    def _add_upload_components(self, paths: list[str], index: int) -> None:
        """Thêm NHIỀU ảnh cùng lúc vào canvas (mỗi ảnh 1 thành phần)."""
        if not self.current or not paths:
            return
        self._save()
        r = self.current.result
        lst = r.get("image_opts_list") or []
        while len(lst) <= index:
            lst.append({})
        ups = list(lst[index].get("uploads") or [])
        for p in paths:
            if not p:
                continue
            if len(ups) >= 8:
                ups[-1] = {"path": p, "pos": [0.5, 0.5]}
            else:
                ups.append({"path": p, "pos": [0.5, 0.5]})
        lst[index]["uploads"] = ups
        r["image_opts_list"] = lst
        self.store.upsert_task(self.current)
        self.store.save()
        self._load(self.current)
        self.recompose_image.emit(self.current, index)
        show_toast(self, f"Đã thêm {len(paths)} ảnh vào canvas", 2200)

    def _add_upload_component(self, path: str, index: int) -> None:
        """Thêm 1 ảnh (tải lên / dán / chọn từ nguồn) thành thành phần ở giữa canvas."""
        if not self.current or not path:
            return
        self._save()
        r = self.current.result
        lst = r.get("image_opts_list") or []
        while len(lst) <= index:
            lst.append({})
        ups = list(lst[index].get("uploads") or [])
        if len(ups) >= 3:
            ups[-1] = {"path": path, "pos": [0.5, 0.5]}   # đủ 3 -> thay cái cuối
        else:
            ups.append({"path": path, "pos": [0.5, 0.5]})  # canh giữa
        lst[index]["uploads"] = ups
        r["image_opts_list"] = lst
        self.store.upsert_task(self.current)
        self.store.save()
        self._load(self.current)
        self.recompose_image.emit(self.current, index)


    def _confirm_delete(self, task_id: str) -> None:
        ans = QMessageBox.question(
            self, "Xoá công việc", "Xoá công việc này khỏi danh sách?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if ans != QMessageBox.Yes:
            return
        if self.current and self.current.id == task_id:
            self.current = None
        self.delete_task.emit(task_id)

    def _save(self) -> None:
        if not self.current:
            return
        r = self.current.result
        r["title"] = self.title_edit.text()
        r["focus_keyword"] = self.kw_edit.text()
        r["description"] = self.desc_edit.toPlainText()
        r["tags"] = self.tags_edit.text()
        r["content_html"] = self.content_edit.get_html()
        self.store.upsert_task(self.current)
        self.store.save()
