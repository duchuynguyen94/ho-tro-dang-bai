"""Màn hình 'Cài đặt'."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import formats_dir, media_dir
from ...storage import Script, ScriptStep, Site, crypto
from ...storage.store import Store
from ..style import Card, make_cfg_panel, polish_combos
from ..toast import show_toast
from ..widgets.update_panel import UpdatePanel
from ..workers import LoginWorker, OpenLoginWorker

IMAGE_FILTER = "Ảnh (*.png *.jpg *.jpeg *.webp *.svg);;Tất cả (*.*)"
FORMAT_FILTER = "Quy định (*.txt *.html *.htm *.pdf *.doc *.docx);;Tất cả (*.*)"


def _pick_file(parent, caption, filt) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, caption, "", filt)
    return path or ""


def _wrap_scroll(w: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setObjectName("siteTabScroll")      # nền trong suốt (xem style.py)
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    s.setWidget(w)
    return s


def _form(parent=None) -> QFormLayout:
    """QFormLayout canh trái, field giãn hết chiều rộng (nhất quán mọi nền tảng)."""
    f = QFormLayout(parent)
    f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    f.setRowWrapPolicy(QFormLayout.DontWrapRows)
    f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    f.setHorizontalSpacing(16)
    f.setVerticalSpacing(12)
    return f


class ConfigPage(QWidget):
    changed = Signal()

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._panels: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, QPushButton] = {}
        self._build()
        self.reload()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # sidebar
        side = QWidget()
        side.setObjectName("sideBar")
        side.setFixedWidth(250)
        self.side_layout = QVBoxLayout(side)
        self.side_layout.setContentsMargins(10, 12, 10, 12)
        self.side_layout.setSpacing(2)
        outer.addWidget(side)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        # xoá sidebar cũ
        while self.side_layout.count():
            it = self.side_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self._panels.clear()

        def section(text):
            lab = QLabel(text.upper())
            lab.setProperty("class", "section")
            self.side_layout.addWidget(lab)

        def nav_button(text, key, checked=False):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(checked)
            btn.clicked.connect(lambda: self._show(key))
            self.side_layout.addWidget(btn)
            self._nav_buttons[key] = btn
            return btn

        self._nav_buttons: dict[str, QPushButton] = {}
        section("Website WordPress")
        for site in self.store.sites:
            panel = SitePanel(self.store, site)
            panel.saved.connect(self._on_site_saved)
            panel.deleted.connect(self._on_site_deleted)
            key = f"site:{site.id}"
            self._panels[key] = panel
            self.stack.addWidget(panel)
            nav_button(site.name or site.url, key)

        add = QPushButton("+ Thêm website")
        add.clicked.connect(self._add_site)
        self.side_layout.addWidget(add)

        section("Thiết lập chung")
        ai_c = AIContentPanel(self.store)
        ai_i = AIImagePanel(self.store)
        fmt = FormatPanel(self.store, self.changed.emit)
        tlinks = TitleLinksPanel(self.store, self.changed.emit)
        updt = UpdatePanel(self.store)
        for key, panel, label in [
            ("ai_content", ai_c, "AI nội dung"),
            ("ai_image", ai_i, "AI ảnh"),
            ("format", fmt, "Format Rule"),
            ("title_links", tlinks, "Link tiêu đề"),
            ("update", updt, "Cập nhật phần mềm"),
        ]:
            self._panels[key] = panel
            self.stack.addWidget(panel)
            nav_button(label, key)

        self.side_layout.addStretch(1)
        first_key = next(iter(self._panels), None)
        if first_key:
            self._show(first_key)
        polish_combos(self)

    def _show(self, key: str) -> None:
        if key not in self._panels:
            return
        self.stack.setCurrentWidget(self._panels[key])
        for k, btn in getattr(self, "_nav_buttons", {}).items():
            btn.setChecked(k == key)
        self._current_key = key

    # ------------------------------------------------------------------ #
    def _add_site(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        name, ok = QInputDialog.getText(
            self, "Thêm website", "Nhập tên website (ví dụ: demo.com):"
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập tên website.")
            return
        if any((s.name or "").strip().lower() == name.lower() for s in self.store.sites):
            QMessageBox.warning(self, "Trùng website", f"Website “{name}” đã tồn tại.")
            return
        if any((s.url or "").strip().lower().rstrip("/") in (f"https://{name}".lower(), name.lower())
               for s in self.store.sites):
            QMessageBox.warning(self, "Trùng website", f"Website “{name}” đã tồn tại.")
            return

        base = name if name.startswith(("http://", "https://")) else f"https://{name}"
        site = Site(
            name=name,
            url=base,
            new_post_url=f"{base.rstrip('/')}/wp-admin/post-new.php?post_type=product",
            # watermark: để trống -> dùng mặc định của phần mềm
        )
        self.store.upsert_site(site)
        self.store.save()
        self.reload()
        self._show(f"site:{site.id}")     # mở luôn panel của website vừa thêm

    def _on_site_saved(self) -> None:
        self.changed.emit()
        key = getattr(self, "_current_key", None)
        if key and key.startswith("site:"):
            site = self.store.get_site(key.split(":", 1)[1])
            btn = self._nav_buttons.get(key)
            if site and btn:
                btn.setText(site.name or site.url)

    def _on_site_deleted(self) -> None:
        self.changed.emit()
        self.reload()


# ======================================================================= #
# Panel cấu hình 1 website
# ======================================================================= #
class SitePanel(QWidget):
    saved = Signal()
    deleted = Signal()

    def __init__(self, store: Store, site: Site, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.site = store.get_site(site.id) or site
        self._steps: list[dict] = [s.to_dict() for s in (self.site.script.steps if self.site.script else [])]
        self.login_worker: LoginWorker | None = None
        self._build()
        self._load()

    def _build(self) -> None:
        self.setObjectName("sitePanel")                       # nền #f8fafc
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 20)

        head = QHBoxLayout()
        self.title = QLabel(self.site.name)
        self.title.setProperty("class", "h2")
        head.addWidget(self.title)
        head.addStretch(1)
        save = QPushButton("Lưu")
        save.setProperty("class", "primary")
        save.clicked.connect(lambda: self._save())
        head.addWidget(save)
        outer.addLayout(head)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.tabs.addTab(_wrap_scroll(self._info_tab()), "Thông tin site")
        self.tabs.addTab(_wrap_scroll(self._account_tab()), "Tài khoản đăng nhập")
        self.tabs.addTab(_wrap_scroll(self._script_tab()), "Kịch bản đăng bài")
        self.tabs.addTab(_wrap_scroll(self._media_tab()), "Logo / Khung")

    # ---------------- Thông tin ---------------- #
    def _info_tab(self) -> QWidget:
        w = QWidget()
        f = _form(w)
        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.newpost_edit = QLineEdit()
        f.addRow("Tên gọi", self.name_edit)
        f.addRow("URL website", self.url_edit)
        f.addRow("Link trang tạo bài viết", self.newpost_edit)

        del_btn = QPushButton("Xoá website này")
        del_btn.setProperty("class", "danger")
        del_btn.clicked.connect(self._delete_site)
        f.addRow(del_btn)
        return w

    # ---------------- Tài khoản ---------------- #
    def _account_tab(self) -> QWidget:
        w = QWidget()
        f = _form(w)
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        f.addRow("Tài khoản (username/email)", self.user_edit)
        f.addRow("Mật khẩu", self.pass_edit)
        note = QLabel("Mật khẩu được mã hoá khi lưu. Session đăng nhập được giữ lại cho lần sau.")
        note.setProperty("class", "hint")
        note.setWordWrap(True)
        f.addRow(note)

        self.login_btn = QPushButton("Đăng nhập thử (mở trình duyệt xem)")
        self.login_btn.setProperty("class", "ghost")
        self.login_btn.clicked.connect(self._test)
        f.addRow(self.login_btn)

        self.login_status = QLabel("")
        self.login_status.setProperty("class", "hint")
        self.login_status.setWordWrap(True)
        f.addRow(self.login_status)
        return w

    # ---------------- Kịch bản ---------------- #
    def _script_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)

        bar = QHBoxLayout()
        for label, slot in [
            ("⬇ Export", self._export),
            ("⬆ Import (thay kịch bản cũ)", self._import),
        ]:
            b = QPushButton(label)
            b.setProperty("class", "ghost")
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch(1)
        save = QPushButton("Lưu thay đổi")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save_steps)
        bar.addWidget(save)
        v.addLayout(bar)

        self.script_table = QTableWidget(0, 4)
        self.script_table.setHorizontalHeaderLabels(
            ["#", "Hành động", "Selector ưu tiên (HTML)", "Nguồn"]
        )
        self.script_table.horizontalHeader().setStretchLastSection(True)
        self.script_table.setColumnWidth(2, 420)
        v.addWidget(self.script_table, 1)
        return w

    # ---------------- Logo / Khung / Watermark ---------------- #
    MEDIA_FIELDS = {
        "logo": ("Logo website (trên-trái)", "logo.png", "Chọn logo website"),
        "bar1": ("Thanh thông tin dưới — hình 1", "bar1.png", "Thanh thông tin — hình 1"),
        "bar2": ("Thanh thông tin dưới — hình 2", "bar2.png", "Thanh thông tin — hình 2"),
    }

    def _media_tab(self) -> QWidget:
        """Logo + 2 thanh thông tin: xem trước ảnh, dùng mặc định nếu chưa chọn file."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        self._media_rows: dict[str, dict] = {}

        note = QLabel(
            "Website <b>chưa chọn file</b> thì phần mềm dùng <b>bộ mặc định</b> (logo + 2 thanh thông tin). "
            "Chọn file riêng thì dùng file của bạn; bấm <b>Xoá</b> để quay về mặc định."
        )
        note.setProperty("class", "sub")
        note.setWordWrap(True)
        v.addWidget(note)

        # ---- URL watermark (chữ chéo trên ảnh) ----
        wm_card = Card("URL watermark (chữ chéo trên ảnh)")
        self.watermark_edit = QLineEdit(self.site.watermark or "")
        self.watermark_edit.setPlaceholderText("https://ngochuyduong.com")
        self.watermark_edit.setToolTip(
            "Để trống thì dùng mặc định https://ngochuyduong.com cho mọi website"
        )
        self.watermark_edit.editingFinished.connect(lambda: self._save(silent=True))
        # tiêu đề SÁT ô nhập: giảm padding dưới header + margin trên body + spacing
        wm_card.header_layout.setContentsMargins(14, 11, 14, 8)   # tiêu đề <-> ô nhập = 8px
        wm_card.body.setContentsMargins(14, 0, 14, 12)
        wm_card.body.setSpacing(8)      # ô nhập ↔ dòng ghi chú
        wm_card.body.addWidget(self.watermark_edit)
        wm_note = QLabel("Để trống → mặc định <b>https://ngochuyduong.com</b>")
        wm_note.setProperty("class", "sub")
        wm_card.body.addWidget(wm_note)
        v.addWidget(wm_card)

        for kind in ("logo", "bar1", "bar2"):
            v.addWidget(self._media_row(kind))
        v.addStretch(1)
        return w

    def _media_row(self, kind: str) -> QWidget:
        title, _dflt, _cap = self.MEDIA_FIELDS[kind]
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        thumb = QLabel()
        thumb.setObjectName("imgThumb")
        thumb.setFixedSize(96, 96)
        thumb.setAlignment(Qt.AlignCenter)
        h.addWidget(thumb)

        right = QVBoxLayout()
        right.setSpacing(2)                    # tiêu đề ↔ mô tả
        lab = QLabel(title)
        lab.setStyleSheet("font-weight:600;")
        lab.setFixedHeight(lab.fontMetrics().height() + 6)   # giảm ~1 nửa leading
        right.addWidget(lab)
        status = QLabel("")
        status.setProperty("class", "sub")
        status.setWordWrap(True)
        right.addWidget(status)

        row = QHBoxLayout()
        pick = QPushButton("Chọn file riêng…")
        pick.setProperty("class", "ghost")
        pick.clicked.connect(lambda _=False, k=kind: self._pick_media(k))
        clear = QPushButton("Xoá")
        clear.setProperty("class", "danger")
        clear.setToolTip("Bỏ file riêng — quay về bộ mặc định của phần mềm")
        clear.clicked.connect(lambda _=False, k=kind: self._clear_media(k))
        row.addWidget(pick)
        row.addWidget(clear)
        row.addStretch(1)
        right.addLayout(row)
        h.addLayout(right, 1)

        self._media_rows[kind] = {"thumb": thumb, "status": status, "clear": clear}
        return box

    # ---------------- logo / thanh thông tin ---------------- #
    def _media_path(self, kind: str) -> str:
        s = self.site
        if kind == "logo":
            return s.logo_path or ""
        bars = list(s.footer_bars or [])
        i = 0 if kind == "bar1" else 1
        return bars[i] if len(bars) > i else ""

    def _set_media_path(self, kind: str, path: str) -> None:
        s = self.site
        if kind == "logo":
            s.logo_path = path
            return
        bars = list(s.footer_bars or [])
        i = 0 if kind == "bar1" else 1
        while len(bars) <= i:
            bars.append("")
        bars[i] = path
        s.footer_bars = bars

    def _pick_media(self, kind: str) -> None:
        _title, _dflt, caption = self.MEDIA_FIELDS[kind]
        path, _ = QFileDialog.getOpenFileName(self, caption, "", IMAGE_FILTER)
        if not path:
            return
        try:
            new_path = Store.import_file(path, media_dir())
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Không chọn được ảnh: {exc}", 3200, ok=False)
            return
        if not new_path:
            show_toast(self, "Không chọn được ảnh", 3200, ok=False)
            return
        self._set_media_path(kind, new_path)
        self._save(silent=True)
        self._refresh_media()

    def _clear_media(self, kind: str) -> None:
        self._set_media_path(kind, "")
        self._save(silent=True)
        self._refresh_media()

    def _refresh_media(self) -> None:
        from ...config import default_asset

        for kind, (_title, dflt, _cap) in self.MEDIA_FIELDS.items():
            ref = self._media_rows.get(kind)
            if not ref:
                continue
            own = self._media_path(kind)
            shown = own or default_asset(dflt)
            if shown and Path(shown).exists():
                pix = QPixmap(shown)
                ref["thumb"].setText("")
                ref["thumb"].setPixmap(
                    pix.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            else:
                ref["thumb"].setPixmap(QPixmap())
                ref["thumb"].setText("—")
            if own:
                ref["status"].setText(f"File riêng: <b>{Path(own).name}</b>")
            else:
                ref["status"].setText("Đang dùng <b>mặc định của phần mềm</b>")
            ref["clear"].setVisible(bool(own))

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        s = self.site
        self.name_edit.setText(s.name)
        self.url_edit.setText(s.url)
        self.newpost_edit.setText(s.new_post_url)
        self.user_edit.setText(s.username)
        self.pass_edit.setText(s.get_password())
        self.watermark_edit.setText(s.watermark or "")
        self._refresh_media()
        self._refresh_steps()

    def _refresh_steps(self) -> None:
        self.script_table.setRowCount(len(self._steps))
        for i, st in enumerate(self._steps):
            self.script_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.script_table.setItem(i, 1, QTableWidgetItem(st.get("note") or st.get("action", "")))
            self.script_table.setItem(i, 2, QTableWidgetItem(st.get("selector", "")))
            src = {"recorded": "Ghi lại", "auto": "Tự động", "fallback": "Dự phòng"}.get(
                st.get("source", "recorded"), "Ghi lại"
            )
            self.script_table.setItem(i, 3, QTableWidgetItem(src))

    def _pick_into(self, edit: QLineEdit, caption: str, filt: str = IMAGE_FILTER) -> None:
        """Chọn ảnh (logo / thanh thông tin / khung) — copy vào thư mục media."""
        path, _ = QFileDialog.getOpenFileName(self, caption, "", filt)
        if not path:
            return
        try:
            new_path = Store.import_file(path, media_dir())
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Không chọn được ảnh: {exc}", 3200, ok=False)
            return
        if not new_path:
            show_toast(self, "Không chọn được ảnh", 3200, ok=False)
            return
        edit.setText(new_path)

    # ------------------------------------------------------------------ #
    def _save_steps(self) -> None:
        try:
            steps: list[dict] = []
            for i in range(self.script_table.rowCount()):
                old = dict(self._steps[i]) if i < len(self._steps) else {}
                old["note"] = self._cell(i, 1)
                old["selector"] = self._cell(i, 2)
                old.setdefault("action", "click")
                old.setdefault("value", "")
                old.setdefault("selectors", [])
                old.setdefault("source", "recorded")
                steps.append(old)
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Lưu kịch bản THẤT BẠI: {exc}", 3400, ok=False)
            return
        self._apply_steps(steps, "Đã lưu kịch bản")

    def _cell(self, row: int, col: int) -> str:
        item = self.script_table.item(row, col)
        return item.text() if item else ""

    def _apply_steps(self, steps: list[dict], msg: str) -> None:
        """Ghi kịch bản vào cấu hình website (tự lưu)."""
        try:
            self._steps = steps
            self.site.script = (Script(steps=[ScriptStep.from_dict(x) for x in steps])
                                if steps else None)
            self.store.upsert_site(self.site)
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"{msg} THẤT BẠI: {exc}", 3400, ok=False)
            return
        self._refresh_steps()
        show_toast(self, msg)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export kịch bản", f"{self.site.name}-kichban.json", "JSON (*.json)"
        )
        if not path:
            return
        data = {"site": self.site.name, "steps": self._steps, "version": 1}
        try:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            show_toast(self, f"Export kịch bản THẤT BẠI: {exc}", 3600, ok=False)
            return
        show_toast(self, f"Đã export kịch bản ({len(self._steps)} bước) → {Path(path).name}", 3000)

    def _import(self) -> None:
        """Import kịch bản từ file — THAY LUÔN kịch bản cũ và tự lưu."""
        path = _pick_file(self, "Import kịch bản", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            show_toast(self, f"File kịch bản không đọc được: {exc}", 3400, ok=False)
            return
        steps = [dict(x) for x in (data.get("steps") or []) if isinstance(x, dict)]
        if not steps:
            show_toast(self, "File kịch bản không có bước nào", 3400, ok=False)
            return
        self._apply_steps(steps, f"Đã import kịch bản ({len(steps)} bước) — thay kịch bản cũ")

    def _test(self) -> None:
        if self.login_worker and self.login_worker.isRunning():
            self.login_worker.stop()
            self.login_worker = None
            self.login_btn.setText("Đăng nhập thử (mở trình duyệt xem)")
            self.login_status.setText("Đã dừng.")
            return

        self._save(silent=True)
        self.login_worker = LoginWorker(self.site)
        self.login_worker.log.connect(self.login_status.setText)
        self.login_worker.ok.connect(
            lambda good: self.login_status.setText(
                "✓ Đăng nhập thành công!" if good else "✗ Chưa đăng nhập được — thử lại trên cửa sổ trình duyệt."
            )
        )
        self.login_worker.failed.connect(lambda err: self.login_status.setText("Lỗi: " + err))
        self.login_worker.finished.connect(lambda: self.login_btn.setText("Đăng nhập thử (mở trình duyệt xem)"))
        self.login_worker.start()
        self.login_btn.setText("■ Dừng")
        self.login_status.setText("Đang mở trình duyệt…")

    # ------------------------------------------------------------------ #
    def _delete_site(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        ans = QMessageBox.question(
            self,
            "Xoá website",
            f"Xoá website “{self.site.name}” và toàn bộ cấu hình của nó?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self.store.remove_site(self.site.id)
        self.store.save()
        self.deleted.emit()

    # ------------------------------------------------------------------ #
    def _save(self, silent: bool = False) -> None:
        try:
            s = self.site
            s.name = self.name_edit.text().strip()
            s.url = self.url_edit.text().strip()
            s.new_post_url = self.newpost_edit.text().strip()
            s.watermark = self.watermark_edit.text().strip()   # để trống -> mặc định
            s.username = self.user_edit.text().strip()
            if self.pass_edit.text():
                s.set_password(self.pass_edit.text())
            # logo / thanh thông tin: đã lưu ngay khi chọn hoặc xoá (xem _pick_media/_clear_media)
            if self._steps:
                s.script = Script(steps=[ScriptStep.from_dict(st) for st in self._steps])
            self.store.upsert_site(s)
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            if not silent:
                show_toast(self, f"Lưu website THẤT BẠI: {exc}", 3400, ok=False)
            return
        if not silent:
            show_toast(self, "Đã lưu website")
        self.saved.emit()


# ======================================================================= #
# Panel AI nội dung
# ======================================================================= #
PROVIDER_LABELS = {
    "gemini": "Google Gemini",
    "groq": "Groq",
    "deepseek": "DeepSeek",
    "chatgpt": "ChatGPT (qua trình duyệt)",
    "openai": "OpenAI API",
}
FREE = {"gemini": "FREE", "groq": "FREE", "deepseek": "RẺ",
        "chatgpt": "FREE*", "openai": "TRẢ PHÍ"}


class DragHandle(QLabel):
    """Tay cầm kéo-thả để sắp xếp thứ tự provider."""

    def __init__(self, key: str, parent=None) -> None:
        super().__init__("⠿", parent)
        self.key = key
        self.setFixedWidth(18)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Kéo để đổi thứ tự ưu tiên (trên = ưu tiên cao hơn)")
        self.setStyleSheet("color:#94a3b8;font-size:16px;")
        self._press = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press = event.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None:
            return
        if (event.pos() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        card = self.parentWidget()
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.key)
        drag.setMimeData(mime)
        pm = card.grab()
        drag.setPixmap(pm.scaled(pm.width() // 2, pm.height() // 2,
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation))
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press = None


class ProviderList(QWidget):
    """Danh sách provider cho phép kéo-thả đổi thứ tự."""

    orderChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(10)
        self.cards: dict[str, QWidget] = {}
        self.number_labels: dict[str, QLabel] = {}

    def add_card(self, key: str, card: QWidget, number_label: QLabel) -> None:
        self.cards[key] = card
        self.number_labels[key] = number_label
        card.setAcceptDrops(False)
        for child in card.findChildren(QWidget):
            child.setAcceptDrops(False)
        self.vbox.addWidget(card)
        self.renumber()

    def keys(self) -> list[str]:
        out: list[str] = []
        for i in range(self.vbox.count()):
            w = self.vbox.itemAt(i).widget()
            if w is None:
                continue
            for k, c in self.cards.items():
                if c is w:
                    out.append(k)
                    break
        return out

    def renumber(self) -> None:
        for i, key in enumerate(self.keys(), 1):
            lab = self.number_labels.get(key)
            if lab:
                lab.setText(f"{i}")

    # ---- drag & drop ----
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        key = event.mimeData().text()
        card = self.cards.get(key)
        if card is None:
            return
        pos = event.position().toPoint().y()
        idx = self.vbox.count()
        for i in range(self.vbox.count()):
            w = self.vbox.itemAt(i).widget()
            if w is None or w is card:
                continue
            if pos < w.y() + w.height() // 2:
                idx = i
                break
        cur = self.vbox.indexOf(card)
        self.vbox.removeWidget(card)
        if cur < idx:
            idx -= 1
        self.vbox.insertWidget(max(0, idx), card)
        self.renumber()
        self.orderChanged.emit()
        event.acceptProposedAction()


class AIContentPanel(QWidget):
    """Cài đặt AI nội dung — nút Lưu GHIM cố định trên đầu panel."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._rows: dict[str, dict] = {}
        self._group = QButtonGroup(self)      # đảm bảo "Mặc định" là duy nhất
        self._group.setExclusive(True)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 12)
        outer.setSpacing(10)

        # ---- header cố định: tiêu đề + nút Lưu (luôn hiển thị khi cuộn) ----
        head = QHBoxLayout()
        title = QLabel("AI nội dung")
        title.setProperty("class", "h2")
        head.addWidget(title)
        head.addStretch(1)
        self.fallback = QCheckBox("Fallback tự động")
        self.fallback.setToolTip(
            "Provider lỗi / hết lượt → tự chuyển sang provider kế tiếp theo thứ tự bên dưới"
        )
        self.fallback.setChecked(bool(self.store.ai_content.get("fallback", True)))
        head.addWidget(self.fallback)
        head.addSpacing(16)                    # không dính sát nút Lưu
        save = QPushButton("Lưu cấu hình AI nội dung")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        head.addWidget(save)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 8)
        v.setSpacing(10)

        sub = QLabel(
            "Ưu tiên miễn phí. <b>Kéo ⠿ để đổi thứ tự</b> — thứ tự này là thứ tự gọi khi bật "
            "<b>Fallback tự động</b>. Chọn 1 provider làm mặc định (gọi trước tiên)."
        )
        sub.setProperty("class", "sub")
        sub.setWordWrap(True)
        v.addWidget(sub)

        cfg = self.store.ai_content
        order = [p for p in (cfg.get("order") or []) if p in cfg["providers"]]
        order += [p for p in cfg["providers"] if p not in order]

        self.list = ProviderList()
        self.list.orderChanged.connect(self._save)
        for key in order:
            pcfg = cfg["providers"].get(key, {})
        # nạp theo đúng thứ tự
        for key in order:
            pcfg = cfg["providers"].get(key, {})
            card, num = self._make_card(key, pcfg)
            self.list.add_card(key, card, num)
        v.addWidget(self.list)

        v.addStretch(1)
        scroll.setWidget(root)
        outer.addWidget(scroll, 1)
        make_cfg_panel(self)

    def _make_card(self, key: str, pcfg: dict):
        card = Card(PROVIDER_LABELS.get(key, key))
        num = QLabel("")
        num.setObjectName("chipBlue")
        handle = DragHandle(key)
        card.header_layout.insertWidget(0, handle)
        card.header_layout.insertWidget(1, num)
        badge = QLabel(FREE.get(key, ""))
        badge.setStyleSheet("color:#047857;font-size:11px;font-weight:700;")
        card.add_header_widget(badge)
        radio = QCheckBox("Mặc định")
        radio.setChecked(self.store.ai_content.get("active") == key)
        self._group.addButton(radio)
        card.add_header_widget(radio)

        body = card.body
        key_edit = None
        model_edit = None
        project_edit = None

        if key == "chatgpt":
            note = QLabel(
                "Không cần API key. Phần mềm dùng <b>trình duyệt riêng</b> để mở ChatGPT; "
                "bạn đăng nhập 1 lần, phiên được lưu lại."
            )
            note.setProperty("class", "hint")
            note.setWordWrap(True)
            body.addWidget(note)
            body.addWidget(QLabel("URL Project"))
            project_edit = QLineEdit(pcfg.get("project_url", ""))
            project_edit.setPlaceholderText("https://chatgpt.com/g/g-p-xxxx-ten-du-an/project")
            body.addWidget(project_edit)
            pnote = QLabel(
                "Mở Project trên ChatGPT → copy URL trên thanh địa chỉ → dán vào đây. "
                "Để trống nếu muốn chat ở ChatGPT thường. Nội dung sẽ được tạo <b>trong đúng Project này</b>."
            )
            pnote.setProperty("class", "hint")
            pnote.setWordWrap(True)
            body.addWidget(pnote)
            self.show_browser = QCheckBox("Hiện cửa sổ Chrome khi tạo nội dung")
            self.show_browser.setChecked(bool(pcfg.get("show_browser", False)))
            body.addWidget(self.show_browser)
            btn = QPushButton("Đăng nhập / Mở trình duyệt xem")
            btn.setProperty("class", "ghost")
            btn.clicked.connect(lambda _=False, b=btn: self._login_chatgpt(b))
            body.addWidget(btn)
        else:
            key_edit = QLineEdit()
            key_edit.setEchoMode(QLineEdit.Password)
            key_edit.setPlaceholderText("API Key")
            key_edit.setText(crypto.decrypt(pcfg.get("api_key_enc", "")))
            body.addWidget(key_edit)
            # nhãn "Model" ↔ ô nhập: 9px (các cặp khác trong card vẫn 10px)
            mbox = QVBoxLayout()
            mbox.setSpacing(9)
            mbox.addWidget(QLabel("Model"))
            model_edit = QLineEdit(pcfg.get("model", ""))
            mbox.addWidget(model_edit)
            body.addLayout(mbox)

        self._rows[key] = {"key": key_edit, "model": model_edit,
                           "project": project_edit, "radio": radio}
        return card, num

    def _save(self) -> None:
        try:
            cfg = self.store.ai_content
            for key, row in self._rows.items():
                p = cfg["providers"].setdefault(key, {})
                if row.get("key") is not None:
                    p["api_key_enc"] = crypto.encrypt(row["key"].text().strip())
                if row.get("model") is not None and row["model"].text().strip():
                    p["model"] = row["model"].text().strip()
                if row.get("project") is not None:
                    p["project_url"] = row["project"].text().strip()
                if key == "chatgpt" and getattr(self, "show_browser", None) is not None:
                    p["show_browser"] = self.show_browser.isChecked()
                if row["radio"].isChecked():
                    cfg["active"] = key
            cfg["order"] = self.list.keys()
            cfg["fallback"] = self.fallback.isChecked()
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Lưu AI nội dung THẤT BẠI: {exc}", 3400, ok=False)
            return
        show_toast(self, "Đã lưu AI nội dung")

    def _login_chatgpt(self, btn) -> None:
        if getattr(self, "_chatgpt_worker", None) and self._chatgpt_worker.isRunning():
            self._chatgpt_worker.stop()
            self._chatgpt_worker = None
            btn.setText("Đăng nhập ChatGPT")
            return
        w = OpenLoginWorker("https://chatgpt.com/", "chatgpt", title="ChatGPT")
        self._chatgpt_worker = w
        w.log.connect(lambda m: show_toast(self, m, 2500))
        w.failed.connect(lambda e: show_toast(self, "Lỗi: " + e[:40], 3000))
        w.finished.connect(lambda: btn.setText("Đăng nhập ChatGPT"))
        w.start()
        btn.setText("■ Đóng trình duyệt")


class AIImagePanel(QWidget):
    """Cài đặt AI ảnh — nút Lưu GHIM cố định trên đầu panel."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._providers: list[QWidget] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 12)
        outer.setSpacing(10)

        # ---- header cố định: tiêu đề + nút Lưu (luôn hiển thị khi cuộn) ----
        head = QHBoxLayout()
        t = QLabel("AI ảnh")
        t.setProperty("class", "h2")
        head.addWidget(t)
        head.addStretch(1)
        save = QPushButton("Lưu cấu hình AI ảnh")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        head.addWidget(save)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 8)
        v.setSpacing(10)

        sub = QLabel("Gắn logo / khung / watermark / thanh thông tin và chỉnh sửa ảnh sản phẩm.")
        sub.setProperty("class", "sub")
        v.addWidget(sub)

        cfg = self.store.ai_image

        # ---- Xử lý ảnh cục bộ (Pillow): luôn bật, bỏ ô tick + bỏ ghi chú ----
        c1 = Card("Xử lý ảnh cục bộ (Pillow)")
        form = _form()
        self.out_fmt = QComboBox()
        self.out_fmt.addItems(["PNG (giữ trong suốt)", "JPG"])
        self.out_fmt.setCurrentIndex(0 if cfg["pillow"].get("output_format", "PNG") == "PNG" else 1)
        form.addRow("Định dạng xuất", self.out_fmt)
        self.size_combo = QComboBox()
        self.size_combo.addItems(["1080 × 1080 (mặc định)", "1200 × 1200", "Giữ nguyên"])
        try:
            _size = int(cfg["pillow"].get("size", 1080) or 0)
        except (TypeError, ValueError):
            _size = 1080
        self.size_combo.setCurrentIndex(0 if _size == 1080 else (1 if _size == 1200 else 2))
        form.addRow("Kích thước ảnh xuất", self.size_combo)
        c1.body.addLayout(form)
        v.addWidget(c1)

        # ---- Tắt AI chỉnh ảnh: công tắc CHUNG, đặt TRÊN danh sách provider ----
        c2 = Card("")
        self.ai_off = QCheckBox("Tắt AI chỉnh ảnh — chỉ dùng Pillow để cắt ghép (không gọi AI)")
        self.ai_off.setChecked(cfg.get("active") == "off")
        self.ai_off.toggled.connect(self._toggle_providers)
        c2.body.addWidget(self.ai_off)
        v.addWidget(c2)

        # ---- AI chỉnh sửa ảnh (các provider) ----
        c3 = Card("AI chỉnh sửa ảnh")
        grid = QGridLayout()
        self._img_rows: dict[str, dict] = {}
        self._img_group = QButtonGroup(self)
        self._img_group.setExclusive(True)
        idx = 0
        for key, pcfg in cfg["providers"].items():
            if key == "off":
                continue                      # đã tách thành công tắc ở trên
            label = {"gemini": "Google Gemini", "fal": "fal.ai — Flux Kontext",
                     "openai": "OpenAI Images"}.get(key, key)
            card = Card(label)
            radio = QCheckBox("Mặc định")
            radio.setChecked(cfg.get("active") == key)
            self._img_group.addButton(radio)
            card.add_header_widget(radio)
            key_edit = QLineEdit()
            key_edit.setEchoMode(QLineEdit.Password)
            key_edit.setPlaceholderText("API Key")
            key_edit.setText(crypto.decrypt(pcfg.get("api_key_enc", "")))
            model_edit = QLineEdit(pcfg.get("model", ""))
            card.body.addWidget(key_edit)
            card.body.addWidget(model_edit)
            self._img_rows[key] = {"key": key_edit, "model": model_edit, "radio": radio}
            self._providers.append(card)
            grid.addWidget(card, idx // 2, idx % 2)
            idx += 1
        c3.body.addLayout(grid)
        v.addWidget(c3)
        self._toggle_providers(self.ai_off.isChecked())

        v.addStretch(1)
        scroll.setWidget(root)
        outer.addWidget(scroll, 1)
        make_cfg_panel(self)

    def _toggle_providers(self, off: bool) -> None:
        """Tắt AI chỉnh ảnh -> khoá danh sách provider."""
        for card in self._providers:
            card.setEnabled(not off)

    def _save(self) -> None:
        try:
            cfg = self.store.ai_image
            cfg["pillow"]["enabled"] = True       # luôn bật (đã bỏ ô tick)
            cfg["pillow"]["output_format"] = "PNG" if self.out_fmt.currentIndex() == 0 else "JPG"
            cfg["pillow"]["size"] = [1080, 1200, 0][self.size_combo.currentIndex()]
            for key, row in self._img_rows.items():
                p = cfg["providers"][key]
                p["api_key_enc"] = crypto.encrypt(row["key"].text().strip())
                if row["model"].text().strip():
                    p["model"] = row["model"].text().strip()
            if self.ai_off.isChecked():
                cfg["active"] = "off"
            else:
                chosen = next((k for k, r in self._img_rows.items() if r["radio"].isChecked()), "")
                if chosen:
                    cfg["active"] = chosen
                elif cfg.get("active") == "off":
                    cfg["active"] = next(iter(self._img_rows), "gemini")
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Lưu AI ảnh THẤT BẠI: {exc}", 3400, ok=False)
            return
        show_toast(self, "Đã lưu AI ảnh")


class SheetsPanel(QScrollArea):
    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWidgetResizable(True)
        cfg = self.store.sheets
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(20, 18, 20, 20)
        t = QLabel("Google Sheets")
        t.setProperty("class", "h2")
        v.addWidget(t)
        sub = QLabel("Lưu <b>link nguồn</b> và <b>link kết quả</b> sau khi đăng bài.")
        sub.setProperty("class", "sub")
        v.addWidget(sub)

        card = Card("Kết nối Google")
        self.enabled = QCheckBox("Bật lưu kết quả")
        self.enabled.setChecked(bool(cfg.get("enabled")))
        card.body.addWidget(self.enabled)
        form = _form()
        self.sa_edit = QLineEdit(cfg.get("service_account_file", ""))
        self.sa_edit.setReadOnly(True)
        b = QPushButton("Chọn file Service Account JSON")
        b.setProperty("class", "ghost")
        b.clicked.connect(self._pick_sa)
        row = QHBoxLayout()
        row.addWidget(self.sa_edit, 1)
        row.addWidget(b)
        form.addRow("Service Account (JSON)", row)
        self.sheet_id = QLineEdit(cfg.get("spreadsheet_id", ""))
        form.addRow("Link / ID Google Sheets", self.sheet_id)
        self.sheet_name = QLineEdit(cfg.get("sheet_name", ""))
        form.addRow("Tên sheet (tab)", self.sheet_name)
        self.col_src = QLineEdit(cfg.get("col_source", "A"))
        self.col_res = QLineEdit(cfg.get("col_result", "B"))
        form.addRow("Cột 'Link nguồn'", self.col_src)
        form.addRow("Cột 'Link kết quả'", self.col_res)
        self.mode = QComboBox()
        self.mode.addItems(["Thêm dòng mới", "Cập nhật dòng trùng"])
        form.addRow("Chế độ ghi", self.mode)
        card.body.addLayout(form)
        v.addWidget(card)

        save = QPushButton("Lưu cấu hình Google Sheets")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        v.addWidget(save, alignment=Qt.AlignRight)
        v.addStretch(1)
        self.setWidget(root)
        make_cfg_panel(self)

    def _pick_sa(self) -> None:
        path = _pick_file(self, "Chọn Service Account JSON", "JSON (*.json)")
        if path:
            self.sa_edit.setText(path)

    def _save(self) -> None:
        try:
            cfg = self.store.sheets
            cfg["enabled"] = self.enabled.isChecked()
            cfg["service_account_file"] = self.sa_edit.text()
            cfg["spreadsheet_id"] = self.sheet_id.text().strip()
            cfg["sheet_name"] = self.sheet_name.text().strip()
            cfg["col_source"] = self.col_src.text().strip() or "A"
            cfg["col_result"] = self.col_res.text().strip() or "B"
            cfg["mode"] = "append" if self.mode.currentIndex() == 0 else "update"
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Lưu Google Sheets THẤT BẠI: {exc}", 3400, ok=False)
            return
        show_toast(self, "Đã lưu Google Sheets")


# ======================================================================= #
# Panel "Link tiêu đề" (link chèn vào các tiêu đề mục)
# ======================================================================= #
class TitleLinksPanel(QWidget):
    """Danh sách link sẽ được chèn vào các tiêu đề mục (từ h2 thứ 2 trở đi)."""

    def __init__(self, store, on_saved=None, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.on_saved = on_saved
        self._rows: list[QLineEdit] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 12)
        outer.setSpacing(10)

        head = QHBoxLayout()
        t = QLabel("Link tiêu đề")
        t.setProperty("class", "h2")
        head.addWidget(t)
        head.addStretch(1)
        save = QPushButton("Lưu danh sách link")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        head.addWidget(save)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 8)
        v.setSpacing(10)

        sub = QLabel(
            "Link ở ô đầu tiên luôn chèn vào <b>tiêu đề đầu tiên (h1 hoặc h2 đầu)</b>. "
            "Các link trong danh sách bên dưới chèn vào <b>tiêu đề thứ 2 trở đi</b> — "
            "mỗi link chèn <b>1 lần</b> (có 2 link thì chèn 2 lần)."
        )
        sub.setProperty("class", "sub")
        sub.setWordWrap(True)
        v.addWidget(sub)

        first_card = Card("Link chèn vào TIÊU ĐỀ ĐẦU TIÊN (h1/h2 đầu)")
        self.first_edit = QLineEdit(self.store.title_link_first)
        self.first_edit.setPlaceholderText("https://ngochuyduong.com")
        first_card.body.addWidget(self.first_edit)
        v.addWidget(first_card)

        card = Card("Danh sách link")
        self.box = QVBoxLayout()
        self.box.setSpacing(8)
        card.body.addLayout(self.box)

        self.add_btn = QPushButton("+ Thêm link")
        self.add_btn.setProperty("class", "ghost")
        self.add_btn.clicked.connect(lambda: self._add_row(""))
        card.body.addWidget(self.add_btn, alignment=Qt.AlignLeft)
        v.addWidget(card)

        v.addStretch(1)
        scroll.setWidget(root)
        outer.addWidget(scroll, 1)
        make_cfg_panel(self)
        self._load()

    def _add_row(self, value: str = "") -> None:
        row = QHBoxLayout()
        lab = QLabel("Link chèn")
        lab.setFixedWidth(70)
        edit = QLineEdit(value)
        edit.setPlaceholderText("https://vidu.com")
        row.addWidget(lab)
        row.addWidget(edit, 1)
        del_btn = QPushButton("✕")
        del_btn.setObjectName("imgDel")
        del_btn.setFixedSize(22, 22)
        del_btn.setToolTip("Xoá link này")
        holder = QWidget()
        holder.setLayout(row)
        del_btn.clicked.connect(lambda _=False, h=holder, e=edit: self._remove_row(h, e))
        row.addWidget(del_btn)
        self.box.addWidget(holder)
        self._rows.append(edit)

    def _remove_row(self, holder, edit) -> None:
        if edit in self._rows:
            self._rows.remove(edit)
        holder.setParent(None)
        holder.deleteLater()

    def _load(self) -> None:
        for link in self.store.title_links:
            self._add_row(link)

    def _save(self) -> None:
        links = [e.text().strip() for e in self._rows if e.text().strip()]
        try:
            self.store.set_title_links(links)
            self.store.set_title_link_first(self.first_edit.text())
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Lưu link tiêu đề THẤT BẠI: {exc}", 3400, ok=False)
            return
        show_toast(self, f"Đã lưu {len(links)} link chèn tiêu đề")
        if self.on_saved:
            self.on_saved()


# ======================================================================= #
# Panel "Format Rule" (dùng chung cho mọi website)
# ======================================================================= #
MAX_IMAGE_RULES = 6


class FormatPanel(QScrollArea):
    def __init__(self, store, on_saved=None, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.on_saved = on_saved
        self.setWidgetResizable(True)
        self._edits: dict[str, QLineEdit] = {}
        self.rule_edits: list[QLineEdit] = []
        self._build()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(20, 18, 20, 20)

        t = QLabel("Format Rule")
        t.setProperty("class", "h2")
        v.addWidget(t)

        card = Card("Rule quy định cho AI")
        f = _form()
        rows = [
            ("content", "Rule Content"),
            ("seo", "Rule SEO"),
            ("extractor", "Rule Model Extractor"),
        ]
        for key, label in rows:
            edit = QLineEdit()
            edit.setReadOnly(True)
            h = QHBoxLayout()
            h.addWidget(edit, 1)
            b = QPushButton("Chọn file")
            b.setProperty("class", "ghost")
            b.clicked.connect(lambda _=False, k=key, e=edit, l=label: self._pick(k, e, l))
            h.addWidget(b)
            f.addRow(label, h)
            self._edits[key] = edit
        card.body.addLayout(f)
        v.addWidget(card)

        # ---- Rule ảnh ----
        img_card = Card("Rule ảnh")
        hint = QLabel(
            "Đặt tên cho ảnh. Dùng biến trong dấu <b>{ }</b>, ví dụ: "
            "<b>Hello world {title}</b> → \"Hello world \" + <b>tiêu đề bài viết</b> (lấy từ kết quả AI). "
            "Có thể thêm tối đa 6 rule."
        )
        hint.setProperty("class", "hint")
        hint.setWordWrap(True)
        img_card.body.addWidget(hint)

        self.rules_box = QVBoxLayout()
        self.rules_box.setSpacing(8)
        img_card.body.addLayout(self.rules_box)

        self.add_rule_btn = QPushButton("+ Thêm rule ảnh")
        self.add_rule_btn.setProperty("class", "ghost")
        self.add_rule_btn.clicked.connect(lambda: self._add_rule_row(""))
        img_card.body.addWidget(self.add_rule_btn, alignment=Qt.AlignLeft)
        v.addWidget(img_card)

        save = QPushButton("Lưu")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        v.addWidget(save, alignment=Qt.AlignRight)

        v.addStretch(1)
        self.setWidget(root)
        make_cfg_panel(self)
        self._load()

    # ------------------------------------------------------------------ #
    def _add_rule_row(self, value: str = "") -> None:
        if len(self.rule_edits) >= MAX_IMAGE_RULES:
            return
        n = len(self.rule_edits) + 1
        row = QHBoxLayout()
        lab = QLabel(f"Ảnh {n}")
        lab.setFixedWidth(52)
        edit = QLineEdit(value)
        edit.setPlaceholderText("vd: Hello world {title}")
        row.addWidget(lab)
        row.addWidget(edit, 1)
        self.rules_box.addLayout(row)
        self.rule_edits.append(edit)
        self.add_rule_btn.setEnabled(len(self.rule_edits) < MAX_IMAGE_RULES)

    def _load(self) -> None:
        fmt = self.store.formats
        for key, edit in self._edits.items():
            edit.setText(getattr(fmt, key, ""))
        for value in self.store.image_rules:
            self._add_rule_row(value)

    # ------------------------------------------------------------------ #
    def _pick(self, key: str, edit: QLineEdit, label: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, label, "", FORMAT_FILTER)
        if not path:
            return
        edit.setText(Store.import_file(path, formats_dir()))

    def _save(self) -> None:
        try:
            fmt = self.store.formats
            for key, edit in self._edits.items():
                setattr(fmt, key, edit.text())
            self.store.set_formats(fmt)
            self.store.set_image_rules([e.text().strip() for e in self.rule_edits])
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            show_toast(self, f"Lưu Format Rule THẤT BẠI: {exc}", 3400, ok=False)
            return
        show_toast(self, "Đã lưu Format Rule")
        if self.on_saved:
            self.on_saved()
