"""Module AI: viết nội dung (1 lần gọi: JSON SEO + nội dung)."""
from .manager import (
    build_combined_prompt,
    generate_content,
    read_rule,
    text_to_html,
)
from .providers import AIError

__all__ = [
    "generate_content",
    "build_combined_prompt",
    "read_rule",
    "text_to_html",
    "AIError",
]
