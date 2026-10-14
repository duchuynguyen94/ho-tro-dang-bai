"""Module Google Sheets."""
from .gsheet import SheetsError, append_row, test_connection

__all__ = ["append_row", "test_connection", "SheetsError"]
