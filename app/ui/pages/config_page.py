"""Màn hình 'Cấu hình'."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
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
from ..style import Card
from ..workers import RecordWorker

FORMAT_FILTER = "Quy định (*.txt *.html *.htm *.doc *.docx);;Tất cả (*.*)"


def _pick_file(parent, caption, filt) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, caption, "", filt)
    return path or ""


class ConfigPage(QWidget):
    changed = Signal()

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.record_worker: RecordWorker | None = None
        self._panels: dict[str, QWidget] = {}
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
        sheets = SheetsPanel(self.store)
        for key, panel, label in [
            ("ai_content", ai_c, "AI nội dung"),
            ("ai_image", ai_i, "AI ảnh"),
            ("sheets", sheets, "Google Sheets"),
        ]:
            self._panels[key] = panel
            self.stack.addWidget(panel)
            nav_button(label, key)

        self.side_layout.addStretch(1)
        first_key = next(iter(self._panels), None)
        if first_key:
            self._show(first_key)

    def _show(self, key: str) -> None:
        if key not in self._panels:
            return
        self.stack.setCurrentWidget(self._panels[key])
        for k, btn in getattr(self, "_nav_buttons", {}).items():
            btn.setChecked(k == key)
        self._current_key = key

    # ------------------------------------------------------------------ #
    def _add_site(self) -> None:
        site = Site(name="website-moi.com", url="https://website-moi.com",
                    new_post_url="https://website-moi.com/wp-admin/post-new.php",
                    watermark="https://website-moi.com")
        self.store.upsert_site(site)
        self.store.save()
        self.reload()

    def _on_site_saved(self) -> None:
        self.changed.emit()
        self.reload()


# ======================================================================= #
# Panel cấu hình 1 website
# ======================================================================= #
class SitePanel(QWidget):
    saved = Signal()

    def __init__(self, store: Store, site: Site, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.site = store.get_site(site.id) or site
        self._steps: list[dict] = [s.to_dict() for s in (self.site.script.steps if self.site.script else [])]
        self._build()
        self._load()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 20)

        head = QHBoxLayout()
        self.title = QLabel(self.site.name)
        self.title.setProperty("class", "h2")
        head.addWidget(self.title)
        head.addStretch(1)
        test = QPushButton("Kiểm tra kết nối")
        test.setProperty("class", "ghost")
        test.clicked.connect(self._test)
        save = QPushButton("Lưu")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        head.addWidget(test)
        head.addWidget(save)
        outer.addLayout(head)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.tabs.addTab(self._info_tab(), "Thông tin site")
        self.tabs.addTab(self._account_tab(), "Tài khoản đăng nhập")
        self.tabs.addTab(self._script_tab(), "Kịch bản đăng bài")
        self.tabs.addTab(self._media_tab(), "Logo / Khung / Watermark")
        self.tabs.addTab(self._format_tab(), "Format bài viết")

    # ---------------- Thông tin ---------------- #
    def _info_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.newpost_edit = QLineEdit()
        self.watermark_edit = QLineEdit()
        self.footer_mode = QComboBox()
        self.footer_mode.addItems(["Random (mặc định)", "Chỉ hình 1", "Chỉ hình 2"])
        f.addRow("Tên gọi", self.name_edit)
        f.addRow("URL website", self.url_edit)
        f.addRow("Link trang tạo bài viết", self.newpost_edit)
        f.addRow("Watermark chéo", self.watermark_edit)
        f.addRow("Mặc định dùng thanh thông tin", self.footer_mode)
        return w

    # ---------------- Tài khoản ---------------- #
    def _account_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        f.addRow("Tài khoản (username/email)", self.user_edit)
        f.addRow("Mật khẩu", self.pass_edit)
        note = QLabel("Mật khẩu được mã hoá khi lưu. Session đăng nhập được giữ lại cho lần sau.")
        note.setProperty("class", "hint")
        f.addRow(note)
        login = QPushButton("Đăng nhập thử")
        login.setProperty("class", "ghost")
        login.clicked.connect(self._test)
        f.addRow(login)
        return w

    # ---------------- Kịch bản ---------------- #
    def _script_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)

        bar = QHBoxLayout()
        self.rec_btn = QPushButton("● Bắt đầu ghi")
        self.rec_btn.setStyleSheet(
            "background:#dc2626;color:#fff;border:none;border-radius:16px;padding:8px 18px;font-weight:700;"
        )
        self.rec_btn.clicked.connect(self._toggle_record)
        bar.addWidget(self.rec_btn)
        bar.addStretch(1)
        for label, slot in [
            ("⬇ Export kịch bản", self._export),
            ("⬆ Import kịch bản", self._import),
        ]:
            b = QPushButton(label)
            b.setProperty("class", "ghost")
            b.clicked.connect(slot)
            bar.addWidget(b)
        v.addLayout(bar)

        self.script_table = QTableWidget(0, 4)
        self.script_table.setHorizontalHeaderLabels(["#", "Hành động", "Selector ưu tiên (HTML)", "Nguồn"])
        self.script_table.horizontalHeader().setStretchLastSection(True)
        self.script_table.setColumnWidth(2, 460)
        v.addWidget(self.script_table, 1)

        help_lbl = QLabel(
            "Khi ghi, phần mềm bắt đúng phần tử và tự sinh selector: "
            "<b>id → name/data-*/aria → text nút → CSS → nth-child</b>. "
            "<b>Export</b> kịch bản ra file để mang sang máy khác <b>Import</b> vào là chạy được ngay."
        )
        help_lbl.setProperty("class", "hint")
        help_lbl.setWordWrap(True)
        v.addWidget(help_lbl)
        return w

    # ---------------- Logo / Khung / Watermark ---------------- #
    def _media_tab(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        self.logo_edit = QLineEdit()
        self.logo_edit.setReadOnly(True)
        b1 = QPushButton("Chọn logo")
        b1.setProperty("class", "ghost")
        b1.clicked.connect(lambda: self._pick_into(self.logo_edit, "Chọn logo website (trên-trái)"))
        grid.addWidget(QLabel("Logo website (trên-trái)"), 0, 0)
        grid.addWidget(self.logo_edit, 0, 1)
        grid.addWidget(b1, 0, 2)

        self.bar1_edit = QLineEdit()
        self.bar1_edit.setReadOnly(True)
        c1 = QPushButton("Chọn hình 1")
        c1.setProperty("class", "ghost")
        c1.clicked.connect(lambda: self._pick_into(self.bar1_edit, "Thanh thông tin — hình 1"))
        grid.addWidget(QLabel("Thanh thông tin dưới — hình 1"), 1, 0)
        grid.addWidget(self.bar1_edit, 1, 1)
        grid.addWidget(c1, 1, 2)

        self.bar2_edit = QLineEdit()
        self.bar2_edit.setReadOnly(True)
        c2 = QPushButton("Chọn hình 2")
        c2.setProperty("class", "ghost")
        c2.clicked.connect(lambda: self._pick_into(self.bar2_edit, "Thanh thông tin — hình 2"))
        grid.addWidget(QLabel("Thanh thông tin dưới — hình 2"), 2, 0)
        grid.addWidget(self.bar2_edit, 2, 1)
        grid.addWidget(c2, 2, 2)

        note = QLabel(
            "Thanh thông tin dưới là <b>1 hình ảnh</b>; mỗi ảnh sẽ random 1 trong 2 hình. "
            "Watermark chéo (nhập ở tab Thông tin site) tự lấy từ URL website."
        )
        note.setProperty("class", "hint")
        note.setWordWrap(True)
        grid.addWidget(note, 3, 0, 1, 3)
        return w

    # ---------------- Format ---------------- #
    def _format_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.fmt_title = QLineEdit()
        self.fmt_content = QLineEdit()
        self.fmt_desc = QLineEdit()
        self.fmt_tags = QLineEdit()
        rows = [
            ("Quy định tiêu đề", self.fmt_title),
            ("Quy định nội dung", self.fmt_content),
            ("Quy định description", self.fmt_desc),
            ("Quy định search tags", self.fmt_tags),
        ]
        for label, edit in rows:
            edit.setReadOnly(True)
            h = QHBoxLayout()
            h.addWidget(edit, 1)
            b = QPushButton("Chọn file")
            b.setProperty("class", "ghost")
            b.clicked.connect(lambda _=False, e=edit, l=label: self._pick_into(e, l))
            h.addWidget(b)
            f.addRow(label, h)
        note = QLabel(
            "File <b>.txt / .html / .doc</b> chứa <b>cả yêu cầu và format</b> để AI tạo nội dung theo quy định. "
            "Chưa có file quy định nội dung thì không tạo được bài."
        )
        note.setProperty("class", "hint")
        note.setWordWrap(True)
        f.addRow(note)
        return w

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        s = self.site
        self.name_edit.setText(s.name)
        self.url_edit.setText(s.url)
        self.newpost_edit.setText(s.new_post_url)
        self.watermark_edit.setText(s.watermark)
        self.footer_mode.setCurrentIndex({"random": 0, "bar1": 1, "bar2": 2}.get(s.footer_mode, 0))
        self.user_edit.setText(s.username)
        self.pass_edit.setText(s.get_password())
        self.logo_edit.setText(s.logo_path)
        self.bar1_edit.setText(s.footer_bars[0] if len(s.footer_bars) > 0 else "")
        self.bar2_edit.setText(s.footer_bars[1] if len(s.footer_bars) > 1 else "")
        self.fmt_title.setText(s.formats.title)
        self.fmt_content.setText(s.formats.content)
        self.fmt_desc.setText(s.formats.description)
        self.fmt_tags.setText(s.formats.tags)
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

    def _pick_into(self, edit: QLineEdit, caption: str, filt: str = "Ảnh (*.png *.jpg *.jpeg *.webp)") -> None:
        path, _ = QFileDialog.getOpenFileName(self, caption, "", filt)
        if path:
            dest_dir = formats_dir() if edit in (self.fmt_title, self.fmt_content, self.fmt_desc, self.fmt_tags) else media_dir()
            saved = Store.import_file(path, dest_dir)
            edit.setText(saved)

    # ------------------------------------------------------------------ #
    def _toggle_record(self) -> None:
        if self.record_worker and self.record_worker.isRunning():
            self.record_worker.stop()
            self.record_worker = None
            self.rec_btn.setText("● Bắt đầu ghi")
            return
        self._steps = []
        self._refresh_steps()
        self.record_worker = RecordWorker(self.site)
        self.record_worker.step.connect(self._on_step)
        self.record_worker.start()
        self.rec_btn.setText("■ Dừng ghi")

    def _on_step(self, payload: dict) -> None:
        self._steps.append(payload)
        self._refresh_steps()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export kịch bản", f"{self.site.name}-kichban.json", "JSON (*.json)"
        )
        if not path:
            return
        data = {"site": self.site.name, "steps": self._steps, "version": 1}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _import(self) -> None:
        path = _pick_file(self, "Import kịch bản", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self._steps = list(data.get("steps", []))
            self._refresh_steps()
        except (json.JSONDecodeError, OSError):
            pass

    def _test(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        try:
            from ...wp import WPBrowser

            br = WPBrowser(headless=True, site_id=self.site.id)
            br.open()
            ok = br.login(self.site)
            br.close()
            QMessageBox.information(self, "Kết nối", "Đăng nhập thành công!" if ok else "Chưa đăng nhập được — kiểm tra lại tài khoản.")
        except Exception as exc:
            QMessageBox.warning(self, "Kết nối", f"Lỗi: {exc}")

    # ------------------------------------------------------------------ #
    def _save(self) -> None:
        s = self.site
        s.name = self.name_edit.text().strip()
        s.url = self.url_edit.text().strip()
        s.new_post_url = self.newpost_edit.text().strip()
        s.watermark = self.watermark_edit.text().strip()
        s.footer_mode = ["random", "bar1", "bar2"][self.footer_mode.currentIndex()]
        s.username = self.user_edit.text().strip()
        if self.pass_edit.text():
            s.set_password(self.pass_edit.text())
        s.logo_path = self.logo_edit.text()
        s.footer_bars = [self.bar1_edit.text(), self.bar2_edit.text()]
        s.formats.title = self.fmt_title.text()
        s.formats.content = self.fmt_content.text()
        s.formats.description = self.fmt_desc.text()
        s.formats.tags = self.fmt_tags.text()
        if self._steps:
            s.script = Script(steps=[ScriptStep.from_dict(st) for st in self._steps])
        self.store.upsert_site(s)
        self.store.save()
        self.saved.emit()


# ======================================================================= #
# Panel AI nội dung
# ======================================================================= #
PROVIDER_LABELS = {
    "gemini": "Google Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "ollama": "Ollama (local)",
    "chatgpt": "ChatGPT (qua trình duyệt)",
    "openai": "OpenAI API",
}
FREE = {"gemini": "FREE", "groq": "FREE", "openrouter": "FREE", "ollama": "OFFLINE",
        "chatgpt": "FREE*", "openai": "TRẢ PHÍ"}


class AIContentPanel(QScrollArea):
    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWidgetResizable(True)
        self._rows: dict[str, dict] = {}
        self._build()

    def _build(self) -> None:
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(20, 18, 20, 20)
        title = QLabel("AI nội dung")
        title.setProperty("class", "h2")
        v.addWidget(title)
        sub = QLabel("Ưu tiên miễn phí — có thể chuyển đổi (switch) giữa nhiều model. Chọn 1 provider làm mặc định.")
        sub.setProperty("class", "sub")
        v.addWidget(sub)

        cfg = self.store.ai_content
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (key, pcfg) in enumerate(cfg["providers"].items()):
            card = Card(PROVIDER_LABELS.get(key, key))
            badge = QLabel(FREE.get(key, ""))
            badge.setStyleSheet("color:#047857;font-size:11px;font-weight:700;")
            card.add_header_widget(badge)
            radio = QCheckBox("Mặc định")
            radio.setChecked(cfg.get("active") == key)
            card.add_header_widget(radio)
            body = card.body
            key_edit = QLineEdit()
            key_edit.setEchoMode(QLineEdit.Password)
            key_edit.setPlaceholderText("API Key")
            key_edit.setText(crypto.decrypt(pcfg.get("api_key_enc", "")))
            model_edit = QLineEdit(pcfg.get("model", ""))
            if key == "ollama":
                body.addWidget(QLabel("Địa chỉ"))
                body.addWidget(QLineEdit(pcfg.get("base_url", "")))
            body.addWidget(key_edit)
            body.addWidget(model_edit)
            self._rows[key] = {"key": key_edit, "model": model_edit, "radio": radio}
            grid.addWidget(card, i // 2, i % 2)

        v.addLayout(grid)

        self.fallback = QCheckBox("Fallback tự động (provider lỗi/hết lượt → chuyển provider kế tiếp)")
        self.fallback.setChecked(bool(cfg.get("fallback", True)))
        v.addWidget(self.fallback)

        save = QPushButton("Lưu cấu hình AI nội dung")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        v.addWidget(save, alignment=Qt.AlignRight)
        v.addStretch(1)
        self.setWidget(root)

    def _save(self) -> None:
        cfg = self.store.ai_content
        for key, row in self._rows.items():
            p = cfg["providers"][key]
            p["api_key_enc"] = crypto.encrypt(row["key"].text().strip())
            if row["model"].text().strip():
                p["model"] = row["model"].text().strip()
            if row["radio"].isChecked():
                cfg["active"] = key
        cfg["fallback"] = self.fallback.isChecked()
        self.store.save()


class AIImagePanel(QScrollArea):
    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWidgetResizable(True)
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(20, 18, 20, 20)
        t = QLabel("AI ảnh")
        t.setProperty("class", "h2")
        v.addWidget(t)
        sub = QLabel("Gắn logo / khung / watermark / thanh thông tin và chỉnh sửa ảnh sản phẩm.")
        sub.setProperty("class", "sub")
        v.addWidget(sub)

        cfg = self.store.ai_image
        c1 = Card("Xử lý ảnh cục bộ (Pillow)")
        c1.body.addWidget(QLabel("Gắn logo, khung, watermark, thanh thông tin và resize — miễn phí, chạy tại máy."))
        self.pillow_on = QCheckBox("Bật")
        self.pillow_on.setChecked(bool(cfg["pillow"].get("enabled", True)))
        c1.body.addWidget(self.pillow_on)
        form = QFormLayout()
        self.out_fmt = QComboBox()
        self.out_fmt.addItems(["PNG (giữ trong suốt)", "JPG"])
        self.out_fmt.setCurrentIndex(0 if cfg["pillow"].get("output_format", "PNG") == "PNG" else 1)
        form.addRow("Định dạng xuất", self.out_fmt)
        self.size_combo = QComboBox()
        self.size_combo.addItems(["1080 × 1080 (mặc định)", "1200 × 1200", "Giữ nguyên"])
        form.addRow("Kích thước ảnh xuất", self.size_combo)
        c1.body.addLayout(form)
        v.addWidget(c1)

        c2 = Card("Xoá nền ảnh sản phẩm")
        self.remove_bg = QCheckBox("Bật xoá nền (xuất PNG trong suốt)")
        self.remove_bg.setChecked(cfg["remove_bg"].get("mode") != "off")
        c2.body.addWidget(self.remove_bg)
        v.addWidget(c2)

        c3 = Card("AI chỉnh sửa ảnh")
        grid = QGridLayout()
        self._img_rows: dict[str, dict] = {}
        for i, (key, pcfg) in enumerate(cfg["providers"].items()):
            label = {"gemini": "Google Gemini 2.5 Flash Image", "fal": "fal.ai — Flux Kontext",
                     "openai": "OpenAI Images", "off": "Tắt AI chỉnh ảnh"}.get(key, key)
            card = Card(label)
            radio = QCheckBox("Mặc định")
            radio.setChecked(cfg.get("active") == key)
            card.add_header_widget(radio)
            key_edit = QLineEdit()
            key_edit.setEchoMode(QLineEdit.Password)
            key_edit.setPlaceholderText("API Key")
            key_edit.setText(crypto.decrypt(pcfg.get("api_key_enc", "")))
            model_edit = QLineEdit(pcfg.get("model", ""))
            card.body.addWidget(key_edit)
            card.body.addWidget(model_edit)
            self._img_rows[key] = {"key": key_edit, "model": model_edit, "radio": radio}
            grid.addWidget(card, i // 2, i % 2)
        c3.body.addLayout(grid)
        v.addWidget(c3)

        save = QPushButton("Lưu cấu hình AI ảnh")
        save.setProperty("class", "primary")
        save.clicked.connect(self._save)
        v.addWidget(save, alignment=Qt.AlignRight)
        v.addStretch(1)
        self.setWidget(root)

    def _save(self) -> None:
        cfg = self.store.ai_image
        cfg["pillow"]["enabled"] = self.pillow_on.isChecked()
        cfg["pillow"]["output_format"] = "PNG" if self.out_fmt.currentIndex() == 0 else "JPG"
        cfg["remove_bg"]["mode"] = "local" if self.remove_bg.isChecked() else "off"
        for key, row in self._img_rows.items():
            p = cfg["providers"][key]
            p["api_key_enc"] = crypto.encrypt(row["key"].text().strip())
            if row["model"].text().strip():
                p["model"] = row["model"].text().strip()
            if row["radio"].isChecked():
                cfg["active"] = key
        self.store.save()


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
        form = QFormLayout()
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

    def _pick_sa(self) -> None:
        path = _pick_file(self, "Chọn Service Account JSON", "JSON (*.json)")
        if path:
            self.sa_edit.setText(path)

    def _save(self) -> None:
        cfg = self.store.sheets
        cfg["enabled"] = self.enabled.isChecked()
        cfg["service_account_file"] = self.sa_edit.text()
        cfg["spreadsheet_id"] = self.sheet_id.text().strip()
        cfg["sheet_name"] = self.sheet_name.text().strip()
        cfg["col_source"] = self.col_src.text().strip() or "A"
        cfg["col_result"] = self.col_res.text().strip() or "B"
        cfg["mode"] = "append" if self.mode.currentIndex() == 0 else "update"
        self.store.save()
