# Hỗ Trợ Đăng Bài (WP Multi Poster)

Ứng dụng desktop (macOS + Windows 10) hỗ trợ tạo nội dung bằng AI và đăng bài lên
**nhiều website WordPress** theo kịch bản ghi lại sẵn.

## Tính năng

- **Đăng bài (bước 1):** nhập 1 link nguồn → chọn 1 website → tạo công việc
- **Công việc đang làm:** chạy nhiều việc song song; bấm 1 việc để duyệt kết quả AI
- **AI nội dung:** tiêu đề / focus keyword / description / search tags / nội dung HTML
  - Ưu tiên provider miễn phí: Gemini, Groq, OpenRouter, Ollama, ChatGPT (browser)
  - Có API key riêng, chọn mặc định, fallback tự động
  - Bắt buộc tuân theo **file quy định (.txt/.html/.doc)** của từng website
- **Ảnh:** ghép theo mẫu vuông 1:1 (logo site – logo brand – ảnh sản phẩm – thanh
  thông tin – watermark chéo); logo thương hiệu do AI tự tìm, có file dự phòng
- **Kịch bản (Recorder):** bấm ghi → thao tác trên trình duyệt → dừng → lưu;
  tự sinh selector theo thứ tự ưu tiên; **Export/Import** sang máy khác
- **Đăng bài:** mở trình duyệt riêng (Chrome core), tự đăng nhập, điền sẵn theo kịch bản;
  người dùng tự kiểm tra và bấm Đăng trên WordPress
- **Google Sheets:** ghi link nguồn + link kết quả

## Cài đặt (phát triển)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium   # (hoặc dùng Chrome/Edge có sẵn)
.venv/bin/python main.py
```

> Ứng dụng ưu tiên dùng **Chrome/Edge có sẵn** trên máy; nếu không có sẽ dùng Chromium kèm theo.

## Dữ liệu người dùng

Lưu trong thư mục dữ liệu riêng của hệ điều hành (lựa chọn "A"):

- macOS: `~/Library/Application Support/Ho Tro Dang Bai/`
- Windows: `%APPDATA%\Ho Tro Dang Bai\`

API key / mật khẩu được **mã hoá** (khoá lưu cùng thư mục, quyền 600).

## Build

- **macOS:** `./build_mac.sh` → `dist/HoTroDangBai.app`
- **Windows 10:** workflow GitHub Actions `.github/workflows/build-windows.yml` → artifact `.zip`

## Cấu trúc

```
app/
  config.py            # đường dẫn dữ liệu
  source.py            # đọc link nguồn
  storage/             # mô hình + lưu trữ + mã hoá
  ai/                  # provider AI viết nội dung
  images/              # ghép ảnh (Pillow)
  wp/                  # trình duyệt, ghi & phát lại kịch bản
  sheets/              # Google Sheets
  ui/                  # giao diện PySide6
tools/dev_shot.py      # tạo dữ liệu mẫu + chụp ảnh màn hình (khi phát triển)
```
