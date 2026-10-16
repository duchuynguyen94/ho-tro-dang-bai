"""Đọc/ghi cấu hình tổng ra config.json + tiện ích lưu file."""
from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

from .. import config
from .models import DEFAULT_CONFIG, Site, Task


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Store:
    """Bọc toàn bộ trạng thái ứng dụng."""

    def __init__(self) -> None:
        self.data: dict = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    # ------------------------------------------------------------------ #
    # Nạp / lưu
    # ------------------------------------------------------------------ #
    def load(self) -> None:
        p = config.config_path()
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                self.data = _deep_merge(DEFAULT_CONFIG, raw)
                self._migrate()
                return
            except (json.JSONDecodeError, OSError):
                pass
        self.data = copy.deepcopy(DEFAULT_CONFIG)

    def _migrate(self) -> None:
        """Chuyển format của site cũ sang format dùng chung (nếu chưa có)."""
        fmt = self.data.setdefault("formats", {})
        for k in ("content", "seo", "extractor"):
            fmt.setdefault(k, "")
        if not fmt.get("content"):
            for s in self.data.get("sites", []):
                sf = s.get("formats") or {}
                if sf.get("content"):
                    fmt["content"] = sf.get("content", "") or ""
                    fmt["seo"] = sf.get("seo") or sf.get("title") or ""
                    break
        if not isinstance(fmt.get("image_rules"), list) or not fmt.get("image_rules"):
            fmt["image_rules"] = ["", "", ""]
        # watermark chéo lấy theo URL website
        for s in self.data.get("sites", []):
            if not s.get("watermark"):
                s["watermark"] = s.get("url", "")

        # cập nhật model Gemini cũ đã bị Google bỏ
        old_models = {"gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-1.5-flash"}
        providers = (self.data.get("ai_content") or {}).get("providers") or {}

        # bỏ Ollama, thêm DeepSeek
        if "ollama" in providers:
            providers.pop("ollama", None)
        if "openrouter" in providers:
            providers.pop("openrouter", None)
        providers.setdefault("deepseek", {"api_key_enc": "", "model": "deepseek-chat"})
        providers.setdefault("chatgpt", {"session_file": "", "project": "", "project_url": ""})
        providers.get("chatgpt", {}).setdefault("project", "")
        providers.get("chatgpt", {}).setdefault("project_url", "")
        providers.get("chatgpt", {}).setdefault("show_browser", False)
        self.data["ai_content"]["providers"] = providers

        default_order = ["gemini", "groq", "deepseek", "chatgpt", "openai"]
        order = [p for p in (self.data["ai_content"].get("order") or []) if p in providers]
        order += [p for p in default_order if p in providers and p not in order]
        order += [p for p in providers if p not in order]
        self.data["ai_content"]["order"] = order
        if self.data["ai_content"].get("active") == "ollama":
            self.data["ai_content"]["active"] = order[0] if order else "gemini"

        g = providers.get("gemini") or {}
        if g.get("model") in old_models:
            g["model"] = "gemini-3.8-flash"

        img_providers = (self.data.get("ai_image") or {}).get("providers") or {}
        gi = img_providers.get("gemini") or {}
        if gi.get("model") in ("gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation", ""):
            gi["model"] = "gemini-3.8-flash-image"

    def save(self) -> None:
        p = config.config_path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(p)

    # ------------------------------------------------------------------ #
    # Sites
    # ------------------------------------------------------------------ #
    @property
    def sites(self) -> list[Site]:
        return [Site.from_dict(d) for d in self.data.get("sites", [])]

    def set_sites(self, sites: list[Site]) -> None:
        self.data["sites"] = [s.to_dict() for s in sites]

    def get_site(self, site_id: str) -> Site | None:
        for s in self.sites:
            if s.id == site_id:
                return s
        return None

    def upsert_site(self, site: Site) -> None:
        sites = self.sites
        for i, s in enumerate(sites):
            if s.id == site.id:
                sites[i] = site
                break
        else:
            sites.append(site)
        self.set_sites(sites)

    def remove_site(self, site_id: str) -> None:
        self.set_sites([s for s in self.sites if s.id != site_id])

    # ------------------------------------------------------------------ #
    # Tasks
    # ------------------------------------------------------------------ #
    @property
    def tasks(self) -> list[Task]:
        return [Task.from_dict(d) for d in self.data.get("tasks", [])]

    def set_tasks(self, tasks: list[Task]) -> None:
        self.data["tasks"] = [t.to_dict() for t in tasks]

    def upsert_task(self, task: Task) -> None:
        tasks = self.tasks
        for i, t in enumerate(tasks):
            if t.id == task.id:
                tasks[i] = task
                break
        else:
            tasks.append(task)
        self.set_tasks(tasks)

    # ------------------------------------------------------------------ #
    # Format & rule dùng chung cho mọi website
    # ------------------------------------------------------------------ #
    @property
    def formats(self) -> "Formats":
        from .models import Formats as _F

        return _F.from_dict(self.data.get("formats"))

    def set_formats(self, fmt) -> None:
        self.data["formats"] = fmt.to_dict()

    def has_format_content(self) -> bool:
        return bool((self.data.get("formats") or {}).get("content"))

    def reset_stale_tasks(self) -> None:
        """Khi mở app: việc đang chạy dở (do tắt app) -> đánh dấu đã dừng."""
        changed = False
        for t in self.data.get("tasks", []):
            if t.get("status") in ("queued", "generating", "posting"):
                t["status"] = "cancelled"
                t["message"] = "Đã dừng (ứng dụng đã đóng khi việc đang chạy)"
                changed = True
        if changed:
            self.save()

    # ------------------------------------------------------------------ #
    # Log lỗi
    # ------------------------------------------------------------------ #
    @property
    def error_log(self) -> list[dict]:
        return list(self.data.get("error_log") or [])

    def log_error(self, source: str, message: str) -> None:
        from .models import now_iso

        log = self.data.setdefault("error_log", [])
        log.append({"time": now_iso(), "source": source, "message": str(message)[:3000]})
        del log[:-500]
        self.save()

    def clear_error_log(self) -> None:
        self.data["error_log"] = []
        self.save()

    @property
    def image_rules(self) -> list[str]:
        rules = (self.data.get("formats") or {}).get("image_rules")
        if not isinstance(rules, list) or not rules:
            rules = ["", "", ""]
        return [str(r) for r in rules]

    def set_image_rules(self, rules: list[str]) -> None:
        self.data.setdefault("formats", {})["image_rules"] = [str(r) for r in rules]

    @property
    def title_links(self) -> list[str]:
        """Danh sách link chèn vào tiêu đề mục (h2 số 2 trở đi)."""
        links = self.data.get("title_links")
        if not isinstance(links, list):
            return []
        return [str(x).strip() for x in links if str(x).strip()]

    def set_title_links(self, links: list[str]) -> None:
        self.data["title_links"] = [str(x).strip() for x in links if str(x).strip()]

    @property
    def title_link_first(self) -> str:
        """Link chèn vào TIÊU ĐỀ ĐẦU TIÊN (h2 đầu)."""
        return str(self.data.get("title_link_first") or "").strip()

    def set_title_link_first(self, link: str) -> None:
        self.data["title_link_first"] = str(link or "").strip()

    @property
    def update_url(self) -> str:
        """Link version.json dùng cho chức năng cập nhật phần mềm."""
        return str(self.data.get("update_url") or "").strip()

    def set_update_url(self, url: str) -> None:
        self.data["update_url"] = str(url or "").strip()

    @property
    def update_token(self) -> str:
        """Token GitHub (chỉ cần khi repo private) — lưu mã hoá."""
        from . import crypto

        return crypto.decrypt(str(self.data.get("update_token_enc") or ""))

    def set_update_token(self, token: str) -> None:
        from . import crypto

        self.data["update_token_enc"] = crypto.encrypt(str(token or "").strip())

    # ------------------------------------------------------------------ #
    # Phần cấu hình con
    # ------------------------------------------------------------------ #
    @property
    def ai_content(self) -> dict:
        return self.data["ai_content"]

    @property
    def ai_image(self) -> dict:
        return self.data["ai_image"]

    @property
    def sheets(self) -> dict:
        return self.data["sheets"]

    # ------------------------------------------------------------------ #
    # Lưu file người dùng tải lên
    # ------------------------------------------------------------------ #
    @staticmethod
    def import_file(src: str | Path, dest_dir: Path, prefix: str = "") -> str:
        """Copy 1 file người dùng chọn vào thư mục dữ liệu, trả về đường dẫn mới."""
        src = Path(src)
        if not src.exists():
            return ""
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe = f"{prefix}{uuid.uuid4().hex[:6]}_{src.name}"
        dest = dest_dir / safe
        shutil.copy2(src, dest)
        return str(dest)
