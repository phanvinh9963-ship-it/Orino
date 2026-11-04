# Cải tiến giao diện Reup Studio

Chép 2 file đè vào dự án: `main.py` (thay file cũ) và `core/ui_helpers.py` (file mới, cạnh pipeline.py).
Tuỳ chọn (kéo-thả video): `pip install tkinterdnd2` — không cài thì app vẫn chạy, chỉ không có kéo-thả.

- Trang Translate: hàng nút "Đi tới: ..." nhảy thẳng tới từng mục trong panel cấu hình dài
- Kéo-thả video (hoặc thư mục) vào cửa sổ -> tự sang Translate và chọn video
- Phím tắt: Ctrl+1…7 chuyển trang · Ctrl+O chọn video · Ctrl+Enter bắt đầu dịch · Ctrl+S lưu cấu hình
- Thông báo nổi (toast) thay hộp thoại chặn khi Lưu/Nạp cấu hình
- Tự lưu cấu hình khi thoát app; mở lại đúng trang đã dùng lần trước
- Nhớ thư mục video gần nhất; chọn video hỗ trợ thêm webm/m4v/flv/wmv/ts/mpg
- Bấm "Bắt đầu dịch" khi chưa có video -> mở luôn hộp chọn video (thay vì chỉ báo lỗi)
