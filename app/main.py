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


def _check_browser() -> int:
    """Chẩn đoán: thử mở trình duyệt và ghi kết quả ra file (dùng khi đóng gói .app)."""
    import traceback

    from .config import app_data_dir
    from .wp import WPBrowser

    out = app_data_dir() / "browser_check.log"
    lines: list[str] = []
    try:
        br = WPBrowser(headless=True, site_id="chatgpt")
        page = br.open()
        lines.append(f"OK | channel_used={br.channel_used} | url={page.url}")
        try:
            br.close()
        except Exception:
            pass
    except Exception as exc:      # noqa: BLE001
        lines.append("LOI: " + str(exc))
        lines.append(traceback.format_exc())
    text = "\n".join(lines)
    try:
        out.write_text(text, encoding="utf-8")
    except OSError:
        pass
    print(text)
    return 0


# --------------------------------------------------------------------------- #
# Chỉ cho phép 1 bản chạy: mở lần 2 -> đưa cửa sổ đang chạy lên trước rồi tự thoát
# --------------------------------------------------------------------------- #
SINGLE_NAME = "ho-tro-dang-bai-single"


def _notify_running_instance() -> bool:
    """Nếu ĐÃ có bản đang chạy -> báo nó hiện lên + trả True (bản mới sẽ thoát)."""
    try:
        from PySide6.QtNetwork import QLocalSocket

        sock = QLocalSocket()
        sock.connectToServer(SINGLE_NAME)
        if sock.waitForConnected(400):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(400)
            try:
                sock.disconnectFromServer()
            except Exception:      # noqa: BLE001
                pass
            return True
    except Exception:      # noqa: BLE001
        pass
    return False


def _start_single_server(win):
    """Lắng nghe lần mở sau -> đưa cửa sổ hiện tại lên trước."""
    try:
        from PySide6.QtNetwork import QLocalServer

        try:
            QLocalServer.removeServer(SINGLE_NAME)
        except Exception:      # noqa: BLE001
            pass
        srv = QLocalServer()
        srv.listen(SINGLE_NAME)

        def _on_new() -> None:
            while srv.hasPendingConnections():
                c = srv.nextPendingConnection()
                try:
                    c.waitForReadyRead(200)
                    c.readAll()
                except Exception:      # noqa: BLE001
                    pass
                try:
                    win.showNormal()
                    win.raise_()
                    win.activateWindow()
                except Exception:      # noqa: BLE001
                    pass

        srv.newConnection.connect(_on_new)
        return srv
    except Exception:      # noqa: BLE001
        return None


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow
    from .ui.style import QSS

    if "--check-browser" in sys.argv:
        _install_error_log()
        return _check_browser()

    _install_error_log()

    app = QApplication(sys.argv)
    app.setApplicationName("Ho Tro Dang Bai")
    app.setOrganizationName("duchuynguyen94")
    app.setStyleSheet(QSS)

    # Đã có bản đang chạy -> đưa lên trước rồi thoát (chỉ 1 bản duy nhất)
    if _notify_running_instance():
        return 0

    win = MainWindow()
    _single_server = _start_single_server(win)      # giữ tham chiếu (không để bị xoá)
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
