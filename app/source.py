"""Đọc nội dung + ảnh từ link nguồn."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import product_dir

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

_IMG_ATTRS = ("src", "data-src", "data-lazy-src", "data-original", "data-srcset")
_SKIP_EXT = (".svg", ".gif", ".ico")


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    for img in soup.find_all("img"):
        for attr in _IMG_ATTRS:
            val = img.get(attr)
            if not val:
                continue
            candidate = str(val).split(",")[0].strip().split(" ")[0]
            if not candidate or candidate.startswith("data:"):
                continue  # bỏ ảnh placeholder nội tuyến, thử thuộc tính kế tiếp (data-src…)
            full = urljoin(base_url, candidate)
            if _is_usable_image(full):
                urls.append(full)
                break
    # loại trùng (kể cả các biến thể -300x300, -150x150 của cùng 1 ảnh), giữ thứ tự
    seen, out = set(), []
    for u in urls:
        key = re.sub(r"-\d{2,4}x\d{2,4}(?=\.[a-z]+$)", "", u.lower())
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def _is_usable_image(url: str) -> bool:
    path = urlparse(url).path.lower()
    if not path:
        return False
    if any(path.endswith(ext) for ext in _SKIP_EXT):
        return False
    lowered = url.lower()
    if any(k in lowered for k in ("logo", "icon", "sprite", "placeholder", "avatar", "banner")):
        return False
    return True


def fetch_source(url: str, max_chars: int = 6000) -> dict:
    """Tải trang nguồn: trả về tiêu đề, văn bản, danh sách ảnh."""
    r = httpx.get(url, headers=UA, follow_redirects=True, timeout=40)
    r.raise_for_status()
    html = r.text

    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form"]):
        tag.decompose()

    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    text = re.sub(r"\n{3,}", "\n\n", text)[:max_chars]

    images = _extract_images(soup, url)
    return {"url": url, "title": title, "text": text, "images": images}


def find_brand_logo(url: str) -> str:
    """Thử tìm logo thương hiệu trên trang nguồn (thẻ <img> có 'logo'/'brand').

    Trả về URL ảnh hoặc "" nếu không tìm thấy (khi đó dùng logo dự phòng).
    """
    try:
        r = httpx.get(url, headers=UA, follow_redirects=True, timeout=30)
        r.raise_for_status()
    except Exception:
        return ""
    soup = BeautifulSoup(r.text, "lxml")
    for img in soup.find_all("img"):
        blob = " ".join(
            str(img.get(a, "")) for a in ("src", "alt", "class", "id", "data-src")
        ).lower()
        if "logo" in blob or "brand" in blob:
            src = img.get("src") or img.get("data-src")
            if src:
                full = urljoin(url, src)
                if full.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")):
                    return full
    return ""


def guess_brand_name(page_title: str) -> str:
    """Đoán tên thương hiệu từ tiêu đề trang (từ viết hoa đầu tiên)."""
    import re as _re

    m = _re.findall(r"\b[A-Z][A-Za-z0-9&.\-]{2,}\b", page_title or "")
    stop = {"The", "And", "For", "With", "Hotline", "Shop", "Giá", "Khuyến"}
    for tok in m:
        if tok not in stop:
            return tok
    return ""


def search_images(query: str, limit: int = 3) -> list[str]:
    """Tìm ảnh trên mạng (Bing Images) — dùng khi link nguồn không có ảnh."""
    q = (query or "").strip()
    if not q:
        return []
    out: list[str] = []
    try:
        r = httpx.get(
            "https://www.bing.com/images/search",
            params={"q": q, "form": "HDRSC2"},
            headers=UA, follow_redirects=True, timeout=40,
        )
        r.raise_for_status()
        html = r.text
        urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', html)
        if not urls:
            urls = re.findall(r'"murl":"(.*?)"', html)
        for u in urls:
            u = u.replace("\\/", "/").strip()
            if u.startswith("http") and u not in out:
                out.append(u)
            if len(out) >= limit:
                break
    except Exception:
        return out
    return out


def save_image_bytes(url: str, data: bytes, prefix: str = "sp") -> str:
    """Lưu ảnh (đã tải trong bộ nhớ) ra máy khi người dùng bấm CHÈN."""
    if not data:
        return ""
    ext = Path(urlparse(url).path).suffix.lower() or ".png"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".png"
    from .storage import new_id

    dest = product_dir() / f"{prefix}_{new_id()}{ext}"
    dest.write_bytes(data)
    return str(dest)


def download_image(url: str, prefix: str = "sp") -> str:
    """Tải 1 ảnh về máy, trả về đường dẫn."""
    r = httpx.get(url, headers=UA, follow_redirects=True, timeout=60)
    r.raise_for_status()
    ext = Path(urlparse(url).path).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    from .storage import new_id

    dest = product_dir() / f"{prefix}_{new_id()}{ext}"
    dest.write_bytes(r.content)
    return str(dest)
