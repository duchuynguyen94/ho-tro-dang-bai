"""Đường dẫn & cấu hình chung của ứng dụng.

Toàn bộ dữ liệu người dùng (cấu hình, key/mật khẩu đã mã hoá, session đăng nhập,
ảnh, file format) được lưu trong thư mục dữ liệu riêng của app — theo lựa chọn "A".
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
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


@lru_cache(maxsize=1)
def app_assets_dir() -> Path:
    """Thư mục asset đóng gói KÈM app (mặc định của phần mềm).

    - Chạy từ mã nguồn: `app/assets`
    - Chạy .app/.exe (PyInstaller): `<_MEIPASS>/app/assets` (do --add-data "app/assets")
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for cand in (base / "app" / "assets", base / "assets"):
            if cand.exists():
                return cand
        return base / "app" / "assets"
    return Path(__file__).resolve().parent / "assets"


@lru_cache(maxsize=256)
def default_asset_path(rel: str) -> str:
    """Đường dẫn asset mặc định theo đường dẫn con (vd "default_rules/rule_content.pdf")."""
    p = app_assets_dir() / rel
    return str(p) if p.exists() else ""


@lru_cache(maxsize=256)
def default_asset(name: str) -> str:
    """Đường dẫn asset mặc định của phần mềm (rỗng nếu chưa có file)."""
    p = app_assets_dir() / "default" / name
    return str(p) if p.exists() else ""


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


def posts_dir() -> Path:
    """Mỗi công việc 1 thư mục riêng (tên = ID công việc) để upload lên web."""
    return _sub("posts")


def sessions_dir() -> Path:
    """Session đăng nhập (cookie) của từng website."""
    return _sub("sessions")


def logs_dir() -> Path:
    return _sub("logs")


def resource_path(rel: str) -> Path:
    """Truy cập tài nguyên đi kèm (assets) khi chạy nguồn hoặc khi đã đóng gói."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return Path(base) / rel
