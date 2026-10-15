"""Điểm khởi chạy ứng dụng."""
from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime


def _install_error_log() -> None:
    """Ghi mọi lỗi KHÔNG bắt được ra <thư mục dữ liệu>/errors.log (để soi lỗi)."""
    try:
        from .config import app_data_dir

        log_path = app_data_dir() / "errors.log"
    except Exception:      # noqa: BLE001
        log_path = None

    def hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(text)
        if log_path is None:
            return
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} =====\n")
                f.write(text)
        except OSError:
            pass

    sys.excepthook = hook

    def thread_hook(args) -> None:
        if args.exc_type is SystemExit:
            return
        hook(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = thread_hook


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow
    from .ui.style import QSS

    _install_error_log()

    app = QApplication(sys.argv)
    app.setApplicationName("Ho Tro Dang Bai")
    app.setOrganizationName("duchuynguyen94")
    app.setStyleSheet(QSS)

    win = MainWindow()
    win.show()
    code = app.exec()
    # Chờ mọi luồng nền kết thúc trước khi thoát (tránh crash 'QThread destroyed while running')
    try:
        win.shutdown_workers()
    except Exception:      # noqa: BLE001
        pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
