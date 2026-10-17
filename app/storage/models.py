"""Mô hình dữ liệu của ứng dụng."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import crypto


def new_id(prefix: str = "") -> str:
    return (prefix + uuid.uuid4().hex[:12]) if prefix else uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Format / quy định cho AI (file .txt | .html | .doc)
# --------------------------------------------------------------------------- #
@dataclass
class Formats:
    """3 file quy định dùng chung: nội dung, SEO/đầu ra, trích xuất model."""

    content: str = ""
    seo: str = ""
    extractor: str = ""
    # giữ lại để tương thích cấu hình cũ
    title: str = ""
    description: str = ""
    tags: str = ""

    RULE_FILES = {"content": "rule_content.pdf", "seo": "rule_seo.pdf",
                  "extractor": "rule_model_extractor.pdf"}

    def rule(self, kind: str) -> str:
        """Đường dẫn file rule HIỆU DỤNG: file riêng của người dùng -> nếu trống thì file mặc định."""
        from ..config import default_asset_path

        own = str(getattr(self, kind, "") or "").strip()
        if own and Path(own).exists():
            return own
        name = self.RULE_FILES.get(kind, "")
        return default_asset_path(f"default_rules/{name}") or own

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "seo": self.seo,
            "extractor": self.extractor,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "Formats":
        d = d or {}
        return cls(
            content=d.get("content", ""),
            seo=d.get("seo", ""),
            extractor=d.get("extractor", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            tags=d.get("tags", ""),
        )


# --------------------------------------------------------------------------- #
# Kịch bản đăng bài (recorder)
# --------------------------------------------------------------------------- #
@dataclass
class ScriptStep:
    action: str = "click"          # open|type|click|upload|select|press|wait
    selector: str = ""             # selector ưu tiên
    selectors: list[str] = field(default_factory=list)  # dự phòng
    value: str = ""                # giá trị cố định hoặc biến {{title}}...
    note: str = ""                 # mô tả tiếng Việt
    source: str = "recorded"       # auto|recorded|fallback
    optional: bool = False         # True = không thấy phần tử thì BỎ QUA, không dừng
    force: bool = False            # True = điền/bấm kể cả khi phần tử đang bị ẩn

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ScriptStep":
        return cls(
            action=d.get("action", "click"),
            selector=d.get("selector", ""),
            selectors=list(d.get("selectors") or []),
            value=d.get("value", ""),
            note=d.get("note", ""),
            source=d.get("source", "recorded"),
            optional=bool(d.get("optional", False)),
            force=bool(d.get("force", False)),
        )


@dataclass
class Script:
    steps: list[ScriptStep] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "Script | None":
        if not d:
            return None
        return cls(
            steps=[ScriptStep.from_dict(s) for s in d.get("steps", [])],
            created_at=d.get("created_at", now_iso()),
            version=int(d.get("version", 1)),
        )


# --------------------------------------------------------------------------- #
# Website
# --------------------------------------------------------------------------- #
@dataclass
class Site:
    id: str = field(default_factory=lambda: new_id("site_"))
    name: str = ""
    url: str = ""
    new_post_url: str = ""
    username: str = ""
    password_enc: str = ""
    logo_path: str = ""
    frame_path: str = ""
    footer_bars: list[str] = field(default_factory=list)   # 2 hình thanh thông tin
    footer_mode: str = "random"                            # random|bar1|bar2
    watermark: str = ""                                    # https://site.com
    formats: Formats = field(default_factory=Formats)
    script: Script | None = None
    session_file: str = ""                                 # session đăng nhập đã lưu

    # --- mật khẩu ---
    def set_password(self, plain: str) -> None:
        self.password_enc = crypto.encrypt(plain)

    def get_password(self) -> str:
        return crypto.decrypt(self.password_enc)

    def has_format_content(self) -> bool:
        return bool(self.formats.content)

    @property
    def watermark_text(self) -> str:
        """Watermark chéo: dùng ô nhập riêng; để trống thì lấy mặc định của phần mềm."""
        return (self.watermark or DEFAULT_WATERMARK).strip()

    # --- serialize ---
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "new_post_url": self.new_post_url,
            "username": self.username,
            "password_enc": self.password_enc,
            "logo_path": self.logo_path,
            "frame_path": self.frame_path,
            "footer_bars": list(self.footer_bars),
            "footer_mode": self.footer_mode,
            "watermark": self.watermark,
            "formats": self.formats.to_dict(),
            "script": self.script.to_dict() if self.script else None,
            "session_file": self.session_file,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Site":
        return cls(
            id=d.get("id") or new_id("site_"),
            name=d.get("name", ""),
            url=d.get("url", ""),
            new_post_url=d.get("new_post_url", ""),
            username=d.get("username", ""),
            password_enc=d.get("password_enc", ""),
            logo_path=d.get("logo_path", ""),
            frame_path=d.get("frame_path", ""),
            footer_bars=list(d.get("footer_bars") or []),
            footer_mode=d.get("footer_mode", "random"),
            watermark=d.get("watermark", ""),
            formats=Formats.from_dict(d.get("formats")),
            script=Script.from_dict(d.get("script")),
            session_file=d.get("session_file", ""),
        )


# --------------------------------------------------------------------------- #
# Công việc đăng bài
# --------------------------------------------------------------------------- #
STATUS_QUEUED = "queued"
STATUS_GENERATING = "generating"
DEFAULT_LOGIN = "ngochuyduong2022@gmail.com"     # tài khoản đăng nhập điền sẵn (mật khẩu KHÔNG lưu)
DEFAULT_WATERMARK = "https://ngochuyduong.com"   # watermark mặc định khi website để trống

# Website tạo sẵn khi MÁY MỚI CÀI phần mềm (kịch bản kèm theo nếu có trong app/assets)
DEFAULT_SITES = (
    "ngochuyduong.com",
    "thietbi-congnghiep.com",
    "thietbi-tudonghoa.com",
    "enda-vietnam.com",
)   # watermark mặc định khi website để trống

STATUS_FINISH = "finish"        # đã tạo xong nội dung
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

STATUS_LABELS = {
    STATUS_QUEUED: "Đang chờ",
    STATUS_GENERATING: "đang tạo",
    STATUS_FINISH: "đã xong",
    STATUS_ERROR: "lỗi",
    STATUS_CANCELLED: "chưa tạo",
}


@dataclass
class Task:
    id: str = field(default_factory=lambda: new_id("task_"))
    site_id: str = ""
    site_name: str = ""
    source_url: str = ""
    brand_logo_fallback: str = ""
    image_count: int = 3
    footer_mode: str = "random"      # random | bar1 | bar2 (chọn ở trình sửa ảnh)
    status: str = STATUS_QUEUED
    progress: int = 0
    error_stage: str = ""   # "" | "content" | "post" (lỗi ở bước nào)
    message: str = ""
    created_at: str = field(default_factory=now_iso)
    result: dict[str, Any] = field(default_factory=dict)
    # result = {title, focus_keyword, description, tags, content_html,
    #           images:[{path, variant, footer}], brand_logo, product_images:[]}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=d.get("id") or new_id("task_"),
            site_id=d.get("site_id", ""),
            site_name=d.get("site_name", ""),
            source_url=d.get("source_url", ""),
            brand_logo_fallback=d.get("brand_logo_fallback", ""),
            image_count=int(d.get("image_count", 3)),
            footer_mode=d.get("footer_mode", "random"),
            status=d.get("status", STATUS_QUEUED),
            progress=int(d.get("progress", 0)),
            error_stage=d.get("error_stage", ""),
            message=d.get("message", ""),
            created_at=d.get("created_at", now_iso()),
            result=dict(d.get("result") or {}),
        )


# --------------------------------------------------------------------------- #
# Cấu hình tổng
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG: dict[str, Any] = {
    "ai_content": {
        "active": "chatgpt",
        "fallback": False,
        "order": ["chatgpt", "gemini", "groq", "deepseek", "openai"],
        "providers": {
            "gemini": {"api_key_enc": "", "model": "gemini-3.8-flash"},
            "groq": {"api_key_enc": "", "model": "llama-3.3-70b-versatile"},
            "deepseek": {"api_key_enc": "", "model": "deepseek-chat"},
            "chatgpt": {"session_file": "", "project": "", "project_url": "",
                        "show_browser": True},
            "openai": {"api_key_enc": "", "model": "gpt-4o-mini"},
        },
    },
    "ai_image": {
        "pillow": {"enabled": True, "output_format": "JPG", "jpg_quality": 90, "size": 1200},
        "active": "off",
        "providers": {
            "gemini": {"api_key_enc": "", "model": "gemini-3.8-flash-image"},
            "fal": {"api_key_enc": "", "model": "flux-kontext/dev"},
            "openai": {"api_key_enc": "", "model": "gpt-image-1"},
            "off": {},
        },
    },
    "title_links": ["https://samoapumps.com", "https://enda-vietnam.com"],
    "title_link_first": "https://ngochuyduong.com",   # link cho TIÊU ĐỀ ĐẦU TIÊN (h1/h2 đầu)
    "sites": [],
    "tasks": [],
    "formats": {          # format & rule dùng chung cho MỌI website
        "content": "",     # Rule Content  – quy tắc viết bài
        "seo": "",         # Rule SEO      – yêu cầu đầu ra (title, keyword, mô tả, tags)
        "extractor": "",   # Rule Model Extractor – trích xuất Product Models
        "image_rules": ["{title}", "Tổng kho hàng sẵn {title}", "Đại lý giá tốt {title}"],
    },
}
