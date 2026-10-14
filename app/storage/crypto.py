"""Mã hoá API key / mật khẩu / session (lựa chọn "A").

Khoá được sinh 1 lần và lưu trong thư mục dữ liệu của app (quyền 600).
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from ..config import secret_key_path


def _load_key() -> bytes:
    p = secret_key_path()
    if p.exists():
        return p.read_bytes().strip()
    key = Fernet.generate_key()
    p.write_bytes(key)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return key


_fernet: Fernet | None = None


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


def encrypt(value: str | None) -> str:
    if not value:
        return ""
    return _f().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str | None) -> str:
    if not token:
        return ""
    try:
        return _f().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # Dữ liệu cũ/không hợp lệ
        return ""


def mask(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    return "•" * max(0, len(value) - keep) + value[-keep:]


def fingerprint(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha1(value.encode()).digest()).decode()[:10]
