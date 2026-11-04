REUP STUDIO NOTE OUTPUT PATCH

Mục tiêu:
- Chỉ thay đổi phần tạo NOTE.txt / metadata video từ bước phân tích Gemini.
- Giữ cấu trúc pipeline/UI hiện có.
- Gemini trả về: video_title, alternative_titles, description_intro, description_points, description_cta, video_description, hashtags.
- NOTE.txt có format cố định:
  <tên video gốc>

  Tiêu đề YouTube (<ngôn ngữ đích>)
  <tiêu đề chính>
  Một số tiêu đề hấp dẫn hơn:
  - ...

  Mô tả video YouTube
  <intro>
  📌 Nội dung chính:
  - ...
  <CTA>
  #hashtag ...

Các file trong patch:
- main.py: parser NOTE hỗ trợ format mới và vẫn hỗ trợ format cũ.
- core/pipeline.py: tạo NOTE theo format mới, dùng dữ liệu AI đã phân tích, không gọi AI thêm.
- core/translate.py: ép schema/prompt metadata đầy đủ và theo target language.

Nếu đang dùng một phiên bản core/pipeline.py hoặc core/translate.py mới hơn, hãy merge các thay đổi tương ứng thay vì thay toàn bộ file.
