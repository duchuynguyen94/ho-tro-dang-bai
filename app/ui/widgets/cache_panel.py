"""Panel “Xoá cache” (Cài đặt → Thiết lập chung).

Xoá TOÀN BỘ: job (nội dung, SEO, chủng loại, thương hiệu) + ảnh đã lưu.
GIỮ: website & kịch bản, cài đặt, đăng nhập website, rule/format.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from ... import config
from ..style import Card, dim_when_disabled, make_cfg_panel


def _dir_size(path: Path) -> int:
    """Tổng dung lượng thư mục (byte)."""
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _mb(n: int) -> str:
    return f"{n / 1048576:.0f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


class CachePanel(QWidget):
    """Nút xoá cache (dữ liệu tạm + ảnh đã lưu + toàn bộ job)."""

    cleared = Signal()

    def __init__(self, store, on_cleared=None, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._on_cleared = on_cleared
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _targets(self) -> list[tuple[str, Path]]:
        return [
            ("Ảnh đã ghép (output)", config.output_dir()),
            ("Ảnh gốc đã tải (products)", config.product_dir()),
            ("Ảnh tải từ website (media)", config.sites_media_dir()),
            ("Bài đã xuất (posts)", config.posts_dir()),
        ]

    def _build(self) -> None:
        from PySide6.QtWidgets import QScrollArea

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        card = Card("Xoá cache")
        desc = QLabel(
            "Xoá TOÀN BỘ job (nội dung, SEO, chủng loại, thương hiệu) và ảnh đã lưu "
            "để giải phóng dung lượng. <b>Không khôi phục được.</b><br>"
            "GIỮ NGUYÊN: website & kịch bản đăng bài, cài đặt, đăng nhập website, Rule/Format."
        )
        desc.setProperty("class", "sub")
        desc.setWordWrap(True)
        card.body.addWidget(desc)
        body = card.body

        self.info = QLabel("")
        self.info.setObjectName("taskMeta")
        self.info.setWordWrap(True)
        body.addWidget(self.info)

        row = QHBoxLayout()
        self.btn = QPushButton("Xoá cache")
        self.btn.setProperty("class", "danger")
        self.btn.clicked.connect(self._confirm)
        row.addWidget(self.btn)
        self.refresh_btn = QPushButton("Tính lại dung lượng")
        self.refresh_btn.setProperty("class", "ghost")
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        body.addLayout(row)

        v.addWidget(card)
        v.addStretch(1)
        scroll.setWidget(root)
        outer.addWidget(scroll, 1)
        make_cfg_panel(self)
        dim_when_disabled(self.btn)

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        try:
            n_tasks = len(self.store.tasks)
        except Exception:      # noqa: BLE001
            n_tasks = 0
        parts = [f"Job đang có: {n_tasks}"]
        total = 0
        for label, path in self._targets():
            size = _dir_size(Path(path)) if Path(path).exists() else 0
            total += size
            parts.append(f"{label}: {_mb(size)}")
        parts.append(f"TỔNG: {_mb(total)}")
        self.info.setText("  ·  ".join(parts))

    def _confirm(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Xoá cache")
        box.setText(
            "Xoá TOÀN BỘ job (nội dung, SEO, chủng loại, thương hiệu) "
            "và tất cả ảnh đã lưu?\n\nKhông khôi phục được."
        )
        box.setInformativeText(
            "GIỮ NGUYÊN: website & kịch bản đăng bài, cài đặt, đăng nhập website."
        )
        yes = box.addButton("Xoá hết", QMessageBox.DestructiveRole)
        box.addButton("Huỷ", QMessageBox.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec()
        if box.clickedButton() is not yes:
            return
        self._do_clear()

    def _do_clear(self) -> None:
        errors: list[str] = []
        # 1) xoá toàn bộ job
        try:
            self.store.set_tasks([])
            self.store.save()
        except Exception as exc:      # noqa: BLE001
            errors.append(f"job: {exc}")

        # 2) xoá các thư mục ảnh (giữ lại thư mục rỗng)
        for label, path in self._targets():
            p = Path(path)
            try:
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
                p.mkdir(parents=True, exist_ok=True)
            except Exception as exc:      # noqa: BLE001
                errors.append(f"{label}: {exc}")

        # 3) xoá trạng thái popup dùng chung (link + kết quả Product Models)
        try:
            ui = self.store.data.get("ui") or {}
            ui.pop("models_state", None)
            self.store.save()
        except Exception:      # noqa: BLE001
            pass

        self.refresh()
        # 4) báo cho cửa sổ chính (xoá cache RAM + nạp lại danh sách)
        try:
            if self._on_cleared is not None:
                self._on_cleared()
        except Exception:      # noqa: BLE001
            pass
        self.cleared.emit()
        if errors:
            QMessageBox.warning(self, "Xoá cache",
                                "Đã xoá nhưng có lỗi:\n" + "\n".join(errors[:6]))
