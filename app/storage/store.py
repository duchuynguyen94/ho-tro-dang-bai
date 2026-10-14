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
        fmt = self.data.setdefault("formats", {"title": "", "content": "", "description": "", "tags": ""})
        if not fmt.get("content"):
            for s in self.data.get("sites", []):
                sf = s.get("formats") or {}
                if sf.get("content"):
                    fmt.update({k: sf.get(k, "") or "" for k in ("title", "content", "description", "tags")})
                    break
        # watermark chéo lấy theo URL website
        for s in self.data.get("sites", []):
            if not s.get("watermark"):
                s["watermark"] = s.get("url", "")

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
