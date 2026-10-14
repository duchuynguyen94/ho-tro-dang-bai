"""Ghi link nguồn + link kết quả vào Google Sheets."""
from __future__ import annotations

from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsError(RuntimeError):
    pass


def _client(sheets_cfg: dict):
    sa = sheets_cfg.get("service_account_file")
    if not sa:
        raise SheetsError("Chưa cấu hình Service Account JSON cho Google Sheets.")
    creds = Credentials.from_service_account_file(sa, scopes=SCOPES)
    return gspread.authorize(creds)


def append_row(sheets_cfg: dict, source_url: str, result_url: str, site_name: str = "") -> bool:
    if not sheets_cfg.get("enabled"):
        return False
    sid = sheets_cfg.get("spreadsheet_id")
    if not sid:
        raise SheetsError("Chưa cấu hình Google Sheets ID.")
    client = _client(sheets_cfg)
    sh = client.open_by_key(sid)
    ws = sh.worksheet(sheets_cfg.get("sheet_name") or sh.sheet1.title)

    if (sheets_cfg.get("mode") or "append") == "append":
        ws.append_row([source_url, result_url, site_name, datetime.now().strftime("%d/%m %H:%M")])
        return True

    # cập nhật nếu trùng link nguồn
    col_src = sheets_cfg.get("col_source", "A")
    try:
        cell = ws.find(source_url, in_column=gspread.utils.a1_to_rowcol(f"{col_src}1")[1])
    except gspread.exceptions.CellNotFound:
        cell = None
    if cell:
        ws.update(f"{sheets_cfg.get('col_result', 'B')}{cell.row}", [[result_url]])
    else:
        ws.append_row([source_url, result_url, site_name, datetime.now().strftime("%d/%m %H:%M")])
    return True


def test_connection(sheets_cfg: dict) -> str:
    client = _client(sheets_cfg)
    sh = client.open_by_key(sheets_cfg.get("spreadsheet_id"))
    return sh.title
