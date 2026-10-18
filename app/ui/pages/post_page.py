"""Màn hình 'Đăng bài' — Bước 1."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...storage.models import Task
from ..style import dim_when_disabled, Card, polish_combos


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
    create_task = Signal(object)
    split_task = Signal(object, int)        # (task mẫu, số bài cần chia)  # Task

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

        b.addWidget(QLabel("Link nguồn (mỗi link 1 dòng — nhiều link = 1 bài viết)"))
        self.source_url = QPlainTextEdit()
        self.source_url.setPlaceholderText("https://...\nhttps://...")
        self.source_url.setFixedHeight(84)
        self.source_url.textChanged.connect(self._validate)
        b.addWidget(self.source_url)

        # CHIA NHIỀU BÀI (ngay dưới ô nhập link): chỉ dùng khi có ĐÚNG 1 link
        b.addSpacing(4)
        srow = QHBoxLayout()
        self.split_check = QCheckBox("Chia nhiều bài")
        self.split_check.setToolTip(
            "Chia 1 link nguồn thành nhiều bài viết (chỉ content, không JSON SEO).\n"
            "Mỗi bài tạo 1 JOB TRỐNG, website chia tuần tự."
        )
        self.split_check.toggled.connect(self._on_split_toggled)
        srow.addWidget(self.split_check)
        self.split_count = QComboBox()
        self.split_count.addItems([f"{n} bài" for n in range(2, 11)])
        self.split_count.setFixedWidth(120)
        self.split_count.setEnabled(False)
        dim_when_disabled(self.split_count, 0.45)     # MỜ khi chưa tick "chia nhiều bài"
        srow.addWidget(self.split_count)
        srow.addStretch(1)
        b.addLayout(srow)
        polish_combos(self)

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
        self.site_label = QLabel("Chọn website đăng (chỉ 1 website)")
        b.addWidget(self.site_label)
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
            lab = QLabel("Chưa có website nào. Vào tab Cài đặt để thêm.")
            lab.setProperty("class", "hint")
            self.sites_box.addWidget(lab)
            self._validate()
            return

        for idx, site in enumerate(sites):
            row = SiteRow(site)
            self._group.addButton(row.radio, idx)
            has_script = bool(site.script and site.script.steps)
            if not has_script:
                # chưa có kịch bản -> MỜ CẢ KHUNG, không chọn được
                row.setToolTip("Website này chưa có kịch bản đăng bài")
                row.setEnabled(False)
                dim_when_disabled(row, 0.45)
            else:
                row.radio.setEnabled(True)
            row.radio.toggled.connect(self._validate)
            self._radios[site.id] = row.radio
            self._rows[site.id] = row
            self.sites_box.addWidget(row)

        # chọn site ĐẦU TIÊN có kịch bản (bỏ qua site chưa có)
        first = next((r for s2, r in self._radios.items()
                      if r.isEnabled()), None)
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

        links = self._links()
        has_link = bool(links)
        self._sync_split_enabled(len(links))
        has_rule = self.store.has_format_content()
        splitting = bool(self.split_check.isChecked() and self.split_check.isEnabled())
        ok = bool(has_rule and (site or splitting))
        self.create_btn.setEnabled(ok and not getattr(self, "_splitting", False))

        problems: list[str] = []
        if not site and not splitting:
            problems.append("chưa chọn website")
        # link nguồn: CÓ THỂ để trống -> sẽ tạo job trống (không chạy AI)

        if problems:
            self.warn.setText("⚠ <b>Chưa thể tạo nội dung:</b> " + "; ".join(problems) + ".")
            self.warn.show()
        else:
            self.warn.hide()

    # ------------------------------------------------------------------ #
    def set_splitting(self, on: bool, n: int = 0) -> None:
        """Đang chia bài -> khoá nút tạo + đổi chữ."""
        self._splitting = bool(on)
        try:
            self.create_btn.setText(f"Đang chia bài… ({n} bài)" if on else "Tạo nội dung bằng AI")
        except Exception:      # noqa: BLE001
            pass
        self._validate()

    def _links(self) -> list[str]:
        """Tách các link nguồn (mỗi dòng 1 link), bỏ trùng, tối đa 10."""
        raw = self.source_url.toPlainText().replace(",", "\n").splitlines()
        out: list[str] = []
        for line in raw:
            u = line.strip()
            if not u or u in out:
                continue
            out.append(u)
            if len(out) >= 10:
                break
        return out

    def _sync_split_enabled(self, n_links: int) -> None:
        """Tick "chia nhiều bài" chỉ HIỆN khi có ĐÚNG 1 link (nhiều link / không link -> ẩn)."""
        only_one = (n_links == 1)
        # ẨN hẳn khi không phải 1 link
        self.split_check.setVisible(only_one)
        self.split_check.setEnabled(only_one)
        if not only_one and self.split_check.isChecked():
            self.split_check.setChecked(False)
        # Ô SỐ LƯỢNG: chỉ HIỆN khi đã tick "chia nhiều bài" (gọn giao diện)
        show_count = bool(only_one and self.split_check.isChecked())
        self.split_count.setVisible(show_count)
        self.split_count.setEnabled(show_count)
        self.split_check.setToolTip(
            "Chia 1 link nguồn thành nhiều bài viết (chỉ content, không JSON SEO).\n"
            "Mỗi bài tạo 1 JOB TRỐNG, website chia tuần tự."
            if only_one else
            "Chỉ dùng được khi nhập ĐÚNG 1 link (nhiều link luôn là 1 bài viết)"
        )

    def _on_split_toggled(self, on: bool) -> None:
        show = bool(on) and self.split_check.isEnabled()
        self.split_count.setVisible(show)
        self.split_count.setEnabled(show)
        # tick "chia nhiều bài" -> ẨN mục chọn website (website chia tuần tự)
        try:
            self.site_label.setVisible(not on)
            for row in getattr(self, "_rows", {}).values():
                row.setVisible(not on)
        except Exception:      # noqa: BLE001
            pass
        self._validate()

    def _split_count_value(self) -> int:
        try:
            return int(self.split_count.currentText().split()[0])
        except Exception:      # noqa: BLE001
            return 2

    def _pick_brand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn logo thương hiệu", "", "Ảnh (*.png *.jpg *.jpeg *.webp *.svg)"
        )
        if path:
            self.brand_logo.setText(path)

    def _create(self) -> None:
        site = self._selected_site()
        links = self._links()
        # link nguồn ĐỂ TRỐNG -> tạo job trống (kind="blank"): không chạy AI, tự điền tay
        if not site or not self.store.has_format_content():
            self._validate()
            return
        count = int(self.image_count.currentText().split()[0])
        brand = self.brand_logo.text().strip()
        # CHIA NHIỀU BÀI (chỉ khi đúng 1 link): chưa tạo job — chờ provider chia xong
        if links and self.split_check.isEnabled() and self.split_check.isChecked():
            task = Task(
                site_id=site.id,
                site_name=site.name,
                source_url=links[0],
                source_urls=[links[0]],
                kind="",
                brand_logo_fallback=brand,
                image_count=count,
            )
            self.split_task.emit(task, self._split_count_value())
            self.source_url.clear()
            self.brand_logo.clear()
            return
        task = Task(
            site_id=site.id,
            site_name=site.name,
            source_url=(links[0] if links else ""),
            source_urls=list(links),
            kind="" if links else "blank",
            brand_logo_fallback=brand,
            image_count=count,
        )
        self.create_task.emit(task)
        self.source_url.clear()
        self.brand_logo.clear()
