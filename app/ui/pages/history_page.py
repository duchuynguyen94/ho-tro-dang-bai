"""Màn hình 'Lịch sử'."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...storage.models import STATUS_DONE, STATUS_ERROR, STATUS_LABELS
from ..style import Card


class HistoryPage(QWidget):
    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 20)
        title = QLabel("Lịch sử")
        title.setProperty("class", "h2")
        v.addWidget(title)

        card = Card("Các bài đã xử lý")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Bài viết", "Website", "Trạng thái", "Link nguồn", "Link kết quả"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        card.body.addWidget(self.table)
        v.addWidget(card, 1)
        self.refresh()

    def refresh(self) -> None:
        tasks = [t for t in self.store.tasks if t.status in (STATUS_DONE, STATUS_ERROR)]
        self.table.setRowCount(len(tasks))
        for i, t in enumerate(reversed(tasks)):
            self.table.setItem(i, 0, QTableWidgetItem((t.result.get("title") or "")[:50]))
            self.table.setItem(i, 1, QTableWidgetItem(t.site_name))
            self.table.setItem(i, 2, QTableWidgetItem(STATUS_LABELS.get(t.status, t.status)))
            self.table.setItem(i, 3, QTableWidgetItem(t.source_url))
            self.table.setItem(i, 4, QTableWidgetItem(t.result.get("result_url", "")))
