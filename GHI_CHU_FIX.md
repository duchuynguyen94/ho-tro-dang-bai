# Ghi chú — 11 mục cần fix (CHỜ LỆNH)

> Trạng thái: **CHƯA LÀM** — chỉ thực hiện khi người dùng nói **"fix"**.
> Ngày ghi: 2026-10-16

---

## Mục 1 — Xoá ô tick "Bật" trong card "Xử lý ảnh cục bộ (Pillow)"
- Vị trí: **Cấu hình → AI ảnh → card "Xử lý ảnh cục bộ (Pillow)"**
- Ô tick `Bật` (`pillow_on`) hiện **không có tác dụng gì** (giá trị `pillow.enabled` chỉ được lưu, không nơi nào đọc).
- → **Xoá ô tick** vì xử lý ảnh cục bộ là **mặc định luôn bật**.

## Mục 2 — Xoá dòng ghi chú trong card "Xử lý ảnh cục bộ (Pillow)"
- Xoá dòng ghi chú (note) hiển thị trong card này.

## Mục 3 — Giữ chọn PNG / JPG khi xuất ảnh, và làm cho nó CÓ TÁC DỤNG THẬT
- Giữ ô chọn **Định dạng xuất: PNG / JPG**.
- Hiện `pillow.output_format` **chưa được dùng** — định dạng thật đang lấy theo **Rule ảnh** (`.jpg`/`.png`).
- **Làm rõ (người dùng xác nhận):** định dạng này áp cho **ảnh xuất ra và lưu vào** `posts/<task_id>/` khi bấm đăng bài (cùng chỗ với Mục 4).
- **Rule ảnh chỉ là TÊN ẢNH (không gồm đuôi):** ví dụ trong **Format Rule → card Ảnh**, input 1 = `{title}`, input 2 = `Tổng kho hàng sẵn {title}`.
- → **Đuôi file do lựa chọn PNG/JPG ở trên quyết định** (lựa chọn **thắng**): ghép thêm `.png` hoặc `.jpg` vào tên theo Rule ảnh.
  - Nếu tên theo Rule ảnh **có sẵn** đuôi (`.png`/`.jpg`) → **thay** bằng đuôi theo lựa chọn.
  - Nếu **không** ghi đuôi → **thêm** đuôi theo lựa chọn.
- → Nối cấu hình này vào bước xuất ảnh (`export_post_images()`) sao cho lựa chọn có hiệu lực thật.

## Mục 4 — Giữ "Kích thước ảnh xuất", và làm cho nó CÓ TÁC DỤNG THẬT
- Giữ ô **Kích thước ảnh xuất** (mặc định 1080).
- Hiện giá trị này **chưa được dùng** — ảnh luôn xuất 1080×1080.
- **Làm rõ (người dùng xác nhận):** kích thước này là **kích thước của các hình ảnh được xuất ra và lưu vào thư mục** `posts/<task_id>/` **sau khi bấm nút đăng bài** ("OK — Đăng bài").
- → Khi bấm đăng bài, ảnh xuất ra phải được **resize theo đúng kích thước đã chọn** trong cấu hình.
- Vị trí code liên quan: `app/ui/workers.py` → `export_post_images()` (hiện chỉ copy / chuyển JPEG–WEBP, **không resize**).

## Mục 5 — Đổi tiêu đề "Google Gemini 2.5 Flash Image" → "Google Gemini"
- Vị trí: **Cấu hình → AI ảnh → card provider**.

## Mục 6 — Lưu cấu hình PHẢI luôn thông báo thành công / thất bại
- Hiện tại bấm **Lưu** chưa hiện thông báo.
- Yêu cầu: bấm Lưu → **bắt buộc** hiện thông báo rõ ràng:
  - **Thành công** (màu xanh)
  - **Thất bại** (màu đỏ)
- Áp cho **mọi mục cấu hình**: site, AI nội dung, AI ảnh, Format Rule.

## Mục 7 — Xoá card "Xoá nền ảnh sản phẩm" toàn cục
- Vị trí: **Cấu hình → AI ảnh → card "Xoá nền ảnh sản phẩm"** (checkbox + ô "Ngưỡng tách").
- Xoá mục `remove_bg` khỏi cấu hình mặc định.
- Bỏ việc **xoá nền toàn cục** khi tạo nội dung (ảnh sản phẩm giữ nguyên nền gốc).
- **Giữ nguyên** chuột phải → **"Xoá nền → trong suốt"** cho **từng thành phần** (sản phẩm, ảnh tải lên, logo brand).

## Mục 8 — "Tắt AI chỉnh ảnh" đưa LÊN TRÊN danh sách provider
- Hiện `Tắt AI chỉnh ảnh` (`off`) đang **lẫn trong danh sách provider** → phải **tách ra, đặt phía trên** dưới dạng **công tắc chung**.
- **Bổ sung:** khi **"Tắt AI chỉnh ảnh"** đang bật → trong **trình sửa ảnh** (panel Kết quả / Công việc) phải **ẩn nút "AI sửa"**.

## Mục 9 — Nút "+ Thêm hình" trong mục Ảnh (panel Kết quả / Công việc)
- Bối cảnh: nhập **URL nguồn** → tạo nội dung AI → panel kết quả có **số hình theo lựa chọn trước đó** (ở **Đăng bài** có ô chọn *3 ảnh / 1 ảnh / 2 ảnh / 4 ảnh / 5 ảnh*, mặc định 3 → `task.image_count`).
- Yêu cầu: trong khu **"Ảnh"** (dãy thumbnail) thêm **nút "+ Thêm hình"**.
  - Ví dụ đang có **Ảnh 1, 2, 3** → bấm **+ Thêm hình** → thành **Ảnh 1, 2, 3, 4**.
  - Bấm vào **Ảnh 4** → **chỉnh sửa riêng của Ảnh 4** (kéo/thả, resize, watermark, chọn thanh thông tin 1/2, tải ảnh, AI sửa, lấy lại ảnh…) — độc lập với 3 ảnh kia.
- Chi tiết kỹ thuật:
  - Thêm 1 entry vào `task.result["images"]` **và** 1 entry tương ứng vào `task.result["image_opts_list"]` (mỗi ảnh có bộ tuỳ chọn riêng).
  - **Ảnh mới = ĐỂ TRỐNG (người dùng đã chốt):** chỉ có sẵn khung mẫu — **logo site, logo brand, watermark, thanh thông tin** — **không có ảnh sản phẩm**; người dùng tự **tải ảnh lên** cho ảnh đó rồi chỉnh riêng.
    - Vì vậy phần **sản phẩm** của ảnh mới để rỗng (chờ tải lên), các thành phần mẫu vẫn hiển thị như các ảnh khác.
  - Các chỗ đang **cứng `[:3]`** phải đổi thành **theo số ảnh thực tế** để ảnh thêm vào vẫn được xuất & có sản phẩm:
    - `app/ui/workers.py` → `export_post_images()` (`images[:3]`)
    - `app/ui/workers.py` → `product_urls = page.get("images", [])[:3]` và `products=prods[:3]`
    - `app/images/composer.py` → `prods = prods[:3]`
    - `app/ui/widgets/image_editor.py` → `keep = [...][:3]`
  - Nút **"+ Thêm hình"** đặt cùng hàng/cạnh dãy thumbnail trong mục **"Ảnh"** của panel kết quả (`jobs_page.py`, `images_row`).
  - **Xoá ảnh (bổ sung):** thêm **nút Xoá** nằm **bên phải chữ "Ảnh 1", "Ảnh 2", "Ảnh 3"…** (ngay trên caption của mỗi thumbnail).
    - Bấm → **hiện popup xác nhận Yes / No**; **mặc định là "Yes"** (bấm **Enter** = Yes, giống dialog xoá công việc).
    - Xoá **ảnh đó**: bỏ entry tương ứng trong `task.result["images"]` **và** `task.result["image_opts_list"]`, xoá cả file ảnh đã ghép (nếu có) trong `posts/` / thư mục tạm.
    - Sau khi xoá → **đánh số lại** caption (Ảnh 1, 2, 3…) và chuyển **ảnh đang chọn** (`_sel_index`) về ảnh hợp lệ.
    - **Giữ lại TỐI THIỂU 1 ẢNH** (người dùng đã chốt) → không cho xoá ảnh cuối cùng (nút Xoá ẩn/khoá khi chỉ còn 1 ảnh).
  - **Sắp xếp ảnh (bổ sung — người dùng yêu cầu):** cho phép **đổi thứ tự ảnh** bằng **kéo–thả thumbnail**.
    - Kéo thumbnail này sang vị trí khác → đổi thứ tự trong `images` + `image_opts_list`, **đánh số lại** caption.
      - Các tuỳ chọn **của riêng ảnh** (vị trí logo/brand/sản phẩm, watermark, ảnh tải lên…) **đi theo ảnh**.
      - **Riêng thanh thông tin** thì gán lại **theo index mới** (xem dòng dưới).
    - **Đánh lại INDEX sau khi sắp xếp (người dùng chốt):** ảnh theo thứ tự mới được đánh lại **index 1, 2, 3, 4…** (caption "Ảnh 1, Ảnh 2, Ảnh 3, Ảnh 4…").
    - **Tên ảnh khi xuất:** gán theo **Rule ảnh**, dùng **dãy index MỚI** → `{index}` lần lượt = **1, 2, 3, 4…** theo thứ tự đã sắp xếp (Rule ảnh dòng 1 cho ảnh index 1, dòng 2 cho index 2…).
      - Ví dụ Rule ảnh dòng 1 = `{title}`, dòng 2 = `Tổng kho hàng sẵn {title}` → ảnh ở vị trí 1 xuất tên `<tiêu đề>`, vị trí 2 xuất `Tổng kho hàng sẵn <tiêu đề>`, …
    - **Thanh thông tin:** gán lại **luân phiên 1→2→1→2 theo index mới** (index 1 = thanh 1, index 2 = thanh 2…).

---

## Mục 10 — Làm đẹp dropdown (select) — cả ô chọn lẫn danh sách xổ xuống
- Vấn đề người dùng nêu: **ô select hiện hơi xấu**, và khi bấm mở ra thì **danh sách chọn hiển thị xấu**.
- Hiện trạng code: `app/ui/style.py` đã có style cho `QComboBox` + `QComboBox QAbstractItemView` (nền trắng, viền `#cbd5e1`, bo 8px, item `padding: 6px 8px`) — nhưng **cửa sổ popup** (khung xổ xuống) **không được bo góc** vì QSS không áp cho **window** của popup trên macOS → trông vuông/vô duyệt; item **không có trạng thái hover**, chiều cao thấp, **scrollbar mặc định xấu**, chiều rộng popup không khớp ô chọn.
- Hướng làm đẹp:
  1. **Ô chọn:** viền + bo góc + padding đều hơn, có **hover** và **focus** rõ ràng, mũi tên (`ARROW`) căn giữa đẹp hơn.
  2. **Danh sách xổ xuống:**
     - Nền trắng, viền nhạt, **bo góc ~10px**, `padding: 6px`, `outline: none`.
     - Item: **padding 8px 10px**, **bo 7px**, có **`:hover`** (nền nhạt `#f8fafc`) và **`:selected`** (nền `#eff6ff`, chữ accent đậm).
     - **Scrollbar trong popup** style mảnh, bo tròn, màu dịu (không dùng thanh mặc định).
  3. **Bo góc cả khung popup** (không chỉ phần view): set cho `combo.view().window()`:
     - `Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint`
     - `setAttribute(Qt.WA_TranslucentBackground)` + chừa margin để thấy viền bo.
     - → Cần một helper (ví dụ `polish_combo(combo)`) áp cho **mọi QComboBox** trong app (gọi lúc tạo, hoặc quét toàn bộ khi khởi động).
  4. **Kích thước popup:** rộng **tối thiểu bằng ô chọn** (`view().setMinimumWidth(combo.width())`), số dòng hiển thị hợp lý (`setMaxVisibleItems`), item cao ~28–30px cho dễ bấm.
- Phạm vi: **toàn app** — mọi `QComboBox` (Đăng bài, Cấu hình, Format Rule, editor `#rteCombo`…).

---

## Mục 11 — Nút "Lưu" ghim cố định (fixed) phía TRÊN ở cấu hình AI nội dung & AI ảnh
- Lý do người dùng nêu: sau này có **nhiều provider**, phải **kéo xuống đáy** mới bấm được **Lưu** → mất thời gian.
- Hiện trạng code: `AIContentPanel` và `AIImagePanel` (`app/ui/pages/config_page.py`) **là chính `QScrollArea`** và nút **Lưu nằm ở cuối phần cuộn** (`v.addWidget(save, alignment=Qt.AlignRight)` ở đáy) → phải cuộn xuống mới thấy.
- Yêu cầu: nút **Lưu luôn hiện, ghim (fixed/sticky) ở phía trên** panel.
- Hướng làm:
  1. Tách mỗi panel thành **2 phần**:
     - **Header cố định (không cuộn):** tiêu đề bên trái + **nút "Lưu cấu hình …"** căn **phải**, luôn hiển thị.
     - **Phần thân cuộn:** `QScrollArea` chứa danh sách provider + các tuỳ chọn (chỉ phần này cuộn).
  2. Đổi class panel từ `QScrollArea` → **`QWidget` container** (bọc `QScrollArea` bên trong). Vì 2 panel chỉ được dùng nội bộ trong `ConfigPage` (`ai_c`, `ai_i` → `self.stack.addWidget`) nên đổi an toàn.
  3. Giữ nguyên hành vi `_save()` và style nút (`class="primary"`).
  4. (Tuỳ chọn — nếu muốn đồng bộ) áp cùng kiểu header-ghim cho **Format Rule** và các tab site dài. *Người dùng chỉ yêu cầu 2 panel AI — chờ xác nhận có mở rộng không.*
- Kết quả mong muốn: cuộn bao nhiêu provider cũng luôn bấm được **Lưu** ngay trên đầu panel.

---

## Ghi chú phụ (ngoài 11 mục — bàn riêng, chưa chốt)
- **AI chỉnh ảnh free:** đã tư vấn. Nổi bật:
  - `rembg` (offline, free) → thay thuật toán xoá nền flood-fill hiện tại, chất lượng tốt hơn hẳn.
  - `IOPaint / LaMa` (offline, free) → xoá vật thể / thành phần.
  - Cloud free: Cloudflare Workers AI, Remove.bg (50 ảnh/tháng), Hugging Face free tier.
  - Model ảnh Gemini **không free** (tính tiền theo ảnh).
  - → Chờ người dùng quyết định có thêm `rembg` hay không.
