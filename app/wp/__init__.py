"""Module WordPress: trình duyệt và phát lại kịch bản."""
from .browser import WPBrowser
from .player import play as play_script, render as render_value

__all__ = ["WPBrowser", "play_script", "render_value"]
