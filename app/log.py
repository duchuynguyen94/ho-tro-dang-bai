"""Ghi lỗi ra <thư mục dữ liệu>/errors.log (dùng chung cho toàn app).

Thay cho các chỗ `except Exception: pass` – lỗi vẫn không làm app dừng,
nhưng ĐƯỢC GHI LẠI để lần sau biết đúng nguyên nhân (tab "Log lỗi").
"""
from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime

from . import config

_LOCK = threading.Lock()
MAX_BYTES = 2 * 1024 * 1024          # 2 MB -> xoay sang errors.log.1


def log_error(source: str, message: str = "", exc: BaseException | None = None) -> None:
    """Ghi 1 dòng lỗi (kèm traceback nếu có). KHÔNG BAO GIỜ raise."""
    try:
        if exc is None:
            exc = sys.exc_info()[1]
        p = config.app_data_dir() / "errors.log"
        with _LOCK:
            try:
                if p.exists() and p.stat().st_size > MAX_BYTES:
                    p.replace(p.with_suffix(".log.1"))
            except Exception:      # noqa: BLE001
                pass
            with p.open("a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {source}: {message}\n")
                if exc is not None:
                    tb = "".join(traceback.format_exception(type(exc), exc,
                                                            exc.__traceback__))
                    f.write(tb[:4000])
                    if not tb.endswith("\n"):
                        f.write("\n")
    except Exception:      # noqa: BLE001
        pass


def log_exc(source: str, message: str = "") -> None:
    """Ghi lỗi đang xảy ra (gọi trong khối `except`)."""
    log_error(source, message, sys.exc_info()[1])
