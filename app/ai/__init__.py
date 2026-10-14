"""Module AI: viết nội dung."""
from .manager import build_prompt, generate_content, read_rule
from .providers import AIError

__all__ = ["generate_content", "build_prompt", "read_rule", "AIError"]
