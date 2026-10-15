"""Module AI: viết nội dung (2 bước Content → SEO)."""
from .manager import (
    build_content_prompt,
    build_seo_prompt,
    generate_content,
    generate_field,
    read_rule,
    text_to_html,
)
from .providers import AIError

__all__ = [
    "generate_content",
    "generate_field",
    "build_content_prompt",
    "build_seo_prompt",
    "read_rule",
    "text_to_html",
    "AIError",
]
