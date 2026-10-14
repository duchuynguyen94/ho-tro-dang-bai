"""Script dùng khi phát triển: tạo dữ liệu mẫu và chụp ảnh từng màn hình.

Chạy:
    HTDB_DATA_DIR=/tmp/htdb_demo QT_QPA_PLATFORM=offscreen .venv/bin/python tools/dev_shot.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from app.config import formats_dir, media_dir, output_dir  # noqa: E402
from app.images import compose, save_composed  # noqa: E402
from app.storage.models import Formats, Script, ScriptStep, Site, Task  # noqa: E402
from app.storage.store import Store  # noqa: E402


def make_png(path: Path, size, color, text="") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", size, color)
    if text:
        d = ImageDraw.Draw(img)
        d.text((10, size[1] // 2 - 8), text, fill=(255, 255, 255, 255))
    img.save(path)
    return str(path)


def seed() -> Store:
    store = Store()
    store.data["sites"] = []
    store.data["tasks"] = []

    fmt = formats_dir()
    (fmt / "quy_dinh_tieu_de.txt").write_text(
        "Tiêu đề tối đa 65 ký tự, chứa từ khóa chính, có số năm.\n", encoding="utf-8"
    )
    (fmt / "quy_dinh_noi_dung.html").write_text(
        "<p>Bài viết gồm: Giới thiệu, Đặc điểm nổi bật, Thông số, Liên hệ.</p>\n", encoding="utf-8"
    )
    (fmt / "quy_dinh_description.txt").write_text("Mô tả SEO dưới 160 ký tự.\n", encoding="utf-8")
    (fmt / "quy_dinh_tags.txt").write_text("4-8 thẻ, cách nhau bởi dấu phẩy.\n", encoding="utf-8")

    logo = make_png(media_dir() / "logo_siteA.png", (420, 160), (37, 99, 235, 255), "NHD")
    bar1 = make_png(media_dir() / "bar_1.png", (1080, 120), (18, 179, 168, 255), "HOTLINE 0909 399 174")
    bar2 = make_png(media_dir() / "bar_2.png", (1080, 120), (37, 99, 235, 255), "EMAIL  info@siteA.com")

    siteA = Site(
        name="siteA.com", url="https://siteA.com",
        new_post_url="https://siteA.com/wp-admin/post-new.php",
        username="admin_siteA", watermark="https://siteA.com",
        logo_path=logo, footer_bars=[bar1, bar2], footer_mode="random",
        formats=Formats(
            title=str(fmt / "quy_dinh_tieu_de.txt"),
            content=str(fmt / "quy_dinh_noi_dung.html"),
            description=str(fmt / "quy_dinh_description.txt"),
            tags=str(fmt / "quy_dinh_tags.txt"),
        ),
        script=Script(steps=[
            ScriptStep(action="open", value="https://siteA.com/wp-admin/post-new.php", note="Mở trang tạo bài", source="auto"),
            ScriptStep(action="type", selector="#title", value="{{title}}", note="Nhập tiêu đề"),
            ScriptStep(action="type", selector=".wp-editor-area[name=\"content\"]", value="{{content_html}}", note="Nhập nội dung"),
            ScriptStep(action="type", selector="#focus-keyword", value="{{focus_keyword}}", note="Nhập focus keyword"),
            ScriptStep(action="type", selector="#yoast-meta-description", value="{{description}}", note="Nhập description"),
            ScriptStep(action="upload", selector="input[type=file]#upload", note="Upload hình ảnh"),
            ScriptStep(action="click", selector="#publish", selectors=['text="Đăng"'], note="Bấm Đăng", source="fallback"),
        ]),
    )
    siteB = Site(name="shopB.vn", url="https://shopB.vn", watermark="https://shopB.vn",
                 username="adminB", formats=Formats(content=str(fmt / "quy_dinh_noi_dung.html")))
    siteC = Site(name="blogC.net", url="https://blogC.net", watermark="https://blogC.net")
    siteA.set_password("matkhau123")
    siteB.set_password("matkhau456")
    store.set_sites([siteA, siteB, siteC])

    # ảnh demo cho task
    brand = make_png(media_dir() / "brand_carten.png", (420, 150), (56, 189, 248, 255), "CARTEN")
    prod = make_png(media_dir() / "sp1.png", (600, 600), (219, 234, 254, 255), "SP")
    imgs = []
    for i in range(3):
        im = compose(size=1080, site_logo=logo, brand_logo=brand, products=[prod, prod],
                     footer_bar=[bar1, bar2][i % 2], watermark="https://siteA.com")
        out = output_dir() / f"demo_{i+1}.png"
        save_composed(im, str(out))
        imgs.append({"path": str(out), "footer": [bar1, bar2][i % 2]})

    t1 = Task(site_id=siteA.id, site_name=siteA.name,
              source_url="https://nguon.com/san-pham/ao-thun-nam-cao-cap.html",
              status="review", progress=100)
    t1.result = {
        "title": "Áo Thun Nam Cao Cấp — Bền Đẹp, Giá Tốt 2026",
        "focus_keyword": "áo thun nam cao cấp",
        "description": "Áo thun nam cao cấp chất liệu cotton 100% thoáng mát, bền đẹp, đủ size M–XXL. Giá tốt, giao nhanh toàn quốc.",
        "tags": "áo thun nam, cotton, thời trang, cao cấp",
        "content_html": "<h2>Giới thiệu</h2><p>Áo thun nam cao cấp chất liệu cotton 100% thoáng mát…</p>",
        "images": imgs,
    }
    t2 = Task(site_id=siteB.id, site_name=siteB.name, status="generating", progress=55,
              source_url="https://nguon.com/san-pham/giay-the-thao-nam.html")
    t3 = Task(site_id=siteA.id, site_name=siteA.name, status="posting", progress=85,
              source_url="https://nguon.com/san-pham/binh-giu-nhiet-500ml.html")
    t4 = Task(site_id=siteC.id, site_name=siteC.name, status="error", progress=0,
              message="Thiếu quy định nội dung", source_url="https://nguon.com/san-pham/dong-ho-abc.html")
    store.set_tasks([t1, t2, t3, t4])
    store.save()
    return store


def shoot() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow
    from app.ui.style import QSS

    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.resize(1240, 900)
    win.show()
    for _ in range(3):
        app.processEvents()

    out = ROOT / "screenshots"
    out.mkdir(exist_ok=True)
    names = ["1-dang-bai", "2-cau-hinh", "3-cong-viec", "4-lich-su"]
    for i, name in enumerate(names):
        win._go(i)
        for _ in range(3):
            app.processEvents()
        p = out / f"{name}.png"
        win.grab().save(str(p))
        print("saved", p)


if __name__ == "__main__":
    seed()
    shoot()
