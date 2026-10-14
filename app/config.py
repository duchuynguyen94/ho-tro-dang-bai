"""Đường dẫn & cấu hình chung của ứng dụng.

Toàn bộ dữ liệu người dùng (cấu hình, key/mật khẩu đã mã hoá, session đăng nhập,
ảnh, file format) được lưu trong thư mục dữ liệu riêng của app — theo lựa chọn "A".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Ho Tro Dang Bai"
APP_SLUG = "ho-tro-dang-bai"


def app_data_dir() -> Path:
    """Thư mục dữ liệu riêng cho từng hệ điều hành.

    Có thể ghi đè bằng biến môi trường HTDB_DATA_DIR (dùng khi phát triển/test).
    """
    override = os.environ.get("HTDB_DATA_DIR")
    if override:
        base = Path(override).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        return base
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    d = app_data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return app_data_dir() / "config.json"


def secret_key_path() -> Path:
    return app_data_dir() / "secret.key"


def sites_media_dir() -> Path:
    """Ảnh cấu hình của website: logo, thanh thông tin..."""
    return _sub("media")


# tên gọi ngắn gọn dùng trong UI
media_dir = sites_media_dir


def formats_dir() -> Path:
    """File quy định/format (.txt .html .doc) của từng site."""
    return _sub("formats")


def product_dir() -> Path:
    """Ảnh sản phẩm tải từ link nguồn."""
    return _sub("products")


def output_dir() -> Path:
    """Ảnh kết quả (thumbnail/slider) sau khi ghép."""
    return _sub("output")


def sessions_dir() -> Path:
    """Session đăng nhập (cookie) của từng website."""
    return _sub("sessions")


def logs_dir() -> Path:
    return _sub("logs")


def resource_path(rel: str) -> Path:
    """Truy cập tài nguyên đi kèm (assets) khi chạy nguồn hoặc khi đã đóng gói."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return Path(base) / rel
