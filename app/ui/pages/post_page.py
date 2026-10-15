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
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...storage.models import Task
from ..style import Card, polish_combos


class SiteRow(QFrame):
    """1 dòng website để chọn (chỉ chọn được 1)."""

    def __init__(self, site, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("siteRow")
        self.site_id = site.id

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 9, 10, 9)
        self.radio = QRadioButton(site.name or site.url)
        self.radio.setObjectName("rowTitle")
        v.addWidget(self.radio)
        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", "true" if on else "false")
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()


class PostPage(QWidget):
    create_task = Signal(object)  # Task

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._radios: dict[str, QRadioButton] = {}
        self._rows: dict[str, SiteRow] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._build()
        self.reload_sites()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 24)

        steps = QHBoxLayout()
        for i, text in enumerate(
            ["Nhập link nguồn & chọn site", "Xếp vào Công việc đang làm",
             "Duyệt & chỉnh sửa", "Đăng bài"]
        ):
            lab = QLabel(f"{i + 1}. {text}")
            lab.setStyleSheet("font-weight:600;" if i == 0 else "color:#94a3b8;")
            steps.addWidget(lab)
            if i < 3:
                arrow = QLabel("→")
                arrow.setStyleSheet("color:#cbd5e1;")
                steps.addWidget(arrow)
        steps.addStretch(1)
        root.addLayout(steps)
        root.addSpacing(10)

        row = QHBoxLayout()
        row.addStretch(1)
        self.card = Card("Bước 1 — Tạo công việc mới")
        self.card.setFixedWidth(700)
        row.addWidget(self.card)
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(1)

        b = self.card.body

        b.addWidget(QLabel("Link bài viết nguồn"))
        self.source_url = QLineEdit()
        self.source_url.setPlaceholderText("https://...")
        self.source_url.textChanged.connect(self._validate)
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
        polish_combos(self)

        b.addSpacing(6)
        self.create_btn = QPushButton("Tạo nội dung bằng AI")
        self.create_btn.setProperty("class", "primary")
        self.create_btn.setEnabled(False)
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
        for btn in list(self._group.buttons()):
            self._group.removeButton(btn)
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

        for idx, site in enumerate(sites):
            row = SiteRow(site)
            self._group.addButton(row.radio, idx)
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

        has_link = bool(self.source_url.text().strip())
        has_rule = self.store.has_format_content()
        ok = bool(site and has_link and has_rule)
        self.create_btn.setEnabled(ok)

        problems: list[str] = []
        if not site:
            problems.append("chưa chọn website")
        if not has_rule:
            problems.append(
                "chưa có file quy định nội dung "
                "(vào <b>Cấu hình → Format &amp; rule bài viết</b> để thêm)"
            )
        if not has_link:
            problems.append("chưa nhập link bài viết nguồn")

        if problems:
            self.warn.setText("⚠ <b>Chưa thể tạo nội dung:</b> " + "; ".join(problems) + ".")
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
        url = self.source_url.text().strip()
        if not site or not url or not self.store.has_format_content():
            self._validate()
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
        self.brand_logo.clear()
