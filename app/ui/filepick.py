"""Hộp chọn file/tệp có NHỚ THƯ MỤC đã dùng gần nhất (config.json -> ui.pick_dir)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog


def last_dir(store) -> str:
    """Thư mục đã chọn lần trước (rỗng nếu chưa có / không còn tồn tại)."""
    try:
        d = str(((store.data.get("ui") or {}).get("pick_dir") or "")).strip()
    except Exception:      # noqa: BLE001
        return ""
    try:
        if d and Path(d).is_dir():
            return d
    except Exception:      # noqa: BLE001
        pass
    return ""


def remember(store, path: str) -> None:
    """Ghi nhớ thư mục của file/thư mục vừa chọn."""
    if not store or not path:
        return
    try:
        p = Path(path)
        d = str(p.parent) if p.is_file() else str(p)
        ui = store.data.setdefault("ui", {})
        if ui.get("pick_dir") != d:
            ui["pick_dir"] = d
            store.save()
    except Exception:      # noqa: BLE001
        pass


def open_file(store, parent, caption: str, filt: str) -> str:
    """Chọn 1 file -> nhớ thư mục. Trả về đường dẫn (rỗng nếu huỷ)."""
    path, _ = QFileDialog.getOpenFileName(parent, caption, last_dir(store), filt)
    if path:
        remember(store, path)
    return path or ""


def open_files(store, parent, caption: str, filt: str) -> list:
    """Chọn NHIỀU file -> nhớ thư mục. Trả về danh sách đường dẫn."""
    paths, _ = QFileDialog.getOpenFileNames(parent, caption, last_dir(store), filt)
    if paths:
        remember(store, paths[0])
    return list(paths or [])
