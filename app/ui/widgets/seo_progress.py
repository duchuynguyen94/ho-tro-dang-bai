"""Lớp phủ báo tiến trình lấy JSON SEO cho các bài đã chia (phủ toàn bộ cửa sổ app).

- Chạy TUẦN TỰ từng bài (do luồng SplitSeoWorker đẩy số liệu vào).
- Đóng bằng nút X / nút "Dừng và đóng" / phím Esc -> phát tín hiệu `cancelled`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)


class SeoProgressOverlay(QWidget):
    """Phủ kín cửa sổ chính: không bấm được gì khác cho tới khi xong / dừng."""

    cancelled = Signal()          # người dùng muốn DỪNG lấy JSON SEO

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("seoOverlay")
        self.setStyleSheet(
            "#seoOverlay { background: rgba(15, 23, 42, 0.45); }"
            "#seoCard { background: #ffffff; border-radius: 14px; }"
        )
        self.setFocusPolicy(Qt.StrongFocus)

        card = QFrame(self)
        card.setObjectName("seoCard")
        card.setFixedWidth(540)

        title_row = QHBoxLayout()
        title = QLabel("Đang lấy JSON SEO…")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #0f172a;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(26, 26)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("Dừng lấy JSON SEO")
        self.close_btn.setStyleSheet(
            "QPushButton { border: none; background: #eef2f7; border-radius: 13px;"
            " color: #334155; font-weight: 700; }"
            "QPushButton:hover { background: #e2e8f0; }"
        )
        self.close_btn.clicked.connect(self._cancel)
        title_row.addWidget(self.close_btn)

        self.step_lbl = QLabel("Bài 0/0")
        self.step_lbl.setStyleSheet("color: #475569; font-weight: 600;")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.status_lbl = QLabel("Đang chuẩn bị…")
        self.status_lbl.setStyleSheet("color: #64748b;")
        self.status_lbl.setWordWrap(True)

        self.stop_btn = QPushButton("Dừng và đóng")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self._cancel)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(self.stop_btn)

        col = QVBoxLayout(card)
        col.setContentsMargins(22, 18, 22, 18)
        col.setSpacing(10)
        col.addLayout(title_row)
        col.addWidget(self.step_lbl)
        col.addWidget(self.bar)
        col.addWidget(self.status_lbl)
        col.addLayout(foot)

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    # ------------------------------------------------------------------ #
    def start(self, total: int) -> None:
        """Hiện lớp phủ và bắt đầu từ bài 0/N."""
        total = max(1, int(total or 1))
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.step_lbl.setText(f"Bài 0/{total}")
        self.status_lbl.setText("Đang chuẩn bị…")
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())
        self.raise_()
        self.show()
        self.setFocus()

    def set_step(self, i: int, total: int, label: str) -> None:
        """Bắt đầu bài thứ i."""
        total = max(1, int(total or 1))
        self.bar.setRange(0, total)
        self.bar.setValue(max(0, int(i) - 1))
        self.step_lbl.setText(f"Bài {i}/{total}")
        self.status_lbl.setText(f"Đang tạo JSON SEO cho {label}…")

    def set_done(self, i: int, total: int) -> None:
        # Xong bài thứ i
        self.bar.setRange(0, max(1, int(total or 1)))
        self.bar.setValue(int(i))

    # ------------------------------------------------------------------ #
    def _cancel(self) -> None:
        self.cancelled.emit()

    def keyPressEvent(self, ev) -> None:      # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(ev)

    def closeEvent(self, ev) -> None:         # noqa: N802
        self.cancelled.emit()
        super().closeEvent(ev)
