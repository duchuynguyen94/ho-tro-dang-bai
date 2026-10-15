# Ghi chú — 8 mục cần fix (CHỜ LỆNH)

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

---

## Ghi chú phụ (ngoài 8 mục — bàn riêng, chưa chốt)
- **AI chỉnh ảnh free:** đã tư vấn. Nổi bật:
  - `rembg` (offline, free) → thay thuật toán xoá nền flood-fill hiện tại, chất lượng tốt hơn hẳn.
  - `IOPaint / LaMa` (offline, free) → xoá vật thể / thành phần.
  - Cloud free: Cloudflare Workers AI, Remove.bg (50 ảnh/tháng), Hugging Face free tier.
  - Model ảnh Gemini **không free** (tính tiền theo ảnh).
  - → Chờ người dùng quyết định có thêm `rembg` hay không.
