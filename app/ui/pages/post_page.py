"""Màn hình 'Đăng bài' — Bước 1."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...storage.models import Task
from ..style import Card


class SiteRow(QFrame):
    """1 dòng website trong danh sách chọn (dùng QSS tập trung theo objectName)."""

    def __init__(self, site, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("siteRow")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.radio = QRadioButton(site.name or site.url)
        self.radio.setObjectName("rowTitle")
        top.addWidget(self.radio)
        if site.username:
            top.addWidget(_chip("đã có tài khoản", "chipGreen"))
        top.addStretch(1)
        v.addLayout(top)

        meta = QHBoxLayout()
        meta.setContentsMargins(22, 0, 0, 0)
        meta.setSpacing(6)
        has_script = bool(site.script and site.script.steps)
        meta.addWidget(
            _chip("đã có kịch bản" if has_script else "chưa có kịch bản",
                  "chipGreen" if has_script else "chipAmber")
        )
        has_fmt = site.has_format_content()
        meta.addWidget(
            _chip("đã có quy định nội dung" if has_fmt else "thiếu quy định nội dung",
                  "chipGreen" if has_fmt else "chipRed")
        )
        meta.addStretch(1)
        v.addLayout(meta)

        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()


def _chip(text: str, obj: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName(obj)
    return lab


class PostPage(QWidget):
    create_task = Signal(object)  # Task

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._radios: dict[str, QRadioButton] = {}
        self._rows: dict[str, SiteRow] = {}
        self._build()
        self.reload_sites()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)

        steps = QHBoxLayout()
        for i, text in enumerate(
            ["Nhập link nguồn & chọn site", "Xếp vào Công việc đang làm", "Duyệt & chỉnh sửa", "Đăng bài"]
        ):
            lab = QLabel(f"{i + 1}. {text}")
            lab.setProperty("class", "hint")
            lab.setStyleSheet("font-weight:600;" if i == 0 else "color:#94a3b8;")
            steps.addWidget(lab)
            if i < 3:
                arrow = QLabel("→")
                arrow.setStyleSheet("color:#cbd5e1;")
                steps.addWidget(arrow)
        steps.addStretch(1)
        outer.addLayout(steps)
        outer.addSpacing(10)

        row = QHBoxLayout()
        row.addStretch(1)
        self.card = Card("Bước 1 — Tạo công việc mới")
        self.card.setFixedWidth(700)
        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        b = self.card.body

        b.addWidget(QLabel("Link bài viết nguồn"))
        self.source_url = QLineEdit()
        self.source_url.setPlaceholderText("https://...")
        b.addWidget(self.source_url)

        b.addSpacing(4)
        b.addWidget(QLabel("Logo thương hiệu (dự phòng — nếu AI không tìm thấy)"))
        h = QHBoxLayout()
        self.brand_logo = QLineEdit()
        self.brand_logo.setPlaceholderText("Chưa chọn file…")
        pick = QPushButton("Chọn file")
        pick.setProperty("class", "ghost")
        pick.clicked.connect(self._pick_brand)
        h.addWidget(self.brand_logo, 1)
        h.addWidget(pick)
        b.addLayout(h)
        hint = QLabel("Để trống thì phần mềm tự tìm logo thương hiệu từ link nguồn.")
        hint.setProperty("class", "hint")
        b.addWidget(hint)

        b.addSpacing(4)
        b.addWidget(QLabel("Chọn website đăng (chỉ 1 website)"))
        self.sites_box = QVBoxLayout()
        self.sites_box.setSpacing(6)
        b.addLayout(self.sites_box)

        b.addSpacing(4)
        b.addWidget(QLabel("Số ảnh cần tạo"))
        self.image_count = QComboBox()
        self.image_count.addItems(["3 ảnh (mặc định)", "1 ảnh", "2 ảnh", "4 ảnh", "5 ảnh"])
        b.addWidget(self.image_count)

        b.addSpacing(6)
        self.create_btn = QPushButton("Tạo nội dung bằng AI")
        self.create_btn.setProperty("class", "primary")
        self.create_btn.clicked.connect(self._create)
        b.addWidget(self.create_btn)

        self.warn = QLabel()
        self.warn.setProperty("class", "warn")
        self.warn.setWordWrap(True)
        self.warn.hide()
        b.addWidget(self.warn)

        notice = QLabel(
            "Bấm <b>Tạo nội dung</b> → công việc được xếp vào tab <b>Công việc đang làm</b>. "
            "Bạn có thể quay lại đây tạo tiếp nhiều công việc khác."
        )
        notice.setProperty("class", "notice")
        notice.setWordWrap(True)
        b.addWidget(notice)

    # ------------------------------------------------------------------ #
    def reload_sites(self) -> None:
        while self.sites_box.count():
            it = self.sites_box.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._radios.clear()
        self._rows.clear()

        sites = self.store.sites
        if not sites:
            lab = QLabel("Chưa có website nào. Vào tab Cấu hình để thêm.")
            lab.setProperty("class", "hint")
            self.sites_box.addWidget(lab)
            self._validate()
            return

        for site in sites:
            row = SiteRow(site)
            row.radio.toggled.connect(self._validate)
            self._radios[site.id] = row.radio
            self._rows[site.id] = row
            self.sites_box.addWidget(row)

        first = next(iter(self._radios.values()), None)
        if first:
            first.setChecked(True)
        self._validate()

    # ------------------------------------------------------------------ #
    def _selected_site(self):
        for sid, rb in self._radios.items():
            if rb.isChecked():
                return self.store.get_site(sid)
        return None

    def _validate(self) -> None:
        site = self._selected_site()
        for sid, row in self._rows.items():
            row.set_selected(bool(site and sid == site.id))
        ok = bool(site and site.has_format_content())
        self.create_btn.setEnabled(ok)
        if site and not site.has_format_content():
            self.warn.setText(
                f"⚠ <b>Chưa thể tạo nội dung.</b> Website <b>{site.name}</b> chưa có file quy định "
                "nội dung trong cấu hình. Vào <b>Cấu hình → Format bài viết</b> để thêm rồi thử lại."
            )
            self.warn.show()
        else:
            self.warn.hide()

    # ------------------------------------------------------------------ #
    def _pick_brand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn logo thương hiệu", "", "Ảnh (*.png *.jpg *.jpeg *.webp *.svg)"
        )
        if path:
            self.brand_logo.setText(path)

    def _create(self) -> None:
        site = self._selected_site()
        if not site:
            return
        url = self.source_url.text().strip()
        if not url:
            self.warn.setText("⚠ Vui lòng nhập link bài viết nguồn.")
            self.warn.show()
            return
        count = int(self.image_count.currentText().split()[0])
        task = Task(
            site_id=site.id,
            site_name=site.name,
            source_url=url,
            brand_logo_fallback=self.brand_logo.text().strip(),
            image_count=count,
        )
        self.create_task.emit(task)
        self.source_url.clear()
