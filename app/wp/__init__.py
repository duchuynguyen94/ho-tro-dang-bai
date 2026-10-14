"""Module WordPress: trình duyệt, ghi kịch bản, phát lại."""
from .browser import WPBrowser
from .player import play as play_script, render as render_value
from . import recorder

__all__ = ["WPBrowser", "play_script", "render_value", "recorder"]
