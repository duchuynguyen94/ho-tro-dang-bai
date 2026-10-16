"""Cập nhật phần mềm (dành cho bản .exe trên Windows).

Cách hoạt động:
1) App đọc file `version.json` ở "Nguồn cập nhật" (Cài đặt → Thiết lập chung):
   {
     "version": "0.2.0",
     "url": "https://.../HoTroDangBai-windows.zip",
     "notes": "Sửa lỗi ... (không bắt buộc)"
   }
2) So sánh với phiên bản đang chạy -> báo có bản mới hay không.
3) Bấm "Cập nhật ngay": tải .zip, giải nén, tạo script .bat rồi chạy script đó.
   Script sẽ: chờ app thoát -> taskkill -> robocopy đè file mới -> mở lại app -> tự xoá.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from . import __version__

# Để trống: người dùng dán link version.json của mình trong Cài đặt
DEFAULT_UPDATE_URL = ""

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def is_windows() -> bool:
    return os.name == "nt"


def can_self_update() -> bool:
    """Chỉ bản .exe đã đóng gói trên Windows mới tự cập nhật được."""
    return is_windows() and bool(getattr(sys, "frozen", False))


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.2.1' -> (0, 2, 1) để so sánh."""
    parts: list[int] = []
    for p in str(text or "").strip().lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def is_newer(remote: str, current: str = __version__) -> bool:
    return parse_version(remote) > parse_version(current)


def check_update(url: str, timeout: float = 20.0) -> dict:
    """Đọc version.json -> {"version", "url", "notes"}."""
    import httpx

    url = (url or "").strip()
    if not url:
        raise RuntimeError("Chưa có link kiểm tra cập nhật (version.json).")
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Không đọc được link cập nhật: {exc}") from exc
    try:
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Link cập nhật không trả về JSON hợp lệ.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Nội dung version.json không hợp lệ.")
    version = str(data.get("version") or "").strip()
    link = str(data.get("url") or data.get("zip") or data.get("download") or "").strip()
    if not version:
        raise RuntimeError("version.json thiếu trường “version”.")
    if not link:
        raise RuntimeError("version.json thiếu trường “url” (link file .zip).")
    return {
        "version": version,
        "url": link,
        "notes": str(data.get("notes") or data.get("note") or "").strip(),
    }


def _download(zip_url: str, dest: Path, log=None) -> None:
    import httpx

    if log:
        log("Đang tải bản mới…")
    with httpx.stream("GET", zip_url, timeout=600, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        got = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(65536):
                f.write(chunk)
                got += len(chunk)
                if log and total:
                    log(f"Đang tải bản mới… {got * 100 // total}%")


def apply_update(zip_url: str, log=None) -> Path:
    """Tải & áp dụng bản mới. Sau khi gọi, app NÊN tự thoát để script cập nhật chạy."""
    if not can_self_update():
        if not is_windows():
            raise RuntimeError("Tự động cập nhật chỉ dành cho bản Windows (.exe).")
        raise RuntimeError("Bản chạy từ mã nguồn — hãy cập nhật bằng git.")

    exe = Path(sys.executable)
    app_dir = exe.parent
    tmp = Path(tempfile.mkdtemp(prefix="htdb_update_"))
    zip_path = tmp / "moi.zip"
    _download(zip_url, zip_path, log)

    if log:
        log("Đang giải nén bản mới…")
    new_dir = tmp / "new"
    new_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(new_dir)
    # zip có thể bọc trong 1 thư mục con -> đi vào đó
    entries = list(new_dir.iterdir())
    dirs = [p for p in entries if p.is_dir()]
    files = [p for p in entries if p.is_file()]
    if len(dirs) == 1 and not files:
        new_dir = dirs[0]
    if not (new_dir / exe.name).exists():
        raise RuntimeError(f"Gói cập nhật không chứa “{exe.name}”.")

    bat = tmp / "cap_nhat.bat"
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'taskkill /IM "{exe.name}" /F >nul 2>&1\r\n'
        "timeout /t 3 /nobreak >nul\r\n"
        f'robocopy "{new_dir}" "{app_dir}" /E /NFL /NDL /NJH /NJS /NP >nul\r\n'
        f'start "" "{app_dir / exe.name}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    if log:
        log("Đang chạy tiến trình cập nhật (app sẽ tự tắt rồi mở lại)…")
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        cwd=str(tmp),
    )
    return tmp
