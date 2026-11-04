"""
core/narration_merge.py
Ghép các đoạn phụ đề (subtitle cue) NGẮN, LIÊN TỤC lại thành từng "khối lời
dẫn" (narration block) để giọng đọc nghe liền mạch, có nhấn nhá/nhịp ngắt tự
nhiên - đúng kiểu 1 người dẫn chuyện thật (review phim, thuyết minh) đọc,
thay vì tạo audio riêng cho từng cue 1-2 giây rời rạc.

TẠI SAO CẦN BƯỚC NÀY:
Mỗi dòng trong translated.srt vốn là 1 đoạn cắt theo VAD (voice activity
detection) của whisper khi tách thoại (core/transcribe.py) - đây là điểm cắt
theo QUÃNG LẶNG trong audio gốc, KHÔNG phải điểm cắt theo câu/ý trọn vẹn theo
ngữ pháp. Có những câu bị cắt làm 2-3 dòng (dòng trước không có dấu câu kết
thúc, ý còn dang dở), có dòng chỉ 1-2 từ ("Đi mất", "thời điểm quan trọng").
Nếu tạo audio riêng cho từng dòng như vậy, giọng đọc nghe bị ngắt cụt, dồn
dập, không giống cách 1 narrator thật kể chuyện.

CÁCH GHÉP:
  - CHỈ ghép các đoạn LIỀN NHAU về thời gian: khoảng trống giữa 2 đoạn nhỏ
    hơn `gap_break_sec`. Khoảng trống lớn hơn mức này được coi là 1 NHỊP DỪNG
    THẬT đã có sẵn trong lời kể gốc (đổi cảnh, đổi ý...) -> LUÔN giữ làm điểm
    ngắt khối, không ghép qua - đây chính là chỗ tạo "nhấn nhá" tự nhiên,
    không phải ghép tất cả thành 1 khối dài vô tận.
  - Gộp dần tới khi khối đạt đủ `min_block_sec` (đủ dài để nghe trọn ý, tránh
    bị cụt lủn từng câu 1-2 giây).
  - Dừng ghép khi khối đã vượt `max_block_sec` (tránh dồn quá nhiều ý vào 1
    hơi đọc, nghe mệt/gấp) - trừ khi khối vẫn còn quá ngắn thì cho nới thêm
    tới `hard_cap_sec` (chặn cứng, tránh khối phình vô hạn nếu gặp một chuỗi
    toàn các cue rất ngắn liên tục).
  - Khi nối 2 đoạn text: nếu đoạn trước CHƯA kết thúc bằng dấu câu (. ! ?),
    nối bằng dấu PHẨY để tạo 1 nhịp ngắt nhẹ khi đọc (giống người dẫn chuyện
    ngắt hơi giữa các ý liên tiếp), thay vì đọc dính liền không ngắt nghỉ.

LƯU Ý (cập nhật): mặc định max_block_sec/hard_cap_sec đã được hạ (6.0->4.5s,
8.0->6.0s). Lý do: việc gộp cue chỉ dựa vào THỜI GIAN của bản gốc, không biết
trước bản DỊCH sẽ dài bao nhiêu ký tự - nếu gộp thành khối quá dài (6-8s) mà
câu dịch (thường dài hơn câu gốc, đặc biệt dịch sang tiếng Việt) lại nhiều chữ,
bước rút gọn ở core/text_fit.py sẽ phải cắt bớt RẤT NHIỀU (có khi mất 40-60%
nội dung) mới kịp vừa khung giờ đọc -> nghe như "thiếu chữ", mất ý. Khối ngắn
hơn giúp mật độ chữ/giây thấp hơn, bước rút gọn chỉ còn phải cắt nhẹ, giữ được
gần trọn ý hơn.

LƯU Ý (cập nhật lần 2 - fix lỗi cắt ngang giữa câu): thuật toán CŨ chỉ dừng gộp
dựa vào max_block_sec/hard_cap_sec (thời lượng thuần tuý), không biết câu đã
kết thúc hay chưa - nên có trường hợp 1 câu hoàn toàn liền mạch (gap=0 giữa các
cue, tức KHÔNG có khoảng lặng thật nào) vẫn bị chặt vụn thành 2-3 khối chỉ vì
chạm max_block_sec giữa chừng, làm mỗi khối quá ngắn để đọc/hiện phụ đề trọn ý.
Giờ ưu tiên dừng đúng tại ĐIỂM HẾT CÂU (đoạn vừa gộp kết thúc bằng dấu . ! ? …)
một khi đã đạt min_block_sec - max_block_sec KHÔNG còn chặn cứng việc gộp khi
câu vẫn đang dang dở (chưa có dấu câu kết thúc): lúc đó cứ gộp tiếp tới khi gặp
dấu câu hoặc chạm hard_cap_sec (chặn cứng tuyệt đối, phòng chuỗi cue dài không
có dấu câu). max_block_sec vẫn giữ trong chữ ký hàm để không phá vỡ chỗ gọi từ
core/pipeline.py, nhưng vai trò giờ chỉ mang tính tham khảo/dự phòng, không còn
trực tiếp quyết định điểm ngắt như trước.

LƯU Ý: đây là heuristic dựa trên THỜI LƯỢNG + KHOẢNG TRỐNG (+ dấu câu ở bản cập
nhật lần 2), không phải phân tích ngữ nghĩa/ngữ pháp thật sự (bản dịch tự động
thường thiếu dấu câu chuẩn nên không thể dựa hoàn toàn vào dấu câu để xác định
ranh giới câu). Nếu cần độ chính xác ngữ nghĩa cao hơn (vd gộp đúng câu bị cắt
dở), nên cân nhắc thêm 1 bước paraphrase/ghép câu bằng LLM trước bước này.
"""
from __future__ import annotations
from typing import Callable, List, Optional

from core.transcribe import SubtitleSegment

TERMINAL_PUNCT = (".", "!", "?", "…")


def _join_glue(prev_text: str) -> str:
    """Chọn cách nối giữa 2 đoạn được ghép để tạo nhịp ngắt tự nhiên khi đọc."""
    t = prev_text.rstrip()
    if t.endswith(TERMINAL_PUNCT) or t.endswith(","):
        return " "   # đã có dấu câu sẵn - TTS tự ngắt hơi đúng chỗ, chỉ cần khoảng trắng
    return ", "       # chưa có dấu câu - thêm dấu phẩy để tạo 1 nhịp ngắt nhẹ, tránh đọc dính liền


def merge_segments_for_narration(
    segments: List[SubtitleSegment],
    min_block_sec: float = 2.5,
    max_block_sec: float = 4.5,
    hard_cap_sec: float = 6.0,
    gap_break_sec: float = 0.5,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[SubtitleSegment]:
    if not segments:
        return []

    out: List[SubtitleSegment] = []
    block_texts = [segments[0].text.strip()]
    block_start = segments[0].start
    block_end = segments[0].end
    block_gender = segments[0].gender
    block_speaker_id = segments[0].speaker_id
    total = max(1, len(segments))

    def _flush():
        joined = block_texts[0]
        for t in block_texts[1:]:
            joined = joined.rstrip() + _join_glue(joined) + t.strip()
        out.append(SubtitleSegment(
            index=len(out) + 1, start=block_start, end=block_end, text=joined,
            gender=block_gender, speaker_id=block_speaker_id,
        ))

    for i in range(1, len(segments)):
        seg = segments[i]
        gap = seg.start - block_end
        block_dur = block_end - block_start
        would_be_dur = seg.end - block_start
        # Đoạn CUỐI CÙNG vừa được gộp vào khối đã kết thúc bằng dấu câu (. ! ? …)
        # hay chưa - đây là tín hiệu quan trọng NHẤT để quyết định điểm dừng, quan
        # trọng hơn cả max_block_sec (xem giải thích trong docstring/CẬP NHẬT bên dưới).
        ends_sentence = block_texts[-1].strip().endswith(TERMINAL_PUNCT)

        if gap >= gap_break_sec:
            merge = False                                             # nhịp dừng thật - luôn giữ
        elif seg.speaker_id and block_speaker_id and seg.speaker_id != block_speaker_id:
            merge = False                                             # khác NHÂN VẬT (dù cùng giới tính) - KHÔNG gộp
        elif seg.gender and block_gender and seg.gender != block_gender:
            merge = False                                             # đổi người nói (khác giới tính) - KHÔNG được gộp
                                                                        # dù liền nhau về thời gian, để mỗi khối chỉ có
                                                                        # đúng 1 giọng đọc, tránh 1 khối bị lẫn 2 giọng
        elif would_be_dur > hard_cap_sec:
            merge = False                                             # chặn cứng TUYỆT ĐỐI, tránh khối phình vô hạn
                                                                        # (vd gặp cả chuỗi câu KHÔNG có dấu chấm câu)
        elif block_dur >= min_block_sec and ends_sentence:
            # CẬP NHẬT (fix lỗi cắt ngang giữa câu): đã đủ dài (>= min_block_sec) VÀ
            # đoạn vừa gộp xong vừa KẾT THÚC 1 CÂU TRỌN VẸN (có dấu câu) -> đây là
            # điểm dừng TỰ NHIÊN NHẤT, dừng ở đây dù CHƯA chạm max_block_sec, để mỗi
            # khối càng khớp đúng 1 câu hoàn chỉnh càng tốt (không gộp thêm câu tiếp
            # theo vào chung 1 khối chỉ vì còn "dư chỗ" tới max_block_sec).
            merge = False
        else:
            # CÒN DANG DỞ GIỮA CÂU (đoạn vừa gộp CHƯA có dấu câu kết thúc) HOẶC khối
            # còn NGẮN HƠN min_block_sec -> LUÔN gộp tiếp, kể cả khi đã vượt quá
            # max_block_sec - vì cắt ngang giữa 1 câu (khi gap=0, tức hoàn toàn không
            # có khoảng lặng thật) luôn tệ hơn nhiều so với 1 khối hơi dài hơn dự kiến.
            # Chỉ hard_cap_sec (chặn cứng ở trên) mới thực sự ngắt trong trường hợp này.
            merge = True

        if merge:
            block_texts.append(seg.text)
            block_end = seg.end
        else:
            _flush()
            block_texts = [seg.text.strip()]
            block_start = seg.start
            block_end = seg.end
            block_gender = seg.gender
            block_speaker_id = seg.speaker_id

        if progress_cb:
            progress_cb(i / total, f"Đang ghép nhịp lời dẫn {i}/{total}")

    _flush()
    if progress_cb:
        progress_cb(1.0, f"Hoàn tất ghép nhịp - {len(segments)} câu gốc -> {len(out)} khối lời dẫn")
    return out

