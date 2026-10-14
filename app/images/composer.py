"""Ghép ảnh theo mẫu (thumbnail + slider): logo site - logo brand - ảnh SP - thanh thông tin - watermark."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

DEFAULT_SIZE = 1080
PAD = 40


# --------------------------------------------------------------------------- #
# Tiện ích
# --------------------------------------------------------------------------- #
def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        p = Path(c)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _load_rgba(path: str) -> Image.Image | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return Image.open(p).convert("RGBA")
    except OSError:
        return None


def _fit(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Thu ảnh theo tỉ lệ để lọt trong khung."""
    w, h = img.size
    if w <= 0 or h <= 0:
        return img
    ratio = min(max_w / w, max_h / h, 1.0)
    return img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)


def remove_background_simple(img: Image.Image, threshold: int = 245) -> Image.Image:
    """Tách nền trắng đơn giản -> PNG trong suốt (không cần AI)."""
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                px[x, y] = (r, g, b, 0)
    return img


def remove_background_auto(img: Image.Image, thresh: int = 42) -> Image.Image:
    """Xoá nền theo vùng liền kề từ 4 góc (flood fill) -> PNG trong suốt."""
    img = img.convert("RGBA")
    w, h = img.size
    if w < 3 or h < 3:
        return img
    for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        try:
            ImageDraw.floodfill(img, xy, (0, 0, 0, 0), thresh=thresh)
        except Exception:
            continue
    return img


def prepare_product(path: str, remove_bg: bool = False, thresh: int = 42) -> Image.Image | None:
    """Mở 1 ảnh sản phẩm, tuỳ chọn xoá nền."""
    img = _load_rgba(path)
    if img is None:
        return None
    if remove_bg:
        img = remove_background_auto(img, thresh)
    return img


def _draw_diagonal_watermark(base: Image.Image, text: str, opacity: int = 18) -> None:
    if not text:
        return
    layer = Image.new("RGBA", base.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(layer)
    font = _find_font(max(28, base.size[0] // 18))
    tmp = Image.new("RGBA", (10, 10))
    tw = draw.textlength(text, font=font)
    text_img = Image.new("RGBA", (int(tw) + 20, int(font.size * 1.6)), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_img)
    td.text((10, 10), text, font=font, fill=(15, 23, 42, opacity))
    text_img = text_img.rotate(34, expand=True, resample=Image.BICUBIC)
    x = (base.size[0] - text_img.size[0]) // 2
    y = (base.size[1] - text_img.size[1]) // 2
    layer.alpha_composite(text_img, (x, y))
    base.alpha_composite(layer)


# --------------------------------------------------------------------------- #
# Ghép ảnh chính
# --------------------------------------------------------------------------- #
def compose(
    size: int = DEFAULT_SIZE,
    site_logo: str = "",
    brand_logo: str = "",
    products: list[str] | None = None,
    footer_bar: str = "",
    frame: str = "",
    watermark: str = "",
    watermark_opacity: int = 18,
    transparent_bg: bool = False,
    remove_bg: bool = False,
    remove_bg_thresh: int = 42,
) -> Image.Image:
    products = [p for p in (products or []) if p]
    bg = (255, 255, 255, 0) if transparent_bg else (255, 255, 255, 255)
    base = Image.new("RGBA", (size, size), bg)

    # --- thanh thông tin dưới (là 1 hình ảnh) ---
    footer_h = 0
    fb = _load_rgba(footer_bar)
    if fb is not None:
        footer_h = int(size * 0.10)
        fb2 = _fit(fb, size, footer_h)
        # kéo giãn theo chiều ngang cho vừa
        fb2 = fb2.resize((size, max(1, int(fb2.size[1] * size / fb2.size[0]))), Image.LANCZOS)
        fb2 = fb2.crop((0, 0, size, footer_h))
        base.alpha_composite(fb2, (0, size - footer_h))

    # --- vùng giữa cho ảnh sản phẩm ---
    top = int(size * 0.16)
    bottom = size - footer_h - PAD
    area_h = max(100, bottom - top)

    prods = [im for im in (prepare_product(p, remove_bg, remove_bg_thresh) for p in products) if im is not None]
    if prods:
        n = min(len(prods), 3)
        prods = prods[:n]
        cols = 1 if n == 1 else (2 if n == 2 else 3)
        rows = 1 if n <= 3 else 2
        cell_w = (size - 2 * PAD) // cols
        cell_h = area_h // rows
        slot = 0
        for r in range(rows):
            for c in range(cols):
                if slot >= n:
                    break
                im = _fit(prods[slot], int(cell_w * 0.9), int(cell_h * 0.9))
                cx = PAD + c * cell_w + (cell_w - im.size[0]) // 2
                cy = top + r * cell_h + (cell_h - im.size[1]) // 2
                base.alpha_composite(im, (cx, cy))
                slot += 1

    # --- logo website (trên-trái) ---
    logo = _load_rgba(site_logo)
    if logo is not None:
        logo = _fit(logo, int(size * 0.26), int(size * 0.12))
        base.alpha_composite(logo, (PAD, PAD))

    # --- logo thương hiệu (trên-phải) ---
    brand = _load_rgba(brand_logo)
    if brand is not None:
        brand = _fit(brand, int(size * 0.34), int(size * 0.13))
        base.alpha_composite(brand, (size - PAD - brand.size[0], PAD))

    # --- khung viền (frame overlay) ---
    fr = _load_rgba(frame)
    if fr is not None:
        fr2 = fr.resize((size, size), Image.LANCZOS)
        base.alpha_composite(fr2)

    # --- watermark chéo ---
    _draw_diagonal_watermark(base, watermark, watermark_opacity)
    return base


def save_composed(img: Image.Image, out_path: str, fmt: str = "PNG", quality: int = 90) -> str:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt.upper() == "JPG":
        img.convert("RGB").save(p, "JPEG", quality=quality)
    else:
        img.save(p, "PNG")
    return str(p)
