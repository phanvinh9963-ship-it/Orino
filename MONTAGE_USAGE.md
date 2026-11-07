# Hướng dẫn dùng OpenMontage kèm Reup Studio (Phương án A)

## Mục đích
Dùng OpenMontage làm công cụ hậu kỳ video (AI dựng video) cho Reup Studio, **không sửa mã nguồn** của Reup Studio, **không import mã OpenMontage** vào `core/` (giấy phép AGPL-3.0). Hai bên trao đổi chỉ qua thư mục `exchange\`.

## Thư mục trao đổi
- `F:\Orino\OpenMontage\exchange\input\` — đặt video + SRT từ Reup Studio vào đây.
- `F:\Orino\OpenMontage\exchange\output\` — lấy video hậu kỳ từ OpenMontage ra đây.

## Luồng sử dụng
1. Trong Reup Studio (tab Translate / Job Center), xuất video `final_vi.mp4` và file phụ đề `translated.srt`.
2. Sao chép 2 file này vào `F:\Orino\OpenMontage\exchange\input\`.
3. Chạy `F:\Orino\run_montage.bat` — nó sẽ kích hoạt môi trường Python cô lập (`.venv`) của OpenMontage và mở `opencode` tại thư mục `F:\Orino\OpenMontage`.
4. Agent đọc `OpenMontage\AGENTS.md` rồi `OpenMontage\AGENTS.local.md`, chọn pipeline phù hợp (ví dụ: `animation`, `cinematic`, `documentary-montage`), thực hiện theo quy tắc xác nhận từng bước.
5. Sau khi xong, lấy file video kết quả từ `F:\Orino\OpenMontage\exchange\output\`.

## Ví dụ câu lệnh hướng dẫn agent (không chạy thử)
> "Tôi có video và SRT tại OpenMontage\exchange\input\. Hãy dùng pipeline animation của OpenMontage để làm hậu kỳ (ghép hiệu ứng, phụ đề, nhạc nền), xuất kết quả sang OpenMontage\exchange\output\. Xác nhận với tôi trước khi render."

## Quy tắc bắt buộc
- **Xác nhận trước khi render:** Mọi bước tạo video phải chờ bạn đồng ý rõ ràng trước khi agent thực hiện render. Không bao giờ render thử hay render lén.
- **Không gọi API trả phí:** Không nhập API key, không dùng dịch vụ cloud sinh video/hình/âm thanh tốn phí trừ khi bạn chủ động cung cấp key và đồng ý.
- **Không render video trong giai đoạn cài đặt này.**

## Cảnh báo giấy phép
OpenMontage dùng giấy phép **GNU AGPLv3**. Nếu Reup Studio là sản phẩm thương mại hoặc đóng nguồn, hãy cân nhắc ảnh hưởng pháp lý trước khi gộp mã OpenMontage vào mã nguồn Reup Studio. Hiện tại OpenMontage được giữ như một thư mục độc lập, chỉ trao đổi qua `exchange\`.

## Lưu ý chi phí token
OpenMontage là hệ thống do AI agent điều khiển: mỗi lần agent phân tích, lập kịch bản, chọn provider sẽ tiêu tốn token của model LLM (khi dùng LLM qua API). Nếu bạn dùng các provider sinh video/hình/âm thanh qua API (FAL, Kling, ElevenLabs, Google…), sẽ có chi phí riêng của từng dịch vụ. Chế độ cài đặt hiện tại chỉ dùng công cụ cục bộ miễn phí (ffmpeg, remotion, Piper TTS) — **không tốn phí API** trừ khi bạn tự thêm key.
