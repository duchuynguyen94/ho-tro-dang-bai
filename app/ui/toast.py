"""Thông báo nhỏ (toast) hiện rồi tự mờ dần."""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

_alive: list = []


def show_toast(source: QWidget, text: str = "Đã lưu thành công", ms: int = 1800,
               ok: bool = True) -> QLabel | None:
    """Hiện thông báo ở góc dưới-phải cửa sổ rồi tự mờ dần và biến mất.

    ok=True  -> nền xanh (thành công)
    ok=False -> nền đỏ  (thất bại)
    """
    win = source.window()
    if win is None:
        return None

    bg = "#16a34a" if ok else "#dc2626"
    icon = "✓" if ok else "✗"
    lab = QLabel(f"{icon}  {text}", win)
    lab.setStyleSheet(
        f"background:{bg};color:#ffffff;border-radius:9px;"
        "padding:11px 18px;font-weight:600;font-size:13px;"
    )
    lab.adjustSize()

    x = max(12, win.width() - lab.width() - 28)
    y = max(12, win.height() - lab.height() - 54)
    lab.move(x, y)
    lab.show()
    lab.raise_()

    eff = QGraphicsOpacityEffect(lab)
    lab.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", lab)
    anim.setDuration(700)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.finished.connect(lab.deleteLater)

    QTimer.singleShot(ms, anim.start)
    _alive.append((lab, anim))
    lab.destroyed.connect(lambda *_: _alive.clear() if not _alive else None)
    return lab
