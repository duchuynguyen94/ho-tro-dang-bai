"""Màn hình 'Công việc đang làm'."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QCursor, QPixmapCache, QDesktopServices, QDrag,
                             QImage, QKeySequence, QPixmap)
from PySide6.QtWidgets import (
    QApplication,
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
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...storage.models import (
    Task,
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_GENERATING,
    STATUS_LABELS,
    STATUS_QUEUED,
    STATUS_FINISH,
)
from ...config import output_dir
from ...images import compose
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
                return JobsPage._ensure_readable_image(str(p))
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


def info_state(task) -> tuple[bool, list[str]]:
    """Job đã ĐẦY ĐỦ thông tin input chưa? -> (đủ?, [tên các ô còn thiếu])."""
    r = task.result or {}
    missing: list[str] = []
    if not str(r.get("title") or "").strip():
        missing.append("Tiêu đề")
    if not str(r.get("focus_keyword") or "").strip():
        missing.append("Focus keyword")
    if not str(r.get("description") or "").strip():
        missing.append("Description")
    if not str(r.get("tags") or "").strip():
        missing.append("Search tags")
    if not str(r.get("content_html") or "").strip():
        missing.append("Nội dung")
    # ẢNH KHÔNG tính là "ô thông tin" (theo yêu cầu)
    return (not missing), missing


def _row_title(task, srcs: list[str]) -> str:
    """Tiêu đề item bên trái.

    - Job BLANK (không link): lấy Ô TIÊU ĐỀ (panel phải); rỗng -> "(blank)".
    - Job thường: link nguồn; không có link -> "(blank)".
    """
    kind = str(getattr(task, "kind", "") or "")
    r = task.result or {}
    if kind == "blank":
        return str(r.get("title") or "").strip() or "(blank)"
    if srcs:
        t = srcs[0]
        if len(srcs) > 1:
            t = f"{t}  (+{len(srcs) - 1})"
        return t
    return str(r.get("title") or "").strip() or "(blank)"


class TaskRow(QFrame):
    """1 dòng trong danh sách công việc (có nút xoá)."""

    clicked = Signal(str)
    delete = Signal(str)
    copied = Signal(str)
    clone = Signal(str)                      # nhân bản job (chỉ lấy hình)

    def __init__(self, task, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("taskRow")
        self.task_id = task.id
        self.source_url = task.source_url or ""
        self.kind = str(getattr(task, "kind", "") or "")
        self.site_id = str(getattr(task, "site_id", "") or "")

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 8, 10)
        h.setSpacing(8)

        v = QVBoxLayout()
        v.setSpacing(3)

        is_blank = (getattr(task, "kind", "") or "") == "blank"
        split_no = int(getattr(task, "split_no", 0) or 0)
        srcs = [u for u in (getattr(task, "source_urls", None) or []) if u]
        if not srcs and task.source_url:
            srcs = [task.source_url]
        # TIÊU ĐỀ ITEM: job CHIA -> "Bài N - link"; job BLANK -> Ô Tiêu đề (rỗng -> "(blank)")
        if split_no > 0:
            title_text = f"Bài {split_no} - {task.source_url or '(blank)'}"
            purple = True
        elif is_blank:
            title_text = _row_title(task, srcs)
            purple = True
        else:
            title_text = _row_title(task, srcs)
            purple = False
        url = QLabel(title_text)
        url.setObjectName("taskTitleBlank" if purple else "taskTitle")
        url.setWordWrap(True)
        self.title_lbl = url                    # để cập nhật lại khi đổi ô Tiêu đề
        v.addWidget(url)

        # DÒNG TRẠNG THÁI (1 nhãn duy nhất — cập nhật lại được khi thông tin thay đổi):
        # - Job đã tạo xong -> nói về THÔNG TIN: "Thông tin đã đầy đủ" (xanh) / "Thiếu thông tin" (vàng)
        # - Job đang chờ / đang tạo / lỗi / chưa tạo -> hiện trạng thái như cũ
        self._task = task
        self._split_no = split_no
        self._is_blank = is_blank
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("taskMeta")
        self.status_lbl.setWordWrap(True)
        v.addWidget(self.status_lbl)
        self.refresh_info()

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

        # Cho chuột "XUYÊN QUA" các nhãn con -> item nhận được HOVER (nền đổi khi rê chuột);
        # nút ✕ vẫn bấm được bình thường.
        try:
            from PySide6.QtWidgets import QWidget as _QW

            for child in self.findChildren(_QW):
                if child is self.del_btn:
                    continue
                child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:      # noqa: BLE001
            pass

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

    def set_hover(self, on: bool) -> None:
        """Đổi nền khi RÊ CHUỘT vào item (theo dõi chuột ở cấp app -> chắc chắn chạy)."""
        if bool(getattr(self, "_hover", False)) == bool(on):
            return
        self._hover = bool(on)
        try:
            self.setProperty("hover", "true" if on else "false")
            st = self.style()
            st.unpolish(self)
            st.polish(self)
            self.update()
        except Exception:      # noqa: BLE001
            pass

    def refresh_title(self) -> None:
        """Cập nhật TIÊU ĐỀ item (job blank -> lấy theo ô Tiêu đề; rỗng -> "(blank)")."""
        task = getattr(self, "_task", None)
        lbl = getattr(self, "title_lbl", None)
        if task is None or lbl is None:
            return
        try:
            split_no = int(getattr(self, "_split_no", 0) or 0)
            if split_no > 0:
                return                       # job CHIA -> giữ "Bài N - link"
            srcs = [u for u in (getattr(task, "source_urls", None) or []) if u]
            if not srcs and task.source_url:
                srcs = [task.source_url]
            lbl.setText(_row_title(task, srcs))
        except Exception:      # noqa: BLE001
            pass

    def refresh_info(self) -> None:
        """Cập nhật dòng trạng thái: đủ thông tin (xanh) / thiếu thông tin (vàng) / trạng thái cũ."""
        task = getattr(self, "_task", None)
        lbl = getattr(self, "status_lbl", None)
        if task is None or lbl is None:
            return
        try:
            if task.status == STATUS_FINISH:
                ok_info, missing = info_state(task)
                lbl.setText("Thông tin đã đầy đủ" if ok_info else "Thiếu thông tin")
                lbl.setObjectName("taskInfoOk" if ok_info else "taskInfoMissing")
                lbl.setToolTip(("Còn thiếu: " + ", ".join(missing)) if missing else "")
                lbl.setVisible(True)
            else:
                split_no = int(getattr(self, "_split_no", 0) or 0)
                is_blank = bool(getattr(self, "_is_blank", False))
                if split_no > 0 or not is_blank:
                    lbl.setText(STATUS_LABELS.get(task.status, task.status))
                    lbl.setObjectName("taskMeta")
                    lbl.setToolTip("")
                    lbl.setVisible(True)
                else:
                    lbl.setVisible(False)
            st = lbl.style()                 # đổi objectName -> phải polish lại mới ăn màu
            st.unpolish(lbl)
            st.polish(lbl)
            lbl.update()
        except Exception:      # noqa: BLE001
            pass

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        act_copy = menu.addAction("Sao chép link nguồn")
        act_copy.setEnabled(bool(self.source_url))
        act_open = menu.addAction("Mở link nguồn")
        act_open.setEnabled(bool(self.source_url))
        menu.addSeparator()
        act_clone = menu.addAction("Nhân bản công việc (chỉ lấy hình)")
        act_del = menu.addAction("Xoá công việc")

        chosen = menu.exec(event.globalPos())
        if chosen == act_copy and self.source_url:
            QApplication.clipboard().setText(self.source_url)
            self.copied.emit(self.source_url)
        elif chosen == act_open and self.source_url:
            QDesktopServices.openUrl(QUrl(self.source_url))
        elif chosen == act_clone:
            self.clone.emit(self.task_id)
        elif chosen == act_del:
            self.delete.emit(self.task_id)


class JobsPage(QWidget):
    regenerate = Signal(object, str)         # (task, field)
    regenerate_images = Signal(object, str)  # (task, footer_mode)
    post = Signal(object)                    # (task)
    models_extract = Signal()                # nút "Product Models" -> popup trích xuất
    seo_all = Signal()                       # lấy JSON SEO hàng loạt (job trống thiếu SEO)
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
    status_msg = Signal(str)                 # báo trạng thái ra thanh dưới cùng của app
    seo_json = Signal(object)                # (task) tạo JSON SEO từ nội dung (job trống)

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.current = None
        self._posting: dict[str, bool] = {}      # task_id -> đang mở Chrome để đăng
        self._ai_busy = False
        self._posting_locked = False      # task_id -> đang mở Chrome để đăng
        self._rows: dict[str, TaskRow] = {}
        self._thumbs: list = []
        self._sel_index = 0
        self._edit_index = 0              # ảnh mà panel phải ĐANG hiển thị (để áp dụng đúng ảnh)
        self._img_cache: dict = {}        # cache ảnh "Hình tự tìm" RIÊNG từng job (task_id -> {url: bytes})
        self._copied_component: dict | None = None   # thành phần đã Ctrl+C (dán sang ảnh khác)
        self._seo_busy = False                       # đang tạo JSON SEO
        self._busy = False                           # cờ "khoá toàn bộ" (có tiến trình chạy)
        self._canvas_worker = None                   # luồng dựng ảnh nền canvas
        self._canvas_workers: list = []
        self._preview_token = 0                      # chỉ áp kết quả dựng nền MỚI NHẤT
        self._build()
        self._init_autosave()
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
        self.seo_all_btn = QPushButton("Lấy JSON SEO hàng loạt")
        self.seo_all_btn.setProperty("class", "ghost")
        self.seo_all_btn.setToolTip(
            "Chạy TUẦN TỰ lấy JSON SEO cho các job TRỐNG còn thiếu Tiêu đề / Description\n"
            "(dùng Nội dung của chính job đó) — có popup tiến trình 1/N."
        )
        self.seo_all_btn.clicked.connect(self.seo_all.emit)
        self.stop_all_btn = QPushButton("■ Dừng tất cả")
        self.stop_all_btn.setProperty("class", "danger")
        self.stop_all_btn.setToolTip("Dừng mọi việc đang chờ / đang tạo → chuyển thành \"chưa tạo\"")
        self.stop_all_btn.clicked.connect(self.stop_all.emit)
        # 2 nút GOM 1 HÀNG, nằm NGAY DƯỚI tiêu đề "Công việc đang làm"
        _btns = QHBoxLayout()
        _btns.setSpacing(8)
        _btns.addWidget(self.seo_all_btn, 1)
        _btns.addWidget(self.stop_all_btn, 1)
        left.body.insertLayout(0, _btns)
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
        self.cat_edit = QLineEdit()
        self.cat_edit.setPlaceholderText("VD: Cảm biến tiệm cận")
        self.cat_edit.setToolTip(
            "Chủng loại (danh mục sản phẩm) trên website.\n"
            "Khi đăng: kịch bản tự chọn danh mục này; nếu website chưa có thì tự THÊM MỚI."
        )
        ev2.addLayout(self._field("Chủng loại (danh mục sản phẩm)", self.cat_edit))
        self.brand_edit = QLineEdit()
        self.brand_edit.setPlaceholderText("VD: Carlo Gavazzi")
        self.brand_edit.setToolTip(
            "Thương hiệu sản phẩm.\n"
            "Khi đăng: kịch bản tự chọn thương hiệu; nếu website chưa có thì tự THÊM MỚI."
        )
        ev2.addLayout(self._field("Thương hiệu", self.brand_edit))
        self.models_edit = QLineEdit()
        self.models_edit.setPlaceholderText("VD: BI15U-EM30WDTC-AP6X, BI10U-EM30WDTC-AP6X")
        self.models_edit.setToolTip("Danh sách mã sản phẩm của nội dung (cách nhau bởi dấu phẩy).")
        ev2.addLayout(self._field("Mã sản phẩm", self.models_edit))
        self.content_edit = RichEditor()
        try:
            self.content_edit.store = self.store      # để "Chèn ảnh" nhớ thư mục
        except Exception:      # noqa: BLE001
            pass
        self.content_edit.changed.connect(self._sync_seo_btn)
        self.content_edit.changed.connect(self._queue_save)
        ev2.addLayout(self._field("Nội dung", self.content_edit,
                                  extra=("Auto format", self._auto_format)))

        self.add_img_btn = QPushButton("+ Thêm hình")
        self.add_img_btn.setProperty("class", "ghost")
        self.add_img_btn.setToolTip(
            "Thêm 1 ảnh TRỐNG (chỉ có logo site, logo brand, watermark, thanh thông tin).\n"
            "Bạn tự tải đối tượng hình ảnh lên cho ảnh đó."
        )
        self.add_img_btn.clicked.connect(self._add_image)
        try:      # copy ảnh/text từ NGOÀI -> bỏ thành phần đã copy trong app
            QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        except Exception:
            pass

        img_head = QHBoxLayout()
        img_lab = QLabel("Ảnh")
        img_lab.setStyleSheet("font-weight:600;")
        img_head.addWidget(img_lab)
        img_head.addWidget(self.add_img_btn)      # nằm ngay BÊN PHẢI chữ "Ảnh"
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

        self.img_editor = ImageEditorPanel()
        # KÉO-THẢ ẢNH vào canvas: file trong máy (Finder/Desktop) hoặc ảnh từ web (link http)
        try:
            self.img_editor.canvas.setAcceptDrops(True)
        except Exception:      # noqa: BLE001
            pass
        self._drop_workers: list = []
        self._drop_jobs: dict = {}
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
        f.addStretch(1)                          # đẩy các nút kia sang PHẢI (right = 0)
        self.seo_btn = QPushButton("Tạo JSON SEO")
        self.seo_btn.setProperty("class", "ghost")
        self.seo_btn.setToolTip(
            "Đọc NỘI DUNG đang soạn -> gọi AI tạo JSON SEO (Title / Description / "
            "Focus keyword / Tags) rồi điền vào các ô."
        )
        self.seo_btn.clicked.connect(
            lambda: self.current and self.seo_json.emit(self.current)
        )
        self.seo_btn.hide()
        f.addWidget(self.seo_btn)                # ngay BÊN TRÁI nút "OK — Đăng bài"
        self.models_btn = QPushButton("Product Models")
        self.models_btn.setProperty("class", "ghost")
        self.models_btn.setToolTip(
            "Trích xuất danh sách Product Models từ link hoặc file (pdf/docx/ảnh)\n"
            "bằng chatbox ChatGPT (dùng URL Project trong Cài đặt)."
        )
        self.models_btn.clicked.connect(lambda: self.models_extract.emit())
        f.addWidget(self.models_btn)             # sát trái nút "OK — Đăng bài"
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

    def _field(self, label: str, widget: QWidget,
               extra: tuple[str, object] | None = None) -> QVBoxLayout:
        box = QVBoxLayout()
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setStyleSheet("font-weight:600;")
        row.addWidget(lab)
        row.addStretch(1)
        if extra is not None:      # nút phụ bên phải nhãn (vd "Auto format")
            name, fn = extra
            ebtn = QPushButton(str(name))
            ebtn.setProperty("class", "ghost")
            ebtn.clicked.connect(fn)
            row.addWidget(ebtn)
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
            row.clone.connect(self._clone_task)
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
        self._recompute_busy()

    def is_posting(self, task_id: str) -> bool:
        return bool(self._posting.get(task_id))

    def _sync_post_btn(self) -> None:
        cur = getattr(self.current, "id", None)
        busy = (bool(cur and self._posting.get(cur))
                or bool(self._posting_locked) or bool(getattr(self, "_busy", False)))
        self.post_btn.setEnabled(not busy)
        if not getattr(self, "_busy", False):      # đang có cờ khoá -> giữ chữ của cờ khoá
            self.post_btn.setText("Đang mở trình duyệt…" if busy else "OK — Đăng bài")

    def select_task(self, task_id: str) -> None:
        task = next((t for t in self.store.tasks if t.id == task_id), None)
        if not task:
            return
        if getattr(self.current, "id", "") and self.current.id != task_id:
            self._save()                  # đổi JOB -> LƯU thông tin đang gõ của job CŨ (không mất)
            self._flush_editor()          # + chốt ảnh đang mở của job CŨ
        self.current = task
        for tid, row in self._rows.items():
            row.set_selected(tid == task_id)
        self.result_card.set_title("")      # đã bỏ tên website ở tiêu đề panel phải
        active = self.store.ai_content.get("active", "")
        self.provider_badge.setText(f"Provider: {active}" if active else "")
        self._show_state()
        self._sync_post_btn()

    # chữ gốc / chữ khi ChatGPT đang bận
    def set_posting_locked(self, locked: bool) -> None:
        """Có 1 việc đang đăng bài -> đặt cờ "khoá toàn bộ"."""
        self._posting_locked = bool(locked)
        self._recompute_busy()

    def set_ai_busy(self, busy: bool) -> None:
        """Có 1 việc tạo nội dung đang chạy -> bật/tắt cờ "khoá toàn bộ"."""
        self._ai_busy = bool(busy)
        self._recompute_busy()

    _BUSY_SUFFIX = " - Đang có tiến trình chạy"

    def _busy_targets(self) -> list:
        """Các nút bị khoá khi có tiến trình chạy."""
        out = []
        for name in ("post_btn", "seo_btn", "regen_all_btn", "retry_btn", "models_btn",
                     "seo_all_btn"):
            b = getattr(self, name, None)
            if b is not None:
                out.append(b)
        return out

    def _recompute_busy(self) -> None:
        """Cờ "khoá toàn bộ" = đang có tiến trình chạy (đăng bài / JSON SEO / tạo nội dung)."""
        busy = (bool(getattr(self, "_ai_busy", False))
                or bool(getattr(self, "_seo_busy", False))
                or bool(getattr(self, "_posting_locked", False))
                or any(getattr(self, "_posting", {}).values()))
        self._apply_busy(busy)

    def _apply_busy(self, busy: bool) -> None:
        """Bật/tắt cờ khoá: nút mờ + chữ "<Tên nút> - Đang có tiến trình chạy"."""
        self._busy = bool(busy)
        for b in self._busy_targets():
            try:
                if busy:
                    if not getattr(b, "_normal_text", ""):
                        b._normal_text = b.text()
                    b.setText(f"{b._normal_text}{self._BUSY_SUFFIX}")
                    b.setToolTip("Đang có tiến trình chạy — chờ xong đã")
                    b.setEnabled(False)
                else:
                    txt = getattr(b, "_normal_text", "")
                    if txt:
                        b.setText(txt)
                    b.setToolTip("")
                    b.setEnabled(True)
            except Exception:
                pass
        if not busy:                 # mở khoá -> đồng bộ lại trạng thái riêng từng nút
            self._sync_post_btn()
            self._sync_seo_btn()

    def set_loading_message(self, text: str) -> None:
        if self.current and self.current.status in (STATUS_QUEUED, STATUS_GENERATING):
            self.loading_note.setText(text)


    # ------------------------------------------------------------------ #
    @staticmethod
    def _has_result(task) -> bool:
        """Job đã có kết quả (nội dung hoặc ảnh) -> LUÔN giữ panel kết quả khi tạo lại."""
        r = task.result or {}
        return bool(str(r.get("title") or "").strip()
                    or str(r.get("content_html") or "").strip()
                    or list(r.get("images") or []))

    def _keep_panel(self, task, note: str) -> None:
        """Giữ nguyên panel kết quả (không đổi sang màn hình chờ / lỗi) — chỉ báo ở dòng dưới."""
        self.footer.show()
        self.check_label.setText(note)
        same = (getattr(self, "_loaded_task_id", "") == getattr(task, "id", "")
                and self.stack.currentWidget() is self.editor_scroll)
        if not same:
            self._load(task)

    def _show_state(self) -> None:
        task = self.current
        # mỗi lần hiển thị 1 job: xoá sạch message cũ (không để lẫn của job khác)
        self.loading_note.setText("")
        if hasattr(self, "check_label"):
            self.check_label.setText("")
        if task is None:
            self.footer.hide()
            self.stack.setCurrentWidget(self.page_empty)
            return

        # Job ĐÃ CÓ kết quả -> giữ panel kết quả (các ô input + ảnh) khi tạo lại
        keep = self._has_result(task)

        if task.status == STATUS_QUEUED:
            if keep:
                self._keep_panel(task, "đang chờ tới lượt…")
                return
            # đang chờ tới lượt: KHÔNG có nút nào, KHÔNG hiện message của việc khác
            self.footer.hide()
            self.loading_label.setText("đang chờ tới lượt…")
            self.loading_note.setText("")
            self.loading_bar.setVisible(False)
            self.stop_btn.setVisible(False)
            self.stack.setCurrentWidget(self.page_loading)
            return

        if task.status == STATUS_GENERATING:
            if keep:
                self._keep_panel(task, "Đang tạo lại nội dung…")
                return
            self.footer.hide()
            self.loading_label.setText("Đang tạo nội dung…")
            self.loading_bar.setVisible(True)
            self.stop_btn.setVisible(True)
            self.stack.setCurrentWidget(self.page_loading)
            return

        if task.status == STATUS_CANCELLED:
            if keep:
                self._keep_panel(task, "Đã dừng tạo nội dung — giữ nguyên kết quả cũ.")
                return
            self.footer.hide()
            self.error_label.setText(
                "<b>Đã dừng tạo nội dung.</b><br><br>"
                "<span style='color:#64748b'>Bấm “Thử tạo lại” nếu muốn chạy lại.</span>"
            )
            self.stack.setCurrentWidget(self.page_error)
            return

        if task.status == STATUS_ERROR:
            if keep:
                # tạo lại lỗi -> BỎ QUA, không làm gì ảnh hưởng tới nội dung/ảnh đang có
                self._keep_panel(task, "Tạo lại lỗi — giữ nguyên kết quả cũ.")
                return
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
        finally:
            self._loading = False        # dù lỗi hay không -> vẫn mở lại TỰ LƯU

    def _load_inner(self, task) -> None:
        self._loading = True              # đang nạp job -> chặn tự lưu
        self._loaded_task_id = getattr(task, "id", "")
        r = task.result or {}
        self.title_edit.setText(r.get("title", ""))
        self.kw_edit.setText(r.get("focus_keyword", ""))
        self.desc_edit.setPlainText(r.get("description", ""))
        self.tags_edit.setText(r.get("tags", ""))
        self.cat_edit.setText(r.get("category_name", ""))
        self.brand_edit.setText(r.get("brand_name", ""))
        self.models_edit.setText(r.get("ma_san_pham", ""))
        self.content_edit.set_html(r.get("content_html", ""))
        self._loading = False             # nạp xong -> cho phép tự lưu lại

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

    def _site_of(self, task):
        """Website của job: đã chọn lúc Đăng -> hoặc MẶC ĐỊNH của phần mềm."""
        from ...storage.models import Site

        return (self.store.get_site(getattr(task, "site_id", ""))
                or getattr(self, "_post_sites", {}).get(getattr(task, "id", ""))
                or Site())

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
        site = self._site_of(task)
        bars = _site_bars(site)
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
    def refresh_info(self) -> None:
        """Cập nhật dòng "Thông tin đã đầy đủ / Thiếu thông tin" của mọi job (nhẹ, không dựng lại list)."""
        for tid, row in list(getattr(self, "_rows", {}).items()):
            t = next((x for x in self.store.tasks if x.id == tid), None)
            if t is None:
                continue
            try:
                row._task = t
                row.refresh_info()
                row.refresh_title()      # đổi ô Tiêu đề -> đổi luôn tiêu đề item bên trái
            except Exception:      # noqa: BLE001
                continue

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
            self.add_img_btn.setEnabled(len(images) < MAX_IMAGES)
            # GIỮ viền "đang sửa" đúng ảnh đang mở (dựng lại danh sách không làm mất viền)
            idx = getattr(self, "_sel_index", 0)
            for box in self._thumbs:
                box.set_selected(box.index == idx)
        except Exception:
            traceback.print_exc()

    def _select_image(self, index: int) -> None:
        if index != getattr(self, "_sel_index", 0):
            self._flush_editor()          # chốt ẢNH CŨ trước khi nạp ảnh mới
        self._sel_index = index
        if self.current:
            self._refresh_preview(self.current)

    def _find_free_spots(self, n: int) -> list[list[float]]:
        """Tìm n CHỖ TRỐNG trên canvas (tránh chồng lên thành phần đang có)."""
        n = max(1, int(n or 1))
        ed = self.img_editor
        try:
            size = max(1, int(ed.canvas.width()))
        except Exception:
            size = 420
        rects: list[tuple[float, float, float, float]] = []   # (x1,y1,x2,y2) theo tỉ lệ canvas
        for it in list(getattr(ed, "_upload_items", [])) + list(getattr(ed, "_product_items", [])):
            try:
                rects.append((it.x() / size, it.y() / size,
                              (it.x() + it.width()) / size, (it.y() + it.height()) / size))
            except Exception:
                pass
        grid = (0.2, 0.5, 0.8)          # 3 × 3 chỗ
        out: list[list[float]] = []
        for gy in grid:
            for gx in grid:
                if any((x1 - 0.05) <= gx <= (x2 + 0.05) and (y1 - 0.05) <= gy <= (y2 + 0.05)
                       for x1, y1, x2, y2 in rects):
                    continue                      # đã có thành phần ở chỗ này
                if any(abs(gx - ox) < 0.2 and abs(gy - oy) < 0.2 for ox, oy in out):
                    continue                      # đã chọn chỗ này cho ảnh khác trong lượt dán
                out.append([round(gx, 4), round(gy, 4)])
                if len(out) >= n:
                    return out
        k = len(out)                    # hết chỗ trống -> xếp so le dần
        while len(out) < n:
            v = min(0.9, 0.15 + 0.1 * k)
            out.append([round(v, 4), round(v, 4)])
            k += 1
        return out

    def _on_clipboard_changed(self) -> None:
        """Clipboard ngoài đổi (người dùng copy ảnh/text khác) -> bỏ thành phần đã copy."""
        self._copied_component = None

    def _paste_component(self, index: int) -> None:
        """Dán thành phần đã Ctrl+C vào ẢNH ĐANG MỞ (mỗi lần 1 chỗ trống)."""
        comp = dict(self._copied_component or {})
        path = str(comp.get("path") or "")
        if not path or not self.current:
            return
        self._save()
        fresh = self._fresh_current()
        if fresh is None:
            return
        r = fresh.result
        lst = r.get("image_opts_list") or []
        while len(lst) <= index:
            lst.append({})
        ups = list(lst[index].get("uploads") or [])
        item: dict = {"path": path, "pos": self._find_free_spots(1)[0]}
        try:
            sc = float(comp.get("scale", 1.0) or 1.0)
            if abs(sc - 1.0) > 0.001:
                item["scale"] = round(sc, 3)
        except Exception:
            pass
        if comp.get("nobg"):
            item["nobg"] = True
        if len(ups) >= 20:
            ups[-1] = item
        else:
            ups.append(item)
        lst[index]["uploads"] = ups
        r["image_opts_list"] = lst
        self.store.upsert_task(self.current)
        self.store.save()
        self._load(self.current)
        self.recompose_image.emit(self.current, index)

    def _track_row_hover(self) -> None:
        """Rê chuột -> item nào thì đổi nền item đó (đáng tin hơn QSS :hover)."""
        try:
            wdg = QApplication.widgetAt(QCursor.pos())   # None = chuột ra ngoài app -> bỏ hover
            row = None
            while wdg is not None:
                if isinstance(wdg, TaskRow):
                    row = wdg
                    break
                wdg = wdg.parentWidget()
            if row is getattr(self, "_hover_row", None):
                return
            old = getattr(self, "_hover_row", None)
            if old is not None:
                old.set_hover(False)
            self._hover_row = row
            if row is not None:
                row.set_hover(True)
        except Exception:      # noqa: BLE001
            pass

    def _sync_seo_btn(self) -> None:
        """Nút "Tạo JSON SEO": chỉ hiện khi job TRỐNG và ô Nội dung CÓ chữ."""
        try:
            task = self.current
            kind = str(getattr(task, "kind", "") or "") if task is not None else ""
            has_text = bool(self.content_edit.get_text().strip())
            show = (kind == "blank") and has_text
            self.seo_btn.setVisible(show)
            self.seo_btn.setEnabled(show and not self._seo_busy
                                     and not getattr(self, "_busy", False))
        except Exception:
            pass

    def set_seo_busy(self, on: bool) -> None:
        """Đang tạo JSON SEO -> khoá nút + báo ở dòng dưới."""
        self._seo_busy = bool(on)
        try:
            # xong / lỗi -> XOÁ dòng trạng thái
            self.check_label.setText("Đang tạo JSON SEO từ nội dung…" if on else "")
        except Exception:
            pass
        self._recompute_busy()

    def _flush_editor(self) -> None:
        """Ghép NGAY phần vừa sửa của ẢNH ĐANG MỞ (đúng ảnh đó, không lây sang ảnh khác)."""
        try:
            self.img_editor.flush()
        except Exception:
            pass

    def _build_preview(self, task, index: int, mode_override: str = "") -> dict:
        site = self._site_of(task)
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

        out = output_dir() / f"preview_{task.id}_{index + 1}.png"
        return {
            "background": str(out),
            "logo": (site.logo_path or default_asset("logo.png")) if site else "",
            "brand": (r.get("brand_logo")
                      or str(getattr(task, "brand_logo_fallback", "") or "")),
            "products": [] if opts.get("no_products") else
                        [p for p in (r.get("product_images") or []) if p],
            "watermark": site.watermark_text,
        }

    def _preview_params(self, task, index: int, mode_override: str = "") -> dict:
        """Tham số dựng ẢNH NỀN canvas (ghép ở luồng riêng — không đứng giao diện)."""
        site = self._site_of(task)
        r = task.result or {}
        images = r.get("images") or []
        footer = str(images[index].get("footer", "") or "") if index < len(images) else ""
        lst = r.get("image_opts_list") or []
        opts = dict(lst[index]) if index < len(lst) else (r.get("image_opts") or {})
        explicit = mode_override or (opts.get("footer_mode")
                                     if opts.get("footer_mode") in ("bar1", "bar2") else "")
        if explicit:
            footer = ""
        if not footer and site:
            from ..workers import _site_bars
            bars = _site_bars(site)
            mode = explicit or self._footer_mode_of(task, index)
            if bars:
                footer = bars[1] if (mode == "bar2" and len(bars) > 1) else bars[0]
        remove_bg, th = _remove_bg_opts(self.store)
        out = output_dir() / f"preview_{task.id}_{index + 1}.png"
        return {
            "out": str(out),
            "footer": footer,
            "remove_bg": remove_bg,
            "remove_bg_thresh": th,
            "product_scale": float(opts.get("product_scale", 1.0) or 1.0),
        }

    def _request_canvas_bg(self, task, index: int, mode_override: str = "") -> None:
        """Dựng lại ảnh nền canvas Ở LUỒNG RIÊNG (chỉ áp kết quả MỚI NHẤT)."""
        try:
            from ..workers import CanvasPreviewWorker
        except Exception:      # noqa: BLE001
            traceback.print_exc()
            return
        try:
            params = self._preview_params(task, index, mode_override)
        except Exception:      # noqa: BLE001
            traceback.print_exc()
            return
        self._preview_token = int(getattr(self, "_preview_token", 0)) + 1
        token = self._preview_token
        try:
            old = getattr(self, "_canvas_worker", None)
            if old is not None and old.isRunning():
                old.stop()
        except Exception:      # noqa: BLE001
            pass
        w = CanvasPreviewWorker(params)
        w.ok.connect(lambda path: self._on_canvas_bg_ok(path, token, task, index))
        w.failed.connect(self._on_canvas_bg_failed)
        w.finished.connect(lambda: self._canvas_worker_done(w))
        self._canvas_worker = w
        self._canvas_workers.append(w)
        w.start()

    def _canvas_worker_done(self, w) -> None:
        try:
            if getattr(self, "_canvas_worker", None) is w:
                self._canvas_worker = None
            if w in self._canvas_workers:
                self._canvas_workers.remove(w)
        except Exception:      # noqa: BLE001
            pass

    def _on_canvas_bg_ok(self, path: str, token: int, task, index: int) -> None:
        """Ảnh nền dựng xong: chỉ áp khi vẫn đang xem ĐÚNG job + ảnh đó (bỏ kết quả cũ)."""
        try:
            if token != int(getattr(self, "_preview_token", 0)):
                return
            if self.current is not task or int(getattr(self, "_sel_index", 0)) != int(index):
                return
            if path:
                self.img_editor.set_background(path)
                # canvas vừa có nền mới -> cập nhật luôn preview trong danh sách ảnh
                QTimer.singleShot(150, self._sync_thumb_from_canvas)
        except Exception:      # noqa: BLE001
            traceback.print_exc()

    def _on_canvas_bg_failed(self, err: str) -> None:
        try:
            traceback.print_exc()
        except Exception:      # noqa: BLE001
            pass

    def _refresh_preview(self, task) -> None:
        r = task.result or {}
        images = r.get("images") or []
        idx = getattr(self, "_sel_index", 0)
        for box in getattr(self, "_thumbs", []):
            box.set_selected(box.index == idx)
        title = f"Ảnh {idx + 1}" if images else ""
        lst = r.get("image_opts_list") or []
        opts_i = dict(lst[idx]) if idx < len(lst) else (r.get("image_opts") or {})
        preview = self._build_preview(task, idx) if images else {}
        self.img_editor.set_ai_enabled((self.store.ai_image or {}).get("active") != "off")
        # thanh thông tin: select phản ánh ĐÚNG thanh đang có trong ảnh
        # job trống: không chạy AI -> ẩn nút Random lại
        self.regen_all_btn.setVisible((getattr(task, "kind", "") or "") != "blank")
        self._edit_index = idx           # nhớ ĐÚNG ảnh đang mở -> mọi thay đổi áp cho ảnh này
        self.img_editor.load(preview, opts_i, self._footer_mode_of(task, idx), title)
        self._request_canvas_bg(task, idx)      # dựng nền ở luồng riêng
        self._sync_seo_btn()

    def _on_footer_changed(self, mode: str) -> None:
        """Đổi select "thanh thông tin": lưu lựa chọn + dựng lại NỀN canvas NGAY.

        Thứ tự: canvas đổi TRƯỚC -> 0.2s sau preview trong danh sách -> 0.5s sau ghép file ảnh thật.
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
        self._request_canvas_bg(self.current, idx, mode)

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
            # dùng ẢNH ĐANG MỞ (không dùng ảnh vừa click) -> không lây tuỳ chọn sang ảnh khác
            idx = int(getattr(self, "_edit_index", getattr(self, "_sel_index", 0)) or 0)
            self.apply_image_opts.emit(self.current, idx, opts)

    def _regen_images(self) -> None:
        if not self.current:
            return
        mode = ["random", "bar1", "bar2"][self.footer_combo.currentIndex()]
        self.current.footer_mode = mode
        self.regenerate_images.emit(self.current, mode)

    def _upload_image(self, index: int) -> None:
        """Chọn NHIỀU ảnh từ máy -> thêm vào canvas thành các thành phần."""
        from ..filepick import open_files

        paths = open_files(self.store, self, "Chọn ảnh (chọn được nhiều ảnh)",
                           "Ảnh (*.png *.jpg *.jpeg *.webp)")
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
            if event.type() in (QEvent.DragEnter, QEvent.DragMove):
                if obj is self.img_editor.canvas:
                    if self._drop_maybe_image(event.mimeData()):
                        event.acceptProposedAction()
                        return True
                return False
            if event.type() == QEvent.Drop:
                if obj is self.img_editor.canvas:
                    if self._drop_on_canvas(event):
                        event.acceptProposedAction()
                        return True
                    return False
            if event.type() in (QEvent.MouseMove, QEvent.Leave):
                self._track_row_hover()
            # macOS: phím "delete" trên bàn phím = Backspace; Windows: Delete
            if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                fw = QApplication.focusWidget()
                if self._is_text_widget(fw):
                    return False
                if self.isVisible() and self.current:
                    if self.img_editor.remove_selected():
                        return True
            if event.type() == QEvent.KeyPress and event.matches(QKeySequence.Copy):
                fw = QApplication.focusWidget()
                if self._is_text_widget(fw):
                    return False
                if self.isVisible() and self.current:
                    comp = self.img_editor.copy_selected()
                    if comp and comp.get("path"):
                        self._copied_component = dict(comp)
                        return True
            if event.type() == QEvent.KeyPress and event.matches(QKeySequence.Paste):
                fw = QApplication.focusWidget()
                if self._is_text_widget(fw):
                    return False
                if self.isVisible() and self.current:
                    if self._copied_component:
                        self._paste_component(getattr(self, "_sel_index", 0))
                        return True
                    if clipboard_image_path():
                        self._paste_clipboard_image()
                        return True
        except Exception:      # noqa: BLE001
            traceback.print_exc()
        return super().eventFilter(obj, event)

    def _auto_format(self) -> None:
        """Auto format nội dung: dọn rác + ICON theo logic + LINK tên miền + LINK tiêu đề mục."""
        if not self.current:
            return
        try:
            from ...ai.manager import (already_auto_formatted, apply_template_icons,
                                       clean_content_html, extract_product_name,
                                       insert_readmore, insert_title_links,
                                       linkify_domains, mark_auto_formatted,
                                       readmore_from_store, set_first_title_link)
        except Exception:      # noqa: BLE001
            traceback.print_exc()
            return
        try:
            html = self.content_edit.get_html() or ""
            if not html.strip():
                show_toast(self, "Ô Nội dung đang trống", 2600, ok=False)
                return
            site = self.store.get_site(getattr(self.current, "site_id", ""))
            site_url = str(getattr(site, "url", "") or "") if site else ""
            if already_auto_formatted(html):
                # Đã format rồi -> CHỈ kiểm tra + sửa link tiêu đề đầu cho đúng website sẽ đăng
                fixed = set_first_title_link(html, site_url)
                fixed = insert_readmore(fixed, readmore_from_store(self.store))
                if fixed != html:
                    self.content_edit.set_html(fixed)
                    self._save()
                    show_toast(self, "Đã cập nhật link tiêu đề đầu theo website sẽ đăng", 3000)
                else:
                    show_toast(self, "Nội dung đã auto format rồi — không chèn lại", 2800)
                return
            r = self.current.result or {}
            out = clean_content_html(html)                    # 1) dọn rác HTML
            out = apply_template_icons(out)                   # 2) icon đầu mục + dòng liên hệ
            all_sites = [(x.url or "", x.name or "") for x in self.store.sites]
            out = linkify_domains(out, all_sites)             # 3) www.<domain> -> link thật
            out = insert_title_links(                          # 4) link vào tiêu đề mục
                out, site_url, list(self.store.title_links),
                [extract_product_name(out, ""), str(r.get("focus_keyword") or ""),
                 str(r.get("title") or ""), ""],
            )
            out = set_first_title_link(out, site_url)         # 5) tiêu đề đầu -> website sẽ đăng
            out = insert_readmore(out, readmore_from_store(self.store))   # 5b) khối "Đọc thêm"
            out = mark_auto_formatted(out)                    # 6) gắn dấu đã auto format
            self.content_edit.set_html(out)
            self._save()
            show_toast(self, "Đã auto format nội dung (icon + link)", 2600)
        except Exception as exc:      # noqa: BLE001
            traceback.print_exc()
            show_toast(self, f"Auto format lỗi: {exc}", 3600, ok=False)

    # ---------------- "Tìm hình": lấy ảnh từ NHIỀU link nguồn ---------------- #
    def _pick_source_image(self) -> None:
        """Popup "Tìm hình": gõ link -> bấm Lấy hình -> chọn ảnh -> chèn vào canvas."""
        if not self.current:
            return
        task = self.current
        r0 = task.result or {}
        links = [u for u in (r0.get("image_links") or []) if u]
        if not links:
            links = list(getattr(task, "source_urls", []) or [])
            if not links and getattr(task, "source_url", ""):
                links = [task.source_url]

        from ..widgets.source_images import SourceImageDialog

        def _save_state(state: dict) -> None:
            """Lưu NGAY link + tick của popup vào job (không mất khi đóng)."""
            try:
                cur = self.current
                if cur is None or getattr(cur, "id", "") != getattr(task, "id", ""):
                    cur = next((x for x in self.store.tasks if x.id == task.id), None)
                if cur is None:
                    return
                r = cur.result = dict(cur.result or {})
                r["image_links"] = list(state.get("links") or [])
                r["image_nobg"] = bool(state.get("nobg"))
                r["image_trim"] = bool(state.get("trim"))
                self.store.upsert_task(cur)
                self.store.save()
            except Exception:      # noqa: BLE001
                pass

        dlg = SourceImageDialog([u for u in (r0.get("source_images") or []) if u], self,
                                links=links,
                                cache=self._img_cache.setdefault(str(task.id), {}),
                                nobg=bool(r0.get("image_nobg")),
                                trim=bool(r0.get("image_trim")),
                                on_save=_save_state)
        accepted = dlg.exec() == QDialog.Accepted
        try:      # nhớ link + danh sách ảnh cho RIÊNG job này
            r = self.current.result = dict(self.current.result or {})
            r["image_links"] = list(dlg.links_list or links)
            r["source_images"] = list(dlg.urls or [])
            self.store.upsert_task(self.current)
            self.store.save()
        except Exception:      # noqa: BLE001
            pass
        if accepted and dlg.chosen:
            self._add_upload_components(list(dlg.chosen), getattr(self, "_sel_index", 0),
                                         nobg=bool(getattr(dlg, "chosen_nobg", False)))

    def _save_source_images(self, urls: list[str], keyword: str = "",
                            meta: list | None = None) -> None:
        """Lưu danh sách ảnh tự tìm + keyword theo TỪNG job (đổi job là làm lại từ đầu)."""
        if not self.current:
            return
        r = self.current.result = dict(self.current.result or {})
        r["source_images"] = [u for u in (urls or []) if u]
        if meta is not None:
            r["source_images_meta"] = list(meta)      # giữ alt/title để lần sau vẫn gán được mã
        if keyword:
            r["image_keyword"] = str(keyword)
        self.store.upsert_task(self.current)
        self.store.save()

    def _add_upload_components(self, paths: list[str], index: int,
                               nobg: bool = False, pos=None) -> None:
        """Thêm NHIỀU ảnh cùng lúc vào canvas (mỗi ảnh 1 thành phần).

        `pos` = [x, y] (tỉ lệ 0..1) — chỗ THẢ CHUỘT; ảnh đầu nằm đúng đó.
        """
        if not self.current or not paths:
            return
        self._save()
        fresh = self._fresh_current()
        if fresh is None:
            return
        r = fresh.result
        lst = r.get("image_opts_list") or []
        while len(lst) <= index:
            lst.append({})
        ups = list(lst[index].get("uploads") or [])
        real = [p for p in paths if p]
        # CHỈ nhận ảnh ĐỌC ĐƯỢC (nếu không sẽ thêm object vô hình vào canvas)
        ok: list[str] = []
        for p in real:
            good = self._ensure_readable_image(p)
            if good:
                ok.append(good)
        if len(ok) < len(real):
            show_toast(self, f"{len(real) - len(ok)} ảnh không đọc được (đã bỏ qua)",
                       2600, ok=False)
        real = ok
        if not real:
            return
        # mỗi ảnh 1 CHỖ TRỐNG (không xếp chồng); có chỗ thả -> ảnh đầu đúng chỗ thả
        spots = self._spots_for(len(real), pos)
        for p, spot in zip(real, spots):
            item = {"path": p, "pos": spot}
            if nobg:
                item["nobg"] = True      # xoá nền y như "chuột phải -> Xoá nền"
            if len(ups) >= 20:
                ups[-1] = item
            else:
                ups.append(item)
        lst[index]["uploads"] = ups
        r["image_opts_list"] = lst
        self.store.upsert_task(self.current)
        self.store.save()
        self._load(self.current)
        self.recompose_image.emit(self.current, index)
        show_toast(self, f"Đã thêm {len(paths)} ảnh vào canvas", 2200)

    # ---------------- KÉO-THẢ ẢNH VÀO CANVAS ---------------- #
    @staticmethod
    def _drop_maybe_image(md) -> bool:
        """Dữ liệu kéo có thể là ảnh không? (file, link, ảnh nhị phân, HTML có <img>)."""
        try:
            if md is None:
                return False
            return bool(md.hasUrls() or md.hasImage() or md.hasHtml()
                        or (md.hasText() and md.text().strip()))
        except Exception:      # noqa: BLE001
            return False

    @classmethod
    def _drop_paths(cls, md) -> tuple[list[str], list[str]]:
        """Đọc dữ liệu kéo-thả -> (file ảnh trong máy, link ảnh cần tải).

        Hỗ trợ: file trong Finder · link http(s) · `data:image/...` (Google Images)
        · ảnh nhị phân trong dữ liệu kéo (Chrome/Firefox) · HTML có <img src=...>.
        """
        files: list[str] = []
        links: list[str] = []
        try:
            if md is None:
                return files, links
            try:
                cls._drop_log(f"drop: formats={md.formats()}")
            except Exception:      # noqa: BLE001
                pass
            # (1) ƯU TIÊN ảnh THẬT đính kèm trong dữ liệu kéo (Chrome/Google Images gửi
            #     application/x-qt-image) — KHÔNG cần tải link (link google là trang HTML).
            try:
                if md.hasImage():
                    qv = md.imageData()
                    img = qv if isinstance(qv, QImage) else QImage(qv)
                    if img is not None and not img.isNull():
                        p_img = cls._save_qimage(img)
                        if p_img:
                            files.append(p_img)
                            cls._drop_log(f"drop: dung anh dinh kem -> {Path(p_img).name}")
                            return files, links
            except Exception:      # noqa: BLE001
                pass
            if md.hasUrls():
                for u in md.urls():
                    lp = u.toLocalFile()
                    if lp:
                        if Path(lp).suffix.lower() in IMAGE_EXTS:
                            files.append(lp)
                        continue
                    s_url = u.toString()
                    if s_url.lower().startswith(("http://", "https://")):
                        links.append(s_url)
                    elif s_url.lower().startswith("data:image/"):
                        p = cls._save_data_uri(s_url)
                        if p:
                            files.append(p)
            # HTML có <img src="...">
            if not files and not links:
                try:
                    if md.hasHtml():
                        import re as _re
                        m = _re.search(r'<img[^>]+src=["\']([^"\']+)["\']',
                                       md.html() or "", _re.I)
                        if m:
                            src = m.group(1).strip()
                            if src.lower().startswith("data:image/"):
                                p = cls._save_data_uri(src)
                                if p:
                                    files.append(p)
                            elif src.lower().startswith(("http://", "https://")):
                                links.append(src)
                except Exception:      # noqa: BLE001
                    pass
            if not files and not links and md.hasText():
                txt = md.text().strip()
                if txt.lower().startswith(("http://", "https://")):
                    links.append(txt)
                elif txt.lower().startswith("data:image/"):
                    p = cls._save_data_uri(txt)
                    if p:
                        files.append(p)
        except Exception:      # noqa: BLE001
            pass
        return files, links

    @staticmethod
    def _drop_log(msg: str) -> None:
        """Ghi log CHẨN ĐOÁN cho tính năng kéo-thả (xem: <dữ liệu>/drop_debug.log)."""
        try:
            from datetime import datetime

            from ...config import app_data_dir

            with (app_data_dir() / "drop_debug.log").open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
        except Exception:      # noqa: BLE001
            pass

    @staticmethod
    def _ensure_readable_image(path: str) -> str:
        """Bảo đảm Qt ĐỌC ĐƯỢC ảnh; nếu không (AVIF, HEIC…) -> chuyển sang PNG.

        Trả về "" nếu file không phải ảnh -> KHÔNG thêm object vô hình vào canvas.
        """
        try:
            from PySide6.QtGui import QImageReader

            if not path or not Path(path).exists():
                JobsPage._drop_log(f"ensure: KHONG TON TAI {path}")
                return ""
            rd = QImageReader(path)
            if rd.canRead():
                return path
            JobsPage._drop_log(f"ensure: Qt KHONG doc duoc {path} | {rd.errorString()}")
            # Qt không đọc được -> thử chuyển bằng Pillow (AVIF/HEIC/...)
            from PIL import Image as _Img

            img = _Img.open(path)
            img.load()
            has_alpha = "A" in img.getbands() or img.mode in ("RGBA", "LA", "P")
            img = img.convert("RGBA" if has_alpha else "RGB")
            out = Path(path).with_suffix(".png")
            if out == Path(path):
                out = Path(path).with_name(Path(path).stem + "_conv.png")
            img.save(out, "PNG")
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:      # noqa: BLE001
                pass
            ok = QImageReader(str(out)).canRead()
            JobsPage._drop_log(f"ensure: chuyen PNG {'OK' if ok else 'LOI'} {out}")
            return str(out) if ok else ""
        except Exception as exc:      # noqa: BLE001
            JobsPage._drop_log(f"ensure: PIL LOI cho {path}: {type(exc).__name__}: {exc}")
            return ""

    @staticmethod
    def _save_qimage(img) -> str:
        """Lưu QImage (ảnh nhận từ dữ liệu kéo) vào media -> đường dẫn."""
        try:
            from datetime import datetime

            from ...config import media_dir

            d = media_dir()
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"keo_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            if img.save(str(p), "PNG"):
                return str(p)
        except Exception:      # noqa: BLE001
            traceback.print_exc()
        return ""

    @classmethod
    def _save_data_uri(cls, uri: str) -> str:
        """Giải mã `data:image/...;base64,...` -> lưu file, trả về đường dẫn."""
        try:
            import base64

            head, _, payload = str(uri or "").partition(",")
            if ";base64" not in head.lower() or not payload:
                return ""
            return cls._save_dropped_bytes(base64.b64decode(payload))
        except Exception:      # noqa: BLE001
            return ""

    def _spots_for(self, n: int, pos=None) -> list[list[float]]:
        """n chỗ đặt ảnh: ảnh đầu ĐÚNG chỗ thả (nếu có), còn lại là chỗ trống."""
        n = max(1, int(n or 1))
        free = self._find_free_spots(n) or [[0.5, 0.5]]
        if not pos:
            return free
        try:
            px = min(0.9, max(0.1, float(pos[0])))
            py = min(0.9, max(0.1, float(pos[1])))
        except Exception:      # noqa: BLE001
            return free
        out: list[list[float]] = [[round(px, 4), round(py, 4)]]
        for p in free:
            if len(out) >= n:
                break
            if abs(p[0] - px) < 0.15 and abs(p[1] - py) < 0.15:
                continue                      # quá gần ảnh vừa thả -> tránh chồng
            out.append(p)
        while len(out) < n:
            out.append([0.5, 0.5])
        return out

    def _drop_point(self, event) -> list[float]:
        """Đổi toạ độ con trỏ lúc thả -> tỉ lệ 0..1 trên canvas."""
        try:
            cv = self.img_editor.canvas
            p = event.position().toPoint()
            w = max(1, cv.width())
            h = max(1, cv.height())
            return [min(0.9, max(0.1, p.x() / w)), min(0.9, max(0.1, p.y() / h))]
        except Exception:      # noqa: BLE001
            return [0.5, 0.5]

    def _drop_on_canvas(self, event) -> bool:
        """Thả ảnh vào canvas -> thành thành phần như ảnh tải lên (kéo/resize/menu chuột phải)."""
        try:
            files, links = self._drop_paths(event.mimeData())
            if not files and not links:
                show_toast(self, "Không đọc được ảnh từ nội dung kéo", 2600, ok=False)
                return False
            if not self.isVisible() or not self.current:
                show_toast(self, "Chưa chọn công việc để thêm ảnh", 2400, ok=False)
                return False
            index = int(getattr(self, "_sel_index", 0))
            pos = self._drop_point(event)
            if files:
                self._add_upload_components(files, index, pos=pos)
            if links:
                self._drop_download_images(links, index, pos, self.current.id)
            return True
        except Exception:      # noqa: BLE001
            traceback.print_exc()
            return False

    @staticmethod
    def _save_dropped_bytes(data: bytes) -> str:
        """Lưu ảnh tải từ link vào thư mục media -> trả về đường dẫn."""
        from datetime import datetime

        from ...config import media_dir

        if not data:
            JobsPage._drop_log("save: du lieu RONG")
            return ""
        head = data[:16]
        JobsPage._drop_log(f"save: {len(data)} bytes | head={head[:8]!r}")
        if head.startswith(b"\x89PNG"):
            ext = ".png"
        elif head.startswith(b"\xff\xd8"):
            ext = ".jpg"
        elif data[8:12] == b"WEBP":
            ext = ".webp"
        elif head[:6] in (b"GIF87a", b"GIF89a"):
            ext = ".gif"
        else:
            ext = ".png"
        d = media_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"keo_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
        p.write_bytes(data)
        # Avatar Google thường là AVIF -> Qt không đọc được -> đổi sang PNG ngay
        return JobsPage._ensure_readable_image(str(p))

    def _drop_download_images(self, links: list[str], index: int, pos, task_id: str) -> None:
        """Ảnh kéo từ WEB (link http) -> tải ở luồng nền rồi thêm vào canvas."""
        try:
            from ..workers import SourceImageDownloadWorker
        except Exception:      # noqa: BLE001
            traceback.print_exc()
            return
        show_toast(self, f"Đang tải {len(links)} ảnh từ link…", 2200)
        saved: list[str] = []

        def _on_done(_url: str, data: bytes) -> None:
            try:
                p = self._save_dropped_bytes(data)
                if p:
                    saved.append(p)
            except Exception:      # noqa: BLE001
                pass

        w = SourceImageDownloadWorker(list(links))
        w.done.connect(_on_done)
        self._drop_jobs[w] = {"saved": saved, "index": index, "pos": pos, "task": task_id}
        w.finished.connect(self._on_drop_worker_finished)
        self._drop_workers.append(w)
        w.start()

    def _on_drop_worker_finished(self) -> None:
        """Tải link xong -> thêm ảnh vào canvas (chạy ở LUỒNG GIAO DIỆN)."""
        try:
            w = self.sender()
            info = getattr(self, "_drop_jobs", {}).pop(w, None)
            self._drop_workers = [x for x in getattr(self, "_drop_workers", []) if x is not w]
            if not info:
                return
            saved = list(info.get("saved") or [])
            self._drop_log(f"worker xong: saved={len(saved)}")
            if not saved:
                show_toast(self, "Không tải được ảnh từ link", 2600, ok=False)
                return
            if not self.current or getattr(self.current, "id", "") != info.get("task"):
                return                        # đã đổi job -> bỏ qua
            self._add_upload_components(saved, int(info.get("index") or 0),
                                         pos=info.get("pos"))
        except Exception:      # noqa: BLE001
            traceback.print_exc()

    def _fresh_current(self):
        """Bản MỚI NHẤT của job đang mở (tránh ghi đè bằng bản cũ đang giữ trong UI)."""
        if not self.current:
            return None
        fresh = next((t for t in self.store.tasks if t.id == self.current.id), None)
        if fresh is None:
            return self.current
        self.current = fresh          # UI theo bản mới nhất
        return fresh

    def _add_upload_component(self, path: str, index: int, pos=None) -> None:
        """Thêm 1 ảnh (tải lên / dán / chọn từ nguồn / KÉO-THẢ) thành thành phần trên canvas.

        `pos` = [x, y] (tỉ lệ 0..1) — chỗ THẢ CHUỘT; bỏ trống -> tự tìm chỗ trống.
        """
        if not self.current or not path:
            return
        path = self._ensure_readable_image(path)
        if not path:
            show_toast(self, "Ảnh không đọc được", 2400, ok=False)
            return
        self._save()
        fresh = self._fresh_current()
        if fresh is None:
            return
        r = fresh.result
        lst = r.get("image_opts_list") or []
        while len(lst) <= index:
            lst.append({})
        ups = list(lst[index].get("uploads") or [])
        # CHỖ THẢ CHUỘT nếu có, không thì TÌM CHỖ TRỐNG (giống tải lên / hình tự tìm)
        spot = (self._spots_for(1, pos) or [[0.5, 0.5]])[0]
        if len(ups) >= 20:
            ups[-1] = {"path": path, "pos": spot}         # đủ 20 -> thay cái cuối
        else:
            ups.append({"path": path, "pos": spot})
        lst[index]["uploads"] = ups
        r["image_opts_list"] = lst
        self.store.upsert_task(self.current)
        self.store.save()
        self._load(self.current)
        self.recompose_image.emit(self.current, index)


    def _clone_task(self, task_id: str) -> None:
        """Nhân bản job: CHỈ giữ HÌNH (ảnh đã ghép + ảnh chèn canvas), các ô khác để trống."""
        src = next((t for t in self.store.tasks if t.id == task_id), None)
        if src is None:
            return
        self._save()                     # chốt thông tin đang gõ của job hiện tại
        r = src.result or {}
        count = max(1, int(getattr(src, "image_count", 3) or 3))
        t = Task(
            kind="blank",                # job trống -> không có link nguồn
            status=STATUS_FINISH,
            progress=100,
            image_count=count,
            footer_mode=str(getattr(src, "footer_mode", "random") or "random"),
            brand_logo_fallback=str(getattr(src, "brand_logo_fallback", "") or ""),
        )
        slots = [dict(x) for x in (r.get("images") or []) if isinstance(x, dict)]
        if not slots:
            slots = [{"path": "", "footer": ""} for _ in range(count)]
        opts = [dict(x) for x in (r.get("image_opts_list") or []) if isinstance(x, dict)]
        t.result = {
            "title": "", "focus_keyword": "", "description": "", "tags": "",
            "category_name": "", "brand_name": "", "ma_san_pham": "",
            "content_html": "",
            "images": slots,
            "image_opts_list": opts,
            "product_images": [x for x in (r.get("product_images") or []) if x],
            "brand_logo": str(r.get("brand_logo") or ""),
        }
        self.store.upsert_task(t)
        self.store.save()
        self.refresh()
        self.select_task(t.id)
        show_toast(self, "Đã nhân bản công việc (chỉ giữ hình)", 2800)

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

    def _init_autosave(self) -> None:
        """TỰ LƯU sau khi ngừng gõ ~1 giây (khỏi mất thông tin khi đổi job / tắt app)."""
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)
        self._save_timer.timeout.connect(self._autosave)
        for w in (self.title_edit, self.kw_edit, self.desc_edit, self.tags_edit,
                  self.cat_edit, self.brand_edit, self.models_edit):
            try:
                w.textChanged.connect(self._queue_save)
            except Exception:      # noqa: BLE001
                pass

    def _queue_save(self, *args) -> None:
        """Có thay đổi ở ô thông tin -> hẹn tự lưu sau 1 giây."""
        if getattr(self, "_loading", False):
            return                      # đang nạp job -> không lưu lại
        try:
            self._save_timer.start()
        except Exception:      # noqa: BLE001
            pass

    def _autosave(self) -> None:
        if getattr(self, "_loading", False):
            return
        try:
            self._save()
        except Exception:      # noqa: BLE001
            pass

    def _save(self) -> None:
        if not self.current:
            return
        # CHỐT AN TOÀN: panel đang hiển thị JOB KHÁC (đang chuyển job) -> KHÔNG ghi đè
        loaded = getattr(self, "_loaded_task_id", "")
        if loaded and loaded != getattr(self.current, "id", ""):
            return
        r = self.current.result
        r["title"] = self.title_edit.text()
        r["focus_keyword"] = self.kw_edit.text()
        r["description"] = self.desc_edit.toPlainText()
        r["tags"] = self.tags_edit.text()
        r["category_name"] = self.cat_edit.text()
        r["brand_name"] = self.brand_edit.text()
        r["ma_san_pham"] = self.models_edit.text()
        r["content_html"] = self.content_edit.get_html()
        self.store.upsert_task(self.current)
        self.store.save()
        self.refresh_info()      # vừa gõ/lưu -> cập nhật ngay "Thông tin đã đầy đủ / Thiếu thông tin"
