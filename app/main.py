"""Điểm khởi chạy ứng dụng."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.style import QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ho Tro Dang Bai")
    app.setOrganizationName("duchuynguyen94")
    app.setStyleSheet(QSS)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
