# Quy định làm việc (AGENTS.md)

> File này để mọi phiên làm việc sau đều đọc và tuân thủ.

## 0. QUAN TRỌNG NHẤT — chỉ làm khi được yêu cầu

- **Chỉ sửa code / thêm tính năng khi người dùng yêu cầu RÕ RÀNG.** Không tự ý fix, không tự thêm.
- Khi người dùng nêu ý kiến/vấn đề: **liệt kê lại để xác nhận đúng ý**, kèm **gợi ý cải thiện** nếu thấy
  cần — nhưng **CHƯA đụng vào code**.
- Chờ người dùng xác nhận (*"ok"*, *"làm đi"*, *"sửa đi"*) → mới thực hiện.
- **Không phá code đang chạy tốt**: sửa tối thiểu, đúng phạm vi, có test trước khi build.
- Nếu thay đổi **có thể xung đột / ảnh hưởng chỗ khác** → **báo trước** để người dùng quyết.
- Làm xong: **báo rõ đã đổi gì + đã test gì**.

### 0.1. CHỈ 5 CÂU LỆNH NÀY MỚI ĐƯỢC PHÉP LÀM

Người dùng chỉ dùng đúng 5 câu sau để ra lệnh; **phải khớp nguyên câu**:

1. `ok làm đi`
2. `ok fix đi`
3. `ok sửa đi`
4. `ok cập nhật đi`
5. `ok thực hiện đi`

**Mọi cách nói khác đều KHÔNG phải lệnh** — kể cả *"ok"*, *"được"*, *"ừ"*, *"triển khai đi"*,
*"làm luôn"*, *"sao không sửa"*, *"cần thêm X"*, *"nên là Y"*, *"hình như lỗi"*…
→ Khi đó **chỉ được tóm tắt lại ý + gợi ý + hỏi xác nhận**, tuyệt đối **không sửa code**.

Mẫu phản hồi khi người dùng nêu vấn đề/ý kiến:

```
Tôi hiểu là: …
Gợi ý thêm: …
Bạn xác nhận giúp (ok làm đi / ok sửa đi …)?
```


## 1. Sản phẩm

App desktop **tiếng Việt** (macOS + Windows 10): dùng AI tạo nội dung/ảnh cho bài đăng WordPress
(WooCommerce product) và **tự điền form đăng bài** bằng **kịch bản riêng cho từng website**
(người dùng tự bấm Đăng trên WordPress).

- Stack: Python 3.13 (`.venv`), PySide6, Playwright (`channel=chrome`/`msedge`), Pillow, httpx, pypdf,
  gspread, cryptography.
- Repo: `github.com/duchuynguyen94/ho-tro-dang-bai` (**public**) — dùng cho GitHub Releases.

## 2. Quy trình bắt buộc sau mỗi lần sửa code

1. **Build lại `.app` macOS và mở lại:** `./dev_rebuild.sh`
2. **KHÔNG build `.exe` Windows** trừ khi được yêu cầu (chạy workflow GitHub Actions, bấm tay).
3. Commit + push lên `main` sau khi xong.

## 3. Quy ước đang áp dụng (đừng tự đổi)

- UI 100% tiếng Việt.
- 1 website = 1 kịch bản; Format Rule dùng chung cho mọi website.
- Thứ tự tab: `Cài đặt` → `Đăng bài` → `Công việc đang làm` → `Log lỗi`; **mở app vào tab "Đăng bài"**.
- **Không tự động bấm Đăng** — người dùng tự bấm trên WordPress.
- **Mỗi công việc chỉ mở 1 Chrome**: nút `OK — Đăng bài` bị **khoá + mờ** khi đang mở, chỉ **mở lại khi
  người dùng ĐÓNG trình duyệt** (không cần biết đã đăng hay chưa).
- **Lỗi ở bước đăng bài:** không hiện cảnh báo, vẫn hiện panel kết quả (giữ nguyên nội dung).
- **Lỗi tạo nội dung:** hiện panel lỗi + nút `↻ Tạo lại`.
- Footer panel kết quả: `[↻ Random lại]` sát **trái**, `[OK — Đăng bài]` sát **phải**.
- **Model Extractor: đã bỏ** (giữ lại ô "Rule Model Extractor" trong Format Rule).
- **Icon trong nội dung**: chỉ đặt ở thẻ `<h2>` + các dòng liên hệ (`🌐` website, `☎️` hotline,
  `✉️` email; `📞` các dòng hotline khác, `📧`, `📩`). Không đặt icon ở `h1/h3/h4`.
- **SEO theo `rule_seo.pdf`**: title 55–60 ký tự `[Keyword] [Brand] [Model] + [USP]` (11 USP),
  `focus_keyword` = Model, `description` 4 phần (câu mô tả + dòng liên hệ + "Tên sản phẩm … models
  tiêu biểu" + tối đa 5 model), `tags` > 350 từ theo 5 nhóm.
- **Cập nhật phần mềm**: chỉ dùng **GitHub Releases** (nguồn gắn sẵn trong app, không nhập gì).
  Mỗi lần phát hành: chạy workflow `build-windows` với **số phiên bản cao hơn** → tự tạo Release.
- Gói Windows **không kèm Chromium** (dùng Chrome/Edge có sẵn) → ~100 MB.

## 4. Dữ liệu & bí mật

- Dữ liệu người dùng: `~/Library/Application Support/Ho Tro Dang Bai/`
  (`config.json`, `sessions/`, `formats/`, `posts/`, `products/`, `errors.log`).
- API key / mật khẩu **lưu mã hoá**; **không** commit `config.json`, `sessions/`, `dist/`.
- Khi cần soi giao diện WordPress thật: dùng profile copy (ví dụ `/tmp/htdb_wp`) và xoá lock
  `Singleton*` trước khi mở.
