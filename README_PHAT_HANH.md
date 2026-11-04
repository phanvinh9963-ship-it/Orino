# Hướng dẫn đóng gói Reup Studio để phát hành cho người khác

Làm trên chính máy Windows đang chạy app tốt (đủ Chrome, ffmpeg...).

## Bước 1 — Chuẩn bị các file

Copy 3 file này vào đúng vị trí:

| File | Copy vào |
|---|---|
| `main.py` (bản mới nhất mình gửi) | `G:\reup-studio\main.py` (đè file cũ) |
| `requirements_full.txt` | `G:\reup-studio\requirements_full.txt` |
| `build_exe.bat` | `G:\reup-studio\build_exe.bat` |
| `setup_embedded_python312.bat` | `G:\reup-studio\TiktokAuto\setup_embedded_python312.bat` |

## Bước 2 — Tạo Python 3.12 portable cho TiktokAuto (làm 1 lần)

```
cd G:\reup-studio\TiktokAuto
setup_embedded_python312.bat
```

Đợi chạy xong (tải + cài thư viện, vài phút). Kết quả tạo ra thư mục
`TiktokAuto\python312_embed\`. `main.py` bản mới sẽ **tự động tìm thấy**
thư mục này và dùng nó thay vì đòi `py -3.12` — người nhận file sau này
không cần tự cài Python 3.12 nữa.

**Lưu ý về Node.js**: cơ chế ký chữ ký TikTok (`tiktok-signature`) cần
Node.js + `node_modules` đã cài sẵn (`npm install` trong
`TiktokAuto\tiktok_uploader\tiktok-signature`). Nếu bạn đã cài rồi thì cứ
để nguyên — bước đóng gói ở dưới sẽ copy nguyên cả thư mục `TiktokAuto`
kèm theo `node_modules`, người nhận không cần cài Node.js nữa. Nếu bạn
chưa cài, chạy `npm install` trong thư mục đó trước khi qua Bước 3.

## Bước 3 — Đóng gói main.py thành .exe

```
cd G:\reup-studio
build_exe.bat
```

Script sẽ: tạo môi trường ảo riêng để build → cài toàn bộ thư viện từ
`requirements_full.txt` → chạy PyInstaller đóng gói `main.py` → tự copy
thêm `ffmpeg/`, `model_cache/`, `TiktokAuto/` vào chung kết quả.

Lần đầu có thể mất 10-20 phút (build các thư viện nặng như
`faster-whisper`, `ctranslate2`, `onnxruntime`). Nếu PyInstaller báo lỗi
"ModuleNotFoundError" khi bạn *chạy thử* file `.exe` sau này (không phải
lúc build), đó là module ẩn PyInstaller chưa dò ra — báo mình tên module
bị thiếu, mình sẽ thêm đúng dòng `--hidden-import` vào `build_exe.bat`.

## Bước 4 — Kiểm tra & dọn dữ liệu cá nhân trước khi gửi đi

Kết quả nằm ở `dist\ReupStudio\`. Trước khi nén gửi cho người khác,
**xoá các file/thư mục chứa dữ liệu riêng của bạn** (không nên chia sẻ):

- `dist\ReupStudio\reup_studio_settings.json` (API key Gemini của bạn)
- `dist\ReupStudio\tiktok_uploaded_log.json`, `youtube_uploaded_log.json`
- `dist\ReupStudio\TiktokAuto\CookiesDir\*` (cookie đăng nhập TikTok của bạn)
- `dist\ReupStudio\TiktokAuto\chrome_profile_data\` (profile Chrome đã đăng nhập của bạn)
- `dist\ReupStudio\TiktokAuto\youtube_token.json`, `client_secret.json` (mỗi người cần OAuth Client riêng của họ — xem Bước 5)
- `dist\ReupStudio\reup_output\` nếu có video của bạn trong đó

Sau đó chạy thử `dist\ReupStudio\ReupStudio.exe` ngay trên máy bạn xem
có mở lên và chạy các tab bình thường không, trước khi nén gửi đi.

## Bước 5 — Nén và gửi

Nén thư mục `dist\ReupStudio` thành `.zip`, gửi cho người dùng. Kèm theo
lời dặn họ:

1. Giải nén ra, chạy `ReupStudio.exe`. Không cần cài Python/pip gì cả.
2. **Vẫn cần tự cài Google Chrome** trên máy (không đóng gói kèm được).
3. Muốn dùng tính năng YouTube: tự tạo Google Cloud OAuth Client riêng
   (Google giới hạn theo từng project/tài khoản, không dùng chung được),
   tải `client_secret.json` rồi trỏ vào trong tab YouTube.
4. Muốn dùng TikTok: lần đăng nhập đầu sẽ mở 1 Chrome trắng riêng của
   app (không phải Chrome cá nhân) để họ tự đăng nhập TikTok 1 lần.

## Giới hạn cần biết

- File `.exe` build ra chỉ chạy được trên **Windows cùng kiến trúc** (64-bit)
  — không chạy được trên máy Mac/Linux.
- Không đóng gói kèm được Chrome (dung lượng lớn + có điều khoản sử dụng
  riêng của Google) — máy nào chạy app cũng cần tự có Chrome cài sẵn.
- Dung lượng gói cuối cùng khá lớn (model AI, ctranslate2, onnxruntime,
  Python embed...) — có thể vài trăm MB đến 1-2 GB tuỳ mô hình dùng.
