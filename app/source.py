"""Đọc nội dung + ảnh từ link nguồn."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

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


def _pdf_source(url: str, data: bytes, max_chars: int) -> dict:
    """Đọc nguồn là FILE PDF (link .pdf hoặc file trên máy)."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [(pg.extract_text() or "") for pg in reader.pages]
    text = "\n".join(pages)
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    text = re.sub(r"\n{3,}", "\n\n", text)[:max_chars]
    title = ""
    try:
        meta = reader.metadata or {}
        title = str(meta.get("/Title") or "").strip()
    except Exception:
        title = ""
    if not title:
        first = next((ln for ln in text.splitlines() if len(ln) > 8), "")
        title = first[:120]
    return {"url": url, "title": title, "text": text, "images": []}


def fetch_source(url: str, max_chars: int = 6000) -> dict:
    """Tải trang nguồn: trả về tiêu đề, văn bản, danh sách ảnh.

    Hỗ trợ cả HTML và FILE PDF (link .pdf hoặc file PDF trên máy).
    """
    # file trên máy
    try:
        local = Path(url)
        if local.exists() and local.is_file():
            data = local.read_bytes()
            if local.suffix.lower() == ".pdf" or data[:4] == b"%PDF":
                return _pdf_source(url, data, max_chars)
            html = data.decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "lxml")
            title = soup.title.string.strip() if (soup.title and soup.title.string) else local.stem
            for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form"]):
                tag.decompose()
            text = "\n".join(ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip())
            return {"url": url, "title": title, "text": re.sub(r"\n{3,}", "\n\n", text)[:max_chars],
                    "images": _extract_images(soup, url)}
    except OSError:
        pass

    r = httpx.get(url, headers=UA, follow_redirects=True, timeout=60)
    r.raise_for_status()

    # nguồn là PDF?
    ctype = (r.headers.get("content-type") or "").lower()
    if url.lower().split("?")[0].endswith(".pdf") or "application/pdf" in ctype \
            or r.content[:4] == b"%PDF":
        try:
            return _pdf_source(url, r.content, max_chars)
        except Exception as exc:      # noqa: BLE001
            raise RuntimeError(f"Không đọc được file PDF: {exc}") from exc

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


def search_images(query: str, limit: int = 10, log=None) -> list[str]:
    """Tìm ảnh trên internet theo mã sản phẩm (dùng trình duyệt thật — chắc hơn scrape HTML).

    Trả về tối đa `limit` URL ảnh (mặc định 10).
    """
    q = (query or "").strip()
    if not q:
        return []
    if log:
        log(f"Đang tìm ảnh trên internet theo mã: {q}…")
    urls: list[str] = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            br = None
            for kwargs in ({"channel": "chrome"}, {"channel": "msedge"}, {}):
                try:
                    br = pw.chromium.launch(headless=True, chromium_sandbox=True, **kwargs)
                    break
                except Exception:
                    br = None
            if br is None:
                return []
            try:
                page = br.new_page(viewport={"width": 1400, "height": 1000})
                page.goto(f"https://www.bing.com/images/search?q={quote(q)}",
                          wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                js = """() => {
                        const out = [];
                        document.querySelectorAll('a.iusc').forEach(a => {
                            try {
                                const m = JSON.parse(a.getAttribute('m') || '{}');
                                if (m.murl) out.push(m.murl);
                            } catch (e) {}
                        });
                        if (!out.length) {
                            document.querySelectorAll('img.mimg').forEach(im => {
                                const s = im.getAttribute('src') || '';
                                if (s.startsWith('http')) out.push(s);
                            });
                        }
                        return out;
                    }"""
                # CUỘN THÊM cho tới khi gom ĐỦ số ảnh cần (mỗi lần cuộn Bing nạp thêm ~35 ảnh)
                target = max(int(limit), 1)
                for _ in range(14):
                    urls = page.evaluate(js) or []
                    if len(urls) >= target * 2:      # dư ra để lọc trùng / loại logo-icon
                        break
                    page.mouse.wheel(0, 1800)
                    page.wait_for_timeout(900)
                if not urls:
                    urls = page.evaluate(js) or []
            finally:
                try:
                    br.close()
                except Exception:
                    pass
    except Exception:
        return []

    seen, out = set(), []
    for u in urls:
        low = u.lower()
        if not str(u).startswith("http"):
            continue
        if any(k in low for k in (".svg", "logo", "icon", "sprite", "avatar")):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= max(1, limit):
            break
    if log:
        log(f"Tìm được {len(out)} ảnh từ internet.")
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
