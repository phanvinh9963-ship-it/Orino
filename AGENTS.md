# Reup Studio — Agent Guide (OpenCode)

## Khi tác vụ liên quan đến dựng / hậu kỳ video
Hãy đọc và làm theo theo thứ tự:
1. `OpenMontage\AGENTS.md` (trỏ tới `AGENT_GUIDE.md` — quy tắc vận hành OpenMontage)
2. `OpenMontage\AGENTS.local.md` (bản bổ sung của dự án Orino)

## Ranhrõ giới hạn tích hợp (bắt buộc)
- **KHÔNG import mã OpenMontage vào `core/`** của dự án chính (giấy phép AGPL-3.0, OpenMontage giữ như thư mục độc lập).
- Hai bên chỉ trao đổi qua hai thư mục:
  - `OpenMontage\exchange\input\` — video + SRT từ Reup Studio gửi sang OpenMontage.
  - `OpenMontage\exchange\output\` — video hậu kỳ từ OpenMontage gửi về.
- Dùng `F:\Orino\run_montage.bat` để khởi chạy môi trường OpenMontage (kích hoạt `.venv`, mở `opencode` tại thư mục OpenMontage).

## Quy tắc chung của dự án chính
- Dự án chính (Reup Studio) phải tiếp tục chạy bình thường sau khi tích hợp.
- Không sửa, xóa hay di chuyển file hiện có của `F:\Orino` hay `F:\Orino\srt-whiteboard-animation` ở giai đoạn cài đặt; chỉ thêm mới.
- Không render video, không gọi API trả phí, không nhập API key cho đến khi được xác nhận bằng văn bản.
