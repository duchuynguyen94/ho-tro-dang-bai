"""Ghép ảnh theo mẫu (thumbnail + slider): logo site - logo brand - ảnh SP - thanh thông tin - watermark."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

DEFAULT_SIZE = 1080
PAD = 40
PRODUCT_BOX = 0.30      # tỉ lệ cạnh hộp sản phẩm so với khổ ảnh


# --------------------------------------------------------------------------- #
# Tiện ích
# --------------------------------------------------------------------------- #
def _font_dirs() -> list[Path]:
    return [
        Path("/Library/Fonts"),
        Path.home() / "Library/Fonts",
        Path("/System/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts"),
        Path("/usr/share/fonts/truetype"),
    ]


# Thứ tự ưu tiên: Canva Sans (nếu có cài) -> Avenir/Futura (giống Canva Sans) -> còn lại
FONT_PREFERENCE = (
    "canvasans",
    "avenirnext",
    "avenir",
    "futura",
    "centurygothic",
    "montserrat",
    "poppins",
    "inter",
    "helveticaneue",
    "helvetica",
    "segoeui",
    "arial",
    "dejavusans",
)


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Chọn font watermark: ưu tiên Canva Sans, rồi Avenir/Futura (giống Canva Sans)."""
    files: list[Path] = []
    for d in _font_dirs():
        try:
            if d.exists():
                files += [p for p in sorted(d.glob("*"))
                          if p.is_file() and p.suffix.lower() in (".ttf", ".otf", ".ttc")]
        except OSError:
            continue

    bad = ("condensed", "narrow", "light", "ultra", "thin", "italic", "oblique",
           "extended", "expanded", "black")

    def norm(p: Path) -> str:
        return p.name.lower().replace(" ", "").replace("-", "").replace("_", "")

    def usable(p: Path) -> bool:
        n = p.name.lower()
        return not any(b in n for b in bad)

    for want in FONT_PREFERENCE:
        for f in files:
            if want not in norm(f) or not usable(f):
                continue
            best = None
            for idx in range(0, 9):
                try:
                    fnt = ImageFont.truetype(str(f), size, index=idx)
                except (OSError, ValueError):
                    continue
                try:
                    _fam, style = fnt.getname()
                except Exception:
                    style = ""
                st = (style or "").lower()
                if "italic" in st or "oblique" in st:
                    continue
                if any(k in st for k in ("demibold", "semi", "bold")):
                    return fnt
                if any(k in st for k in ("medium", "regular")) and best is None:
                    best = fnt
                elif best is None:
                    best = fnt
            if best is not None:
                return best
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


def _fit(img: Image.Image, max_w: int, max_h: int, upscale: bool = True) -> Image.Image:
    """Thu/phóng ảnh theo tỉ lệ để lọt trong khung (mặc định cho phép phóng to)."""
    w, h = img.size
    if w <= 0 or h <= 0:
        return img
    ratio = min(max_w / w, max_h / h)
    if not upscale:
        ratio = min(ratio, 1.0)
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


def _draw_diagonal_watermark(base: Image.Image, text: str, opacity: int = 15,
                             scale: float = 1.0, rotate: float = 34) -> None:
    if not text:
        return
    alpha = max(0, min(255, int(opacity * 255 / 100)))     # 0..100 -> 0..255
    if alpha <= 0:
        return
    layer = Image.new("RGBA", base.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(layer)
    font = _find_font(max(18, int((base.size[0] // 18) * max(0.3, scale))))
    tmp = Image.new("RGBA", (10, 10))
    tw = draw.textlength(text, font=font)
    text_img = Image.new("RGBA", (int(tw) + 20, int(font.size * 1.6)), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_img)
    td.text((10, 10), text, font=font, fill=(15, 23, 42, alpha))
    text_img = text_img.rotate(float(rotate or 0), expand=True, resample=Image.BICUBIC)
    x = (base.size[0] - text_img.size[0]) // 2
    y = (base.size[1] - text_img.size[1]) // 2
    layer.alpha_composite(text_img, (x, y))
    base.alpha_composite(layer)


# --------------------------------------------------------------------------- #
# Ghép ảnh chính
# --------------------------------------------------------------------------- #
def product_box(size: int, scale: float = 1.0) -> int:
    return max(60, int(size * PRODUCT_BOX * (scale or 1.0)))


def default_product_positions(n: int, size: int,
                              scale: float = 1.0) -> list[tuple[float, float]]:
    """Vị trí mặc định cho n ảnh sản phẩm (một hàng, canh giữa)."""
    n = max(1, n)
    box = product_box(size, scale)
    gap = int(size * 0.03)
    total = n * box + (n - 1) * gap
    x0 = max(PAD, (size - total) // 2)
    y = int(size * 0.36)
    return [((x0 + i * (box + gap)) / size, y / size) for i in range(n)]


def compose(
    size: int = DEFAULT_SIZE,
    site_logo: str = "",
    brand_logo: str = "",
    products: list[str] | None = None,
    footer_bar: str = "",
    frame: str = "",
    watermark: str = "",
    watermark_opacity: int = 15,
    watermark_size: float = 1.0,
    watermark_rotate: float = 34,
    transparent_bg: bool = False,
    remove_bg: bool = False,
    remove_bg_thresh: int = 42,
    logo_pos: tuple[float, float] = (0.025, 0.032),
    brand_pos: tuple[float, float] = (0.955, 0.032),
    logo_scale: float = 1.8,
    brand_scale: float = 1.0,
    brand_nobg: bool = False,
    brand_hidden: bool = False,
    product_scale: float = 1.0,
    product_positions: list | None = None,
    product_scales: list | None = None,
    product_nobg: list | None = None,
    uploads: list | None = None,
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
        prods = prods[:3]
        n = len(prods)
        box = product_box(size, product_scale)
        pos = list(product_positions or [])
        if len(pos) < n:
            pos += default_product_positions(n, size, product_scale)[len(pos):]
        scales = list(product_scales or [])
        nobg = list(product_nobg or [])
        for i, im in enumerate(prods):
            sc = float(scales[i]) if i < len(scales) else 1.0
            box_i = product_box(size, sc)
            if i < len(nobg) and nobg[i]:
                im = remove_background_auto(im, remove_bg_thresh)
            im = _fit(im, box_i, box_i)
            fx, fy = pos[i]
            px = int(fx * size)
            py = int(fy * size)
            px = max(0, min(size - im.size[0], px))
            py = max(0, min(size - im.size[1], py))
            base.alpha_composite(im, (px, py))

    # --- thành phần TẢI LÊN (per-image), canh theo tâm ---
    for up in (uploads or []):
        path = up.get("path") if isinstance(up, dict) else str(up)
        pos = (up.get("pos") if isinstance(up, dict) else None) or [0.5, 0.5]
        im = prepare_product(path, remove_bg, remove_bg_thresh)
        if im is None:
            continue
        sc = float(up.get("scale", 1.0)) if isinstance(up, dict) else 1.0
        box = product_box(size, sc)
        if isinstance(up, dict) and up.get("nobg"):
            im = remove_background_auto(im, remove_bg_thresh)
        im = _fit(im, box, box)
        px = int(pos[0] * size - im.size[0] / 2)
        py = int(pos[1] * size - im.size[1] / 2)
        px = max(0, min(size - im.size[0], px))
        py = max(0, min(size - im.size[1], py))
        base.alpha_composite(im, (px, py))

    # --- logo website (trên-trái) ---
    logo = _load_rgba(site_logo)
    if logo is not None:
        logo = _fit(logo, int(size * 0.26 * logo_scale), int(size * 0.12 * logo_scale))
        lx = int(logo_pos[0] * size)
        ly = int(logo_pos[1] * size)
        lx = max(0, min(size - logo.size[0], lx))
        ly = max(0, min(size - logo.size[1], ly))
        base.alpha_composite(logo, (lx, ly))

    # --- logo thương hiệu (trên-phải) ---
    brand = None if brand_hidden else _load_rgba(brand_logo)
    if brand is not None and brand_nobg:
        brand = remove_background_auto(brand, remove_bg_thresh)
    if brand is not None:
        brand = _fit(brand, int(size * 0.34 * brand_scale), int(size * 0.13 * brand_scale))
        bx = int(brand_pos[0] * size) - brand.size[0]
        by = int(brand_pos[1] * size)
        bx = max(0, min(size - brand.size[0], bx))
        by = max(0, min(size - brand.size[1], by))
        base.alpha_composite(brand, (bx, by))

    # --- khung viền (frame overlay) ---
    fr = _load_rgba(frame)
    if fr is not None:
        fr2 = fr.resize((size, size), Image.LANCZOS)
        base.alpha_composite(fr2)

    # --- watermark chéo ---
    _draw_diagonal_watermark(base, watermark, watermark_opacity, watermark_size, watermark_rotate)
    return base


def trim_borders(path: str, tol: int = 16) -> str:
    """CẮT VIỀN quanh đối tượng (viền trong suốt hoặc màu nền ở 4 góc).

    Trả về đường dẫn file mới (thêm hậu tố _trim). Nếu không cắt được gì thì trả về path cũ.
    """
    from PIL import ImageChops

    p = Path(path)
    if not p.exists():
        return path
    try:
        im = Image.open(p).convert("RGBA")
    except Exception:
        return path

    box = None
    # 1) ảnh có vùng TRONG SUỐT -> cắt theo vùng hiện hình
    alpha = im.getchannel("A")
    abox = alpha.getbbox()
    if abox and (abox[2] - abox[0] < im.width or abox[3] - abox[1] < im.height):
        box = abox
    else:
        # 2) ảnh nền đặc -> cắt theo màu nền ở 4 góc (so sánh trên kênh màu)
        bg = Image.new("RGB", im.size, im.convert("RGB").getpixel((0, 0)))
        diff = ImageChops.difference(im.convert("RGB"), bg).convert("L")
        mask = diff.point(lambda v: 255 if v > tol else 0)
        box = mask.getbbox()

    if not box:
        return path
    w, h = box[2] - box[0], box[3] - box[1]
    if w < 8 or h < 8 or (w >= im.width - 2 and h >= im.height - 2):
        return path
    out = p.with_name(f"{p.stem}_trim{p.suffix}")
    try:
        im.crop(box).save(out)
    except Exception:
        return path
    return str(out)


def save_composed(img: Image.Image, out_path: str, fmt: str = "PNG", quality: int = 90) -> str:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt.upper() == "JPG":
        img.convert("RGB").save(p, "JPEG", quality=quality)
    else:
        img.save(p, "PNG")
    return str(p)
