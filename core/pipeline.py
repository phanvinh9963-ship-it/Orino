"""
core/pipeline.py
Điều phối toàn bộ pipeline: Transcript -> Translate -> Subtitles -> Voice -> Export
Chạy trong thread riêng, báo tiến độ qua callback để GUI cập nhật an toàn.
"""
from __future__ import annotations
import os
import re
import shutil
import unicodedata
import uuid
from pathlib import Path
import traceback
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.transcribe import transcribe_video, save_srt, parse_srt, SubtitleSegment
from core.translate import translate_segments
from core.narration_merge import merge_segments_for_narration
from core.text_fit import fit_segments_to_timing, split_segments_for_display
from core.tts import synthesize_segments, build_dubbed_track, build_dubbed_track_from_real_audio
from core.export import (
    burn_subtitles, add_watermark,
    add_watermark_image, add_moving_watermark_text, blur_region, mux_audio_advanced,
    flip_video, apply_filters, change_aspect_ratio, change_resolution,
    trim_video, apply_voice_transform,
)
from core.history import JobRecord, append_history
import time


@dataclass
class PipelineConfig:
    video_path: str
    work_dir: str
    history_dir: Optional[str] = None      # nơi lưu history.json - để None thì dùng chung work_dir (như trước đây).
                                            # Tách riêng để hỗ trợ work_dir = folder con RIÊNG cho từng video (mỗi lần
                                            # chạy 1 folder khác nhau, không đè file lẫn nhau), trong khi history.json
                                            # vẫn gom về 1 chỗ DUY NHẤT (folder gốc) để Job Center liệt kê đủ mọi video.
    source_lang: str = "Chinese"
    target_lang: str = "English"
    translation_method: str = "gemini"       # ĐỔI mặc định: dùng thẳng Gemini API chính thức (API key), không cần Gemini Web2API/server phụ nữa
    translate_batch_size: Optional[int] = None  # số câu gộp mỗi lượt gọi API dịch - để trống (None) =
                                            # dùng mặc định 100 câu/lượt (core/translate.py). TĂNG số
                                            # này giúp GIẢM SỐ LƯỢT GỌI API cho video dài - hữu ích với
                                            # Gemini free tier (giới hạn 20 LƯỢT GỌI/ngày, không phải
                                            # giới hạn token) - chỉ áp dụng khi translation_method="gemini".
    whisper_model: str = "small"
    device: str = "auto"
    do_subtitles: bool = True
    do_dubbing: bool = False
    # do_watermark: bool (đã bỏ) - THAY bằng 2 cờ ĐỘC LẬP bên dưới (do_watermark_text /
    # do_watermark_logo), vì trước đây dùng chung 1 cờ + watermark_mode dạng radio
    # (chỉ chọn được 1 trong 2 kiểu) khiến người dùng KHÔNG THỂ bật cả chữ chạy VÀ
    # logo cùng lúc. watermark_text giữ nguyên vị trí field cũ để không phá vỡ thứ
    # tự các field phía dưới.
    watermark_text: str = "Reup Studio"
    subtitle_preset: str = "Classic"
    font_size: int = 20
    subtitle_display_mode: str = "sentence"   # "sentence" (cả câu) | "word" (từng chữ, kiểu TikTok)
    subtitle_font: str = "Arial"
    subtitle_position: str = "bottom"         # vị trí phụ đề trên khung hình - "top"|"middle"|"bottom"|"custom"
    subtitle_pos_x_frac: Optional[float] = None  # dùng khi subtitle_position="custom": toạ độ TÂM chữ,
                                            # tỉ lệ 0..1 chiều rộng khung hình (0=trái, 1=phải)
    subtitle_pos_y_frac: Optional[float] = None  # tương tự, tỉ lệ 0..1 chiều cao khung hình (0=trên, 1=dưới)
    subtitle_box_enabled: bool = False        # bật nền phía sau chữ
    subtitle_box_color: str = "&H000000&"     # màu nền (định dạng ASS/SSA BGR hex)
    subtitle_box_opacity: float = 0.6         # độ mờ của nền phía sau chữ
    subtitle_effect: str = "none"             # hiệu ứng chữ phụ đề (vd fade, karaoke...)
    keep_original_audio_in_dub: bool = False  # mặc định TẮT: chỉ giữ giọng đọc mới, khớp với UI

    # --- Viết lại/biến tấu THÊM 1 lượt trên bản dịch (né trùng lặp nội dung gốc) rồi
    # TỰ CANH LẠI TIMELINE theo đúng độ dài văn bản mới - trước đây tính năng này (core/
    # rewrite_srt.py) CHỈ được nối vào nút phụ "Dịch & Tải file SRT" (main.py, export_srt_only),
    # KHÔNG hề chạy trong luồng chính (nút "Bắt đầu dịch" -> Pipeline.run() ở đây) - nên dù
    # bật checkbox trên UI, video xuất ra vẫn KHÔNG được viết lại. Giờ nối thẳng vào đây,
    # chạy tự động ngay sau bước Translate (mục 3 bên dưới), ÁP DỤNG LUÔN cho cả job có
    # do_dubbing=True lẫn False (rewrite xong, các bước validate/TTS/burn sub phía sau vẫn
    # chạy bình thường trên bản văn bản MỚI + timeline MỚI này).
    rewrite_after_translate: bool = False  # TẮT theo yêu cầu - luồng giờ chỉ còn: tách thoại -> dịch -> lồng tiếng -> xuất video, KHÔNG viết lại kịch bản nữa. Timeline vẫn khớp chuẩn nhờ build_dubbed_track_from_real_audio (xếp theo audio thật, không cần bước viết-lại-khớp-nhịp hỗ trợ nữa).
    rewrite_keep_ratio: float = 0.4        # 0.4 = giữ ~40% ý gốc, viết mới ~60% - khớp UI slider
                                            # "Mức giữ ý gốc" (0.1 = biến tấu rất mạnh, 0.9 = biến tấu nhẹ)
    rewrite_min_gap_sec: float = 0.12      # khoảng nghỉ tối thiểu giữa 2 câu khi canh lại timing
    rewrite_max_gap_sec: float = 0.55      # GIẢM từ 1.2 -> 0.55: phân tích tín hiệu âm thanh 1 video mẫu
    # phong cách "dồn dập, liên tục" (kiểu Discovery/Veritasium tốc độ cao) cho thấy khoảng nghỉ THẬT giữa
    # các câu chỉ trung bình ~0.26s, hiếm khi vượt quá 0.9s - để max_gap_sec=1.2 (mặc định cũ) sẽ tạo ra
    # những quãng nghỉ dài hơn hẳn phong cách này, nghe rời rạc/chậm hơn ý muốn. Nếu bạn thích phong cách
    # đọc CHẬM RÃI, NHẤN NHÁ (có quãng lặng kịch tính dài hơn) thay vì dồn dập, tăng lại giá trị này lên
    # ~1.0-1.5 tuỳ ý.
    extend_video_tail_if_longer: bool = True   # MỚI: nếu audio lồng tiếng dài hơn video gốc (vd
    # chủ động thêm lời kêu gọi "để lại bình luận, bấm theo dõi kênh" ở cuối) -> KÉO DÀI đuôi
    # video (lặp khung hình cuối, đứng yên) cho khớp, thay vì ép nén/tăng tốc audio dồn dập hay
    # để mux cắt mất phần dư. Tắt (False) để quay lại hành vi cũ: ép audio vừa đúng khung giờ
    # video gốc (tăng tốc đều nếu cần, xem core/tts.py:build_dubbed_track_from_real_audio).
    outro_cta_text: Optional[str] = "Hãy Like và Theo dõi kênh. Để Đón Xem Những Video Hữu Ích Khác."
    # MỚI: tự động chèn thêm 1 CÂU CUỐI CÙNG vào bản dịch (sau khi dịch/viết lại xong, trước khi
    # lồng tiếng) với đúng nội dung này - không cần gõ tay vào kịch bản mỗi lần. Để trống ("" hoặc
    # None) để KHÔNG chèn gì cả. Câu này tự động được lồng tiếng + xếp timeline + tự kéo dài đuôi
    # video (nếu extend_video_tail_if_longer=True) y hệt các câu khác, không cần xử lý gì thêm.
    outro_cta_gap_sec: float = 0.5   # khoảng nghỉ giữa câu cuối cùng của nội dung gốc và câu CTA này
    tts_engine: str = "online"        # "online" (edge-tts) | "offline" (pyttsx3) | "clone" (giọng riêng, XTTS-v2) | "vieneu" (VieNeu-TTS, local, chỉ tiếng Việt) | "omnivoice" (OmniVoice, local, 600+ ngôn ngữ, clone HOẶC voice design)
    voice_name: Optional[str] = None      # tên voice profile đã lưu, bắt buộc nếu tts_engine="clone"; với
                                            # tts_engine="omnivoice" là TUỲ CHỌN (có thì clone giọng đó, không
                                            # có thì dùng omnivoice_instruct để voice design, hoặc auto voice)
    voice_profiles_dir: str = "voice_profiles"  # thư mục chứa các voice profile đã lưu
    clone_device: str = "auto"            # "auto" | "cpu" | "cuda", chỉ áp dụng khi tts_engine="clone"

    # --- OmniVoice (tts_engine="omnivoice") - xem core/omnivoice_tts.py. voice_name/
    # voice_profiles_dir ở trên dùng CHUNG cho chế độ clone. Các field dưới đây chỉ
    # dùng riêng cho OmniVoice. ---
    omnivoice_instruct: Optional[str] = None       # mô tả giọng cho VOICE DESIGN (vd "female, low
                                            # pitch, british accent") - chỉ dùng khi KHÔNG có voice_name.
    omnivoice_instruct_male: Optional[str] = None  # mô tả giọng RIÊNG cho câu có gender="male" (cần
                                            # detect_speaker_gender hoặc detect_speaker_by_face bật)
    omnivoice_instruct_female: Optional[str] = None  # tương tự, cho gender="female"
    omnivoice_device: str = "auto"         # "auto" | "cpu" | "cuda:0" | "mps"
    omnivoice_num_step: int = 32           # số bước diffusion (16 = nhanh hơn/chất lượng thấp hơn, 32 = mặc định)
    omnivoice_speed: float = 1.0           # hệ số tốc độ đọc riêng của OmniVoice (độc lập với speech_rate,
                                            # vốn chỉ áp dụng cho engine="online")

    # --- Ghép nhịp lời dẫn: gộp các cue ngắn liên tục thành khối đọc liền mạch ---
    merge_narration: bool = True          # BẬT LẠI mặc định - TẮT nó (bản trước) chính là nguyên nhân câu dịch
                                            # bị cụt lủn kiểu "Ngay sau đó." / "Nhưng để đảm bảo chất lượng." (thực
                                            # ra là NỬA CÂU bị cắt lìa khỏi câu trước/sau, vì video gốc tách thoại
                                            # ra từng mảnh rất ngắn <2s/câu, dịch riêng lẻ từng mảnh nghe cụt/khựng).
                                            # Giờ timeline được xếp theo audio THẬT sau khi lồng tiếng (xem
                                            # build_dubbed_track_from_real_audio, core/tts.py) - không còn phải ép
                                            # khớp từng mảnh gốc như trước nữa, nên gộp câu lại hoàn toàn an toàn.
    merge_min_block_sec: float = 3.0      # khối ngắn hơn mức này sẽ tiếp tục được gộp thêm
    merge_max_block_sec: float = 6.5       # NÂNG từ 4.5 -> 6.5: với video gốc đọc nhanh, segment vụn ~2-4s liền
                                            # mí gần như không khoảng lặng (vd whisper tách phim tài liệu TQ), khối
                                            # 4.5s cũ vẫn còn quá ngắn để câu dịch tiếng Việt (cần nhiều ký tự hơn
                                            # hẳn cho cùng ý) đủ chỗ diễn đạt trọn nghĩa - dịch xong hay bị ép cắt
                                            # cụt câu. Dừng gộp khi khối đã đạt mức này (trừ khi vẫn còn quá ngắn,
                                            # hoặc câu chưa hết - xem core/narration_merge.py)
    merge_hard_cap_sec: float = 9.0        # NÂNG từ 6.0 -> 9.0, chặn cứng, không cho khối phình quá mức này
    merge_gap_break_sec: float = 0.5      # khoảng lặng thật (giây) giữa 2 cue - luôn giữ làm điểm ngắt khối, không gộp qua

    # --- (đã dọn trùng lặp - field rewrite_after_translate/rewrite_keep_ratio định nghĩa DUY NHẤT ở trên) ---


    # --- Khớp thời lượng câu dịch với audio (thay cho việc tăng tốc audio mạnh) ---
    fit_text_to_timing: bool = True       # rút ngắn câu dịch (chỉ dùng cho audio, KHÔNG đụng vào phụ đề hiển thị) nếu ước lượng đọc lâu hơn khoảng trống gốc
    fit_text_tolerance: float = 1.2       # NÂNG từ 1.08 -> 1.2: ngưỡng ở text_fit.py - PHẢI thấp hơn rõ rệt dub_max_speedup bên dưới, để phần rút gọn văn bản
                                            # gánh phần lớn việc khớp thời lượng, atempo chỉ còn xử lý phần dư rất nhỏ (tránh tình trạng câu
                                            # nào cũng bị đổi tốc độ với tỉ lệ dao động lung tung, nghe không lọt tai)
    dub_max_speedup: float = 1.15         # atempo tối đa còn lại, chỉ dùng cho phần lệch NHỎ còn sót sau khi đã rút gọn văn bản
    dub_emergency_max_speedup: float = 1.6  # NẤC KHẨN CẤP: nếu tăng tốc tới dub_max_speedup vẫn chưa đủ khớp khung
                                            # giờ gốc, tăng tốc THÊM tới mức này TRƯỚC KHI cắt bớt đuôi câu - vì mất
                                            # chữ luôn tệ hơn nghe hơi nhanh 1 chút. Chỉ khi tăng tốc tới mức này vẫn
                                            # còn dư (cực hiếm) mới thật sự cắt (và báo cảnh báo riêng, khác "đã tăng tốc").
    dub_min_speedup_ratio: float = 1.03   # lệch nhỏ hơn mức này thì bỏ qua, không chạy atempo (không đáng đổi tốc độ đọc)
    sync_subtitle_to_dub: bool = True     # khi có lồng tiếng: phụ đề HIỂN THỊ dùng ĐÚNG bản văn bản đã rút gọn cho
                                            # giọng đọc (thay vì bản dịch đầy đủ), để chữ trên màn hình luôn khớp với
                                            # những gì được đọc ra - tránh cảm giác "đọc thiếu chữ" (khán giả thấy 1
                                            # câu dài trên phụ đề nhưng giọng đọc chỉ đọc được 1 phần vì hết giờ).
                                            # Chỉ áp dụng khi do_dubbing=True; nếu không lồng tiếng, phụ đề vẫn dùng
                                            # bản dịch đầy đủ (đọc bằng mắt không bị giới hạn tốc độ như giọng đọc).
    llm_shorten_fn: Optional[Callable[[str, str, int], str]] = None  # tuỳ chọn: hàm gọi LLM riêng của bạn để rút gọn câu tốt hơn rule-based, chữ ký (text, lang, target_chars) -> str
    grok_api_keys: List[str] = field(default_factory=list)  # danh sách API key Grok (xAI) - CHỈ còn dùng cho
                                                  # translation_method="grok" (bước DỊCH). Bước RÚT GỌN câu cho
                                                  # khớp timing giờ dùng Gemini Web2API (xem llm_shorten_use_gemini_fastapi
                                                  # bên dưới), không còn phụ thuộc Grok nữa.
    llm_shorten_use_gemini_fastapi: bool = False  # KHÔNG còn dùng tới (llm_shorten_fn không còn cần thiết từ khi đổi sang retime_segments) - giữ field để tương thích ngược, không có tác dụng
    llm_shorten_use_gemini_webapi: bool = False   # tương tự - KHÔNG còn dùng tới, giữ để tương thích ngược
    speech_rate: str = "+8%"              # tốc độ đọc GỐC của edge-tts (native prosody, không phải tăng tốc hậu kỳ) - đây
                                            # là cách "tăng speed" đúng chỗ và tự nhiên nhất để đỡ mất chữ: tăng ~8% giúp
                                            # MỌI câu có thêm ~8% thời gian dư so với ước lượng, nên bước rút gọn văn bản
                                            # (text_fit.py) phải cắt ít hơn, mà giọng đọc vẫn tự nhiên (không "gấp gáp" như
                                            # atempo hậu kỳ vì ngữ điệu/chỗ ngắt hơi được chính model tính lại theo tốc độ
                                            # mới). Có thể chỉnh "+10%"~"+15%" nếu vẫn còn mất chữ nhiều và bạn thấy giọng
                                            # đọc nhanh hơn vẫn nghe ổn ("+0%" = tốc độ mặc định của giọng, không tăng gì).
                                            # LƯU Ý: speech_rate CHỈ áp dụng cho engine="online" (edge-tts hỗ trợ SSML rate);
                                            # engine="clone" (voice clone) đọc theo tốc độ tự nhiên của giọng mẫu, không
                                            # chỉnh được qua tham số này - xem calibrate_speech_rate_cps bên dưới.
    calibrate_speech_rate_cps: bool = True  # TỰ ĐỘNG đo tốc độ đọc THỰC TẾ của đúng engine/giọng sẽ dùng (tổng hợp thử 1
                                            # câu mẫu, đo thời lượng file audio thật - xem core/tts.py:measure_actual_cps)
                                            # thay vì dùng bảng CHARS_PER_SEC tĩnh (hiệu chỉnh cho edge-tts). QUAN TRỌNG với
                                            # engine="clone" hoặc "offline" vì tốc độ đọc của các giọng này khác hẳn edge-tts
                                            # - đây chính là nguyên nhân câu vẫn bị atempo dù văn bản đã "rút gọn cho vừa"
                                            # (ước lượng dùng số cho edge-tts trong khi audio thật lại là giọng clone).
                                            # Tốn thêm ~1 lượt tổng hợp audio mẫu trước khi xử lý cả video (vài giây).

    # --- Kỹ thuật "giãn giờ": làm chậm video gốc TRƯỚC khi chạy pipeline để có thêm thời
    # gian đọc (giảm/khỏi phải nén giọng đọc -> tránh chồng tiếng), rồi TĂNG TỐC lại video
    # output cuối cùng để nhịp phim không bị ì. Giống thao tác thủ công quen thuộc trên
    # CapCut: giảm tốc video gốc về 0.7x -> lồng tiếng -> tăng tốc video ra về 1.3x.
    # Chỉ áp dụng khi do_dubbing=True. Để None (mặc định) = TẮT, giữ hành vi cũ (không đổi
    # tốc độ video, chỉ atempo audio ở build_dubbed_track như trước).
    pre_slowdown_speed: Optional[float] = None    # vd 0.7 = làm chậm video gốc về 70% tốc độ TRƯỚC khi tách thoại/dịch/TTS
    post_speedup_speed: Optional[float] = None    # vd 1.3 = tăng tốc video output cuối cùng lên 130% SAU khi ghép xong

    # --- Tự nhận diện Nam/Nữ cho từng câu thoại, dùng giọng TTS riêng cho mỗi giới tính
    # (xem core/gender_detect.py) - phù hợp video có 2 nhân vật đối thoại (1 nam + 1 nữ),
    # giúp video hấp dẫn hơn thay vì cả video chỉ 1 giọng đọc duy nhất.
    # Chỉ áp dụng khi do_dubbing=True và tts_engine="online" (edge-tts có đủ giọng nam/nữ
    # riêng biệt cho từng ngôn ngữ - xem core/tts.py:VOICE_MAP_BY_GENDER).
    # Yêu cầu: pip install librosa numpy
    detect_speaker_gender: bool = False

    # --- Nhận diện người nói theo KHẨU HÌNH/KHUÔN MẶT (core/face_speaker_detect.py) -
    # CHÍNH XÁC HƠN detect_speaker_gender (vốn chỉ đoán theo pitch từng câu riêng lẻ, dễ
    # nhầm lẫn). Nếu bật, sẽ DÙNG THAY THẾ detect_speaker_gender (không chạy cả 2, tránh
    # dư thừa) - vừa xác định Nam/Nữ vừa phân biệt được TỪNG nhân vật (speaker_id), gộp
    # pitch theo cả nhóm nhân vật thay vì quyết định lẻ từng câu -> ổn định hơn nhiều.
    # Yêu cầu: pip install mediapipe opencv-python numpy librosa
    detect_speaker_by_face: bool = False
    n_speakers_expected: int = 2   # số nhân vật dự kiến cần phân biệt (mặc định 2: 1 nam + 1 nữ)

    # --- Chọn TAY giọng Nam/Nữ cho CẢ VIDEO (chỉ áp dụng khi tts_engine="online" và KHÔNG
    # bật detect_speaker_gender/detect_speaker_by_face - 2 cái đó tự động đoán theo từng
    # câu, còn cái này là 1 lựa chọn CỐ ĐỊNH duy nhất do người dùng tự quyết, phù hợp nhất
    # với video review/thuyết minh cắt cảnh nhanh (nơi auto-detect dễ bị nhảy tone lung
    # tung vì mỗi cảnh lại có nhân vật khác nhau - xem thảo luận trước đó).
    voice_gender: str = "female"   # "male" | "female"

    # --- Lồng tiếng · Giọng lồng · Tiếng Việt (chỉ áp dụng khi tts_engine="vieneu") -
    # gán RIÊNG 1 giọng VieNeu-TTS cho mỗi giới tính nhân vật, thay vì cả video chỉ
    # dùng 1 giọng (voice_name) duy nhất. Mỗi giá trị là tên 1 voice profile trong
    # voice_profiles_dir HOẶC ID 1 giọng dựng sẵn của VieNeu-TTS (xem
    # core/vieneu_tts.py:list_all_vieneu_voice_options). Chỉ có tác dụng với các câu
    # ĐÃ có gender riêng (cần bật detect_speaker_gender hoặc detect_speaker_by_face ở
    # trên) - câu không có gender riêng vẫn dùng voice_name làm giọng nền. Để trống
    # (None) = giữ hành vi cũ, cả video 1 giọng duy nhất theo voice_name.
    vieneu_voice_male: Optional[str] = None
    vieneu_voice_female: Optional[str] = None

    # --- Tương tự vieneu_voice_male/female ở trên nhưng cho tts_engine="online"
    # (edge-tts) - TỰ CHỌN đúng 1 giọng Edge cụ thể cho mỗi giới tính, thay vì
    # luôn dùng đúng 1 cặp cố định trong core/tts.py:VOICE_MAP_BY_GENDER. Cần
    # bật detect_speaker_gender hoặc detect_speaker_by_face ở trên để có tác
    # dụng (câu không có gender riêng vẫn dùng voice_gender làm giọng nền).
    # Để trống (None) = dùng cặp mặc định của VOICE_MAP_BY_GENDER như cũ.
    edge_voice_male: Optional[str] = None
    edge_voice_female: Optional[str] = None

    # --- Dịch bằng Gemini API (thay thế cho online/offline khi translation_method="gemini") ---
    gemini_api_key: Optional[str] = None
    gemini_api_keys: Optional[List[str]] = None  # nhiều key - xoay vòng khi 1 key hết quota
    gemini_model: str = "gemini-3.6-flash"

    # --- Dịch bằng Grok/xAI (thay thế khi translation_method="grok") - dùng CHUNG danh
    # sách grok_api_keys ở trên (xoay vòng nhiều key khi hết quota miễn phí). Model dịch
    # tách riêng khỏi llm_shorten_model (dùng cho việc rút gọn câu) để có thể đổi độc lập.
    grok_translate_model: str = "grok-4.5"

    # --- Content Rewriter: persona/giọng điệu THEO CHỦ ĐỀ áp dụng khi dịch bằng
    # Gemini/Grok/Gemini Web2API (xem TOPIC_PERSONAS trong core/translate.py). None =
    # TỰ ĐỘNG chọn theo "category" mà AI tự nhận diện từ chính transcript gốc (khoa
    # học/lịch sử/tâm lý/tài chính/công nghệ/khác). Đặt 1 trong các giá trị "science"|
    # "history"|"psychology"|"finance"|"technology"|"other" để ÉP CỨNG persona, bỏ
    # qua nhận diện tự động. Chỉ có tác dụng khi translation_method="gemini"/"grok"/
    # "gemini_fastapi" (online/offline dùng deep-translator/argos-translate thuần
    # túy, không hỗ trợ viết lại theo persona).
    content_persona: Optional[str] = None

    # --- Dịch bằng Gemini Web2API (backend gemini-web2api) - server
    # server HTTP LOCAL bọc Gemini web thành API tương thích OpenAI, dùng khi
    # translation_method="gemini_fastapi". Không cần API key trả phí của Google, chỉ
    # cần server đang chạy (xem core/gemini_fastapi_server.py để tự khởi động cùng app).
    gemini_fastapi_base_url: str = "http://127.0.0.1:8000"
    gemini_fastapi_api_key: Optional[str] = None   # CHỈ cần nếu server bật api_keys trong cấu hình Web2API
    gemini_fastapi_model: str = "gemini-3.6-flash"
    gemini_fastapi_auto_start: bool = True   # MỚI: TỰ khởi động + CHỜ server sẵn sàng ngay trong Pipeline.run(),
    # không phụ thuộc việc main.py đã tự khởi động lúc mở app hay chưa (tránh lỗi "CHƯA CHẠY" do
    # bấm chạy job NGAY khi vừa mở app, trong lúc server nền còn đang khởi động dở - race condition).
    gemini_web2api_cookie_file: Optional[str] = None   # để trống = dùng Flash anonymous (không cookie)
    gemini_web2api_proxy: Optional[str] = None

    # --- Dịch bằng "Gemini API master" (gemini_webapi, https://github.com/HanaokaYuzu/Gemini-API)
    # - thay thế khi translation_method="gemini_webapi". Gọi THẲNG gemini.google.com bằng
    # cookie trình duyệt (__Secure-1PSID/__Secure-1PSIDTS), KHÔNG cần chạy thêm server phụ
    # như Gemini Web2API, và cũng KHÔNG cần API key trả phí của Google. Thư mục source
    # "Gemini-API-master" (giải nén từ zip cùng tên) cần đặt CẠNH main.py - xem
    # core/gemini_webapi_client.py.
    gemini_webapi_secure_1psid: Optional[str] = None
    gemini_webapi_secure_1psidts: Optional[str] = None   # không bắt buộc với mọi tài khoản
    gemini_webapi_proxy: Optional[str] = None
    gemini_webapi_model: str = "gemini-3-flash"

    # --- Dịch bằng CLIProxyAPI (https://github.com/router-for-me/CLIProxyAPI) - server
    # Go LOCAL, dùng khi translation_method="cliproxy". Bọc các CLI OAuth (mặc định
    # dùng ở đây: Codex/ChatGPT) thành API tương thích OpenAI, KHÔNG cần API key trả
    # phí theo token riêng - chỉ cần server CLIProxyAPI đang chạy và đã đăng nhập OAuth
    # sẵn. Method này TÁCH BIỆT hoàn toàn khỏi gemini_fastapi (xem core/translate.py:
    # translate_segments_cliproxy / check_cliproxy_health).
    cliproxy_base_url: str = "http://127.0.0.1:8317"
    cliproxy_api_key: Optional[str] = None   # CHỈ cần nếu server bật api-keys trong config.yaml
    cliproxy_model: str = "gpt-5-codex"

    # --- 5 "núm vặn" style cho AI Script Rewriter (GUI: Narrative Style / Audience /
    # Speaking Speed / Creativity / Hook Level) - chỉ có tác dụng khi translation_method
    # dùng LLM viết lại (gemini/grok/gemini_fastapi). Để None/"auto" = không ép hướng
    # nào, giữ hành vi mặc định của CONTENT_REWRITER_INSTRUCTIONS (xem core/translate.py
    # :_style_dial_block cho danh sách giá trị hợp lệ của từng field).
    narrative_style: Optional[str] = None   # "documentary"|"storytelling"|"educational"|"casual_vlog"|"news_recap"
    audience: Optional[str] = None          # "beginner"|"general"|"expert"|"gen_z"
    speaking_speed: Optional[str] = None    # "slow"|"normal"|"fast"
    creativity: Optional[str] = None        # "low"|"medium"|"high"
    hook_level: Optional[str] = None        # "low"|"medium"|"high"

    # --- Watermark: LOGO (ảnh) và CHỮ (cố định hoặc chạy) hoàn toàn ĐỘC LẬP với
    # nhau - có thể bật CẢ HAI cùng lúc, chỉ 1 trong 2, hoặc không bật cái nào.
    # (Trước đây dùng chung watermark_mode kiểu radio "text"|"moving_text"|"image"
    # nên chỉ chọn được 1 trong 3 - đã tách hẳn ra để hỗ trợ bật đồng thời.)
    do_watermark_text: bool = False        # Bật watermark CHỮ (cố định hoặc chạy quanh video)
    watermark_text_style: str = "text"     # "text" (cố định) | "moving_text" (chạy quanh video)
    do_watermark_logo: bool = False        # Bật chèn LOGO ảnh - ĐỘC LẬP với watermark chữ ở trên
    watermark_logo_path: Optional[str] = None
    watermark_position: str = "top-right"  # "top-left" | "top-right" | "bottom-left" | "bottom-right" | "custom"
    watermark_x_frac: Optional[float] = None
    watermark_y_frac: Optional[float] = None
    watermark_scale_frac: float = 0.18
    # Độ mờ TÁCH RIÊNG cho chữ và logo (trước đây dùng chung watermark_opacity,
    # khiến kéo thanh nào cũng đổi luôn cả 2 - giờ độc lập hoàn toàn).
    watermark_text_opacity: float = 0.6     # gợi ý: 0.35-0.55 vừa thấy rõ chữ mà không chói/che nội dung
    watermark_logo_opacity: float = 0.8     # gợi ý: 0.6-0.9 - logo cần rõ nét hơn chữ để nhận diện thương hiệu
    watermark_speed: float = 0.5   # chỉ dùng khi watermark_text_style="moving_text" - tốc độ/tần suất đổi vị trí
    watermark_pattern: str = "drift"   # "drift" (trôi chậm ngẫu nhiên - mặc định mới) | "bounce" | "zigzag" | "random_jump" | "four_corners" - chỉ dùng khi watermark_text_style="moving_text"
    watermark_font_size: int = 28   # cỡ chữ RIÊNG cho watermark chữ chạy - KHÔNG dùng chung với font_size của phụ đề

    # --- MỚI: TỰ ĐỘNG dò + XOÁ (không chỉ blur) logo/watermark và phụ đề hardsub gốc
    # của kênh nguồn - không cần tự vẽ vùng bằng tay như blur_regions bên dưới. Xem
    # core/export.py:detect_logo_region / detect_hardsub_band / delogo_region.
    auto_remove_original_logo: bool = False
    auto_remove_original_subtitle: bool = False
    watermark_removal_engine: str = "delogo"   # "delogo" (ffmpeg, NHANH, chỉ xoá được logo TĨNH ở góc
    # khung hình + hardsub đủ tương phản) | "ai" (core/ai_watermark_remove.py - Florence-2 dò theo
    # PROMPT văn bản ở BẤT KỲ ĐÂU trong khung hình + LaMA nội suy, xoá được cả logo nằm giữa/có hiệu
    # ứng mờ dần/nền phức tạp - CHẤT LƯỢNG CAO HƠN HẲN nhưng CHẬM HƠN NHIỀU, cần GPU CUDA để chạy đủ
    # nhanh, cần cài thêm torch/transformers/iopaint - xem ai_watermark_remove.py:is_available()).
    # Khi "ai", auto_remove_original_logo/auto_remove_original_subtitle vẫn dùng làm 2 công tắc bật/tắt
    # như cũ, nhưng KHÔNG cần detect_logo_region/detect_hardsub_band nữa (AI tự dò trong lúc xử lý).

    # --- Làm mờ 1 vùng cố định để che phụ đề gốc đã hardsub sẵn trong video (người
    # dùng tự chọn khung chữ nhật trên khung hình mẫu ở UI). Toạ độ tính bằng PIXEL
    # theo đúng độ phân giải gốc của video input. Dùng làm PHƯƠNG ÁN DỰ PHÒNG khi
    # chế độ tự động ở trên không dò đủ tin cậy (vd nền phức tạp, logo không tĩnh).
    blur_original_subtitle: bool = False
    blur_regions: List[tuple] = field(default_factory=list)   # danh sách [(x, y, w, h), ...] tính bằng pixel, có thể chọn NHIỀU vùng
    blur_strength: int = 20

    # --- Trộn âm thanh nâng cao: tắt hẳn audio gốc (kể cả khi KHÔNG lồng tiếng),
    # thêm nhạc nền riêng, chỉnh âm lượng từng nguồn.
    remove_original_audio: bool = False    # chỉ áp dụng khi do_dubbing=False (khi CÓ lồng tiếng, dùng keep_original_audio_in_dub như cũ)
    background_music_path: Optional[str] = None
    bg_music_volume: float = 0.25
    dub_volume: float = 1.0

    # --- Lật video ---
    flip_horizontal: bool = False
    flip_vertical: bool = False

    # --- Filter hình ảnh: blur/sharpen/brightness/contrast/saturation (0/mặc định = tắt) ---
    filter_blur: float = 0.0
    filter_sharpen: float = 0.0
    filter_brightness: float = 0.0
    filter_contrast: float = 1.0
    filter_saturation: float = 1.0

    # --- Tỉ lệ khung hình & độ phân giải output. None/"original" = giữ nguyên. ---
    aspect_ratio: Optional[str] = None     # "16:9" | "9:16" | "4:3" | "1:1" | None
    aspect_mode: str = "crop"              # "crop" | "pad" | "blur_pad" | "blur_pad_zoom" - xem core/export.py:change_aspect_ratio
    # --- Nạp phụ đề CÓ SẴN (.srt), thay cho việc tự tách thoại (Transcript) + dịch
    # (Translate). Coi nội dung text trong file này đã là NGÔN NGỮ ĐÍCH cuối cùng
    # (dùng thẳng cho Subtitles/Voice/Export) - bỏ qua hoàn toàn 2 bước Transcript/
    # Translate khi field này được set (không cần whisper_model/translation_method).
    input_srt_path: Optional[str] = None

    resolution: Optional[str] = None       # "480p" | "720p" | "1080p" | "1440p" | "4k" | None

    # --- Dọn dẹp file trung gian sau khi chạy XONG THÀNH CÔNG, chỉ giữ lại video hoàn
    # chỉnh cuối cùng + vài file nhỏ hữu ích (srt, history.json) - tránh mỗi lần chạy
    # lại chất thêm cả chục file .mp4 trung gian nặng máy, đầy ổ đĩa. Khi pipeline LỖI
    # giữa chừng, các file trung gian được GIỮ LẠI để còn debug được nguyên nhân.
    cleanup_intermediate_files: bool = True

    # --- Cắt đầu/đuôi video theo số giây tuỳ chỉnh - chạy NGAY BƯỚC ĐẦU TIÊN, trước
    # cả transcribe/dịch, vì cắt sau đó sẽ làm lệch toàn bộ timestamp phụ đề/audio.
    trim_start_sec: float = 0.0    # cắt bỏ bấy nhiêu giây ở ĐẦU video (0 = không cắt)
    trim_end_sec: float = 0.0      # cắt bỏ bấy nhiêu giây ở ĐUÔI video (0 = không cắt)

    # --- Biến đổi giọng đọc (mục ÂM THANH trên UI): đổi CAO ĐỘ và/hoặc TỐC ĐỘ ĐỌC
    # của track lồng tiếng ĐÃ TẠO XONG, dùng filter 'rubberband' (đổi độc lập pitch/
    # tempo, không như atempo thường sẽ kéo theo đổi cao độ). Áp dụng SAU khi ghép
    # dub_track, TRƯỚC khi mux vào video - chỉ có tác dụng khi do_dubbing=True.
    voice_pitch_semitones: float = 0.0   # -12..+12, 0 = giữ nguyên cao độ gốc của giọng
    voice_speed: float = 1.0             # 0.5..2.0, 1.0 = giữ nguyên tốc độ đọc gốc

    # --- Ép phụ đề HIỂN THỊ ngắn lại: câu dịch dài sẽ được TÁCH thành nhiều dòng
    # ngắn hiện LẦN LƯỢT trong đúng khung giờ gốc (không bớt/đổi nội dung, chỉ tách
    # cách hiển thị) - xem core/text_fit.py:split_segments_for_display. Khác hẳn
    # sync_subtitle_to_dub/fit_text_to_timing ở trên (2 cái đó RÚT NGẮN nội dung cho
    # audio) - cái này giữ nguyên 100% chữ, chỉ chia nhỏ khung hiển thị.
    split_long_subtitles: bool = True
    max_subtitle_chars: int = 42   # quá ngưỡng này (ký tự) mới bắt đầu tách dòng

    # --- Video KHÔNG CÓ LỜI THOẠI (chỉ có hành động/hình ảnh, có thể có nhạc nền):
    # AI (Gemini) XEM TRỰC TIẾP video (không cần audio thoại) để hiểu hành động đang
    # diễn ra, TỰ VIẾT 1 kịch bản lời dẫn/thuyết minh bằng target_lang KHỚP với hành
    # động trên màn hình, dùng thẳng làm segments cho các bước lồng tiếng/phụ đề/xuất
    # video tiếp theo - BỎ QUA HẲN bước Tách thoại (whisper) VÀ bước Dịch (kịch bản
    # sinh ra đã sẵn ở ngôn ngữ đích). Cần ít nhất 1 Gemini API key (dùng CHUNG
    # gemini_api_key/gemini_api_keys/gemini_model đã khai báo ở trên, không cần cấu
    # hình riêng). Xem core/pipeline.py:run() bước 1, core/translate.py:
    # generate_script_from_video.
    silent_video_ai_script: bool = False
    silent_video_narration_style: str = "neutral"   # "neutral" (khách quan) | "dramatic" (kịch tính/giật tít)

    # --- Intro Hook: AI tự đọc phụ đề ĐÃ DỊCH, tự chọn 1 đoạn gây cấn/twist nhất
    # (độ dài tự quyết theo nội dung, không ép cứng số giây) + tự viết riêng 1 câu
    # hook giật tít (khác câu thoại gốc), cắt đúng đoạn đó từ video ĐÃ XUẤT HOÀN
    # CHỈNH (đã lồng tiếng/phụ đề/watermark) rồi ghép lên ĐẦU video làm phần mở màn
    # kiểu "cold open" - video CHÍNH vẫn phát ĐẦY ĐỦ từ đầu như bình thường (không
    # cắt bỏ đoạn đã dùng làm intro). Cần ít nhất 1 Gemini API key (dùng CHUNG
    # gemini_api_key/gemini_api_keys/gemini_model đã khai báo ở trên, không cần cấu
    # hình riêng) - nếu thiếu key hoặc AI lỗi, tự BỎ QUA bước này (video vẫn xuất ra
    # bình thường, không raise lỗi làm hỏng cả job). Xem core/pipeline.py:_maybe_add_hook_intro,
    # core/translate.py:pick_hook_intro, core/export.py:build_hook_intro_clip/concat_intro_and_main.
    add_hook_intro: bool = False


StepCallback = Callable[[str, float, str], None]  # (step_name, 0..1, message)


class Pipeline:
    def __init__(self, config: PipelineConfig, on_progress: Optional[StepCallback] = None):
        self.cfg = config
        self.on_progress = on_progress or (lambda step, pct, msg: None)
        self.result_video: Optional[str] = None
        self.srt_path: Optional[str] = None
        self.error: Optional[str] = None

    def _progress(self, step: str):
        def cb(pct: float, msg: str):
            self.on_progress(step, pct, msg)
        return cb

    @staticmethod
    def _safe_filename(text: str, max_len: int = 90) -> str:
        """Sanitize text for a Windows folder/file name."""
        text = (text or "").strip()
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
        text = re.sub(r"\s+", " ", text).strip(" .")
        if len(text) > max_len:
            text = text[:max_len].rstrip(" .")
        return text or "Video"

    @staticmethod
    def _strip_vn_diacritics(text: str) -> str:
        """Bỏ dấu tiếng Việt (giữ nguyên chữ Nhật/Hàn/Trung nếu có) - dùng để tạo
        hashtag kiểu 'CamelCase không dấu' (vd 'đường' -> 'Duong') giống phong cách
        hashtag phổ biến trên YouTube/TikTok quốc tế, thay vì để nguyên dấu."""
        text = text.replace("đ", "d").replace("Đ", "D")
        normalized = unicodedata.normalize("NFD", text)
        return "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    @classmethod
    def _make_hashtag_word(cls, word: str, target_lang: str) -> str:
        """Chuẩn hoá 1 từ khoá thành dạng hashtag đẹp: 'CamelCase không dấu' cho các
        ngôn ngữ dùng chữ Latin (tiếng Việt/Anh...), giữ nguyên cho chữ tượng hình
        (Nhật/Hàn/Trung) vì các ngôn ngữ đó không có khái niệm viết hoa chữ cái đầu."""
        if target_lang.startswith(("ja", "jpn", "japanese", "ko", "kor", "korean", "zh", "chi", "zho", "chinese")):
            return word
        ascii_word = cls._strip_vn_diacritics(word)
        return ascii_word[:1].upper() + ascii_word[1:] if ascii_word else word

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """Tách văn bản đã dịch thành từng câu (dùng dấu .!?… làm ranh giới) để
        chọn lọc thành các gạch đầu dòng 'Nội dung chính' trong mô tả - thay vì cắt
        cứng theo số ký tự (dễ cắt ngang giữa câu, đọc rất chán)."""
        text = re.sub(r"\s+", " ", (text or "").strip())
        if not text:
            return []
        parts = re.split(r"(?<=[.!?…])\s+", text)
        return [p.strip(" .-–—") for p in parts if len(p.strip(" .-–—")) >= 8]

    @staticmethod
    def _truncate_at_word(text: str, max_len: int) -> str:
        text = text.strip()
        if len(text) <= max_len:
            return text
        return text[:max_len].rsplit(" ", 1)[0].rstrip(" .,;:!?-") + "…"

    def _build_output_metadata(self):
        """Ưu tiên dùng title/description/hashtags do AI viết (note_title/note_title_alternatives/
        note_description/note_hashtags - lấy chung từ lượt gọi phân tích ngữ cảnh đã có sẵn lúc dịch,
        XEM context_output ở core/translate.py -> KHÔNG tốn thêm lượt gọi API nào).

        Chỉ khi không có (vd dùng engine offline/online không phân tích ngữ cảnh, hoặc bước
        đó lỗi) mới rơi về cách cũ: tự ghép câu thô từ phụ đề đã dịch, không cần API, đảm
        bảo NOTE.txt vẫn luôn được tạo ra dù mạng/API có vấn đề sau khi dịch xong. Bản
        fallback này được viết lại theo dạng "hấp dẫn" (hook + 📌 gạch đầu dòng nội dung
        chính + 💡 điểm nhấn + 👍 lời kêu gọi theo dõi) thay vì chỉ dán nguyên đoạn thoại
        thô, và hashtag được viết hoa chữ đầu/bỏ dấu (CamelCase) cho đẹp mắt hơn.

        Trả về "hashtags" (5 cái ĐẦU, dùng cho dòng HASHTAGS chính - phần TikTok/YouTube tab
        đọc lên khi đăng) và "hashtags_full" (toàn bộ hashtag AI viết, nếu có).
        QUAN TRỌNG: hashtags_full KHÔNG được ghi vào phần MÔ TẢ VIDEO trong NOTE.txt;
        hashtag chỉ nằm ở section HASHTAGS (5) riêng biệt để parser YouTube đọc đúng.
        """
        ctx = getattr(self, "_video_context_result", None) or {}
        ai_title = str(ctx.get("note_title") or "").strip()
        ai_title_alts_raw = ctx.get("note_title_alternatives") or []
        ai_title_alts = [str(t).strip() for t in ai_title_alts_raw if str(t).strip()]
        ai_description = str(ctx.get("note_description") or "").strip()
        ai_hashtags_raw = ctx.get("note_hashtags") or []
        ai_hashtags_full = [str(h).strip() for h in ai_hashtags_raw if str(h).strip()]
        ai_hashtags_full = [h if h.startswith("#") else f"#{h}" for h in ai_hashtags_full]
        # ĐÃ BỎ giới hạn 5 hashtag theo yêu cầu - NOTE.txt giờ ghi TOÀN BỘ hashtag AI
        # viết thẳng ra (không cắt, không tách file NOTE_extra.txt riêng nữa). Giữ
        # nguyên biến "ai_hashtags" để không phải sửa lại điều kiện fallback bên dưới.
        ai_hashtags = ai_hashtags_full

        # BUG ĐÃ SỬA: AI đôi khi tự chèn thẳng hashtag ("#tag") vào NGAY TRONG câu
        # title/description nó viết (vd viết title kiểu "...!#SomeTag" cho giật gân) -
        # dòng title/description đó khi ghi vào NOTE.txt sẽ bị parser của
        # TiktokAuto/batch_upload.py (hàm parse_note - đọc THEO DÒNG, không phân biệt
        # được hashtag lẫn trong 1 dòng title/description) hiểu NHẦM 1 phần nội dung
        # là hashtag hoặc gộp lẫn qua section khác, gây ra đúng hiện tượng "mô tả bị
        # nhét nhầm hashtag vào" như trên UI. Tự động BÓC hết token "#..." ra khỏi
        # title/description TRƯỚC khi ghi (hashtag đã có chỗ RIÊNG là note_hashtags).
        def _strip_inline_hashtags(text: str) -> str:
            cleaned = re.sub(r"(?:\s|^)#[^\s#]*", " ", text)   # bỏ "#word" VÀ cả "#" trơ trọi (không có chữ theo sau)
            cleaned = cleaned.replace("#", " ")                 # phòng hờ còn sót "#" dính liền chữ không có khoảng trắng trước
            return re.sub(r"\s+", " ", cleaned).strip(" -–—!.,;:")

        ai_title = _strip_inline_hashtags(ai_title)
        ai_description = _strip_inline_hashtags(ai_description)

        if ai_title and ai_description and len(ai_hashtags) >= 3:
            return {
                "title": ai_title[:150],
                "title_alternatives": ai_title_alts,
                "description": ai_description,
                "hashtags": ai_hashtags,
                "hashtags_full": ai_hashtags,
            }

        segments = getattr(self, "_translated_segments", None) or []
        texts = [str(getattr(x, "text", "") or "").strip() for x in segments]
        texts = [re.sub(r"\s+", " ", x) for x in texts if x]
        full_text = " ".join(texts).strip()
        target_lang = str(getattr(self.cfg, "target_lang", "") or "").strip().lower()

        sentences = self._split_sentences(full_text)

        # ----- Title: câu đầu tiên đủ "hook", không cắt ngang giữa câu nếu vừa độ dài -----
        title = ""
        if sentences:
            first = sentences[0]
            if len(first) <= 95:
                title = first
            else:
                title = self._truncate_at_word(first, 90)
        if not title:
            title = Path(self.cfg.video_path).stem
        title = title[:150]

        # ----- Description: hook + 📌 gạch đầu dòng nội dung chính + 💡 điểm nhấn + 👍 CTA -----
        if sentences:
            hook = sentences[0]
            # Chọn tối đa 5 câu tiếp theo, rải đều trong video (không lấy dồn 5 câu
            # liền kề đầu tiên) để phần "Nội dung chính" bao quát cả video, không chỉ
            # phần mở đầu - đọc lên đỡ chán và đúng tinh thần "tóm tắt" hơn.
            rest = [s for s in sentences[1:] if s.casefold() != hook.casefold()]
            bullet_count = min(5, len(rest))
            bullets = []
            if bullet_count:
                step = max(1, len(rest) // bullet_count)
                seen = set()
                for i in range(0, len(rest), step):
                    key = rest[i].casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    bullets.append(self._truncate_at_word(rest[i], 140))
                    if len(bullets) >= bullet_count:
                        break
            insight_candidates = [s for s in reversed(sentences) if s.casefold() not in {hook.casefold(), *[b.casefold() for b in bullets]}]
            insight = self._truncate_at_word(insight_candidates[0], 160) if insight_candidates else ""

            desc_parts = [hook]
            if bullets:
                desc_parts.append("")
                desc_parts.append("📌 Nội dung chính:")
                desc_parts.extend(f"* {b}" for b in bullets)
            if insight:
                desc_parts.append("")
                desc_parts.append(f"💡 {insight}")
            desc_parts.append(
                "👍 Nếu bạn thấy nội dung hữu ích, hãy Like, Lưu video và Theo dõi kênh để không bỏ lỡ "
                "những video hấp dẫn tiếp theo!"
            )
            description = "\n".join(desc_parts)
        else:
            description = "Video được dịch sang tiếng Việt."

        # ----- Hashtags fallback: keyword theo tần suất, viết dạng CamelCase không dấu -----
        stopwords = {
            "những", "nhưng", "được", "trong", "với", "cho", "của", "một", "các",
            "này", "đó", "là", "và", "thì", "khi", "từ", "đến", "theo", "đang",
            "không", "chúng", "bạn", "có", "như", "nên", "sẽ", "rất", "để",
            "this", "that", "with", "from", "have", "your", "will", "are", "the",
            "and", "for", "you", "not", "but", "can", "how", "what", "why",
            "これ", "それ", "この", "その", "ため", "こと", "もの", "よう", "です", "ます",
        }

        words = re.findall(r"[^\W_]{2,}", full_text.lower(), flags=re.UNICODE)
        counts = {}
        for w in words:
            w = unicodedata.normalize("NFC", w).strip()
            if w in stopwords or w.isdigit():
                continue
            if len(w) > 24:
                continue
            counts[w] = counts.get(w, 0) + 1
        ranked = sorted(counts, key=lambda w: (-counts[w], -len(w), w))

        hashtags = []
        seen = set()
        for word in ranked:
            clean = re.sub(r"[^\w\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7afÀ-ỹĐđ]", "", word, flags=re.UNICODE)
            if len(clean) < 2:
                continue
            tag = "#" + self._make_hashtag_word(clean, target_lang)
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            hashtags.append(tag)
            if len(hashtags) == 5:
                break

        # Fallback luôn theo target language, tuyệt đối không nhét hashtag Việt vào
        # video Japanese/English/... chỉ vì AI thiếu hashtag.
        if target_lang.startswith(("ja", "jpn", "japanese")):
            fallback_tags = ["#豆知識", "#雑学", "#解説", "#情報", "#動画"]
        elif target_lang.startswith(("ko", "kor", "korean")):
            fallback_tags = ["#상식", "#정보", "#해설", "#지식", "#영상"]
        elif target_lang.startswith(("zh", "chi", "zho", "chinese")):
            fallback_tags = ["#知识", "#科普", "#解说", "#信息", "#视频"]
        elif target_lang.startswith(("en", "eng", "english")):
            fallback_tags = ["#Facts", "#Explained", "#Knowledge", "#Information", "#Video"]
        else:
            fallback_tags = ["#KienThucHay", "#GiaiThich", "#ThongTin", "#SuThat", "#KhoaHoc"]

        for tag in fallback_tags:
            if len(hashtags) == 5:
                break
            if tag.casefold() not in seen:
                hashtags.append(tag)
                seen.add(tag.casefold())

        return {
            "title": title,
            "title_alternatives": [],
            "description": description,
            "hashtags": hashtags[:5],
            "hashtags_full": hashtags[:5],
        }

    def _maybe_add_hook_intro(self):
        """Nếu bật cfg.add_hook_intro: gọi AI (Gemini) chọn 1 đoạn gây cấn/twist nhất
        từ video ĐÃ XUẤT HOÀN CHỈNH (self.result_video - đã lồng tiếng/phụ đề/watermark),
        tự viết 1 câu hook giật tít riêng, cắt đoạn đó + đè hook lên rồi ghép lên ĐẦU
        video. Video CHÍNH vẫn phát ĐẦY ĐỦ từ đầu như bình thường (không cắt bỏ đoạn
        đã dùng làm intro) - kiểu phim mở đầu bằng cảnh cao trào rồi quay lại kể từ đầu.

        Đây là bước PHỤ TRỢ, KHÔNG được phép làm hỏng cả job - mọi lỗi (thiếu API key,
        AI trả JSON sai, ffmpeg lỗi...) đều bị bắt lại, chỉ log cảnh báo rồi GIỮ NGUYÊN
        video như chưa bật tính năng này, không raise.
        """
        if not self.cfg.add_hook_intro:
            return
        if not self.result_video or not os.path.isfile(self.result_video):
            return

        api_keys = list(self.cfg.gemini_api_keys or [])
        if self.cfg.gemini_api_key:
            api_keys.append(self.cfg.gemini_api_key)
        if not api_keys:
            self.on_progress("Export", 1.0, "⚠ Bỏ qua Intro Hook: cần ít nhất 1 Gemini API key.")
            return

        segments = getattr(self, "_translated_segments", None) or []
        if not segments:
            self.on_progress("Export", 1.0, "⚠ Bỏ qua Intro Hook: không có phụ đề đã dịch để AI chọn đoạn.")
            return

        try:
            from core.translate import pick_hook_intro
            from core.export import build_hook_intro_clip, concat_intro_and_main

            self.on_progress("Export", 0.0, "🎬 AI đang chọn đoạn Intro Hook gây cấn nhất...")
            pick = pick_hook_intro(
                segments, self.cfg.target_lang, api_keys,
                model=self.cfg.gemini_model or "gemini-3.6-flash",
                progress_cb=self._progress("Export"),
            )
            if not pick:
                self.on_progress("Export", 1.0, "⚠ Bỏ qua Intro Hook: AI không chọn được đoạn phù hợp.")
                return

            intro_path = os.path.join(self.cfg.work_dir, "hook_intro_clip.mp4")
            build_hook_intro_clip(
                self.result_video, pick["start"], pick["end"], pick["hook_text"], intro_path,
                progress_cb=self._progress("Export"),
            )

            combined_path = os.path.join(self.cfg.work_dir, "with_hook_intro.mp4")
            concat_intro_and_main(
                intro_path, self.result_video, combined_path, progress_cb=self._progress("Export"),
            )

            self.result_video = combined_path
            self.on_progress(
                "Export", 1.0,
                f"✅ Đã thêm Intro Hook ({pick['start']:.1f}s-{pick['end']:.1f}s): \"{pick['hook_text']}\"",
            )
        except Exception as e:
            self.on_progress("Export", 1.0, f"⚠ Bỏ qua Intro Hook do lỗi: {e}")

    def _package_final_output(self):
        """Move only the finished assets into a clean per-video folder.

        Final layout:
          reup_output/<video gốc> => <tiêu đề tiếng Việt>/
              final_vi.mp4
              translated.srt
              NOTE.txt
        """
        if not self.result_video or not os.path.isfile(self.result_video):
            return

        root_dir = os.path.abspath(self.cfg.history_dir or os.path.dirname(self.cfg.work_dir))
        os.makedirs(root_dir, exist_ok=True)
        metadata = self._build_output_metadata()
        original_stem = Path(self.cfg.video_path).stem
        folder_name = self._safe_filename(f"{original_stem} => {metadata['title']}", 150)
        final_dir = os.path.join(root_dir, folder_name)

        # Avoid overwriting an existing completed video from an earlier run.
        if os.path.abspath(final_dir) == os.path.abspath(self.cfg.work_dir):
            final_dir = os.path.join(root_dir, self._safe_filename(folder_name + " - output", 150))
        if os.path.exists(final_dir):
            suffix = time.strftime("%Y%m%d_%H%M%S")
            final_dir = os.path.join(root_dir, self._safe_filename(f"{folder_name} - {suffix}", 150))
        os.makedirs(final_dir, exist_ok=True)

        final_video = os.path.join(final_dir, "final_vi.mp4")
        shutil.move(self.result_video, final_video)
        self.result_video = final_video

        if self.srt_path and os.path.isfile(self.srt_path):
            final_srt = os.path.join(final_dir, "translated.srt")
            shutil.move(self.srt_path, final_srt)
            self.srt_path = final_srt

        note_path = os.path.join(final_dir, "NOTE.txt")
        with open(note_path, "w", encoding="utf-8") as f:
            # Dòng thông tin nguồn (KHÔNG phải section - nằm TRƯỚC header "Tiêu đề"
            # đầu tiên nên parser theo dòng (main.py:_youtube_parse_note_file và
            # TiktokAuto/batch_upload.py) sẽ bỏ qua, an toàn 100%). Định dạng
            # "<tên file gốc> [<id ngắn>]" - giữ vết về video gốc, giống kiểu
            # "<id> - <tiêu đề gốc> [<id nội bộ>]" hay gặp trên các file note đã tải.
            f.write(f"{original_stem} [{uuid.uuid4().hex[:12]}]\n\n")

            # LƯU Ý: đổi tên 2 header này từ "TIÊU ĐỀ VIDEO"/"MÔ TẢ VIDEO" cũ sang
            # "Tiêu đề YouTube (Tiếng Việt)"/"Mô tả video YouTube" cho tự nhiên, dễ đọc
            # hơn. An toàn với parser NỘI BỘ của app (main.py:_youtube_parse_note_file
            # chỉ so khớp TIỀN TỐ "TIÊU ĐỀ"/"MÔ TẢ" không phân biệt hoa-thường, câu nào
            # bắt đầu bằng các từ đó đều nhận diện đúng section). NẾU bạn còn dùng công
            # cụ TiktokAuto/batch_upload.py (parse_note) để tự đăng TikTok và nó so khớp
            # CHUỖI CHÍNH XÁC "TIÊU ĐỀ VIDEO"/"MÔ TẢ VIDEO", hãy đổi lại 2 chuỗi bên dưới
            # về đúng như cũ để không bị gãy tool đó.
            f.write("Tiêu đề YouTube (Tiếng Việt)\n")
            f.write(metadata["title"] + "\n\n")

            f.write("Mô tả video YouTube\n")
            # QUAN TRỌNG: section này CHỈ được chứa ĐÚNG 1 nội dung là mô tả - KHÔNG được
            # thêm dòng nào bắt đầu bằng "Tiêu đề"/"Mô tả"/"Hashtag" (case-insensitive) ở
            # giữa nội dung, vì parser đọc THEO DÒNG sẽ hiểu nhầm đó là section mới và cắt
            # mất phần còn lại. Các dòng 📌/*/💡/👍 KHÔNG trùng tiền tố nào ở trên nên an
            # toàn để làm mô tả "hấp dẫn" hơn (hook + gạch đầu dòng + điểm nhấn + CTA).
            f.write(metadata["description"] + "\n")

            # THEO YÊU CẦU MỚI: KHÔNG còn giới hạn 5 hashtag / KHÔNG còn header
            # "HASHTAGS (n)" riêng nữa - ghi TOÀN BỘ hashtag AI viết thẳng ra 1 dòng
            # ngay sau mô tả (không có dòng trống ở giữa), giống đúng cấu trúc NOTE.txt
            # mẫu mà người dùng yêu cầu. LƯU Ý: vì không còn header "HASHTAGS", parser
            # NỘI BỘ (main.py:_youtube_parse_note_file) sẽ tự động coi dòng hashtag này
            # là PHẦN CUỐI của section "Mô tả video YouTube" (vẫn đúng ý, vì YouTube
            # cũng thường đặt hashtag ở cuối mô tả). NẾU bạn còn dùng công cụ ngoài
            # TiktokAuto/batch_upload.py (parse_note) và nó bắt buộc phải có 1 header
            # "HASHTAGS" tách riêng để hoạt động, hãy báo lại - file đó không có trong
            # dự án này nên chưa thể tự sửa kèm ở đây.
            if metadata["hashtags"]:
                f.write(" ".join(metadata["hashtags"]) + "\n")

        # Phần "làm giàu" thêm (tiêu đề thay thế để tham khảo) - ghi ra file RIÊNG,
        # KHÔNG đụng vào NOTE.txt. Hashtag giờ không còn bị cắt/tách ra file riêng nữa
        # (đã ghi đủ thẳng vào NOTE.txt ở trên).
        extra_lines = []
        if metadata.get("title_alternatives"):
            extra_lines.append("TIÊU ĐỀ THAY THẾ (tham khảo, không dùng để đăng tự động)")
            extra_lines.extend(f"* {alt}" for alt in metadata["title_alternatives"])
            extra_lines.append("")
        if extra_lines:
            with open(os.path.join(final_dir, "NOTE_extra.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(extra_lines) + "\n")

        # Remove now-empty processing folder and any leftover temp assets.
        try:
            if os.path.isdir(self.cfg.work_dir):
                shutil.rmtree(self.cfg.work_dir, ignore_errors=True)
        except OSError:
            pass

    def _cleanup_intermediates(self):
        """
        Xoá các file .mp4 TRUNG GIAN sinh ra trong quá trình xử lý (mỗi bước export
        đều lưu ra 1 file .mp4 mới để bước sau xử lý tiếp), CHỈ GIỮ LẠI video hoàn
        chỉnh cuối cùng (self.result_video) + vài file nhỏ hữu ích (phụ đề, track
        lồng tiếng, lịch sử job). Chỉ chạy khi pipeline đã XONG THÀNH CÔNG.
        """
        intermediate_names = [
            "blurred_sub.mp4", "flipped.mp4", "subbed.mp4", "filtered.mp4",
            "ratio.mp4", "resized.mp4", "dubbed.mp4", "audio_swapped.mp4",
            "_preview_frame.jpg",
        ]
        for name in intermediate_names:
            path = os.path.join(self.cfg.work_dir, name)
            if path == self.result_video:
                continue   # phòng trường hợp không bước nào chạy, current_video vẫn trỏ tới 1 trong các tên này
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass   # không chặn pipeline chỉ vì xoá file dọn dẹp thất bại (vd file đang mở ở chỗ khác)

        # tts_segments/ chứa hàng trăm file .wav nhỏ lẻ cho từng câu - không cần giữ
        # lại sau khi đã ghép xong thành dubbed_track.mp3.
        tts_dir = os.path.join(self.cfg.work_dir, "tts_segments")
        if os.path.isdir(tts_dir):
            import shutil
            try:
                shutil.rmtree(tts_dir, ignore_errors=True)
            except OSError:
                pass

    def run(self):
        try:
            os.makedirs(self.cfg.work_dir, exist_ok=True)

            # -2. Đảm bảo Gemini Web2API SỐNG trước khi làm bất cứ gì khác - tự khởi động
            # (nếu bật gemini_fastapi_auto_start và có bundle sẵn) rồi CHỜ tới khi sẵn sàng,
            # thay vì phó mặc cho main.py tự khởi động lúc mở app (dễ dính race condition:
            # bấm chạy job ngay khi vừa mở app, trong lúc server nền còn đang khởi động dở
            # -> lỗi "CHƯA CHẠY" dù server thật ra sắp sẵn sàng). Chỉ cần khi có bước nào đó
            # thật sự dùng tới Gemini Web2API (dịch hoặc viết-lại-khớp-nhịp).
            # -2. Đảm bảo Gemini Web2API SỐNG - CHỈ khi thật sự cần tới nó, tức là KHÔNG
            # có Gemini API key nào khả dụng cho các bước liên quan (dịch/viết-lại-khớp-nhịp).
            # Có API key rồi thì bỏ qua hẳn Web2API, gọi thẳng API - không cần server phụ,
            # không cần cookie, không lo "CHƯA CHẠY" nữa.
            has_gemini_api_keys = bool(self.cfg.gemini_api_keys) or bool(self.cfg.gemini_api_key)
            needs_gemini_fastapi = (not has_gemini_api_keys) and (
                self.cfg.translation_method == "gemini_fastapi"
                or (self.cfg.rewrite_after_translate and self.cfg.gemini_fastapi_base_url)
                or self.cfg.llm_shorten_use_gemini_fastapi
            )
            if needs_gemini_fastapi and self.cfg.gemini_fastapi_base_url:
                from core.gemini_fastapi_server import (
                    check_server_health, GeminiFastAPIProcess, get_bundled_server_dir,
                )
                ok, msg = check_server_health(self.cfg.gemini_fastapi_base_url, timeout=3.0)
                if not ok:
                    if self.cfg.gemini_fastapi_auto_start and get_bundled_server_dir() is not None:
                        self.on_progress("Translate", 0.0, "Gemini Web2API chưa chạy - đang tự khởi động...")
                        proc = GeminiFastAPIProcess()
                        started = proc.start(
                            api_key=self.cfg.gemini_fastapi_api_key,
                            cookie_file=self.cfg.gemini_web2api_cookie_file,
                            proxy=self.cfg.gemini_web2api_proxy,
                            base_url=self.cfg.gemini_fastapi_base_url,
                            log_cb=lambda m: self.on_progress("Translate", 0.0, f"[Gemini Web2API] {m}"),
                        )
                        if started:
                            ready = proc.wait_until_ready(
                                self.cfg.gemini_fastapi_base_url, timeout=30.0,
                                log_cb=lambda m: self.on_progress("Translate", 0.0, f"[Gemini Web2API] {m}"),
                            )
                            if ready:
                                self._gemini_fastapi_proc = proc  # giữ tham chiếu để không bị garbage-collect giữa chừng
                                self.on_progress("Translate", 0.0, "✓ Gemini Web2API đã sẵn sàng.")
                            else:
                                raise RuntimeError(
                                    f"Gemini Web2API khởi động nhưng KHÔNG sẵn sàng sau 30s tại "
                                    f"{self.cfg.gemini_fastapi_base_url}. Kiểm tra log '[Gemini Web2API]' ở trên."
                                )
                        else:
                            raise RuntimeError(
                                "Không tự khởi động được Gemini Web2API. Kiểm tra thư mục "
                                "'gemini_web2api_server/' có nằm cạnh main.py không."
                            )
                    else:
                        raise RuntimeError(
                            f"{msg} Bật 'Tự khởi động Gemini Web2API cùng app' (gemini_fastapi_auto_start=True), "
                            "hoặc tự khởi động server tay rồi thử lại."
                        )

            # -1. (Tuỳ chọn) Cắt bớt ĐẦU/ĐUÔI video theo số giây tuỳ chỉnh - PHẢI chạy
            # TRƯỚC MỌI bước khác (kể cả pre_slowdown) vì đây là thay đổi timeline gốc.
            source_video = self.cfg.video_path
            if (self.cfg.trim_start_sec or 0) > 0 or (self.cfg.trim_end_sec or 0) > 0:
                self.on_progress("Transcript", 0.0, "Đang cắt bớt đầu/đuôi video...")
                trimmed_path = os.path.join(self.cfg.work_dir, "input_trimmed.mp4")
                source_video = trim_video(
                    source_video, trimmed_path,
                    trim_start_sec=self.cfg.trim_start_sec, trim_end_sec=self.cfg.trim_end_sec,
                    progress_cb=self._progress("Transcript"),
                )

            # 0. (Tuỳ chọn) Làm chậm video gốc TRƯỚC khi tách thoại, để giãn hết mốc thời
            # gian ra -> bước fit_segments_to_timing có nhiều chỗ trống hơn cho giọng đọc,
            # ít phải nén/tăng tốc audio -> tránh chồng tiếng. Chỉ áp dụng khi có lồng tiếng.
            if self.cfg.do_dubbing and self.cfg.pre_slowdown_speed and self.cfg.pre_slowdown_speed != 1.0:
                # Cảnh báo NGAY nếu post_speedup_speed không khớp nghịch đảo chính xác của
                # pre_slowdown_speed - lệch cặp này khiến video output DÀI/NGẮN hơn bản gốc
                # (không phải lỗi từng khớp/cắt câu, mà lệch TỔNG THỜI LƯỢNG cả video so với
                # gốc, dễ gây cảm giác giọng đọc/nội dung "không khớp với video" khi xem).
                exact_inverse = 1.0 / self.cfg.pre_slowdown_speed
                configured_post = self.cfg.post_speedup_speed or 1.0
                drift_pct = abs(configured_post - exact_inverse) / exact_inverse * 100
                if drift_pct > 1.0:
                    final_ratio = exact_inverse / configured_post
                    self.on_progress(
                        "Transcript", 0.0,
                        f"⚠ post_speedup_speed ({configured_post:.4f}) LỆCH với nghịch đảo chính "
                        f"xác của pre_slowdown_speed ({exact_inverse:.4f}) - video output sẽ "
                        f"{'DÀI' if final_ratio > 1 else 'NGẮN'} hơn bản gốc khoảng "
                        f"{abs(final_ratio - 1) * 100:.1f}%. Nên đặt post_speedup_speed = "
                        f"{exact_inverse:.4f} để khớp đúng thời lượng gốc.",
                    )
                self.on_progress(
                    "Transcript", 0.0,
                    f"Đang làm chậm video gốc về {self.cfg.pre_slowdown_speed}x trước khi tách thoại...",
                )
                from core.speed_adjust import change_video_speed
                slowed_path = os.path.join(self.cfg.work_dir, "input_slowed.mp4")
                source_video = change_video_speed(
                    source_video, self.cfg.pre_slowdown_speed, slowed_path,
                    progress_cb=self._progress("Transcript"),
                )

            # 1. Transcript (BỎ QUA nếu người dùng đã nạp sẵn 1 file .srt - dùng thẳng
            # nội dung đó thay vì tự tách thoại bằng whisper. BỎ QUA THEO KIỂU KHÁC
            # nếu bật "video không có lời thoại" - AI xem video sinh kịch bản thẳng
            # bằng ngôn ngữ đích, cũng không cần whisper).
            self._is_silent_video_script = False
            if self.cfg.input_srt_path:
                self.on_progress(
                    "Transcript", 0.0,
                    f"Đang nạp phụ đề có sẵn: {os.path.basename(self.cfg.input_srt_path)}...",
                )
                segments = parse_srt(self.cfg.input_srt_path)

                # QUAN TRỌNG: file .srt nạp vào (vd xuất từ nút "Xuất SRT", hoặc tự
                # chuẩn bị từ nguồn khác) có timestamp tính theo video GỐC (tốc độ
                # thường), KHÔNG biết gì về pre_slowdown_speed vừa áp ở bước 0 - nếu
                # dùng thẳng, timestamp sẽ LỆCH TỈ LỆ với video đã bị làm chậm (source_
                # video từ giờ trở đi là bản ĐÃ CHẬM), khiến giọng đọc/burn sub đặt sai
                # vị trí so với hình - đúng lỗi "sub chạy chậm hơn audio" khi bật CapCut
                # trick. Co giãn lại đúng theo pre_slowdown_speed để khớp video đã chậm.
                if self.cfg.do_dubbing and self.cfg.pre_slowdown_speed and self.cfg.pre_slowdown_speed != 1.0:
                    segments = [
                        SubtitleSegment(
                            index=s.index,
                            start=s.start / self.cfg.pre_slowdown_speed,
                            end=s.end / self.cfg.pre_slowdown_speed,
                            text=s.text, gender=s.gender, speaker_id=s.speaker_id,
                        )
                        for s in segments
                    ]

                self.on_progress("Transcript", 1.0, f"Đã nạp {len(segments)} dòng phụ đề có sẵn")
            elif self.cfg.silent_video_ai_script:
                self.on_progress(
                    "Transcript", 0.0,
                    "🎬 Video không có lời thoại - AI đang xem video để viết kịch bản...",
                )
                api_keys = list(self.cfg.gemini_api_keys or [])
                if self.cfg.gemini_api_key:
                    api_keys.append(self.cfg.gemini_api_key)
                if not api_keys:
                    raise RuntimeError(
                        "Chế độ 'Video không có lời thoại - AI viết kịch bản' cần ít nhất 1 Gemini API key "
                        "(xem https://aistudio.google.com/apikey)."
                    )
                from core.translate import generate_script_from_video
                segments = generate_script_from_video(
                    source_video, self.cfg.target_lang, api_keys,
                    model=self.cfg.gemini_model or "gemini-3.6-flash",
                    narration_style=self.cfg.silent_video_narration_style,
                    progress_cb=self._progress("Transcript"),
                )
                self._is_silent_video_script = True
                self.on_progress("Transcript", 1.0, f"✓ AI đã viết xong kịch bản ({len(segments)} đoạn)")
            else:
                self.on_progress("Transcript", 0.0, "Bắt đầu tách thoại...")
                segments = transcribe_video(
                    source_video,
                    model_size=self.cfg.whisper_model,
                    device=self.cfg.device,
                    progress_cb=self._progress("Transcript"),
                )
            orig_srt = save_srt(segments, os.path.join(self.cfg.work_dir, "original.srt"))

            # 1b. (Tuỳ chọn) Tự nhận diện Nam/Nữ / từng nhân vật cho mỗi câu thoại. Ưu
            # tiên nhận diện theo KHẨU HÌNH/khuôn mặt (chính xác hơn) nếu bật; nếu không,
            # fallback về nhận diện theo pitch thuần (kém chính xác hơn khi nhiều nhân
            # vật/nhiễu nhưng nhẹ, không cần xử lý hình ảnh). PHẢI chạy TRƯỚC Translate/
            # merge (dùng đúng segments với timestamp còn nguyên bản). BỎ QUA hoàn toàn
            # khi silent_video_ai_script: video không có thoại gốc nên không có pitch/
            # khẩu hình THẬT nào để nhận diện - giọng đọc dùng đúng lựa chọn Nam/Nữ mặc
            # định trên UI như bình thường.
            if self.cfg.do_dubbing and self.cfg.detect_speaker_by_face and not self._is_silent_video_script:
                self.on_progress("Transcript", 0.0, "Đang nhận diện nhân vật theo khẩu hình...")
                try:
                    from core.face_speaker_detect import detect_speakers_by_face
                    segments = detect_speakers_by_face(
                        source_video, segments, n_speakers=self.cfg.n_speakers_expected,
                        progress_cb=self._progress("Transcript"),
                    )
                except Exception as e:
                    self.on_progress(
                        "Transcript", 1.0,
                        f"⚠ Không nhận diện được theo khẩu hình ({e}) - dùng 1 giọng mặc định cho cả video",
                    )
            elif self.cfg.do_dubbing and self.cfg.detect_speaker_gender and not self._is_silent_video_script:
                self.on_progress("Transcript", 0.0, "Đang nhận diện giọng Nam/Nữ...")
                try:
                    from core.gender_detect import detect_speaker_gender
                    segments = detect_speaker_gender(
                        source_video, segments, progress_cb=self._progress("Transcript"),
                    )
                except Exception as e:
                    self.on_progress(
                        "Transcript", 1.0,
                        f"⚠ Không nhận diện được Nam/Nữ ({e}) - dùng 1 giọng mặc định cho cả video",
                    )

            # 2. Ghép nhịp lời dẫn - áp dụng cho CẢ 2 trường hợp: tự dịch lẫn dùng file
            # .srt có sẵn do người dùng tự nạp vào. Lý do: file .srt (dù tự tách thoại
            # hay do người dùng chuẩn bị sẵn từ nguồn khác - fansub, caption có sẵn...)
            # đều có thể bị cắt vụn theo quãng lặng/điểm cắt gốc, KHÔNG phải ranh giới
            # câu/ý trọn vẹn. Ghép TRƯỚC khi dịch (nếu cần dịch) để model nhận đúng khung
            # giờ THẬT (tránh bị ép ngắn giả tạo theo khung giờ vụn); còn nếu dùng file
            # .srt có sẵn (bỏ qua dịch), ghép NGAY TRÊN CHÍNH văn bản đích đó, để khỏi
            # phải tự canh/gộp tay trước khi nạp vào - bước fit_text_to_timing/tách hiển
            # thị phía sau vẫn tự lo phần rút gọn/tách dòng cho khớp timeline như thường.
            if self.cfg.merge_narration:
                self.on_progress("Translate", 0.0, "Đang ghép nhịp lời dẫn...")
                segments = merge_segments_for_narration(
                    segments,
                    min_block_sec=self.cfg.merge_min_block_sec,
                    max_block_sec=self.cfg.merge_max_block_sec,
                    hard_cap_sec=self.cfg.merge_hard_cap_sec,
                    gap_break_sec=self.cfg.merge_gap_break_sec,
                    progress_cb=self._progress("Translate"),
                )

            # 3. Translate (BỎ QUA nếu dùng phụ đề có sẵn, HOẶC vừa dùng kịch bản do AI
            # xem video viết thẳng - coi text trong đó đã là ngôn ngữ đích, dùng thẳng
            # không dịch lại)
            if self.cfg.input_srt_path or self._is_silent_video_script:
                self.on_progress(
                    "Translate", 1.0,
                    "Bỏ qua dịch (kịch bản AI đã ở ngôn ngữ đích)" if self._is_silent_video_script
                    else "Bỏ qua dịch (đang dùng phụ đề có sẵn)",
                )
                translated = segments
            else:
                self.on_progress("Translate", 0.2, "Bắt đầu dịch...")
                self._video_context_result: dict = {}  # se duoc translate_segments() tu do ket qua
                                                        # phan tich ngu canh vao (kem note_title/
                                                        # note_description/note_hashtags) - dung ghi
                                                        # NOTE.txt sau export, KHONG ton them luot goi API.
                translated = translate_segments(
                    segments,
                    self.cfg.source_lang,
                    self.cfg.target_lang,
                    method=self.cfg.translation_method,
                    progress_cb=self._progress("Translate"),
                    gemini_api_key=self.cfg.gemini_api_key,
                    gemini_api_keys=self.cfg.gemini_api_keys,
                    gemini_model=self.cfg.gemini_model,
                    grok_api_keys=self.cfg.grok_api_keys,
                    grok_model=self.cfg.grok_translate_model,
                    content_persona=self.cfg.content_persona,
                    gemini_fastapi_base_url=self.cfg.gemini_fastapi_base_url,
                    gemini_fastapi_api_key=self.cfg.gemini_fastapi_api_key,
                    gemini_fastapi_model=self.cfg.gemini_fastapi_model,
                    gemini_webapi_secure_1psid=self.cfg.gemini_webapi_secure_1psid,
                    gemini_webapi_secure_1psidts=self.cfg.gemini_webapi_secure_1psidts,
                    gemini_webapi_proxy=self.cfg.gemini_webapi_proxy,
                    gemini_webapi_model=self.cfg.gemini_webapi_model,
                    cliproxy_base_url=self.cfg.cliproxy_base_url,
                    cliproxy_api_key=self.cfg.cliproxy_api_key,
                    cliproxy_model=self.cfg.cliproxy_model,
                    narrative_style=self.cfg.narrative_style,
                    audience=self.cfg.audience,
                    speaking_speed=self.cfg.speaking_speed,
                    creativity=self.cfg.creativity,
                    hook_level=self.cfg.hook_level,
                    batch_size=self.cfg.translate_batch_size,
                    context_output=self._video_context_result,
                )

            # Lưu bản dịch trong memory để tạo tên folder + NOTE.txt sau khi export.
            self._translated_segments = translated

            # 3a. Đo tốc độ đọc THỰC TẾ của đúng engine/giọng sẽ dùng (thay cho bảng
            # CHARS_PER_SEC tĩnh) - chuyển lên đây, TRƯỚC bước rewrite/retime bên dưới
            # (trước đây bước đo này nằm mãi trong "3. Voice", chạy SAU retime_segments -
            # khiến retime phải đoán mò theo bảng chung chung, lệch với tốc độ giọng THẬT
            # sẽ dùng để đọc -> đây chính là nguyên nhân khiến gần như CẢ VIDEO cùng lúc
            # bị thiếu giờ ở bước TTS/fit_segments_to_timing về sau, dù retime_segments đã
            # canh "vừa khít" theo tính toán RIÊNG của chính nó).
            cps_override = None
            if self.cfg.do_dubbing and self.cfg.calibrate_speech_rate_cps:
                self.on_progress("Translate", 0.0, "Đang đo tốc độ đọc thực tế của giọng...")
                from core.tts import measure_actual_cps, CALIBRATION_SAMPLE_TEXT
                sample_text = CALIBRATION_SAMPLE_TEXT.get(
                    self.cfg.target_lang,
                    "This is a calibration sentence used to measure the actual speaking rate of this voice.",
                )
                cps_override = measure_actual_cps(
                    sample_text, self.cfg.target_lang,
                    engine=self.cfg.tts_engine,
                    voice_name=self.cfg.voice_name,
                    profiles_dir=self.cfg.voice_profiles_dir,
                    clone_device=self.cfg.clone_device,
                    speech_rate=self.cfg.speech_rate,
                    omnivoice_instruct=self.cfg.omnivoice_instruct,
                    omnivoice_device=self.cfg.omnivoice_device,
                    omnivoice_num_step=self.cfg.omnivoice_num_step,
                    omnivoice_speed=self.cfg.omnivoice_speed,
                )
                if cps_override:
                    self.on_progress("Translate", 0.0, f"Tốc độ đọc thực tế đo được: {cps_override:.1f} ký tự/giây")
                else:
                    self.on_progress("Translate", 0.0, "⚠ Không đo được tốc độ đọc thực tế - dùng bảng ước lượng mặc định")

            # 3b. ĐƠN GIẢN HOÁ: thay vì "dịch xong rồi mới tìm cách nhét vừa khung giờ"
            # (dễ phải cắt/tăng tốc như trước), giờ cho AI biết NGAY ngân sách ký tự của
            # từng câu (tính từ tốc độ đọc THẬT × thời lượng cue gốc) khi viết lại - để
            # AI tự viết súc tích, tự nhiên, vừa khít TỪ ĐẦU. Ưu tiên GỌI THẲNG Gemini API
            # bằng key (không cần server Web2API phụ) - chỉ dùng Web2API nếu không có key nào.
            gemini_api_keys = list(self.cfg.gemini_api_keys or [])
            if self.cfg.gemini_api_key:
                gemini_api_keys.append(self.cfg.gemini_api_key)

            if self.cfg.rewrite_after_translate and (gemini_api_keys or self.cfg.gemini_fastapi_base_url):
                self.on_progress("Translate", 0.0, "Đang viết lại ngắn gọn, khớp nhịp đọc...")
                from core.rewrite_srt import (
                    rewrite_segments_gemini_api, rewrite_segments_gemini_fastapi, retime_segments,
                )
                from core.text_fit import CHARS_PER_SEC, DEFAULT_CPS, FIXED_OVERHEAD_SEC
                cps_for_budget = cps_override or CHARS_PER_SEC.get(self.cfg.target_lang, DEFAULT_CPS)
                char_budgets = [
                    max(8, int((seg.end - seg.start - FIXED_OVERHEAD_SEC) * cps_for_budget))
                    for seg in translated
                ]
                if gemini_api_keys:
                    translated = rewrite_segments_gemini_api(
                        translated, self.cfg.target_lang, api_keys=gemini_api_keys,
                        model=self.cfg.gemini_model, char_budgets=char_budgets,
                        progress_cb=self._progress("Translate"),
                    )
                else:
                    translated = rewrite_segments_gemini_fastapi(
                        translated, self.cfg.target_lang, base_url=self.cfg.gemini_fastapi_base_url,
                        api_key=self.cfg.gemini_fastapi_api_key, model=self.cfg.gemini_fastapi_model,
                        char_budgets=char_budgets, progress_cb=self._progress("Translate"),
                    )
                self.on_progress("Translate", 1.0, "Đã viết lại xong.")
                # (Không còn cần retime_segments ước lượng ở đây nữa - timeline THẬT sẽ được
                # tính SAU khi có audio thật, xem build_dubbed_track_from_real_audio ở bước Voice
                # bên dưới - chính xác 100%, không còn phải đoán trước nữa.)
            elif self.cfg.rewrite_after_translate:
                self.on_progress(
                    "Translate", 1.0,
                    "⚠ Bỏ qua bước viết lại ngắn gọn: cần ít nhất 1 Gemini API key "
                    "(gemini_api_keys) hoặc Gemini Web2API (gemini_fastapi_base_url) để dùng bước này.",
                )

            # 3a. Tự động chèn câu CTA cuối cùng (nếu cấu hình) - NGAY SAU khi dịch/viết
            # lại xong, TRƯỚC khi lồng tiếng, để nó đi qua đúng luồng như mọi câu khác
            # (đo tốc độ đọc thật, xếp timeline theo audio thật, tự kéo dài đuôi video
            # nếu cần - không cần xử lý riêng gì thêm).
            if self.cfg.outro_cta_text and self.cfg.outro_cta_text.strip() and translated:
                from dataclasses import replace as _replace_seg
                last = translated[-1]
                cta_start = last.end + self.cfg.outro_cta_gap_sec
                translated = translated + [
                    _replace_seg(
                        last, index=last.index + 1, start=cta_start,
                        end=cta_start + 2.0,  # ước lượng tạm - sẽ được ghi đè bằng độ dài audio thật ở bước Voice
                        text=self.cfg.outro_cta_text.strip(),
                    )
                ]
                self.on_progress("Translate", 1.0, f"Đã thêm câu CTA cuối video: \"{self.cfg.outro_cta_text.strip()}\"")

            # 3. Voice (dubbing) - tuỳ chọn. Tính TRƯỚC bước lưu phụ đề (thay vì sau như
            # trước đây), vì khi sync_subtitle_to_dub=True, phụ đề hiển thị sẽ cần dùng
            # đúng bản văn bản đã rút gọn cho giọng đọc bên dưới.
            current_video = source_video
            dub_segments = translated
            subtitle_segments = translated

            if self.cfg.do_dubbing:
                self.on_progress("Voice", 0.0, "Đang tạo giọng đọc...")
                audio_dir = os.path.join(self.cfg.work_dir, "tts_segments")
                if self.cfg.tts_engine == "clone" and not self.cfg.voice_name:
                    raise ValueError("tts_engine='clone' yêu cầu phải chọn voice_name (voice profile đã lưu)")

                # (Đã dọn: llm_shorten_fn không còn dùng tới - từ khi đổi fit_segments_to_timing
                # sang retime_segments, không còn bước nào cần "viết lại câu để cắt ngắn" nữa.)


                # FIX TRIỆT ĐỂ nạn cắt chữ: KHÔNG còn ước lượng timeline trước khi có audio
                # nữa (mọi ước lượng trước đều có sai số nhỏ so với audio thật, dẫn tới phải
                # cắt khi ghép). Giờ ĐẢO THỨ TỰ - sinh audio TRƯỚC (dùng timeline gốc/dịch chỉ
                # để chọn giọng nam/nữ theo đúng người nói, KHÔNG ảnh hưởng nội dung đọc), rồi
                # xếp timeline THẬT dựa trên độ dài audio đã sinh ra (build_dubbed_track_from_
                # real_audio, core/tts.py) - vị trí đặt luôn khớp 100% với clip thật.
                audio_paths = synthesize_segments(
                    translated, self.cfg.target_lang, audio_dir,
                    engine=self.cfg.tts_engine,
                    voice_name=self.cfg.voice_name,
                    profiles_dir=self.cfg.voice_profiles_dir,
                    clone_device=self.cfg.clone_device,
                    speech_rate=self.cfg.speech_rate,
                    voice_gender=self.cfg.voice_gender,
                    vieneu_voice_male=self.cfg.vieneu_voice_male,
                    vieneu_voice_female=self.cfg.vieneu_voice_female,
                    edge_voice_male=self.cfg.edge_voice_male,
                    edge_voice_female=self.cfg.edge_voice_female,
                    omnivoice_instruct=self.cfg.omnivoice_instruct,
                    omnivoice_instruct_male=self.cfg.omnivoice_instruct_male,
                    omnivoice_instruct_female=self.cfg.omnivoice_instruct_female,
                    omnivoice_device=self.cfg.omnivoice_device,
                    omnivoice_num_step=self.cfg.omnivoice_num_step,
                    omnivoice_speed=self.cfg.omnivoice_speed,
                    progress_cb=self._progress("Voice"),
                )

                self.on_progress("Voice", 0.0, "Đang xếp timeline theo audio thật...")
                from core.export import probe_duration as _probe_for_pace, extend_video_tail as _extend_tail
                video_duration_before_dub = _probe_for_pace(source_video)
                dub_track, dub_segments = build_dubbed_track_from_real_audio(
                    translated, audio_paths,
                    os.path.join(self.cfg.work_dir, "dubbed_track.wav"),
                    min_gap_sec=self.cfg.rewrite_min_gap_sec, max_gap_sec=self.cfg.rewrite_max_gap_sec,
                    keep_original_start=True,
                    # KHÔNG còn ép trần theo video gốc mặc định nữa (total_duration_sec=None
                    # khi extend_video_tail_if_longer=True) - để audio chạy đúng độ dài THẬT
                    # cần có (vd người dùng chủ động thêm lời kêu gọi "để lại bình luận, bấm
                    # theo dõi kênh" ở cuối, dài hơn video gốc còn lại) - KHÔNG tăng tốc dồn
                    # dập, KHÔNG cắt chữ. Nếu audio dài hơn video, kéo dài ĐUÔI video (giữ
                    # khung hình cuối) cho khớp - xem đoạn xử lý ngay dưới đây.
                    total_duration_sec=(None if self.cfg.extend_video_tail_if_longer else video_duration_before_dub),
                    max_speedup=self.cfg.dub_max_speedup,
                    progress_cb=self._progress("Voice"),
                )

                # Audio dài hơn video gốc (vd thêm lời kêu gọi hành động ở cuối) -> KÉO DÀI
                # ĐUÔI video (lặp khung hình cuối, đứng yên) cho khớp với đúng audio, thay vì
                # để mux cắt mất phần audio dư hoặc phải nén/tăng tốc dồn dập.
                if self.cfg.extend_video_tail_if_longer and dub_segments:
                    dub_total = dub_segments[-1].end
                    extra_needed = dub_total - video_duration_before_dub
                    if extra_needed > 0.15:
                        self.on_progress(
                            "Voice", 0.0,
                            f"Audio dài hơn video {extra_needed:.2f}s (vd lời kêu gọi cuối video) "
                            f"- đang kéo dài đuôi video cho khớp...",
                        )
                        extended_path = os.path.join(self.cfg.work_dir, "video_extended_tail.mp4")
                        source_video = _extend_tail(
                            source_video, extended_path, extra_needed,
                            progress_cb=self._progress("Voice"),
                        )
                        current_video = source_video  # các bước sau (burn phụ đề, watermark, mux) dùng đúng video ĐÃ kéo dài

                # Phụ đề hiển thị dùng ĐÚNG timeline THẬT vừa xếp, để khớp với giọng đọc.
                if self.cfg.sync_subtitle_to_dub:
                    subtitle_segments = dub_segments

                # (Tuỳ chọn) Biến đổi giọng đọc: đổi cao độ (pitch) và/hoặc tốc độ đọc
                # (speed) của CẢ track lồng tiếng - áp dụng SAU khi ghép xong, TRƯỚC khi
                # mux vào video, để không ảnh hưởng tới bước tính toán khớp thời lượng.
                if abs(self.cfg.voice_pitch_semitones or 0.0) > 0.01 or abs((self.cfg.voice_speed or 1.0) - 1.0) > 0.01:
                    self.on_progress("Voice", 0.0, "Đang biến đổi giọng đọc (cao độ/tốc độ)...")
                    transformed_track = os.path.join(self.cfg.work_dir, "dubbed_track_transformed.mp3")
                    dub_track = apply_voice_transform(
                        dub_track, transformed_track,
                        pitch_semitones=self.cfg.voice_pitch_semitones,
                        speed=self.cfg.voice_speed,
                        progress_cb=self._progress("Voice"),
                    )

                dubbed_video = os.path.join(self.cfg.work_dir, "dubbed.mp4")
                current_video = mux_audio_advanced(
                    current_video, dub_track, dubbed_video,
                    keep_original_audio=self.cfg.keep_original_audio_in_dub,
                    dub_volume=self.cfg.dub_volume,
                    background_music_path=self.cfg.background_music_path,
                    bg_music_volume=self.cfg.bg_music_volume,
                    progress_cb=self._progress("Voice"),
                )
            elif self.cfg.remove_original_audio or self.cfg.background_music_path:
                # Không lồng tiếng, nhưng vẫn cần tắt audio gốc và/hoặc thêm nhạc nền riêng.
                self.on_progress("Voice", 0.0, "Đang xử lý audio (tắt tiếng gốc / thêm nhạc nền)...")
                muxed_video = os.path.join(self.cfg.work_dir, "audio_swapped.mp4")
                current_video = mux_audio_advanced(
                    current_video, None, muxed_video,
                    keep_original_audio=not self.cfg.remove_original_audio,
                    background_music_path=self.cfg.background_music_path,
                    bg_music_volume=self.cfg.bg_music_volume,
                    progress_cb=self._progress("Voice"),
                )
            else:
                self.on_progress("Voice", 1.0, "Bỏ qua lồng tiếng")

            # 4. Subtitles (tạo file srt đã dịch - hoặc đã rút gọn khớp giọng đọc)
            self.on_progress("Subtitles", 0.0, "Đang tạo file phụ đề...")

            # Ép phụ đề HIỂN THỊ ngắn lại: câu dài được TÁCH thành nhiều dòng hiện lần
            # lượt trong đúng khung giờ gốc, KHÔNG bớt/đổi nội dung (khác bước rút gọn
            # cho TTS ở trên) - tránh phụ đề dài tràn dòng nhìn xấu video.
            if self.cfg.split_long_subtitles:
                subtitle_segments = split_segments_for_display(
                    subtitle_segments, self.cfg.target_lang,
                    max_chars=self.cfg.max_subtitle_chars,
                    speech_rate=self.cfg.speech_rate,
                )

            translated_srt = save_srt(subtitle_segments, os.path.join(self.cfg.work_dir, "translated.srt"))
            self.srt_path = translated_srt
            self.on_progress("Subtitles", 1.0, "Đã tạo phụ đề dịch")

            # 5. Export - làm mờ sub gốc + burn phụ đề mới + lật/filter/tỉ lệ/độ phân giải + watermark
            self.on_progress("Export", 0.0, "Đang xuất video...")

            # 5a. TỰ ĐỘNG dò + XOÁ (delogo, không chỉ blur) logo/watermark và phụ đề
            # HARDSUB gốc của kênh nguồn - PHẢI chạy TRƯỚC khi burn phụ đề mới, để
            # không xoá luôn chữ vừa thêm vào. Toạ độ tự dò được tính trên khung hình
            # GỐC (chưa lật), nên phải chạy TRƯỚC bước lật video bên dưới.
            if self.cfg.auto_remove_original_logo:
                if self.cfg.watermark_removal_engine == "ai":
                    self.on_progress("Export", 0.0, "Đang xoá logo/watermark gốc bằng AI...")
                    try:
                        from core.ai_watermark_remove import ai_remove_watermark_video, is_available
                    except ModuleNotFoundError as e:
                        self.on_progress(
                            "Export", 1.0,
                            f"⚠ Chưa có module core/ai_watermark_remove.py ({e}) - bỏ qua bước xoá logo bằng AI. "
                            "Đổi 'Cách xoá logo/watermark' về 'delogo' (ffmpeg) trong Cài đặt nếu muốn xoá logo.",
                        )
                    else:
                        if not is_available():
                            self.on_progress(
                                "Export", 1.0,
                                "⚠ Chưa cài đủ thư viện cho chế độ AI (xem core/ai_watermark_remove.py) - bỏ qua bước xoá logo.",
                            )
                        else:
                            ai_logo_video = os.path.join(self.cfg.work_dir, "ai_delogo.mp4")
                            current_video = ai_remove_watermark_video(
                                current_video, ai_logo_video, detection_prompt="watermark",
                                progress_cb=self._progress("Export"),
                            )
                else:
                    self.on_progress("Export", 0.0, "Đang tự động dò logo/watermark gốc...")
                    from core.export import detect_logo_region, delogo_region
                    logo_box = detect_logo_region(current_video, progress_cb=self._progress("Export"))
                    if logo_box:
                        x, y, w, h = logo_box
                        self.on_progress("Export", 0.0, f"Đã tìm thấy logo tại ({x},{y}) kích thước {w}x{h} - đang xoá...")
                        delogoed_video = os.path.join(self.cfg.work_dir, "delogo_original.mp4")
                        current_video = delogo_region(
                            current_video, delogoed_video, x, y, w, h,
                            progress_cb=self._progress("Export"),
                        )
                    else:
                        self.on_progress("Export", 1.0, "⚠ Không dò được logo/watermark nào đủ tin cậy - bỏ qua bước này.")

            if self.cfg.auto_remove_original_subtitle:
                if self.cfg.watermark_removal_engine == "ai":
                    self.on_progress("Export", 0.0, "Đang xoá phụ đề gốc bằng AI...")
                    try:
                        from core.ai_watermark_remove import ai_remove_watermark_video, is_available
                    except ModuleNotFoundError as e:
                        self.on_progress(
                            "Export", 1.0,
                            f"⚠ Chưa có module core/ai_watermark_remove.py ({e}) - bỏ qua bước xoá phụ đề gốc bằng AI. "
                            "Đổi 'Cách xoá logo/watermark' về 'delogo' (ffmpeg) trong Cài đặt, hoặc tự vẽ vùng che thủ công.",
                        )
                    else:
                        if not is_available():
                            self.on_progress(
                                "Export", 1.0,
                                "⚠ Chưa cài đủ thư viện cho chế độ AI (xem core/ai_watermark_remove.py) - bỏ qua bước xoá phụ đề gốc.",
                            )
                        else:
                            ai_sub_video = os.path.join(self.cfg.work_dir, "ai_desub.mp4")
                            current_video = ai_remove_watermark_video(
                                current_video, ai_sub_video, detection_prompt="subtitle text at the bottom",
                                progress_cb=self._progress("Export"),
                            )
                else:
                    self.on_progress("Export", 0.0, "Đang tự động dò phụ đề (hardsub) gốc...")
                    from core.export import detect_hardsub_band, delogo_region
                    sub_box = detect_hardsub_band(current_video, progress_cb=self._progress("Export"))
                    if sub_box:
                        x, y, w, h = sub_box
                        self.on_progress("Export", 0.0, f"Đã tìm thấy phụ đề gốc tại ({x},{y}) kích thước {w}x{h} - đang xoá...")
                        desub_video = os.path.join(self.cfg.work_dir, "delogo_hardsub.mp4")
                        current_video = delogo_region(
                            current_video, desub_video, x, y, w, h,
                            progress_cb=self._progress("Export"),
                        )
                    else:
                        self.on_progress("Export", 1.0, "⚠ Không dò được phụ đề gốc nào đủ tin cậy - bỏ qua bước này.")

            # 5a-2. Làm mờ vùng phụ đề GỐC theo TỌA ĐỘ TỰ CHỌN THỦ CÔNG (nếu người dùng
            # tự vẽ vùng thay vì dùng chế độ tự động ở trên) - giữ lại làm phương án dự
            # phòng cho trường hợp tự động dò không đủ tin cậy (vd nền phức tạp).
            if self.cfg.blur_original_subtitle and self.cfg.blur_regions:
                for i, (x, y, w, h) in enumerate(self.cfg.blur_regions):
                    blurred_video = os.path.join(self.cfg.work_dir, f"blurred_sub_{i}.mp4")
                    current_video = blur_region(
                        current_video, blurred_video, x, y, w, h,
                        strength=self.cfg.blur_strength,
                        progress_cb=self._progress("Export"),
                    )

            # 5b. Lật video (nếu bật) - PHẢI chạy TRƯỚC khi burn phụ đề mới, nếu không
            # chữ phụ đề vừa ghi vào cũng sẽ bị lật ngược/lật gương theo, đọc không được.
            if self.cfg.flip_horizontal or self.cfg.flip_vertical:
                flipped_video = os.path.join(self.cfg.work_dir, "flipped.mp4")
                current_video = flip_video(
                    current_video, flipped_video,
                    horizontal=self.cfg.flip_horizontal,
                    vertical=self.cfg.flip_vertical,
                    progress_cb=self._progress("Export"),
                )

            if self.cfg.do_subtitles:
                subbed_video = os.path.join(self.cfg.work_dir, "subbed.mp4")
                current_video = burn_subtitles(
                    current_video, translated_srt, subbed_video,
                    preset=self.cfg.subtitle_preset,
                    font_size=self.cfg.font_size,
                    display_mode=self.cfg.subtitle_display_mode,
                    font_name=self.cfg.subtitle_font,
                    position=self.cfg.subtitle_position,
                    x_frac=self.cfg.subtitle_pos_x_frac,
                    y_frac=self.cfg.subtitle_pos_y_frac,
                    box_enabled=self.cfg.subtitle_box_enabled,
                    box_color=self.cfg.subtitle_box_color,
                    box_opacity=self.cfg.subtitle_box_opacity,
                    effect=self.cfg.subtitle_effect,
                    progress_cb=self._progress("Export"),
                )

            # 5c. Filter hình ảnh (blur/sharpen/brightness/contrast/saturation)
            has_filter = (
                self.cfg.filter_blur > 0 or self.cfg.filter_sharpen > 0
                or self.cfg.filter_brightness != 0.0 or self.cfg.filter_contrast != 1.0
                or self.cfg.filter_saturation != 1.0
            )
            if has_filter:
                filtered_video = os.path.join(self.cfg.work_dir, "filtered.mp4")
                current_video = apply_filters(
                    current_video, filtered_video,
                    blur=self.cfg.filter_blur, sharpen=self.cfg.filter_sharpen,
                    brightness=self.cfg.filter_brightness, contrast=self.cfg.filter_contrast,
                    saturation=self.cfg.filter_saturation,
                    progress_cb=self._progress("Export"),
                )

            # 5d. Tỉ lệ khung hình
            if self.cfg.aspect_ratio and self.cfg.aspect_ratio != "original":
                ratio_video = os.path.join(self.cfg.work_dir, "ratio.mp4")
                current_video = change_aspect_ratio(
                    current_video, ratio_video, ratio=self.cfg.aspect_ratio,
                    mode=self.cfg.aspect_mode, progress_cb=self._progress("Export"),
                )

            # 5e. Độ phân giải
            if self.cfg.resolution and self.cfg.resolution != "original":
                res_video = os.path.join(self.cfg.work_dir, "resized.mp4")
                current_video = change_resolution(
                    current_video, res_video, resolution=self.cfg.resolution,
                    progress_cb=self._progress("Export"),
                )

            # 5f. Watermark: LOGO (ảnh) và CHỮ (cố định/chạy) hoàn toàn ĐỘC LẬP - có thể
            # bật CẢ HAI cùng lúc (logo trước, chữ đè lên sau), chỉ 1 trong 2, hoặc không
            # bật cái nào. (Trước đây if/elif loại trừ nhau nên chỉ áp dụng được 1 loại.)
            final_video = os.path.join(self.cfg.work_dir, "final_output.mp4")

            wm_steps: list[str] = []
            if self.cfg.do_watermark_logo and self.cfg.watermark_logo_path:
                wm_steps.append("logo")
            if self.cfg.do_watermark_text and self.cfg.watermark_text_style == "moving_text":
                wm_steps.append("moving_text")
            elif self.cfg.do_watermark_text:
                wm_steps.append("text")

            if wm_steps:
                for idx, step in enumerate(wm_steps):
                    is_last = idx == len(wm_steps) - 1
                    step_out = final_video if is_last else os.path.join(
                        self.cfg.work_dir, f"watermark_{step}_{idx}.mp4"
                    )
                    if step == "logo":
                        current_video = add_watermark_image(
                            current_video, self.cfg.watermark_logo_path, step_out,
                            position=self.cfg.watermark_position,
                            x_frac=self.cfg.watermark_x_frac, y_frac=self.cfg.watermark_y_frac,
                            scale_width_frac=self.cfg.watermark_scale_frac,
                            opacity=self.cfg.watermark_logo_opacity,
                            progress_cb=self._progress("Export"),
                        )
                    elif step == "moving_text":
                        current_video = add_moving_watermark_text(
                            current_video, self.cfg.watermark_text, step_out,
                            opacity=self.cfg.watermark_text_opacity,
                            font_size=self.cfg.watermark_font_size,
                            speed=self.cfg.watermark_speed,
                            pattern=self.cfg.watermark_pattern,
                            progress_cb=self._progress("Export"),
                        )
                    else:  # "text" cố định
                        current_video = add_watermark(
                            current_video, self.cfg.watermark_text, step_out,
                            opacity=self.cfg.watermark_text_opacity,
                            font_size=self.cfg.watermark_font_size,
                            progress_cb=self._progress("Export"),
                        )
            elif current_video != final_video:
                import shutil
                if current_video == source_video:
                    shutil.copy(current_video, final_video)
                else:
                    shutil.move(current_video, final_video)
                current_video = final_video

            # 6. (Tuỳ chọn) Tăng tốc lại video output cuối cùng SAU khi đã ghép xong, để bù
            # lại phần đã làm chậm ở bước 0 - nhịp phim gần với tự nhiên hơn. Áp dụng lên
            # ĐÚNG file final_output (đã có phụ đề/watermark nếu bật), rồi ghi đè lại chính
            # file đó để không phải đổi tên/đường dẫn trả về cho phần còn lại của app.
            if self.cfg.do_dubbing and self.cfg.post_speedup_speed and self.cfg.post_speedup_speed != 1.0:
                self.on_progress(
                    "Export", 0.0,
                    f"Đang tăng tốc video output lên {self.cfg.post_speedup_speed}x...",
                )
                from core.speed_adjust import change_video_speed
                sped_path = os.path.join(self.cfg.work_dir, "final_output_sped.mp4")
                change_video_speed(
                    current_video, self.cfg.post_speedup_speed, sped_path,
                    progress_cb=self._progress("Export"),
                )
                import shutil
                shutil.move(sped_path, final_video)
                current_video = final_video

                # QUAN TRỌNG: phụ đề đã BURN CỨNG vào khung hình (final_video) tự động
                # co giãn đúng theo post_speedup_speed vì change_video_speed đổi tốc độ
                # CẢ khung hình lẫn tiếng cùng lúc trong 1 lệnh ffmpeg. Nhưng file
                # translated.srt (bản RỜI, đã lưu ở bước 4 - TRƯỚC bước tăng tốc này)
                # vẫn đang ở timeline CŨ (đã làm chậm ở bước 0, chưa tăng tốc lại) - nếu
                # không co giãn lại, ai đó nạp riêng file .srt này vào video final_output
                # (vd để có phụ đề mềm thay vì chỉ có bản burn cứng) sẽ bị lệch giờ đúng
                # theo tỉ lệ post_speedup_speed. Co giãn lại và ghi đè cùng đường dẫn cũ.
                if self.srt_path and os.path.exists(self.srt_path):
                    try:
                        srt_segments = parse_srt(self.srt_path)
                        rescaled = [
                            SubtitleSegment(
                                index=s.index,
                                start=s.start / self.cfg.post_speedup_speed,
                                end=s.end / self.cfg.post_speedup_speed,
                                text=s.text, gender=s.gender, speaker_id=s.speaker_id,
                            )
                            for s in srt_segments
                        ]
                        save_srt(rescaled, self.srt_path)
                    except Exception as e:
                        self.on_progress(
                            "Export", 1.0,
                            f"⚠ Không co giãn lại được translated.srt theo tốc độ mới ({e}) - "
                            f"file .srt rời có thể lệch giờ so với video output, phụ đề BURN CỨNG trong video vẫn đúng.",
                        )

            self.result_video = current_video
            self.on_progress("Export", 1.0, "Hoàn tất!")

            # Intro Hook (tuỳ chọn): thêm SAU KHI video chính đã xuất xong hoàn chỉnh
            # (đã lồng tiếng/phụ đề/watermark) - cắt đoạn AI chọn TỪ CHÍNH video này,
            # nên phải chạy ở đây, sau dòng self.result_video = current_video ở trên,
            # và TRƯỚC cleanup/_package_final_output.
            self._maybe_add_hook_intro()

            if self.cfg.cleanup_intermediate_files:
                self._cleanup_intermediates()

            # Đóng gói output sau cleanup: chỉ giữ video hoàn chỉnh + SRT + NOTE.txt.
            self._package_final_output()

            append_history(self.cfg.history_dir or self.cfg.work_dir, JobRecord(
                timestamp=time.time(),
                input_video=self.cfg.video_path,
                output_video=self.result_video or "",
                srt_path=self.srt_path or "",
                source_lang=self.cfg.source_lang,
                target_lang=self.cfg.target_lang,
                subtitles=self.cfg.do_subtitles,
                dubbing=self.cfg.do_dubbing,
                watermark=(self.cfg.do_watermark_text or self.cfg.do_watermark_logo),
                status="done",
            ))

        except Exception as e:
            self.error = f"{e}\n{traceback.format_exc()}"
            self.on_progress("Error", 0.0, str(e))
            append_history(self.cfg.history_dir or self.cfg.work_dir, JobRecord(
                timestamp=time.time(),
                input_video=self.cfg.video_path,
                output_video="",
                srt_path=self.srt_path or "",
                source_lang=self.cfg.source_lang,
                target_lang=self.cfg.target_lang,
                subtitles=self.cfg.do_subtitles,
                dubbing=self.cfg.do_dubbing,
                watermark=(self.cfg.do_watermark_text or self.cfg.do_watermark_logo),
                status="error",
                error_msg=str(e),
            ))
            raise
