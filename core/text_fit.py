"""
core/text_fit.py
Rút ngắn câu dịch để KHỚP thời lượng cho phép trước khi đưa vào TTS,
thay vì tăng tốc audio (nghe không tự nhiên, không đồng đều giữa các câu,
gây khó chịu tai cho người xem).

VẤN ĐỀ CŨ:
build_dubbed_track (core/tts.py) chỉ biết tăng tốc (atempo) hoặc cắt cụt clip
audio ĐÃ TẠO XONG khi nó dài hơn khoảng trống thời gian gốc. Với video có
nhiều câu dịch dài hơn câu gốc (rất phổ biến khi dịch sang tiếng Việt), rất
nhiều câu liên tiếp bị đẩy lên tốc độ tối đa -> nghe "dồn dập", không tự
nhiên, đặc biệt rõ ở các video dài (câu 100+ vẫn bị tăng tốc liên tục như log
bạn gửi).

GIẢI PHÁP Ở ĐÂY:
Xử lý NGAY Ở BƯỚC VĂN BẢN, trước khi tạo audio:
  1. Ước lượng thời lượng đọc của câu dịch dựa trên tốc độ đọc trung bình
     (ký tự/giây) của ngôn ngữ đích.
  2. So với khoảng trống thời gian cho phép (tính từ timestamp gốc, CÙNG công
     thức với build_dubbed_track để 2 nơi nhất quán với nhau).
  3. Nếu câu dự kiến đọc LÂU HƠN khoảng trống -> rút ngắn văn bản (bỏ từ đệm,
     cụm thừa; nếu vẫn còn dài thì cắt bớt vế câu cuối tại ranh giới từ/dấu câu
     gần nhất) TRƯỚC khi đưa vào TTS.

Sau bước này, atempo trong core/tts.py chỉ còn phải xử lý phần LỆCH NHỎ còn
sót lại (ước lượng tốc độ đọc vốn không thể chính xác 100%), nên max_speedup
mặc định cũng được hạ xuống (xem core/tts.py) - gần như không nghe ra khác biệt.

CHẤT LƯỢNG RÚT GỌN:
Rule-based (mặc định) chỉ bỏ từ đệm + cắt cụt cơ học, KHÔNG hiểu ngữ nghĩa,
nên chỉ nên coi là giải pháp "chặn dưới". Nếu bạn có sẵn 1 API LLM (Claude,
GPT...), hãy tự viết 1 hàm nhỏ gọi API đó để paraphrase câu ngắn lại mà vẫn
giữ đúng nghĩa, rồi truyền vào qua `llm_shorten_fn` - chất lượng sẽ tốt hơn
nhiều so với rule-based. Chữ ký hàm cần đúng:

    def my_llm_shorten(text: str, lang: str, target_chars: int) -> str:
        ...  # gọi API, yêu cầu paraphrase ngắn còn khoảng target_chars ký tự
        return shortened_text
"""
from __future__ import annotations
import re
from typing import Callable, List, Optional

from core.transcribe import SubtitleSegment

# Ước lượng tốc độ đọc trung bình (ký tự/giây, TÍNH CẢ khoảng trắng) ở tốc độ
# đọc bình thường của giọng TTS neural (edge-tts). Đây là số liệu THAM KHẢO
# ban đầu - nếu thấy ước lượng lệch nhiều so với giọng bạn thực tế dùng, cứ
# chỉnh lại dict này (đo bằng cách: thời lượng file audio thực tế / số ký tự).
CHARS_PER_SEC = {
    "Vietnamese": 16.5,    # đã tăng nhẹ từ 15.0 - 15 hơi chậm so với tốc độ đọc thuyết minh/review
                            # tự nhiên thực tế của giọng edge-tts, khiến bước rút gọn phải cắt oan
                            # nhiều hơn mức cần thiết. NÊN tự đo lại bằng giọng bạn thực dùng (thời
                            # lượng audio thực tế / số ký tự văn bản) và chỉnh số này cho khớp.
    "English": 15.5,
    "Chinese": 4.2,       # tính theo ký tự Hán, mỗi ký tự ~ 1 âm tiết
    "Japanese": 6.5,
    "Korean": 9.0,
    "French": 15.0,
    "Spanish": 16.0,
}
DEFAULT_CPS = 14.0

# Khoảng đệm cố định (giây) cộng thêm vào ước lượng - hầu hết giọng TTS có
# một khoảng lặng ngắn ở đầu/cuối file audio.
FIXED_OVERHEAD_SEC = 0.35


def parse_rate_multiplier(speech_rate: str) -> float:
    """
    Chuyển chuỗi tốc độ đọc kiểu edge-tts ("+10%", "-5%", "+0%") thành hệ số nhân
    (vd "+10%" -> 1.10). Dùng để CHARS_PER_SEC phản ánh đúng tốc độ đọc GỐC thực
    tế của giọng TTS (core/tts.py:speech_rate) thay vì luôn giả định "+0%".

    Đây là cách "tăng tốc" ĐÚNG chỗ và tự nhiên nhất: tăng tốc độ đọc GỐC của
    chính giọng AI (ngữ điệu, chỗ ngắt hơi được tính lại theo tốc độ mới), thay
    vì atempo hậu kỳ (chỉ kéo giãn/nén sóng âm có sẵn, dễ nghe "gấp gáp" nếu tăng
    nhiều). Tăng tốc độ đọc gốc thêm ~8-10% giúp MỌI câu có thêm ~8-10% thời gian
    "dư" so với ước lượng cũ, nên bước rút gọn văn bản (bên dưới) sẽ phải cắt ít
    hơn đáng kể cho những câu dài mà vẫn không cần đụng tới atempo.
    """
    if not speech_rate:
        return 1.0
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)%$", speech_rate.strip())
    if not m:
        return 1.0
    pct = float(m.group(1))
    return max(0.5, 1.0 + pct / 100.0)


def estimate_duration_sec(text: str, lang: str, speech_rate: str = "+0%", cps_override: Optional[float] = None) -> float:
    """Ước lượng số giây cần để đọc `text` bằng giọng TTS ngôn ngữ `lang`, có tính
    tới tốc độ đọc gốc `speech_rate` (vd "+8%") nếu core/tts.py dùng tốc độ khác mặc định.
    `cps_override`: dùng tốc độ đọc ĐÃ ĐO THỰC TẾ (xem core/tts.py:measure_actual_cps)
    thay cho bảng CHARS_PER_SEC tĩnh - chính xác hơn nhiều, đặc biệt với giọng nhân
    bản (voice clone) hoặc giọng offline vốn có tốc độ đọc khác hẳn edge-tts mặc định."""
    n_chars = len(text.strip())
    if n_chars == 0:
        return 0.0
    base_cps = cps_override if cps_override else CHARS_PER_SEC.get(lang, DEFAULT_CPS)
    cps = base_cps * parse_rate_multiplier(speech_rate)
    return n_chars / cps + FIXED_OVERHEAD_SEC


def available_seconds(segments: List[SubtitleSegment], index: int, min_gap_sec: float = 0.08) -> float:
    """
    Khoảng trống thời gian cho phép của segment tại vị trí `index` (0-based).
    CÙNG công thức với phần tính available_ms trong build_dubbed_track (core/tts.py)
    để 2 nơi ước lượng nhất quán - tránh trường hợp text_fit nói "vừa" nhưng
    lúc ghép track vẫn bị tăng tốc mạnh do lệch công thức.
    """
    seg = segments[index]
    if index + 1 < len(segments):
        next_start = segments[index + 1].start
    else:
        next_start = seg.end + 1.0  # câu cuối cùng: cho thêm 1s đệm
    return max(0.2, next_start - seg.start - min_gap_sec)


# Cụm từ đệm / thừa thường gặp - lược bỏ để rút ngắn mà KHÔNG đổi nghĩa,
# ưu tiên áp dụng bước này trước khi phải cắt cụt câu.
FILLER_PATTERNS_VI = [
    r"\bcó thể nói rằng\b", r"\bnói chung là\b", r"\bmột cách\b", r"\bthật ra là\b",
    r"\bnhư chúng ta đã biết\b", r"\bđiều đó có nghĩa là\b", r"\bnói cách khác\b",
    r"\bkỳ thực\b", r"\bthực sự là\b", r"\bmà thôi\b",
]
FILLER_PATTERNS_EN = [
    r"\bin other words\b", r"\bas we all know\b", r"\bactually\b", r"\bbasically\b",
    r"\byou know\b", r"\bkind of\b", r"\bsort of\b", r"\bI mean\b",
]
FILLER_MAP = {"Vietnamese": FILLER_PATTERNS_VI, "English": FILLER_PATTERNS_EN}


def _strip_fillers(text: str, lang: str) -> str:
    for pattern in FILLER_MAP.get(lang, []):
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text


def _split_clauses(text: str) -> List[str]:
    """Tách câu thành các mệnh đề theo dấu phẩy/chấm phẩy (giữ dấu ở cuối mỗi mệnh đề).
    CHỈ dùng để tách MỆNH ĐỀ PHỤ bên trong 1 câu đã quá dài - KHÔNG dùng để tách
    ranh giới câu (đó là việc của _split_sentences bên dưới)."""
    parts = re.split(r'(?<=[,;])\s+', text.strip())
    return [p for p in parts if p.strip()]


def _split_sentences(text: str) -> List[str]:
    """Tách văn bản thành các CÂU riêng biệt theo dấu chấm câu KẾT THÚC câu
    (., !, ?), giữ dấu câu ở cuối mỗi câu. Đây là ranh giới đúng để áp dụng
    "1 dòng = 1 câu" khi hiển thị phụ đề - khác _split_clauses (chỉ tách theo
    dấu phẩy/chấm phẩy, dùng cho mệnh đề phụ TRONG 1 câu, không phải giữa các câu).
    Không tách nhầm ở dấu chấm của số thập phân/viết tắt kiểu "1.5" hay "TP.HCM"
    (chỉ coi là kết thúc câu khi sau dấu câu là khoảng trắng rồi tới chữ hoa/hết chuỗi,
    không phải một chữ số ngay sau dấu chấm)."""
    parts = re.split(r'(?<=[.!?])\s+(?=[A-ZÀ-ỴĐ0-9"\u2018\u201c]|$)', text.strip())
    return [p for p in parts if p.strip()]


def _hard_trim(text: str, target_chars: int) -> str:
    """
    Last resort THẬT SỰ - chỉ chạy khi câu chỉ còn 1 mệnh đề (không thể bỏ bớt
    mệnh đề phụ nào nữa) mà vẫn dài hơn target_chars. Cắt tại ranh giới từ gần
    nhất (KHÔNG BAO GIỜ cắt giữa từ).
    """
    if len(text) <= target_chars:
        return text
    window = text[:target_chars]
    last_space = window.rfind(" ")
    if last_space > 0:
        window = window[:last_space]
    window = window.rstrip(" ,;")
    if not window.endswith((".", "!", "?")):
        window += "."
    return window


def shorten_text_rule_based(text: str, lang: str, target_chars: int) -> str:
    """
    Rút gọn câu theo 2 bước, ưu tiên GIỮ TRỌN Ý hơn là cắt cơ học:
      1. Bỏ từ đệm/cụm thừa (không đổi nghĩa).
      2. Nếu vẫn dài: bỏ dần MỆNH ĐỀ PHỤ ở CUỐI câu (theo dấu phẩy/chấm phẩy),
         luôn giữ lại mệnh đề đầu tiên (thường chứa chủ ngữ - vị ngữ, tức ý
         chính của câu) - nghe trọn ý hơn nhiều so với cắt cụt giữa câu theo
         số ký tự.
      3. Chỉ khi đã bỏ hết mệnh đề phụ mà mệnh đề chính còn lại vẫn dài hơn
         target_chars mới cắt theo ký tự (rất hiếm khi xảy ra).
    """
    text = _strip_fillers(text, lang)
    if len(text) <= target_chars:
        return text

    clauses = _split_clauses(text)
    if len(clauses) > 1:
        kept = clauses[:]
        while len(kept) > 1:
            candidate = " ".join(kept[:-1]).rstrip(" ,;")
            if not candidate.endswith((".", "!", "?")):
                candidate += "."
            if len(candidate) <= target_chars:
                return candidate
            kept = kept[:-1]
        text = kept[0].rstrip(" ,;")
        if not text.endswith((".", "!", "?")):
            text += "."

    if len(text) <= target_chars:
        return text
    return _hard_trim(text, target_chars)


def split_segments_for_display(
    segments: List[SubtitleSegment],
    target_lang: str,
    max_chars: int = 42,
    min_chunk_sec: float = 0.9,
    speech_rate: str = "+0%",
    cps_override: Optional[float] = None,
    min_gap_sec: float = 0.08,
    max_extend_sec: float = 3.0,
) -> List[SubtitleSegment]:
    """
    Tách câu phụ đề DÀI thành NHIỀU DÒNG NGẮN hiển thị LẦN LƯỢT - KHÔNG bớt/đổi
    1 chữ nào (khác fit_segments_to_timing - hàm đó RÚT NGẮN văn bản dùng cho
    TTS; hàm này CHỈ tách cách HIỂN THỊ, giữ nguyên 100% nội dung).

    Ví dụ: "Bạn có dám tin rằng, chỉ cần đổ thêm nước vào bể" (khung 0s-4s) sẽ
    tách thành 2 dòng hiện nối tiếp nhau:
      0.0s - 1.8s : "Bạn có dám tin rằng"
      1.8s - 4.0s : "chỉ cần đổ thêm nước vào bể"
    (mốc 1.8s ước lượng theo tỉ lệ số ký tự mỗi vế so với tốc độ đọc, KHÔNG phải
    chia đều thời gian theo số vế - vế dài hơn được hiện lâu hơn tương ứng.)

    max_chars: quá ngưỡng này (ước lượng theo số ký tự hiển thị 1 dòng cho dễ
    đọc) mới bắt đầu tách - câu ngắn hơn giữ nguyên, không tách vô ích.
    min_chunk_sec: mỗi dòng con tối thiểu hiện bấy nhiêu giây, dù ước lượng đọc
    ra ngắn hơn - tránh nháy quá nhanh khó đọc kịp.

    QUAN TRỌNG (fix): bản cũ luôn ép TỔNG thời gian các dòng con phải KHỚP
    ĐÚNG duration gốc (seg.end - seg.start) - tức khung giờ của câu bên NGÔN
    NGỮ GỐC (thường ngắn/súc tích hơn). Khi câu dịch (vd tiếng Việt) cần nhiều
    ký tự hơn hẳn để diễn đạt cùng ý, ép vừa khung giờ gốc khiến tốc độ đọc
    (cps) bị đẩy lên rất cao (thực tế đo được nhiều dòng 28-32 cps, trong khi
    tốc độ đọc thoải mái của tiếng Việt chỉ ~16-17 cps) -> phụ đề nháy quá
    nhanh, đọc không kịp, cảm giác "vỡ/toang".

    Từ nay, nếu tổng thời gian CẦN (raw, đã có sàn min_chunk_sec) vượt quá
    duration gốc, hàm sẽ "mượn" thêm thời gian từ khoảng LẶNG trước khi câu kế
    tiếp bắt đầu (tối đa `max_extend_sec` giây, và LUÔN chừa lại `min_gap_sec`
    giây đệm trước câu kế - không bao giờ lấn đúng lúc câu sau cần hiện). Chỉ
    khi mượn hết mức vẫn không đủ mới rescale ép nhỏ lại (nén cps) như cũ - lúc
    đó nên cân nhắc rút gọn văn bản dịch thay vì chỉ chỉnh timing hiển thị.
    """
    base_cps = cps_override if cps_override else CHARS_PER_SEC.get(target_lang, DEFAULT_CPS)
    cps = base_cps * parse_rate_multiplier(speech_rate)

    out: List[SubtitleSegment] = []
    for i, seg in enumerate(segments):
        text = seg.text.strip()
        duration = max(0.05, seg.end - seg.start)

        sentence_count = len(_split_sentences(text))
        if len(text) <= max_chars and sentence_count <= 1:
            # Ngắn và chỉ có 1 câu -> giữ nguyên, không tách vô ích.
            out.append(seg)
            continue

        # BƯỚC 1 - tách theo CÂU (dấu ., !, ?) trước tiên. Mỗi câu = 1 dòng
        # riêng, KHÔNG gộp nhiều câu lại với nhau dù gộp vẫn <= max_chars - đúng
        # yêu cầu "1 dòng = 1 câu". Đây là chỗ bản cũ bị sai: bản cũ tách theo
        # _split_clauses (chỉ biết dấu , ;) rồi GỘP các mệnh đề/câu liền kề cho
        # đầy max_chars, nên nhiều khi 2-3 câu bị dồn chung 1 dòng, còn dòng kế
        # lại bắt đầu giữa câu -> vừa sai dấu câu vừa cắt không theo ý nghĩa.
        sentences = _split_sentences(text)
        chunks: List[str] = []
        for sent in sentences:
            if len(sent) <= max_chars:
                chunks.append(sent)
                continue
            # Câu quá dài để hiện trên 1 dòng -> tách tiếp theo MỆNH ĐỀ PHỤ
            # (dấu phẩy/chấm phẩy) trong nội bộ câu đó, và CHỈ gộp lại nếu các
            # mệnh đề phụ này vẫn thuộc cùng 1 câu (không lấn sang câu khác).
            clauses = _split_clauses(sent)
            if len(clauses) > 1:
                cur = ""
                for cl in clauses:
                    candidate = (cur + " " + cl).strip() if cur else cl
                    if len(candidate) <= max_chars or not cur:
                        cur = candidate
                    else:
                        chunks.append(cur)
                        cur = cl
                if cur:
                    chunks.append(cur)
            else:
                chunks.append(sent)

        # BƯỚC 2 - vế nào vẫn còn dài hơn max_chars (1 mệnh đề/câu tự nó đã rất
        # dài, không còn dấu phẩy nào để tách tiếp) -> LAST RESORT: cắt tại ranh
        # giới TỪ (không bao giờ cắt giữa từ, không bỏ chữ nào - chỉ ngắt dòng,
        # phần còn lại đẩy sang dòng kế tiếp).
        final_chunks: List[str] = []
        for ch in chunks:
            remaining = ch
            while len(remaining) > max_chars:
                if len(remaining) <= max_chars * 2:
                    # CHỈ CÒN ĐÚNG 2 MẢNH CUỐI - chia ĐỀU quanh điểm giữa (vẫn tại
                    # ranh giới từ) thay vì tham lam lấy tối đa max_chars cho mảnh
                    # đầu. Lấy tối đa cho mảnh đầu dễ để lại mảnh sau chỉ còn vài
                    # chữ MỒ CÔI (vd "tấn." đứng riêng 1 dòng cả câu) - chia đều cho
                    # 2 dòng cân đối, dễ đọc hơn nhiều dù mảnh đầu không đầy hết cỡ.
                    target = len(remaining) // 2
                    left_space = remaining.rfind(" ", 0, target)
                    right_space = remaining.find(" ", target)
                    candidates = [p for p in (left_space, right_space) if p > 0]
                    cut = min(candidates, key=lambda p: abs(p - target)) if candidates else target
                else:
                    window = remaining[:max_chars]
                    last_space = window.rfind(" ")
                    cut = last_space if last_space > 0 else max_chars
                final_chunks.append(remaining[:cut].strip())
                remaining = remaining[cut:].strip()
            if remaining:
                final_chunks.append(remaining)

        if len(final_chunks) <= 1:
            out.append(seg)
            continue

        # Chia thời lượng của segment gốc cho các dòng con - TỈ LỆ THUẬN với số
        # ký tự mỗi dòng (dòng dài hiện lâu hơn), có sàn min_chunk_sec để không
        # dòng nào bị nháy quá nhanh.
        raw = [max(min_chunk_sec, len(c) / cps) for c in final_chunks]
        total_raw = sum(raw)
        if total_raw <= 0:
            out.append(seg)
            continue

        # Khung giờ TỐI ĐA có thể "mượn" thêm mà không lấn câu kế tiếp.
        if i + 1 < len(segments):
            hard_limit = max(duration, segments[i + 1].start - seg.start - min_gap_sec)
        else:
            hard_limit = duration + max(max_extend_sec, 1.0)  # câu cuối cùng - nới thoải mái hơn
        extended_cap = min(hard_limit, duration + max_extend_sec)

        if total_raw <= duration:
            use_duration = duration  # đủ khung giờ gốc - giữ nguyên như cũ
        else:
            use_duration = min(total_raw, extended_cap)  # mượn thêm, không vượt trần an toàn

        scale = use_duration / total_raw
        durs = [r * scale for r in raw]
        seg_extended_end = seg.start + use_duration

        t = seg.start
        for j, (chunk_text, d) in enumerate(zip(final_chunks, durs)):
            chunk_end = t + d if j < len(final_chunks) - 1 else seg_extended_end
            out.append(SubtitleSegment(
                index=0,  # đánh lại số thứ tự ở cuối, sau khi đã có đủ list cuối cùng
                start=t, end=chunk_end, text=chunk_text,
                gender=seg.gender, speaker_id=seg.speaker_id,
            ))
            t = chunk_end

    for i, s in enumerate(out, start=1):
        s.index = i
    return out


def rebalance_group_timing(
    segments: List[SubtitleSegment],
    target_lang: str,
    pause_threshold_sec: float = 0.25,
    min_chunk_sec: float = 0.6,
    speech_rate: str = "+0%",
    cps_override: Optional[float] = None,
) -> List[SubtitleSegment]:
    """
    Cân lại NHỊP ĐỌC giữa các segment liền kề thuộc cùng 1 mạch nói liên tục.

    VẤN ĐỀ: sau khi dịch, độ dài từng câu có thể xê dịch RẤT khác so với câu
    gốc tương ứng (dịch diễn giải khác, gộp/tách ý khác cách nói gốc), nhưng
    mốc start/end của mỗi segment vẫn là mốc THỜI GIAN NÓI GỐC (từ ASR/merge),
    không hề đổi. Kết quả: 1 câu dịch NGẮN ("Bạn có biết.") có thể rơi đúng vào
    1 khung giờ DÀI của câu gốc tương ứng (~4s) - đọc/nói bị kéo lê rất chậm -
    trong khi câu dịch NGAY SAU đó dài hơn hẳn lại rơi vào khung giờ ngắn hơn -
    bị nói dồn dập. Xét RIÊNG từng câu vẫn có thể "trong ngưỡng cps cho phép",
    nhưng tốc độ đọc nhảy vọt lên xuống giữa các câu cạnh nhau nghe/đọc rất
    khó chịu ("không đồng đều", "không lọt tai").

    CÁCH LÀM: gom các segment liên tiếp có khoảng cách (start sau - end trước)
    < pause_threshold_sec thành 1 "nhóm" (coi như 1 mạch nói không ngắt hơi
    đáng kể - < 0.25s không đủ để là 1 chỗ ngắt hơi thật). Trong mỗi nhóm:
      - Mốc bắt đầu của segment ĐẦU và mốc kết thúc của segment CUỐI được GIỮ
        NGUYÊN (không đụng tới timeline tổng thể của video, không lấn nhóm
        khác/không tạo khoảng trống mới).
      - CHỈ chia lại các ranh giới GIỮA những segment trong nhóm, theo tỉ lệ
        số ký tự câu dịch của từng segment (câu dài hơn được cấp nhiều thời
        gian hơn tương ứng), có sàn `min_chunk_sec` để câu nào cũng có tối
        thiểu 1 khoảng đọc hợp lý dù rất ngắn.
    Những chỗ ngắt hơi THẬT (>= pause_threshold_sec) giữa 2 nhóm được giữ
    nguyên, không bị nhóm chung - tôn trọng nhịp nghỉ tự nhiên của giọng gốc.

    Gọi hàm này NGAY SAU translate_segments(...) và TRƯỚC fit_segments_to_timing
    / split_segments_for_display, để 2 bước đó làm việc trên khung giờ đã hợp
    lý, thay vì è văn bản vào 1 khung giờ vốn dĩ sai lệch ngay từ đầu.
    """
    base_cps = cps_override if cps_override else CHARS_PER_SEC.get(target_lang, DEFAULT_CPS)
    cps = base_cps * parse_rate_multiplier(speech_rate)

    out: List[SubtitleSegment] = []
    n = len(segments)
    i = 0
    while i < n:
        j = i
        while (
            j + 1 < n
            and (segments[j + 1].start - segments[j].end) < pause_threshold_sec
            and segments[j].text.strip()
            and segments[j + 1].text.strip()
        ):
            j += 1
        group = segments[i:j + 1]

        if len(group) == 1:
            out.append(group[0])
            i = j + 1
            continue

        group_start = group[0].start
        group_end = group[-1].end
        total_duration = max(0.1, group_end - group_start)

        raw = [max(min_chunk_sec, len(g.text.strip()) / cps) for g in group]
        total_raw = sum(raw)
        scale = total_duration / total_raw if total_raw > 0 else 1.0
        durs = [r * scale for r in raw]

        t = group_start
        for k, (g, d) in enumerate(zip(group, durs)):
            g_end = t + d if k < len(group) - 1 else group_end  # segment cuối LUÔN khớp đúng mốc gốc
            out.append(SubtitleSegment(
                index=g.index, start=t, end=g_end, text=g.text,
                gender=g.gender, speaker_id=g.speaker_id,
            ))
            t = g_end

        i = j + 1

    return out


def fit_segments_to_timing(
    segments: List[SubtitleSegment],
    target_lang: str,
    min_gap_sec: float = 0.08,
    tolerance: float = 1.08,  # dưới ngưỡng này: KHÔNG rút gọn gì cả, để atempo nhẹ xử lý phần lệch NHỎ còn sót
    # (do sai số ước lượng tốc độ đọc). QUAN TRỌNG: giá trị này phải THẤP HƠN RÕ RỆT so với
    # dub_max_speedup (core/tts.py) - nếu 2 giá trị bằng nhau (như cấu hình cũ 1.25/1.25),
    # bước rút gọn văn bản gần như không làm gì cả cho những câu lệch 5-25%, đẩy TOÀN BỘ phần
    # đó xuống cho atempo xử lý -> gần như câu nào cũng bị đổi tốc độ (ratio dao động lung tung
    # 1.01x, 1.05x, 1.17x, 1.25x...) nghe không lọt tai. Để tolerance thấp (~1.05-1.10) thì phần
    # lớn việc "khớp thời lượng" được xử lý NGAY ở văn bản (rút câu, không đổi tốc độ đọc), atempo
    # chỉ còn phải can thiệp cho phần dư rất nhỏ, hiếm khi xảy ra và mức đổi tốc độ cũng nhỏ hơn nhiều.
    speech_rate: str = "+0%",  # PHẢI truyền ĐÚNG tốc độ đọc gốc dùng ở core/tts.py (vd "+8%") để ước lượng
    # khớp với audio thực tế được tạo ra. Tăng speech_rate là cách "tận dụng tăng speed" tốt
    # nhất để bớt phải cắt chữ: mọi câu đều có thêm thời gian dư tương ứng % tăng, mà giọng đọc
    # vẫn tự nhiên (ngữ điệu tính lại theo tốc độ mới) chứ không "gấp gáp" như atempo hậu kỳ.
    cps_override: Optional[float] = None,  # tốc độ đọc (ký tự/giây) đã ĐO THỰC TẾ trên chính engine/giọng
    # sẽ dùng để tạo audio (xem core/tts.py:measure_actual_cps, được core/pipeline.py tự động đo trước
    # khi gọi hàm này nếu calibrate_speech_rate_cps=True). Chính xác hơn NHIỀU so với bảng CHARS_PER_SEC
    # tĩnh, nhất là với giọng nhân bản (voice clone/XTTS) hay giọng offline (pyttsx3) - những giọng này
    # có tốc độ đọc thực tế khác hẳn edge-tts (giọng dùng để hiệu chỉnh bảng CHARS_PER_SEC ban đầu).
    # Đây chính là nguyên nhân câu 1, câu 5 trong log vẫn bị tăng tốc 1.08x/1.13x dù đã "rút gọn cho vừa":
    # ước lượng dùng bảng tĩnh (cho edge-tts) trong khi audio thật lại được tạo bằng giọng clone (viXTTS).
    llm_shorten_fn: Optional[Callable[[str, str, int], str]] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[SubtitleSegment]:
    """
    Duyệt các segment ĐÃ DỊCH, câu nào ước lượng đọc lâu hơn khoảng trống thời
    gian gốc thì rút ngắn văn bản ngay (trước khi tạo audio). Trả về list mới,
    KHÔNG sửa list gốc - dùng list gốc (đầy đủ) cho phụ đề, list rút gọn này
    chỉ dùng để tạo giọng đọc, vì tốc độ đọc phụ đề (mắt) và tốc độ nghe (tai)
    là khác nhau, không cần rút gọn phụ đề hiển thị.
    """
    out: List[SubtitleSegment] = []
    total = max(1, len(segments))
    n_shortened = 0
    rate_mult = parse_rate_multiplier(speech_rate)

    for i, seg in enumerate(segments):
        avail = available_seconds(segments, i, min_gap_sec)
        needed = estimate_duration_sec(seg.text, target_lang, speech_rate, cps_override)
        new_text = seg.text

        if needed > avail * tolerance:
            base_cps = cps_override if cps_override else CHARS_PER_SEC.get(target_lang, DEFAULT_CPS)
            cps = base_cps * rate_mult
            target_chars = max(10, int((avail * tolerance - FIXED_OVERHEAD_SEC) * cps))

            if llm_shorten_fn is not None:
                try:
                    new_text = llm_shorten_fn(seg.text, target_lang, target_chars)
                    # Lưới an toàn: LLM không phải lúc nào cũng bám sát target_chars tuyệt đối
                    # (ưu tiên giữ ý hơn đúng số ký tự) - nếu kết quả VẪN còn dài hơn hẳn khung
                    # giờ cho phép (>15% so với target), cắt tiếp bằng rule-based trên chính kết
                    # quả đó (giữ nguyên văn phong đã viết lại, chỉ bớt mệnh đề cuối) để đảm bảo
                    # KHÔNG BAO GIỜ phải nhờ tới atempo/cắt audio ở bước sau.
                    if len(new_text.strip()) > target_chars * 1.15:
                        new_text = shorten_text_rule_based(new_text, target_lang, target_chars)
                except Exception:
                    new_text = shorten_text_rule_based(seg.text, target_lang, target_chars)
            else:
                new_text = shorten_text_rule_based(seg.text, target_lang, target_chars)

            if new_text.strip() and new_text != seg.text:
                n_shortened += 1

        out.append(SubtitleSegment(index=seg.index, start=seg.start, end=seg.end, text=new_text or seg.text, gender=seg.gender, speaker_id=seg.speaker_id))
        if progress_cb:
            tag = " (đã rút gọn)" if out[-1].text != seg.text else ""
            progress_cb((i + 1) / total, f"Đang khớp thời lượng câu {i + 1}/{total}{tag}")

    if progress_cb:
        progress_cb(1.0, f"Hoàn tất khớp thời lượng - đã rút gọn {n_shortened}/{total} câu")

    return out