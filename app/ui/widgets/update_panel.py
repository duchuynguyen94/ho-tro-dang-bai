"""Panel "Cập nhật phần mềm" (Cài đặt → Thiết lập chung).

Nguồn cập nhật: GitHub Releases của repo (gắn sẵn trong app) — người dùng
không phải nhập gì, chỉ bấm "Cập nhật ngay".
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ... import update as upd
from ..style import Card, dim_when_disabled
from ..workers import UpdateWorker


class UpdatePanel(QWidget):
    """Kiểm tra & cập nhật phần mềm (bản .exe Windows, nguồn GitHub Releases)."""

    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.worker: UpdateWorker | None = None
        self._info: dict | None = None
        self._auto_checked = False
        self._build()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 12)
        outer.setSpacing(10)

        head = QHBoxLayout()
        t = QLabel("Cập nhật phần mềm")
        t.setProperty("class", "h2")
        head.addWidget(t)
        head.addStretch(1)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 8)
        v.setSpacing(10)

        # ---- phiên bản hiện tại ----
        card = Card("Phiên bản")
        row = QHBoxLayout()
        row.addWidget(QLabel("Phiên bản đang dùng:"))
        self.ver_label = QLabel(f"<b>{__version__}</b>")
        row.addWidget(self.ver_label)
        row.addStretch(1)
        card.body.addLayout(row)
        self.os_label = QLabel(
            "Hệ điều hành: <b>Windows</b>" if upd.is_windows()
            else f"Hệ điều hành: <b>{sys.platform}</b>"
        )
        self.os_label.setProperty("class", "sub")
        card.body.addWidget(self.os_label)
        self.src_label = QLabel(f"Nguồn cập nhật: <b>GitHub Releases</b> · <code>{upd.DEFAULT_UPDATE_REPO}</code>")
        self.src_label.setProperty("class", "sub")
        self.src_label.setWordWrap(True)
        card.body.addWidget(self.src_label)
        v.addWidget(card)

        # ---- thực hiện ----
        card3 = Card("Thực hiện")
        row2 = QHBoxLayout()
        self.check_btn = QPushButton("Kiểm tra cập nhật")
        self.check_btn.setProperty("class", "primary")
        self.check_btn.clicked.connect(self._check)
        self.apply_btn = QPushButton("Cập nhật ngay")
        self.apply_btn.setProperty("class", "green")
        self.apply_btn.clicked.connect(self._apply)
        self.apply_btn.setEnabled(False)
        row2.addWidget(self.check_btn)
        row2.addWidget(self.apply_btn)
        row2.addStretch(1)
        card3.body.addLayout(row2)

        self.status = QLabel("")
        self.status.setObjectName("taskMeta")
        self.status.setWordWrap(True)
        card3.body.addWidget(self.status)

        if not upd.is_windows():
            note = QLabel(
                "ℹ️ Chức năng cập nhật chỉ dùng cho bản <b>Windows (.exe)</b>. "
                "Trên macOS, hãy build lại từ mã nguồn."
            )
        elif not upd.can_self_update():
            note = QLabel(
                "ℹ️ Đang chạy từ mã nguồn nên không tự cập nhật được — "
                "chỉ bản <b>.exe</b> đã đóng gói mới cập nhật được."
            )
        else:
            note = None
        if note is not None:
            note.setProperty("class", "sub")
            note.setWordWrap(True)
            card3.body.addWidget(note)
        v.addWidget(card3)

        v.addStretch(1)
        scroll.setWidget(root)
        outer.addWidget(scroll, 1)

        dim_when_disabled(self.apply_btn)
        dim_when_disabled(self.check_btn)

    # ------------------------------------------------------------------ #
    def showEvent(self, event) -> None:      # noqa: N802
        super().showEvent(event)
        if not self._auto_checked:           # mở panel là tự kiểm tra 1 lần
            self._auto_checked = True
            from PySide6.QtCore import QTimer

            QTimer.singleShot(300, self._check)

    def _set_busy(self, busy: bool) -> None:
        self.check_btn.setEnabled(not busy)
        has_new = (self._info is not None
                   and upd.is_newer(self._info.get("version", ""))
                   and upd.can_self_update())
        self.apply_btn.setEnabled(not busy and has_new)

    def _check(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self._info = None
        self.status.setText("Đang kiểm tra bản mới trên GitHub…")
        self._set_busy(True)
        w = UpdateWorker()
        self.worker = w
        w.log.connect(self.status.setText)
        w.checked.connect(self._on_checked)
        w.failed.connect(self._on_failed)
        w.finished.connect(lambda: self._set_busy(False))
        w.start()

    def _on_checked(self, info: dict) -> None:
        self._info = info
        ver = info.get("version", "")
        if upd.is_newer(ver):
            notes = info.get("notes") or ""
            msg = f"🎉 Có bản mới <b>{ver}</b> (đang dùng {__version__})."
            if notes:
                msg += f"<br>{notes}"
            self.status.setText(msg)
        else:
            self._info = None
            self.status.setText(f"✅ Đang dùng bản mới nhất ({__version__}).")
            self.apply_btn.setEnabled(False)

    def _on_failed(self, err: str) -> None:
        low = str(err).lower()
        if any(k in low for k in ("404", "not found", "connect", "timed out", "timeout",
                                  "getaddrinfo", "name or service", "ssl")):
            self.status.setText(
                "ℹ️ Chưa kiểm tra được bản phát hành trên GitHub. Chi tiết: " + str(err)[:160]
            )
        else:
            self.status.setText("✗ Lỗi: " + str(err)[:300])

    def _apply(self) -> None:
        if not self._info:
            return
        if self.worker and self.worker.isRunning():
            return
        self.status.setText("Bắt đầu tải bản mới…")
        self._set_busy(True)
        w = UpdateWorker(apply_url=self._info.get("url", ""))
        self.worker = w
        w.log.connect(self.status.setText)
        w.applied.connect(self._on_applied)
        w.failed.connect(self._on_failed)
        w.finished.connect(lambda: self._set_busy(False))
        w.start()

    def _on_applied(self, _tmp: str) -> None:
        self.status.setText("Đang khởi động lại phần mềm để hoàn tất cập nhật…")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1200, self._quit_app)

    def _quit_app(self) -> None:
        from PySide6.QtWidgets import QApplication

        win = self.window()
        if hasattr(win, "shutdown_workers"):
            try:
                win.shutdown_workers()
            except Exception:
                pass
        QApplication.quit()
