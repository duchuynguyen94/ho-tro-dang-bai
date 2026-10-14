"""Màn hình 'Log lỗi'."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..style import Card


class ErrorLogPage(QWidget):
    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 20)

        head = QHBoxLayout()
        title = QLabel("Log lỗi")
        title.setProperty("class", "h2")
        head.addWidget(title)
        head.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("taskMeta")
        head.addWidget(self.count_label)
        clear = QPushButton("Xoá log")
        clear.setProperty("class", "danger")
        clear.clicked.connect(self._clear)
        head.addWidget(clear)
        v.addLayout(head)

        card = Card("Lỗi gần đây")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Thời gian", "Nguồn", "Nội dung lỗi"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 160)
        self.table.setWordWrap(True)
        card.body.addWidget(self.table)
        v.addWidget(card, 1)

        self.refresh()

    def refresh(self) -> None:
        rows = list(reversed(self.store.error_log))
        self.count_label.setText(f"{len(rows)} lỗi")
        self.table.setRowCount(len(rows))
        for i, item in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(item.get("time", "")))
            self.table.setItem(i, 1, QTableWidgetItem(item.get("source", "")))
            self.table.setItem(i, 2, QTableWidgetItem(item.get("message", "")))

    def _clear(self) -> None:
        ans = QMessageBox.question(
            self, "Xoá log", "Xoá toàn bộ log lỗi?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self.store.clear_error_log()
        self.refresh()
