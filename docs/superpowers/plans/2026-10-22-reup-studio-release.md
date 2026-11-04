# Kế hoạch phát hành công khai "Reup Studio"

Ngày: 2026-10-22 · Nguồn: `F:\Reup Studio` → bản phát hành tên **Reup Studio**

## 0. Quyết định thiết kế đã chốt (theo đặc tả người dùng)

| Hạng mục | Quyết định |
|---|---|
| Tên hiển thị | **Reup Studio** (UI, tiêu đề cửa sổ, header, About, README) |
| Tên tệp / thư mục | **ReupStudio** (exe, spec, thư mục dữ liệu, tệp cấu hình) |
| Thư mục dữ liệu người dùng | `%APPDATA%\ReupStudio` (cấu hình, log, lịch sử, cache) |
| Cookie Douyin | `<thư mục app>\cookies\douyin_cookies.txt` (theo đặc tả bước 5) — dự phòng `%APPDATA%\ReupStudio\cookies\douyin_cookies.txt` nếu thư mục cài không ghi được |
| Cookie Gemini Web2API | để TRỐNG mặc định (`placeholder: "Để trống = dùng Flash ẩn danh"`) |
| Ghi chú trong code & UI | **100% tiếng Việt** |
| Module Douyin | `F:\Reup Studio\douyin_batch\` (đổi tên package gốc `core/utils/config/...` → prefix `douyin_batch.`) |
| Công cụ ngoài Python | `F:\Reup Studio\vendor\bin\` (ffmpeg.exe, ffprobe.exe + DLL) |
| Build | PyInstaller `--onedir` → `dist\ReupStudio\ReupStudio.exe` |
| Installer | Inno Setup 6 → `ReupStudio_Setup.exe` (giao diện tiếng Việt) |

## 1. Các bước thực hiện (mỗi bước test trước khi đi tiếp)

- [ ] **B0. Sao lưu** `F:\Reup Studio` → `F:\Reup Studio_backup`
- [ ] **B1. Đổi tên** toàn bộ Reup Studio → Reup Studio (code, UI, file, spec, build script, README)
- [ ] **B2. Logo mới** — SVG + PNG + `.ico` (16/32/48/64/128/256); gắn vào cửa sổ / exe / installer / header
- [ ] **B3. Xóa thông tin cá nhân** — cookie, key, đường dẫn tuyệt đối, log, cache, `__pycache__`, `.git`; dọn `core/` (bỏ bản sao Python 3.11 + module trùng); dọn `TiktokAuto` (chrome profile, cookies)
- [ ] **B4. Tích hợp Douyin vào tab Download** — module `douyin_batch` + khối UI mới (link, thư mục lưu, Bắt đầu/Dừng, tiến trình, bảng trạng thái, lỗi tiếng Việt, mở thư mục)
- [ ] **B5. Cookie Douyin cố định** — đọc `<app>\cookies\douyin_cookies.txt`, file mẫu trống kèm hướng dẫn
- [ ] **B6. Thư viện + công cụ** — `requirements.txt` ghim phiên bản, `vendor/bin`, trình kiểm tra lúc khởi động, test trên venv sạch
- [ ] **B7. Đóng gói** — PyInstaller exe + Inno Setup installer (tiếng Việt, shortcut, uninstall, tự cài lần đầu)
- [ ] **B8. Nghiệm thu** — cài thử Setup, chạy app, kiểm tra từng yêu cầu, báo cáo tiếng Việt

## 2. Rủi ro đã biết

- `venv_build` cũ **hỏng** (trỏ `C:\Users\WIN 10\...` không tồn tại) → phải tạo lại venv sạch bằng Python 3.12.
- **Inno Setup chưa cài** → phải tải & cài (inno setup 6) trước khi build installer.
- `core/` lẫn bản cài Python 3.11.15 (147 MB) + các bản sao module trùng trong `core\encodings`, `core\dbm`, `core\xml` → dọn để giảm bóng bóng & giảm dung lượng gói.
- `core\pipeline.py` khác `core\encodings\pipeline.py` (hash khác nhau) → giữ bản ở `core\pipeline.py`, xoá bản trùng.
