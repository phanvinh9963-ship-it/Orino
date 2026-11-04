"""
core/translate.py
Dịch danh sách SubtitleSegment sang ngôn ngữ đích.
Hỗ trợ 2 chế độ:
  - "online": deep-translator (Google Translate, cần internet)
  - "offline": argos-translate (dịch offline, cần tải gói ngôn ngữ 1 lần)
"""
from __future__ import annotations
import json
import random
import re
import time

from typing import Callable, List, Optional, Tuple

from core.transcribe import SubtitleSegment

LANG_CODE = {
    "Chinese": "zh-CN",
    "English": "en",
    "Vietnamese": "vi",
    "Japanese": "ja",
    "Korean": "ko",
    "French": "fr",
    "Spanish": "es",
}
# ============================================================
# YOUTUBE OUTPUT NOTE / METADATA
# ============================================================

YOUTUBE_METADATA_OUTPUT_PROMPT = """
Bạn là chuyên gia xây dựng nội dung video đa ngôn ngữ cho YouTube/Short Video.

NHIỆM VỤ:
Từ TIÊU ĐỀ GỐC và TOÀN BỘ TRANSCRIPT được cung cấp, hãy tạo metadata YouTube bằng ngôn ngữ đầu ra được yêu cầu.

QUY TẮC NGÔN NGỮ:
- Toàn bộ output phải dùng đúng ngôn ngữ đầu ra.
- Không trộn ngôn ngữ.
- Không dịch máy móc từng chữ.
- Văn phong tự nhiên, hấp dẫn, phù hợp YouTube/Short Video.
- Được phép viết lại tự nhiên nhưng phải giữ đúng nội dung nguồn.

QUY TẮC NỘI DUNG:
- Đọc và hiểu TOÀN BỘ transcript trước khi viết.
- Không lấy một câu subtitle riêng lẻ làm tiêu đề hoặc mô tả.
- Không ghép các subtitle bị cắt thành câu sai nghĩa.
- Giữ đúng sự kiện, nhân vật, thuật ngữ, số liệu và quan hệ nguyên nhân-kết quả có trong nguồn.
- KHÔNG bịa thông tin.
- Không thêm nhân vật, sự kiện, số liệu hoặc chi tiết không có trong nguồn.
- Không tự suy đoán khi transcript không đủ thông tin.

TIÊU ĐỀ:
- Chỉ tạo 1 tiêu đề.
- Tiêu đề phải là một câu/tiêu đề hoàn chỉnh.
- Dễ hiểu ngay khi đọc.
- Có keyword chính của chủ đề.
- Có yếu tố tò mò nhưng không giật tít sai sự thật.
- Không dịch cứng nhắc tiêu đề gốc.
- Không để tiêu đề bị cụt giữa câu.

MÔ TẢ:
- Viết khoảng 150–250 từ bằng ngôn ngữ đầu ra.
- 1–2 câu đầu tạo sự tò mò và nêu đúng vấn đề chính của video.
- Sau đó giới thiệu video đang giải thích/khám phá điều gì.
- Phải dựa trên TOÀN BỘ transcript.
- Không lặp lại tiêu đề quá nhiều.
- Không bịa thông tin.

NỘI DUNG CHÍNH:
- Tạo 5–8 ý chính.
- Mỗi ý là một câu hoặc đoạn hoàn chỉnh.
- Mỗi ý phải có chủ ngữ và ý nghĩa rõ ràng.
- Không để ý bị cắt giữa câu.
- Các ý phải theo logic nội dung video.
- Không lặp nhau.
- Không thêm ý không có trong nguồn.

KẾT:
- Viết một đoạn kết ngắn.
- Có thể có CTA tự nhiên như Like, Subscribe, Follow hoặc xem video tiếp theo nếu phù hợp.
- Không dùng một câu CTA cố định cho mọi video.
- Không viết CTA quá dài.

HASHTAG:
- Tạo 10–15 hashtag.
- Hashtag phải liên quan trực tiếp đến chủ đề, nội dung và lĩnh vực của video.
- Ưu tiên hashtag là CỤM TỪ CÓ NGHĨA, có thể chứa nhiều từ.
- Hashtag phải tự nhiên trong ngôn ngữ đầu ra.
- Không dùng hashtag rác hoặc chung chung như #viral, #fyp nếu chúng không liên quan trực tiếp.
- Không dùng hashtag vô nghĩa hoặc ghép chữ tùy tiện.
- Không lặp hashtag.
- Hashtag phải phản ánh đúng nội dung video.

FORMAT BẮT BUỘC:

Tiêu đề YouTube

[1 tiêu đề hoàn chỉnh]

Mô tả video YouTube

[150–250 từ]

📌 Nội dung chính:

* [Ý chính 1]
* [Ý chính 2]
* [Ý chính 3]
* [Ý chính 4]
* [Ý chính 5]
* [Có thể thêm tối đa 8 ý]

Kết

[Đoạn kết và CTA ngắn, tự nhiên nếu phù hợp]

HASHTAGS

[#hashtag1 #hashtag2 #hashtag3 ...]

YÊU CẦU CUỐI:
1. Đúng ngôn ngữ đầu ra.
2. Chỉ có 1 tiêu đề.
3. Tiêu đề không bị cụt.
4. Mô tả khoảng 150–250 từ.
5. Có đúng mục "📌 Nội dung chính:".
6. Có 5–8 ý chính hoàn chỉnh.
7. Có đoạn kết.
8. Có 10–15 hashtag liên quan.
9. Hashtag phải có nghĩa và liên quan trực tiếp.
10. Không bịa thông tin.
11. Không để lại câu bị cắt hoặc placeholder.
12. Không thêm giải thích ngoài FORMAT.
"""

_LANG_NAME_TO_ISO = {
    "chinese": "zh-CN",
    "english": "en",
    "vietnamese": "vi",
    "japanese": "ja",
    "korean": "ko",
    "french": "fr",
    "spanish": "es",
}


def validate_youtube_metadata_output(output: str) -> bool:
    """Kiểm tra output metadata YouTube có đúng format tối thiểu hay không."""
    if not output or not output.strip():
        return False

    s = output.strip()
    lines = s.splitlines()

    required = [
        "Tiêu đề YouTube",
        "Mô tả video YouTube",
        "📌 Nội dung chính:",
        "HASHTAGS",
    ]

    if not all(x in s for x in required):
        return False

    # --------------------------------------------------------
    # Kiểm tra tiêu đề
    # --------------------------------------------------------
    try:
        title_index = next(
            i for i, line in enumerate(lines)
            if line.strip() == "Tiêu đề YouTube"
        )
    except StopIteration:
        return False

    title = ""
    for line in lines[title_index + 1:]:
        line = line.strip()
        if line:
            title = line
            break

    if not title:
        return False

    # Tiêu đề quá ngắn thường là output bị cụt.
    if len(title) < 12:
        return False

    # Không chấp nhận placeholder.
    if title.startswith("[") and title.endswith("]"):
        return False

    # Không chấp nhận các dạng câu bị cắt phổ biến.
    if title.endswith(("...", "…", " vì", " và", " với", " là", " khi", " tại sao")):
        return False

    # --------------------------------------------------------
    # Kiểm tra mục Nội dung chính
    # --------------------------------------------------------
    try:
        content_index = next(
            i for i, line in enumerate(lines)
            if line.strip() == "📌 Nội dung chính:"
        )
    except StopIteration:
        return False

    try:
        hashtags_index = next(
            i for i, line in enumerate(lines)
            if line.strip() == "HASHTAGS"
        )
    except StopIteration:
        return False

    if hashtags_index <= content_index:
        return False

    bullet_lines = [
        line.strip()
        for line in lines[content_index + 1:hashtags_index]
        if line.strip().startswith(("* ", "- "))
    ]

    if not 5 <= len(bullet_lines) <= 8:
        return False

    # Không cho phép bullet rỗng hoặc placeholder.
    for bullet in bullet_lines:
        text = bullet[2:].strip()

        if not text:
            return False

        if text.startswith("[") and text.endswith("]"):
            return False

        if text.endswith(("...", "…")):
            return False

    # --------------------------------------------------------
    # Kiểm tra hashtag
    # --------------------------------------------------------
    hashtag_text = "\n".join(lines[hashtags_index + 1:])

    # Hỗ trợ hashtag Unicode, bao gồm tiếng Việt.
    hashtags = re.findall(
        r"(?<!\w)#[^\s#]+",
        hashtag_text,
        flags=re.UNICODE,
    )

    # Loại bỏ hashtag trùng.
    unique_hashtags = list(dict.fromkeys(
        h.lower() for h in hashtags
    ))

    if not 10 <= len(hashtags) <= 15:
        return False

    if len(unique_hashtags) != len(hashtags):
        return False

    # Hashtag phải có nội dung thật sau dấu #.
    for hashtag in hashtags:
        if len(hashtag) <= 1:
            return False

    # --------------------------------------------------------
    # Kiểm tra mô tả
    # --------------------------------------------------------
    try:
        description_index = next(
            i for i, line in enumerate(lines)
            if line.strip() == "Mô tả video YouTube"
        )
    except StopIteration:
        return False

    description_end = content_index

    description_lines = [
        line.strip()
        for line in lines[description_index + 1:description_end]
        if line.strip()
    ]

    if not description_lines:
        return False

    description = " ".join(description_lines)

    # Đếm từ tương đối, hỗ trợ tiếng Việt và các ngôn ngữ không cách từ.
    word_count = len(description.split())

    if not 150 <= word_count <= 250:
        return False

    return True


def _to_iso_lang(lang: str) -> str:
    if not lang:
        return "auto"
    key = lang.strip().lower()
    if key in _LANG_NAME_TO_ISO:
        return _LANG_NAME_TO_ISO[key]
    # Đã là mã ISO sẵn (vd người dùng truyền thẳng "vi", "en-US"...) - dùng nguyên văn.
    if len(key) <= 5:
        return lang.strip()
    return "auto"


# --- Ép ngắn bản dịch NGAY SAU KHI NHẬN TỪ AI (lưới an toàn ở tầng dịch) -------
# Các prompt Gemini/Grok/... vẫn có thể "phớt lờ" ngân sách ký tự đã ghi trong
# prompt (VN_CPS_ESTIMATE bên dưới) vì các chỉ dẫn "Keep every fact/number/name,
# never remove information" trong CONTENT_REWRITER_INSTRUCTIONS thường được model
# ưu tiên hơn 1 dòng ghi chú độ dài. Thay vì để nguyên và đẩy hết việc rút gọn
# xuống fit_segments_to_timing (core/text_fit.py, chỉ chạy cho bản TTS) hay
# split_segments_for_display (chỉ "mượn" thời gian, không rút chữ), bước này rút
# ngắn NGAY tại tầng dịch cho MỌI method - vừa giảm tải 2 bước sau, vừa đảm bảo
# file .srt xuất ra (dùng để đọc/sửa tay) cũng đã gọn sẵn chứ không phải đợi tới
# bước TTS mới được rút gọn.
TRANSLATE_BUDGET_CPS = {
    "Vietnamese": 15.0,
    "English": 15.0,
    "Chinese": 4.2,
    "Japanese": 6.5,
    "Korean": 9.0,
    "French": 15.0,
    "Spanish": 16.0,
}
DEFAULT_TRANSLATE_BUDGET_CPS = 14.0


def _enforce_char_budget(
    texts: List[str],
    durations: List[float],
    target_lang: str,
    tolerance: float = 1.15,
) -> List[str]:
    """
    Duyệt qua các câu VỪA dịch xong (trước khi gán vào SubtitleSegment): câu nào
    dài hơn `tolerance` lần ngân sách ký tự ước tính từ khung thời gian của nó
    (cùng công thức CHARS_PER_SEC/tolerance với core/text_fit.py, để 2 nơi nhất
    quán) thì RÚT GỌN NGAY bằng shorten_text_rule_based (bỏ từ đệm, bớt mệnh đề
    phụ cuối câu, giữ đúng ý chính - KHÔNG cắt cụt vô nghĩa).

    Import core.text_fit ngay trong hàm (không import ở đầu file) để tránh vòng
    lặp import (core/text_fit.py không cần import ngược lại core/translate.py,
    nhưng để code gọn và tách rời 2 module, cứ import cục bộ khi cần dùng).
    """
    try:
        from core.text_fit import shorten_text_rule_based
    except Exception:
        return list(texts)  # môi trường thiếu core.text_fit -> bỏ qua, không crash cả job

    cps = TRANSLATE_BUDGET_CPS.get(target_lang, DEFAULT_TRANSLATE_BUDGET_CPS)
    out: List[str] = []
    for text, dur in zip(texts, durations):
        text = (text or "").strip()
        budget = max(10, int(dur * cps))
        if len(text) > budget * tolerance:
            try:
                text = shorten_text_rule_based(text, target_lang, budget)
            except Exception:
                pass  # rút gọn lỗi -> giữ nguyên bản dịch gốc, không làm hỏng cả lô
        out.append(text)
    return out


def translate_segments_online(
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    max_retries: int = 4,
    retry_delay: float = 2.0,
    request_delay: float = 0.3,
) -> List[SubtitleSegment]:
    """
    Dịch NHANH, CÂU-ĐỐI-CÂU qua Google Translate (endpoint web miễn phí, KHÔNG cần
    API key, KHÔNG cần cookie, KHÔNG phụ thuộc Gemini/Gemini Web2API dưới bất kỳ hình
    thức nào - độc lập hoàn toàn, dùng được ngay cả khi Gemini đang gặp sự cố).

    KHÁC với gemini/grok/gemini_fastapi/gemini_webapi/chatanywhere: đây là dịch LITERAL
    (bám sát nghĩa gốc, câu-đối-câu), KHÔNG viết lại văn phong/hook/CTA kiểu "Content
    Rewriter" - phù hợp khi cần dịch NHANH/ỔN ĐỊNH hơn là cần chất lượng thuyết minh
    video, hoặc làm phương án dự phòng cuối cùng khi mọi phương án AI đều lỗi.

    Mỗi câu phụ đề là 1 request riêng (không gộp lô) - tránh lỗi lệch số dòng khi
    Google Translate xử lý nhiều dòng trong 1 lần gọi. Lỗi ở 1 câu KHÔNG làm hỏng cả
    video - câu đó giữ nguyên bản gốc, log cảnh báo, và tiếp tục dịch các câu còn lại.
    """
    import requests

    sl = _to_iso_lang(source_lang)
    tl = _to_iso_lang(target_lang)
    url = "https://translate.googleapis.com/translate_a/single"

    out: List[SubtitleSegment] = []
    total = max(1, len(segments))
    for i, seg in enumerate(segments):
        text = seg.text.strip()
        if not text:
            out.append(seg)
            continue

        translated: Optional[str] = None
        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    url,
                    params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": text},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                # Cấu trúc trả về: [[[translated_chunk, original_chunk, ...], ...], ...]
                # Google có thể tách câu dài thành nhiều "chunk" nhỏ - nối lại đủ.
                translated = "".join(chunk[0] for chunk in data[0] if chunk and chunk[0])
                if translated:
                    break
                last_err = ValueError("Google Translate trả về nội dung rỗng")
            except Exception as e:
                last_err = e
                if progress_cb:
                    progress_cb(
                        i / total,
                        f"⚠ Dịch online lỗi câu {i + 1}/{total} (lần {attempt + 1}/{max_retries}): {e} - đang thử lại...",
                    )
                time.sleep(retry_delay * (attempt + 1))

        if not translated:
            if progress_cb:
                progress_cb(i / total, f"⚠ Bỏ qua câu {i + 1}/{total} (giữ nguyên bản gốc) - lỗi cuối: {last_err}")
            translated = text

        out.append(SubtitleSegment(
            index=seg.index, start=seg.start, end=seg.end,
            text=translated, gender=seg.gender, speaker_id=seg.speaker_id,
        ))
        if progress_cb:
            progress_cb((i + 1) / total, f"Đang dịch (online) {i + 1}/{total}")
        if request_delay > 0:
            time.sleep(request_delay)

    return out

DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"

# --- Persona/giọng điệu THEO CHỦ ĐỀ (mục 5 trong yêu cầu nâng cấp) ---------------
# key phải khớp với giá trị "category" mà build_video_context / build_video_context_grok
# yêu cầu model trả về, để có thể TỰ ĐỘNG chọn persona theo chủ đề video (không cần
# người dùng tự chọn tay). Người dùng vẫn có thể ép cứng 1 persona qua tham số
# `content_persona` (ghi đè lựa chọn tự động) nếu muốn kiểm soát văn phong chắc chắn hơn.
TOPIC_PERSONAS = {
    "science": (
        "Giọng THUYẾT MINH KHOA HỌC kiểu Discovery/Veritasium: giải thích cơ chế bằng "
        "ví dụ đời thường dễ hình dung, tạo cảm giác 'À, ra là vậy!' khi tiết lộ dữ kiện, "
        "nhấn mạnh sự bất ngờ/thú vị ẩn sau hiện tượng khoa học."
    ),
    "history": (
        "Giọng THUYẾT MINH LỊCH SỬ kiểu phim tài liệu (documentary): trang trọng vừa "
        "phải, kể theo dòng thời gian, gợi không khí thời đại, nhấn nhá rõ ở các mốc "
        "sự kiện bước ngoặt."
    ),
    "psychology": (
        "Giọng KỂ CHUYỆN TÂM LÝ: gần gũi như đang tâm sự, đặt câu hỏi gợi mở để người "
        "xem tự liên hệ bản thân, dùng tình huống đời thường quen thuộc để minh hoạ khái niệm."
    ),
    "finance": (
        "Giọng PHÂN TÍCH TÀI CHÍNH: rõ ràng, logic, bám sát số liệu/dẫn chứng cụ thể, "
        "tạo cảm giác đáng tin cậy như 1 nhà phân tích đang giải thích cho người mới bắt đầu."
    ),
    "technology": (
        "Giọng GIẢI THÍCH CÔNG NGHỆ: dễ hiểu cho người không rành kỹ thuật, hay so sánh "
        "với vật dụng/khái niệm quen thuộc, nhấn mạnh ứng dụng thực tế và tác động tới người dùng."
    ),
    "other": (
        "Giọng THUYẾT MINH TỰ NHIÊN, cuốn hút, linh hoạt theo đúng nội dung video, không "
        "gò theo khuôn mẫu chủ đề cụ thể nào."
    ),
}
PERSONA_KEYS = list(TOPIC_PERSONAS.keys())

# Văn phong mặc định khi dịch bằng Gemini/Grok: KHÔNG còn là "dịch" theo nghĩa
# word-by-word/câu-đối-câu, mà là VIẾT LẠI HOÀN TOÀN (content rewrite) theo kiểu
# biên kịch video ngắn - giữ đúng kiến thức/dữ kiện gốc nhưng đổi >90% cách diễn
# đạt, có hook/mở đầu cuốn hút, gài open loop, chèn nhịp giữ chân người xem, và
# kết thúc bằng CTA tự nhiên. Đây là hướng đi DUY NHẤT từ nay (không còn chế độ
# dịch câu-đối-câu cũ song song) - style_notes của người dùng chỉ NỐI THÊM chi
# tiết riêng, không thay thế khối này.
CONTENT_REWRITER_INSTRUCTIONS = """
You are an award-winning YouTube Script Writer.

Your job is NOT translating.

Your job is rewriting narration.

The audience must believe this video was originally written in the target language.

====================================================

PRIMARY GOAL

Rewrite naturally.

Never translate literally.

Keep every fact.

Keep every number.

Keep every name.

Keep every event.

Keep every cause and effect.

Never invent information.

Never remove information.

====================================================

STYLE

Write exactly like a native narrator.

Natural spoken language.

Never sound like Google Translate.

Never sound like Wikipedia.

Never sound like textbook.

Never sound robotic.

====================================================

REWRITE LEVEL

Rewrite over 90%.

Different wording.

Different sentence structure.

Different information order if needed.

Merge ideas naturally.

Split ideas naturally.

Do whatever native speakers normally do.

====================================================

RHYTHM

Write for voice-over.

Easy to read.

Easy for TTS.

Natural pauses.

Short sentences preferred.

Avoid long nested grammar.

====================================================

EMOTION

Increase curiosity.

Increase surprise.

Increase storytelling.

Increase engagement.

WITHOUT changing any fact.

====================================================

NARRATION

Imagine you are talking directly to one viewer.

Not reading subtitles.

Not reading documents.

Talking.

====================================================

LOCALIZATION

Use expressions that native speakers actually use.

Do not preserve source language grammar.

Prioritize fluency over literal accuracy.

====================================================

SELF CHECK

Before returning:

Read every sentence.

If any sentence sounds translated,

rewrite it.

Repeat until it sounds native.

====================================================

OUTPUT

Return ONLY rewritten subtitles.

No markdown.

No explanation.

No numbering.

No timestamps.

Nothing except subtitles.
"""
# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are a Senior Script Writer.

You specialize in:

- YouTube Documentary
- Shorts
- TikTok
- Documentary Narration
- Viral Storytelling

You never translate.

You rewrite.

Your writing must sound completely native.

You always optimize for:

• retention

• curiosity

• storytelling

• natural TTS

• native narration

without changing any factual information.
"""


# ============================================================
# VIDEO OUTPUT METADATA PROMPT
# ============================================================
# Dùng khi AI cần tạo TIÊU ĐỀ + MÔ TẢ + HASHTAG từ tiêu đề gốc.
# Không đưa khối này vào prompt rewrite subtitle vì subtitle pipeline
# bắt buộc trả đúng số segment và chỉ được trả subtitle.
VIDEO_OUTPUT_PROMPT_NOTE = """
Bạn là chuyên gia xây dựng nội dung video đa ngôn ngữ.

NHIỆM VỤ:
Nhận TIÊU ĐỀ GỐC và chuyển thành nội dung hoàn chỉnh theo đúng NGÔN NGỮ ĐẦU RA.

QUY TẮC NGÔN NGỮ:
- Nếu có ngôn ngữ đầu ra, toàn bộ kết quả phải dùng đúng ngôn ngữ đó.
- Không tự ý trộn nhiều ngôn ngữ.
- Nếu chỉ định quốc gia/thị trường, dùng ngôn ngữ phù hợp với thị trường đó.
- Không mặc định ngôn ngữ là tiếng Việt.
- Tên riêng và thuật ngữ quốc tế chỉ giữ nguyên khi phù hợp với ngôn ngữ đích.

HIỂU CHỦ ĐỀ:
- Đọc và hiểu chính xác tiêu đề gốc trước khi viết.
- Tự xác định chủ đề dựa trên tiêu đề; không mặc định đây là lịch sử, khoa học hay bất kỳ lĩnh vực nào.
- Giữ đúng bản chất và ý chính của tiêu đề.
- Không dịch từng chữ một cách máy móc.
- Nếu tiêu đề có phong cách TikTok/Douyin/Short Video, hãy chuyển sang cách diễn đạt tự nhiên của thị trường đích.
- Không bịa số liệu, nhân vật, sự kiện, nguyên nhân, địa điểm hoặc chi tiết không được hỗ trợ bởi tiêu đề.
- Không đổi chủ đề và không thêm thông tin không liên quan.

TIÊU ĐỀ VIDEO:
- Chỉ tạo 1 tiêu đề chính.
- Tự nhiên như người bản địa.
- Dễ hiểu ngay khi đọc.
- Có yếu tố tò mò nhưng không clickbait sai sự thật.
- Ưu tiên từ khóa chính của chủ đề.
- Không bắt buộc dùng một công thức cố định như "Vì sao...?" hay "Bí mật...?".
- Chọn cách đặt tiêu đề phù hợp nhất với chính nội dung.

MÔ TẢ VIDEO:
- Viết khoảng 150-250 từ bằng đúng ngôn ngữ đầu ra.
- Mở đầu bằng 1-2 câu tạo tò mò, đặt vấn đề trực tiếp.
- Tiếp theo giới thiệu ngắn gọn video và những điều người xem sẽ khám phá.
- Có phần "📌 Nội dung chính:".
- Liệt kê khoảng 5-8 ý chính, logic, không lặp lại, bám sát chủ đề.
- Kết thúc bằng một đoạn ngắn giải thích vì sao chủ đề đáng tìm hiểu.
- CTA ở cuối phải tự nhiên và phù hợp với ngôn ngữ/thị trường/chủ đề.
- CTA có thể kêu gọi Like, Subscribe/Đăng ký, bật chuông hoặc theo dõi, nhưng không được máy móc và không dùng một câu cố định cho mọi video.

HASHTAG:
- Tạo 10-15 hashtag.
- Dùng đúng ngôn ngữ/thị trường mục tiêu.
- Ưu tiên từ khóa chính, chủ đề, khái niệm quan trọng và lĩnh vực liên quan.
- Không thêm hashtag không liên quan chỉ để đủ số lượng.

OUTPUT:
Trả về đúng cấu trúc sau, không thêm lời giải thích:
Tiêu đề video

[1 tiêu đề chính]

Mô tả video

[Đoạn mở đầu]

[Đoạn giới thiệu]

📌 Nội dung chính:

[Ý 1]
[Ý 2]
[Ý 3]
[Ý 4]
[Ý 5]
[Ý 6]
[Ý 7]

[Đoạn kết]

[CTA phù hợp]

#Hashtag1 #Hashtag2 #Hashtag3 #Hashtag4 #Hashtag5 #Hashtag6 #Hashtag7 #Hashtag8 #Hashtag9 #Hashtag10

TỰ KIỂM TRA TRƯỚC KHI TRẢ:
1. Đúng ngôn ngữ đầu ra 100%.
2. Chỉ có 1 tiêu đề.
3. Mô tả nằm trong khoảng 150-250 từ.
4. Có 5-8 ý chính.
5. Có CTA tự nhiên.
6. Có 10-15 hashtag liên quan.
7. Không bịa thông tin.
8. Không đổi chủ đề.
9. Không dịch cứng nhắc.
10. Văn phong tự nhiên như người bản địa.
"""


def build_video_metadata_prompt(original_title: str, target_lang: str) -> str:
    """Tạo prompt hoàn chỉnh cho AI viết title/description/hashtags đa ngôn ngữ.

    Hàm này độc lập với pipeline subtitle: không làm thay đổi số segment
    hoặc format <<<SEG>>> của các hàm dịch hiện có.
    """
    title = (original_title or "").strip()
    lang = (target_lang or "").strip()
    if not title:
        raise ValueError("original_title không được để trống")
    if not lang:
        raise ValueError("target_lang không được để trống")

    return (
        f"{VIDEO_OUTPUT_PROMPT_NOTE}\n\n"
        "============================================================\n"
        f"NGÔN NGỮ ĐẦU RA: {lang}\n"
        "TIÊU ĐỀ GỐC:\n"
        f"{title}\n"
        "============================================================\n"
        "Hãy xử lý tiêu đề trên và chỉ trả về kết quả theo đúng OUTPUT FORMAT."
    )

# ============================================================
# RETENTION ENGINE
# ============================================================

RETENTION_ENGINE = """
Whenever suitable,

slightly increase curiosity.

Delay small pieces of information.

Build anticipation.

Keep viewers watching.

Never invent facts.

Never exaggerate facts.
"""

# ============================================================
# HOOK ENGINE
# ============================================================

HOOK_ENGINE = """
If these are the first subtitles,

rewrite them into a stronger hook.

Create curiosity.

Open a question.

Create an information gap.

Never invent new facts.
"""

# ============================================================
# CTA ENGINE
# ============================================================

CTA_ENGINE = """
If these are the final subtitles,

rewrite the last sentence naturally.

Soft ending.

Natural CTA.

Invite viewers to continue watching or follow.

Do NOT create an extra subtitle.
"""

# ============================================================
# TTS ENGINE
# ============================================================

TTS_ENGINE = """
Optimize punctuation for speech.

Natural pauses.

Readable in one breath.

Avoid excessive commas.

Avoid awkward wording.
"""

# ============================================================
# SEGMENT ENGINE
# ============================================================

SEGMENT_ENGINE = """
You MUST return exactly the same number of subtitle segments.

Each segment is separated ONLY by:

<<<SEG>>>

Never merge output separators.

Never create extra segments.

Never remove segments.
"""

# ============================================================
# TIMESTAMP ENGINE
# ============================================================

TIMESTAMP_ENGINE = """
Input timestamps exist ONLY for pacing.

Never output timestamps.

Never mention timestamps.

Ignore them in the final answer.
"""

# Giữ tên cũ để tương thích ngược nếu có chỗ khác trong code còn tham chiếu.
_DEFAULT_REWRITE_STYLE = CONTENT_REWRITER_INSTRUCTIONS

def _persona_block(context: dict, persona_override: Optional[str] = None) -> str:
    """
    Chọn khối hướng dẫn văn phong THEO CHỦ ĐỀ (mục 5): ưu tiên `persona_override` nếu
    người dùng ép cứng 1 lựa chọn cụ thể; nếu không, dùng "category" mà build_video_context
    (Gemini) / build_video_context_grok (Grok) đã tự nhận diện từ transcript gốc; nếu cả 2
    đều không có, dùng persona "other" (giọng tự nhiên chung chung).
    """
    key = (persona_override or context.get("category") or "other").strip().lower()
    persona_text = TOPIC_PERSONAS.get(key, TOPIC_PERSONAS["other"])
    return f"\nPHONG CÁCH/GIỌNG ĐIỆU cần áp dụng khi viết lại: {persona_text}\n"


def _hook_cta_note(is_first_batch: bool, is_last_batch: bool) -> str:
    """
    Ghi chú thêm cho lô ĐẦU (cần hook mở đầu + open loop) và lô CUỐI (cần CTA tự nhiên) -
    chỉ áp dụng khi viết lại các dòng tương ứng nằm trong lô đó, KHÔNG thêm dòng mới (số
    dòng trả về vẫn phải khớp CHÍNH XÁC số dòng gửi vào, để không phá vỡ đồng bộ thời gian
    với video gốc).
    """
    parts = []
    if is_first_batch:
        parts.append(
            "Đây là NHỮNG DÒNG MỞ ĐẦU video: hãy viết lại (các) dòng đầu tiên thành 1 HOOK "
            "cuốn hút ngay từ giây đầu (gợi tò mò/đặt vấn đề bất ngờ) và cài 1 OPEN LOOP "
            "(hé lộ 1 phần, hứa hẹn sẽ giải đáp/tiết lộ tiếp ở phần sau) - vẫn PHẢI giữ đúng "
            "ý/dữ kiện của câu gốc, chỉ đổi CÁCH MỞ ĐẦU cho cuốn hút hơn, KHÔNG bịa thêm sự "
            "kiện không có thật."
        )
    if is_last_batch:
        parts.append(
            "Đây là NHỮNG DÒNG KẾT THÚC video: hãy để dòng cuối cùng khép lại bằng 1 lời "
            "CTA (call-to-action) TỰ NHIÊN, ngắn gọn, đúng giọng người dẫn chuyện (vd mời "
            "theo dõi/để lại bình luận/xem thêm...) - chỉ điều chỉnh nhẹ câu cuối, KHÔNG "
            "thêm hẳn 1 dòng CTA tách biệt (vẫn phải giữ đúng số dòng)."
        )
    return ("\n" + "\n".join(parts) + "\n") if parts else ""


# --- 5 "núm vặn" style cho GUI (Narrative Style / Audience / Speaking Speed /
# Creativity / Hook Level) - mỗi dict map giá trị GUI -> 1 câu chỉ dẫn ngắn, GỘP
# CHUNG thành 1 khối duy nhất (_style_dial_block) thay vì rải rác nhiều mục lặp
# lại như bản prompt cũ, để không làm phình prompt thêm. Giá trị "auto"/None =
# không chèn gì thêm, giữ hành vi mặc định của CONTENT_REWRITER_INSTRUCTIONS.
NARRATIVE_STYLES = {
    "documentary": "Kể theo phong cách PHIM TÀI LIỆU: trang trọng vừa phải, nhịp chậm rãi, nhấn vào dữ kiện/bối cảnh.",
    "storytelling": "Kể theo phong cách KỂ CHUYỆN (storytelling): có mở đầu-cao trào-kết, dẫn dắt cảm xúc người nghe.",
    "educational": "Kể theo phong cách GIẢNG GIẢI/EDUCATIONAL: rõ ràng, mạch lạc từng bước, ưu tiên dễ hiểu hơn kịch tính.",
    "casual_vlog": "Kể theo phong cách VLOG ĐỜI THƯỜNG: gần gũi, xưng hô thân mật, như đang nói chuyện trực tiếp với 1 người bạn.",
    "news_recap": "Kể theo phong cách BẢN TIN TÓM TẮT: súc tích, đi thẳng vào trọng tâm, ít hoa mỹ.",
}
AUDIENCES = {
    "beginner": "Đối tượng nghe là NGƯỜI MỚI/không có nền tảng: giải thích thuật ngữ bằng từ ngữ đơn giản, tránh biệt ngữ chuyên ngành.",
    "general": "Đối tượng nghe là ĐẠI CHÚNG: cân bằng giữa dễ hiểu và đủ chiều sâu, không cần giải thích quá cơ bản.",
    "expert": "Đối tượng nghe là NGƯỜI AM HIỂU chủ đề: có thể giữ nguyên thuật ngữ chuyên ngành, không cần giải thích lại khái niệm cơ bản.",
    "gen_z": "Đối tượng nghe là GIỚI TRẺ (Gen Z): văn phong trẻ trung, năng lượng cao, có thể dùng cách nói hiện đại (nhưng KHÔNG chèn tiếng lóng làm sai lệch nghĩa).",
}
SPEAKING_SPEEDS = {
    "slow": "Nhịp đọc CHẬM: câu ngắn, nhiều khoảng ngắt, mỗi câu chỉ mang đúng 1 ý.",
    "normal": "Nhịp đọc VỪA PHẢI: độ dài câu tự nhiên, xen kẽ câu ngắn/dài như hội thoại thật.",
    "fast": "Nhịp đọc NHANH, DỒN DẬP: câu ngắn liên tiếp, ít từ đệm, tạo cảm giác gấp gáp/cuốn.",
}
CREATIVITY_LEVELS = {
    "low": "Mức sáng tạo THẤP: viết lại tự nhiên nhưng bám sát cấu trúc câu gốc, hạn chế thêm thắt cách diễn đạt mới.",
    "medium": "Mức sáng tạo VỪA: viết lại thoải mái theo văn phong bản ngữ (đúng như CONTENT_REWRITER_INSTRUCTIONS mặc định).",
    "high": "Mức sáng tạo CAO: được phép thay đổi mạnh cấu trúc câu, thêm ẩn dụ/so sánh đời thường phù hợp để tăng độ cuốn, miễn KHÔNG đổi sự thật.",
}
HOOK_LEVELS = {
    "low": "Mức độ hook NHẸ: chỉ chỉnh câu mở đầu cho mượt hơn, không cần tạo kịch tính.",
    "medium": "Mức độ hook VỪA (mặc định): câu mở đầu tạo tò mò nhẹ theo đúng HOOK ENGINE.",
    "high": "Mức độ hook MẠNH: câu mở đầu PHẢI tạo cảm giác tò mò/bất ngờ rõ rệt, dùng dạng câu hỏi hoặc tuyên bố gây chú ý nếu phù hợp với dữ kiện gốc.",
}


def _style_dial_block(
    narrative_style: Optional[str] = None,
    audience: Optional[str] = None,
    speaking_speed: Optional[str] = None,
    creativity: Optional[str] = None,
    hook_level: Optional[str] = None,
) -> str:
    """Gộp 5 lựa chọn từ GUI (Narrative Style/Audience/Speaking Speed/Creativity/
    Hook Level) thành 1 khối chỉ dẫn NGẮN GỌN duy nhất. Giá trị None/"auto"/"" bị bỏ
    qua (không chèn dòng nào) để không ép model theo hướng người dùng chưa chọn."""
    lines = []
    for value, table in (
        (narrative_style, NARRATIVE_STYLES),
        (audience, AUDIENCES),
        (speaking_speed, SPEAKING_SPEEDS),
        (creativity, CREATIVITY_LEVELS),
        (hook_level, HOOK_LEVELS),
    ):
        if value and value != "auto" and value in table:
            lines.append(f"- {table[value]}")
    if not lines:
        return ""
    return "\nYÊU CẦU RIÊNG (do người dùng chọn trên giao diện, ƯU TIÊN cao):\n" + "\n".join(lines) + "\n"


def _retention_pacing_note() -> str:
    return (
        "\nMỗi dòng đầu vào có kèm mốc thời gian ước lượng dạng '[Ns]' (giây thứ N tính từ "
        "đầu video) CHỈ để bạn ước lượng nhịp video, TUYỆT ĐỐI KHÔNG in mốc thời gian này ra "
        "trong bản viết lại. Cứ khoảng mỗi 20-30 giây trôi qua, nếu gặp 1 dòng phù hợp, hãy "
        "khéo léo lồng 1 câu 'giữ chân người xem' ngắn (retention hook) vào NGAY ĐẦU dòng đó "
        "(không phải dòng nào cũng cần, tránh lặp lại máy móc, chỉ chèn khi mạch nội dung cho "
        "phép tự nhiên).\n"
    )


def _extract_json_block(text: str) -> str:
    """Bỏ hàng rào ```json ... ``` hoặc ``` ... ``` nếu model tự thêm vào, chỉ giữ JSON thô."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def build_video_context(
    client,
    model: str,
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    max_chars: int = 12000,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    Gọi Gemini 1 LẦN DUY NHẤT ở đầu quá trình dịch: đọc TOÀN BỘ transcript gốc,
    trả về JSON {"topic", "tone", "glossary"} để nhét vào MỌI batch dịch phía
    sau - tránh tình trạng dịch rời rạc từng lô dẫn đến sai thuật ngữ do không
    biết ngữ cảnh chung (vd 1 từ chuyên ngành xuất hiện xuyên suốt video nhưng
    bị dịch sai/không nhất quán giữa các lô vì mỗi lô không biết lô khác dịch gì).

    max_chars: giới hạn độ dài transcript gửi đi (tránh video quá dài vượt context
    window) - nếu vượt, chỉ lấy phần ĐẦU + GIỮA + CUỐI để vẫn nắm được mạch video.

    Lỗi ở bước này KHÔNG raise - trả về {} và để pipeline dịch tiếp bình thường
    (không có ngữ cảnh vẫn hơn là làm crash cả job vì 1 bước phụ trợ).
    """
    texts = [s.text.strip() for s in segments if s.text.strip()]
    full_text = "\n".join(texts)
    if not full_text:
        return {}
    if len(full_text) > max_chars:
        third = max_chars // 3
        full_text = (
            full_text[:third] + "\n...\n"
            + full_text[len(full_text) // 2 - third // 2: len(full_text) // 2 + third // 2]
            + "\n...\n" + full_text[-third:]
        )

    prompt = (
        f"Đây là toàn bộ (hoặc trích đoạn đại diện) lời thoại gốc ({source_lang}) của 1 video ngắn:\n\n"
        f"{full_text}\n\n"
        f"Trả lời DUY NHẤT 1 JSON hợp lệ (không markdown, không giải thích thêm), đúng cấu trúc:\n"
        '{"topic": "chủ đề chính của video, 1 câu ngắn", '
        '"tone": "giọng điệu/phong cách phù hợp khi thuyết minh lại (vd: hài hước, kịch tính, giải thích khoa học dễ hiểu...)", '
        f'"category": "PHẢI là 1 trong các giá trị: science, history, psychology, finance, technology, other - '
        f'chọn đúng nhất theo nội dung video", '
        f'"glossary": {{"thuật ngữ/tên riêng gốc": "cách dịch sang {target_lang} thống nhất xuyên suốt video"}}}}\n'
        "glossary CHỈ liệt kê thuật ngữ chuyên ngành/tên riêng/số liệu quan trọng LẶP LẠI nhiều lần "
        "(bỏ qua từ thông thường). Nếu không có, để glossary rỗng {}."
    )

    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            data = json.loads(_extract_json_block((resp.text or "").strip()))
            if isinstance(data, dict):
                if progress_cb:
                    progress_cb(0.0, f"✓ Đã phân tích ngữ cảnh video: {data.get('topic', '(không rõ)')}")
                return data
        except Exception as e:
            if progress_cb:
                progress_cb(0.0, f"⚠ Lấy ngữ cảnh video lỗi (lần {attempt + 1}/{max_retries}): {e}")
            time.sleep(retry_delay)

    if progress_cb:
        progress_cb(0.0, "⚠ Bỏ qua bước phân tích ngữ cảnh video (lỗi hết số lần thử) - vẫn tiếp tục dịch")
    return {}


def _format_context_block(context):

    if not context:
        return ""

    lines=[]

    keys=[
        "topic",
        "summary",
        "audience",
        "emotion",
        "pace",
        "tone",
        "story_style",
        "retention_style",
        "hook_style",
        "cta_style",
    ]

    for k in keys:

        if context.get(k):

            lines.append(f"- {k}: {context[k]}")

    glossary=context.get("glossary") or {}

    if glossary:

        gl="; ".join(
            f"{k}->{v}"
            for k,v in glossary.items()
        )

        lines.append(f"- glossary: {gl}")

    return "\n".join(lines)


def generate_script_from_video(
    video_path: str,
    target_lang: str,
    api_keys,
    model: str = DEFAULT_GEMINI_MODEL,
    narration_style: str = "neutral",     # "neutral" (khách quan) | "dramatic" (kịch tính/giật tít)
    max_retries: int = 3,
    retry_delay: float = 3.0,
    upload_timeout: float = 180.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[SubtitleSegment]:
    """Dành cho video KHÔNG CÓ LỜI THOẠI (chỉ có hành động/hình ảnh, có thể có nhạc
    nền/SFX): AI (Gemini) XEM TRỰC TIẾP file video (upload qua File API, không cần
    tách audio trước) để hiểu hành động đang diễn ra, rồi TỰ VIẾT 1 kịch bản lời
    dẫn/thuyết minh bằng target_lang, chia thành từng đoạn kèm mốc thời gian KHỚP
    với hành động trên màn hình.

    Kết quả trả về dùng THẲNG làm segments cho các bước lồng tiếng/phụ đề/xuất video
    tiếp theo - BỎ QUA HẲN bước tách thoại (whisper) VÀ bước dịch (kịch bản sinh ra
    đã sẵn ở ngôn ngữ đích). Xem core/pipeline.py:run() bước 1.

    narration_style:
      - "neutral": tường thuật KHÁCH QUAN, bám sát chính xác hành động/sự kiện đang
        diễn ra theo đúng trình tự thời gian, giọng văn trung lập kiểu tài liệu/thời
        sự, không suy đoán/bịa thêm chi tiết không có thật.
      - "dramatic": dẫn chuyện GIÀU CẢM XÚC, tạo kịch tính/tò mò/hồi hộp kiểu video
        viral mạng xã hội (có thể dùng câu hỏi tu từ, nhấn nhá) - nhưng vẫn phải bám
        sát ĐÚNG hành động thực tế trên màn hình, không bịa thêm tình tiết không có.

    KHÁC với các hàm build_video_context()/pick_hook_intro() (chỉ đọc TEXT phụ đề đã
    có sẵn) - hàm này gửi thẳng FILE VIDEO cho Gemini xem, nên cần thời gian upload +
    chờ Google xử lý xong (state ACTIVE) trước khi hỏi.

    Đây là bước THAY THẾ HẲN transcribe (không phải bước phụ trợ) - nếu thiếu API key
    hoặc AI không trả được kịch bản hợp lệ sau max_retries lần cho MỌI key, hàm RAISE
    lỗi (không có kịch bản thì không có gì để lồng tiếng/phụ đề tiếp theo).
    """
    try:
        from google import genai
    except ImportError as e:
        raise ImportError(
            "Cần cài đặt: pip install google-genai để dùng tính năng AI xem video viết kịch bản."
        ) from e

    if isinstance(api_keys, str):
        api_keys = [api_keys]
    keys = [k.strip() for k in (api_keys or []) if k and k.strip()]
    if not keys:
        raise ValueError(
            "Chế độ 'Video không có lời thoại - AI viết kịch bản' cần ít nhất 1 Gemini API key "
            "(xem https://aistudio.google.com/apikey)"
        )

    if narration_style == "dramatic":
        style_instruction = (
            "Viết kịch bản dẫn chuyện GIÀU CẢM XÚC, tạo kịch tính/tò mò/hồi hộp đúng kiểu video "
            "viral mạng xã hội (có thể dùng câu hỏi tu từ, nhấn nhá, gợi tò mò) - nhưng vẫn phải "
            "bám sát ĐÚNG hành động thực tế đang diễn ra trên màn hình, TUYỆT ĐỐI không bịa thêm "
            "tình tiết/nhân vật/sự kiện không có thật."
        )
    else:
        style_instruction = (
            "Viết kịch bản tường thuật KHÁCH QUAN, mô tả CHÍNH XÁC những hành động/sự kiện đang "
            "diễn ra trên màn hình theo đúng trình tự thời gian, giọng văn trung lập kiểu phóng "
            "sự/tài liệu, không thêm chi tiết bịa, không suy đoán cảm xúc/động cơ nhân vật nếu "
            "không thể hiện rõ ràng trên hình."
        )

    prompt = (
        f"Đây là 1 video KHÔNG CÓ LỜI THOẠI (chỉ có hành động/hình ảnh, có thể kèm nhạc nền). "
        f"Hãy XEM KỸ TOÀN BỘ video này từ đầu đến cuối, chia thành các đoạn theo hành động/sự "
        f"kiện diễn ra, và viết 1 kịch bản lời dẫn/thuyết minh bằng {target_lang} cho từng đoạn, "
        "bám sát ĐÚNG những gì đang xảy ra trên màn hình theo đúng trình tự thời gian thực tế "
        "của video.\n\n"
        f"{style_instruction}\n\n"
        "Mỗi đoạn kịch bản phải đủ NGẮN để đọc thành lời vừa khít trong đúng khung thời gian của "
        "đoạn đó (ước lượng khoảng 2-3 từ mỗi giây) - không viết dài hơn thời lượng đoạn cho phép. "
        "Các đoạn phải nối tiếp nhau theo thời gian, bao phủ gần hết thời lượng video, KHÔNG chồng "
        "lấn thời gian giữa các đoạn, KHÔNG bỏ sót những đoạn dài không có hành động gì (gộp vào "
        "đoạn liền kề nếu cần).\n\n"
        "Trả lời DUY NHẤT 1 JSON array hợp lệ (không markdown, không giải thích thêm), mỗi phần tử "
        'đúng cấu trúc: [{"start": <giây bắt đầu, số thực>, "end": <giây kết thúc, số thực>, '
        '"text": "<câu kịch bản>"}, ...]'
    )

    last_err: Optional[Exception] = None
    for key_idx, key in enumerate(keys):
        try:
            client = genai.Client(api_key=key)
        except Exception as e:
            last_err = e
            continue

        # Upload video qua File API - cần thiết cho file lớn/video dài, và Google cần
        # thời gian xử lý (chuyển trạng thái PROCESSING -> ACTIVE) trước khi model
        # có thể đọc được. Video quá ngắn/nhẹ Google vẫn xử lý qua luồng này, chỉ
        # nhanh hơn - không cần nhánh riêng cho file nhỏ.
        try:
            if progress_cb:
                progress_cb(0.05, f"Đang tải video lên Gemini (key #{key_idx + 1})...")
            video_file = client.files.upload(file=video_path)

            waited = 0.0
            poll_interval = 2.0
            while getattr(video_file, "state", None) is not None and str(video_file.state) not in (
                "ACTIVE", "FileState.ACTIVE",
            ):
                if str(getattr(video_file, "state", "")) in ("FAILED", "FileState.FAILED"):
                    raise RuntimeError("Google xử lý video thất bại (file state = FAILED).")
                if waited >= upload_timeout:
                    raise TimeoutError(f"Google xử lý video quá {upload_timeout:.0f}s mà chưa xong.")
                time.sleep(poll_interval)
                waited += poll_interval
                video_file = client.files.get(name=video_file.name)
                if progress_cb:
                    progress_cb(0.1, f"Google đang xử lý video... ({waited:.0f}s)")

            if progress_cb:
                progress_cb(0.2, "✓ Video đã sẵn sàng - AI đang xem và viết kịch bản...")
        except Exception as e:
            last_err = e
            if progress_cb:
                progress_cb(0.0, f"⚠ Upload video lỗi với key #{key_idx + 1} ({e}) - thử key khác...")
            continue

        for attempt in range(max_retries):
            try:
                resp = client.models.generate_content(model=model, contents=[video_file, prompt])
                data = json.loads(_extract_json_block((resp.text or "").strip()))
                if not isinstance(data, list) or not data:
                    raise ValueError("AI không trả về danh sách đoạn kịch bản hợp lệ.")

                segments: List[SubtitleSegment] = []
                for i, item in enumerate(data, start=1):
                    start = float(item.get("start"))
                    end = float(item.get("end"))
                    text = str(item.get("text") or "").strip()
                    if not text or end <= start:
                        continue
                    segments.append(SubtitleSegment(index=i, start=start, end=end, text=text))

                if not segments:
                    raise ValueError("AI trả về JSON nhưng không có đoạn kịch bản nào hợp lệ.")

                if progress_cb:
                    progress_cb(1.0, f"✓ AI đã viết xong kịch bản ({len(segments)} đoạn)")
                return segments
            except Exception as e:
                last_err = e
                if progress_cb:
                    progress_cb(
                        0.2, f"⚠ Viết kịch bản lỗi (key #{key_idx + 1}, lần {attempt + 1}/{max_retries}): {e}",
                    )
                time.sleep(retry_delay)

    raise RuntimeError(
        f"Không viết được kịch bản từ video sau khi thử hết {len(keys)} key. Lỗi cuối: {last_err}"
    )


def pick_hook_intro(
    segments: List[SubtitleSegment],
    target_lang: str,
    api_keys,
    model: str = DEFAULT_GEMINI_MODEL,
    max_retries: int = 2,
    max_chars: int = 12000,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Optional[dict]:
    """Gọi Gemini 1 LẦN để AI TỰ ĐỌC toàn bộ phụ đề ĐÃ DỊCH (kèm mốc thời gian), TỰ
    CHỌN 1 đoạn liên tục gây tò mò/bất ngờ/kịch tính NHẤT trong video để dùng làm
    Intro Hook (đoạn "cold open" đặt lên đầu video), ĐỒNG THỜI tự viết riêng 1 câu
    hook giật tít (KHÁC hẳn nguyên văn câu thoại gốc tại đoạn đó) để đè chữ lên khi
    dựng đoạn intro này.

    AI TỰ QUYẾT độ dài đoạn theo nội dung - chỉ gợi ý khung 3-20 giây cho hợp lý làm
    intro, KHÔNG ép cứng 1 con số cụ thể.

    Trả về {"start": float, "end": float, "hook_text": str} nếu thành công, hoặc
    None nếu hết key/hết lượt thử mà vẫn lỗi - để nơi gọi (core/pipeline.py:
    _maybe_add_hook_intro) tự bỏ qua bước Intro Hook, KHÔNG làm hỏng video chính.
    """
    if isinstance(api_keys, str):
        api_keys = [api_keys]
    keys = [k.strip() for k in (api_keys or []) if k and k.strip()]
    if not keys:
        return None

    lines = []
    for s in segments:
        text = (s.text or "").strip()
        if not text:
            continue
        lines.append(f"[{s.start:.1f}s-{s.end:.1f}s] {text}")
    transcript_block = "\n".join(lines)
    if not transcript_block:
        return None
    if len(transcript_block) > max_chars:
        transcript_block = transcript_block[:max_chars]

    prompt = (
        f"Đây là phụ đề ĐÃ DỊCH sang {target_lang} của 1 video ngắn, mỗi dòng kèm mốc thời gian "
        f"gốc trong video:\n\n{transcript_block}\n\n"
        "Hãy chọn ra 1 ĐOẠN LIÊN TỤC (mốc thời gian có thể lấy tuỳ ý trong phạm vi dữ liệu trên, "
        "không cần trùng khớp từng dòng) gây tò mò/bất ngờ/kịch tính NHẤT trong toàn bộ video - đoạn "
        "này sẽ được cắt ra đặt lên ĐẦU video làm phần mở màn kiểu \"cold open\" (giống phim mở đầu "
        "bằng đúng cảnh cao trào rồi mới quay lại kể từ đầu). Độ dài đoạn DO BẠN TỰ QUYẾT theo nội "
        "dung, hợp lý trong khoảng 3-20 giây - KHÔNG ép cứng 1 con số cụ thể, ưu tiên chọn đúng ranh "
        f"giới câu cho tự nhiên. Đồng thời viết 1 CÂU HOOK giật tít NGẮN GỌN (khác hẳn nguyên văn câu "
        f"thoại gốc tại đoạn đó, tối đa khoảng 18 từ) bằng {target_lang} để đè chữ lên đoạn intro này, "
        "tạo cảm giác tò mò khiến người xem phải xem tiếp.\n\n"
        "Trả lời DUY NHẤT 1 JSON hợp lệ (không markdown, không giải thích thêm), đúng cấu trúc:\n"
        '{"start": <giây bắt đầu, số thực>, "end": <giây kết thúc, số thực>, "hook_text": "<câu hook>"}'
    )

    from google import genai
    for key in keys:
        try:
            client = genai.Client(api_key=key)
        except Exception:
            continue
        for attempt in range(max_retries):
            try:
                resp = client.models.generate_content(model=model, contents=prompt)
                data = json.loads(_extract_json_block((resp.text or "").strip()))
                start = float(data.get("start"))
                end = float(data.get("end"))
                hook_text = str(data.get("hook_text") or "").strip()
                if hook_text and end > start and (end - start) >= 1.0:
                    if progress_cb:
                        progress_cb(1.0, f"✓ AI chọn đoạn intro hook {start:.1f}s-{end:.1f}s")
                    return {"start": start, "end": end, "hook_text": hook_text}
                if progress_cb:
                    progress_cb(0.0, f"⚠ AI trả kết quả chọn intro hook không hợp lệ (lần {attempt + 1}/{max_retries})")
            except Exception as e:
                if progress_cb:
                    progress_cb(0.0, f"⚠ Chọn đoạn intro hook lỗi (lần {attempt + 1}/{max_retries}): {e}")
                time.sleep(1.5)

    if progress_cb:
        progress_cb(0.0, "⚠ Bỏ qua Intro Hook (hết lượt thử mà vẫn không chọn được đoạn phù hợp)")
    return None


def translate_segments_gemini(
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    api_keys,
    model: str = DEFAULT_GEMINI_MODEL,
    batch_size: int = 30,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    max_retries: int = 4,
    retry_delay: float = 2.0,
    style_notes: Optional[str] = None,
    use_video_context: bool = True,
    continuity_tail_lines: int = 3,
    content_persona: Optional[str] = None,
    context_output: Optional[dict] = None,
) -> List[SubtitleSegment]:
    """
    Dịch bằng Gemini API CHÍNH THỨC (Google, https://aistudio.google.com/apikey) -
    gộp nhiều dòng vào 1 lần gọi (batch) để nhanh và rẻ hơn, giữ ngữ cảnh liền
    mạch giữa các câu liên tiếp (giống hệ thống "Content Rewriter" ở gemini_fastapi).

    HỖ TRỢ NHIỀU API KEY - truyền `api_keys` là 1 chuỗi (1 key) hoặc list nhiều
    key: XOAY VÒNG (round-robin) giữa các lô dịch để chia đều tải, và tự động
    chuyển sang key kế tiếp nếu key đang dùng bị rate-limit (HTTP 429/quota) hoặc
    bị từ chối (401/403) - phù hợp khi dùng nhiều API key MIỄN PHÍ (mỗi key có
    quota riêng theo ngày) để cộng dồn quota cho khối lượng dịch lớn.

    Cài đặt: pip install google-genai

    style_notes/content_persona/use_video_context/continuity_tail_lines: xem
    translate_segments_grok (cùng cơ chế).

    QUAN TRỌNG: nếu CẢ danh sách key đều lỗi THẬT SỰ (sai key, hết quota, model
    không tồn tại, mất mạng...) sau khi đã thử hết max_retries lần - hàm RAISE
    lỗi ngay lập tức (không chia đôi batch mãi mãi, vì chia nhỏ không sửa được
    lỗi key/mạng, chỉ khiến quá trình "treo" rất lâu mà không báo lỗi rõ ràng).
    """
    try:
        from google import genai
    except ImportError as e:
        raise ImportError(
            "Cần cài đặt: pip install google-genai để dùng dịch bằng Gemini."
        ) from e

    if isinstance(api_keys, str):
        api_keys = [api_keys]
    keys = [k.strip() for k in (api_keys or []) if k and k.strip()]
    if not keys:
        raise ValueError(
            "translation_method='gemini' cần ít nhất 1 Gemini API key (xem https://aistudio.google.com/apikey)"
        )

    _clients = {}

    def _client_for(key: str):
        if key not in _clients:
            _clients[key] = genai.Client(api_key=key)
        return _clients[key]

    # --- Bước 0: phân tích ngữ cảnh toàn video - thử LẦN LƯỢT từng key tới khi
    # có 1 key dùng được (không cần đúng thứ tự round-robin như lúc dịch chính,
    # đây chỉ chạy 1 lần duy nhất ở đầu).
    video_context: dict = {}
    if use_video_context:
        if progress_cb:
            progress_cb(0.0, "Đang phân tích ngữ cảnh toàn video trước khi dịch...")
        for key in keys:
            try:
                video_context = build_video_context(
                    _client_for(key), model, segments, source_lang, target_lang, progress_cb=progress_cb,
                )
                if video_context:
                    break
            except Exception as e:
                if progress_cb:
                    progress_cb(0.0, f"⚠ Lỗi lấy ngữ cảnh video với 1 key ({e}) - thử key khác...")
                continue
    context_block = _format_context_block(video_context)

    # Trả context về cho Pipeline nếu caller cung cấp dict.
    # Không cung cấp thì hành vi cũ giữ nguyên.
    if context_output is not None:
        context_output.clear()
        context_output.update(video_context)

    SEP = "\n<<<SEG>>>\n"
    _rr_state = {"idx": 0}
    style_block = f"\n{CONTENT_REWRITER_INSTRUCTIONS}\n" + _persona_block(video_context, content_persona)
    if style_notes and style_notes.strip():
        style_block += (
            f"\nYêu cầu thêm về văn phong/kịch bản (BẮT BUỘC tuân theo khi dịch/viết lại):\n"
            f"{style_notes.strip()}\n"
        )

    def _call_gemini(prompt: str) -> str:
        """Gọi 1 lần tới Gemini, tự xoay vòng qua các key nếu key hiện tại lỗi/hết quota."""
        start = _rr_state["idx"]
        _rr_state["idx"] = (start + 1) % len(keys)   # lô kế tiếp bắt đầu từ key khác
        last_err: Optional[Exception] = None

        for offset in range(len(keys)):
            key_idx = (start + offset) % len(keys)
            key = keys[key_idx]
            try:
                resp = _client_for(key).models.generate_content(model=model, contents=prompt)
                return (resp.text or "")
            except Exception as e:
                text = str(e).lower()
                is_quota = "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text
                is_auth = "401" in text or "403" in text or "permission" in text or "api key not valid" in text
                if is_quota or is_auth:
                    last_err = e
                    if progress_cb:
                        reason = "hết quota (429)" if is_quota else "bị từ chối (401/403 - sai key hoặc hết quyền)"
                        progress_cb(0.0, f"⚠ Gemini key #{key_idx + 1} {reason} - chuyển key kế tiếp...")
                    continue
                last_err = e
                continue

        raise RuntimeError(f"Cả {len(keys)} Gemini API key đều lỗi/hết quota. Lỗi cuối: {last_err}")

    def _translate_batch(
        texts: List[str],
        starts: List[float],
        tail_text: str = "",
        depth: int = 0,
        is_first_batch: bool = False,
        is_last_batch: bool = False,
    ) -> List[str]:
        if not texts:
            return []

        tail_block = ""
        if tail_text:
            tail_block = f"""

==========================
ĐOẠN TRƯỚC

{tail_text}

Đây chỉ là ngữ cảnh.

KHÔNG được dịch lại.

KHÔNG được trả lại.

==========================

"""
        pacing_block = _retention_pacing_note()
        hook_cta_block = _hook_cta_note(is_first_batch, is_last_batch)
        lines_with_ts = SEP.join(f"<{int(s)}s> {t}" for s, t in zip(starts, texts))

        prompt = f"""
        {SYSTEM_PROMPT}

        {RETENTION_ENGINE}

        {TTS_ENGINE}

        {SEGMENT_ENGINE}

        {TIMESTAMP_ENGINE}

        {HOOK_ENGINE if is_first_batch else ""}

        {CTA_ENGINE if is_last_batch else ""}

        ==========================================================
        Dịch/viết lại từ {source_lang} sang {target_lang}. Trả về ĐÚNG {len(texts)}
        câu, mỗi câu cách nhau bằng dòng '<<<SEG>>>', ĐÚNG thứ tự, KHÔNG thêm số
        thứ tự, KHÔNG giải thích, KHÔNG in lại mốc thời gian '<Ns>' trong kết quả.
        {context_block}
        {style_block}
        {pacing_block}
        {hook_cta_block}
        {tail_block}
        ==========================================================
        CÁC CÂU CẦN DỊCH/VIẾT LẠI:
        {lines_with_ts}
        """

        last_err: Optional[Exception] = None
        is_mismatch = False
        for attempt in range(max_retries):
            try:
                out_text = (_call_gemini(prompt) or "").strip()
                parts = [p.strip() for p in out_text.split("<<<SEG>>>")]
                if len(parts) > len(texts):
                    parts = [p for p in parts if p]
                if len(parts) == len(texts):
                    return parts
                last_err = ValueError(f"Gemini trả về {len(parts)} dòng, cần {len(texts)} dòng.")
                is_mismatch = True
            except Exception as e:
                last_err = e
                is_mismatch = False
            if progress_cb:
                progress_cb(0.0, f"⚠ Retry {attempt + 1}/{max_retries}: {last_err}")
            time.sleep(retry_delay * (attempt + 1))

        if is_mismatch and len(texts) > 1:
            mid = len(texts) // 2
            return (
                _translate_batch(texts[:mid], starts[:mid], tail_text, depth + 1,
                                  is_first_batch=is_first_batch, is_last_batch=False)
                + _translate_batch(texts[mid:], starts[mid:], tail_text, depth + 1,
                                    is_first_batch=False, is_last_batch=is_last_batch)
            )
        if is_mismatch:
            return texts

        raise RuntimeError(f"Dịch bằng Gemini thất bại sau {max_retries} lần thử (đã xoay vòng {len(keys)} key): {last_err}")

    out: List[SubtitleSegment] = []
    total_batches = max(1, (len(segments) + batch_size - 1) // batch_size)
    tail_text = ""  # vài câu dịch cuối của lô trước, mang sang lô sau để giữ mạch văn phong
    for b in range(total_batches):
        chunk = segments[b * batch_size: (b + 1) * batch_size]
        texts = [seg.text.strip() for seg in chunk]
        starts = [seg.start for seg in chunk]
        durations = [max(0.3, seg.end - seg.start) for seg in chunk]
        if progress_cb:
            progress_cb(b / total_batches, f"Đang gửi lô {b + 1}/{total_batches} tới Gemini...")
        translated_texts = _translate_batch(
            texts, starts, tail_text,
            is_first_batch=(b == 0), is_last_batch=(b == total_batches - 1),
        )
        translated_texts = _enforce_char_budget(translated_texts, durations, target_lang)
        for seg, tr in zip(chunk, translated_texts):
            out.append(SubtitleSegment(
                index=seg.index, start=seg.start, end=seg.end,
                text=tr or seg.text, gender=seg.gender, speaker_id=seg.speaker_id,
            ))
        if continuity_tail_lines > 0 and translated_texts:
            tail_text = "\n".join(translated_texts[-continuity_tail_lines:])
        if progress_cb:
            progress_cb((b + 1) / total_batches, f"Đang dịch (Gemini) lô {b + 1}/{total_batches}")

    return out


DEFAULT_GROK_MODEL = "grok-4.5"
GROK_BASE_URL = "https://api.x.ai/v1/chat/completions"


def build_video_context_grok(
    api_keys: List[str],
    model: str,
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    max_chars: int = 12000,
    timeout: float = 30.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """
    Bản Grok của build_video_context (Gemini): gọi Grok 1 LẦN ở đầu quá trình dịch
    để đọc toàn bộ transcript gốc, trả về JSON {"topic", "tone", "category", "glossary"}
    dùng chung cho mọi lô dịch phía sau. Lỗi ở bước này KHÔNG raise - trả về {} và để
    pipeline dịch tiếp bình thường bằng persona mặc định "other".
    """
    import requests

    texts = [s.text.strip() for s in segments if s.text.strip()]
    full_text = "\n".join(texts)
    if not full_text:
        return {}
    if len(full_text) > max_chars:
        third = max_chars // 3
        full_text = (
            full_text[:third] + "\n...\n"
            + full_text[len(full_text) // 2 - third // 2: len(full_text) // 2 + third // 2]
            + "\n...\n" + full_text[-third:]
        )

    prompt = (f"""
    Bạn là Senior Content Strategist.

    Bạn sẽ đọc toàn bộ transcript của video.

    Mục tiêu KHÔNG phải dịch.

    Mục tiêu là giúp một Script Writer khác hiểu toàn bộ video trước khi viết lại.

    ================================================

    Hãy phân tích video này.

    Trả về DUY NHẤT JSON.

    Không markdown.

    Không giải thích.

    ================================================

    JSON:

    {{
        "topic":"",

        "summary":"",

        "category":"",

        "audience":"",

        "emotion":"",

        "pace":"",

        "tone":"",

        "story_style":"",

        "retention_style":"",

        "hook_style":"",

        "cta_style":"",

        "glossary":{{}}
    }}

    ================================================

    Ý nghĩa từng trường

    topic

    → chủ đề chính.

    summary

    → tóm tắt video trong 3 câu.

    category

    Chỉ được chọn:

    science

    history

    technology

    finance

    psychology

    other

    audience

    Ví dụ

    General Audience

    Kids

    Teen

    Adults

    Movie Fans

    Crime Fans

    History Lovers

    ...

    emotion

    Ví dụ

    Curious

    Dark

    Funny

    Suspense

    Inspirational

    Emotional

    Documentary

    pace

    Slow

    Medium

    Fast

    Very Fast

    tone

    Ví dụ

    Friendly

    Professional

    Excited

    Calm

    Serious

    story_style

    Ví dụ

    Storytelling

    Explainer

    Documentary

    Narration

    Movie Recap

    Reaction

    Educational

    retention_style

    Mô tả cách giữ chân người xem.

    hook_style

    Mô tả kiểu hook phù hợp.

    cta_style

    Mô tả CTA phù hợp.

    glossary

    Liệt kê

    - tên riêng

    - thuật ngữ

    - địa danh

    - tổ chức

    - công nghệ

    - từ chuyên ngành

    cần giữ thống nhất.

    ================================================

    Transcript

    {full_text}

    """
    )

    keys = [k.strip() for k in api_keys if k and k.strip()]
    if not keys:
        return {}

    for attempt in range(max_retries):
        for key in keys:
            try:
                resp = requests.post(
                    GROK_BASE_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "Bạn là biên tập viên phân tích nội dung video ngắn."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    timeout=timeout,
                )
                resp.raise_for_status()
                out_text = resp.json()["choices"][0]["message"]["content"] or ""
                data = json.loads(_extract_json_block(out_text.strip()))
                if isinstance(data, dict):
                    if progress_cb:
                        progress_cb(0.0, f"✓ Đã phân tích ngữ cảnh video: {data.get('topic', '(không rõ)')}")
                    return data
            except Exception as e:
                if progress_cb:
                    progress_cb(0.0, f"⚠ Lấy ngữ cảnh video (Grok) lỗi: {e}")
                continue
        time.sleep(retry_delay)

    if progress_cb:
        progress_cb(0.0, "⚠ Bỏ qua bước phân tích ngữ cảnh video (lỗi hết số lần thử) - vẫn tiếp tục dịch")
    return {}


def translate_segments_grok(
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    api_keys: List[str],
    model: str = DEFAULT_GROK_MODEL,
    batch_size: int = 30,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    max_retries: int = 4,
    retry_delay: float = 2.0,
    timeout: float = 30.0,
    style_notes: Optional[str] = None,
    use_video_context: bool = True,
    content_persona: Optional[str] = None,
) -> List[SubtitleSegment]:
    """
    Viết lại hoàn toàn bằng Grok (xAI API), gộp nhiều dòng vào 1 lần gọi (batch) giống Gemini
    để nhanh hơn và giữ ngữ cảnh liền mạch giữa các câu liên tiếp. Áp dụng ĐẦY ĐỦ hệ
    thống "Content Rewriter" giống Gemini (xem CONTENT_REWRITER_INSTRUCTIONS, TOPIC_PERSONAS,
    hook mở đầu/CTA kết thúc, retention hook theo mốc thời gian).

    HỖ TRỢ NHIỀU API KEY (vd 5 key) - xoay vòng (round-robin) giữa các lô dịch để
    chia đều tải, và tự động chuyển sang key kế tiếp trong danh sách nếu key đang
    dùng bị rate-limit (HTTP 429) hoặc lỗi tạm thời khác.

    style_notes: ghi chú/yêu cầu thêm về văn phong, nhịp điệu, phong cách kịch bản...
    do người dùng tự nhập, được nối THÊM vào sau CONTENT_REWRITER_INSTRUCTIONS.

    content_persona: ép cứng 1 persona theo chủ đề (xem TOPIC_PERSONAS). None = tự động
    theo "category" nhận diện được từ build_video_context_grok.

    QUAN TRỌNG: nếu CẢ danh sách key đều lỗi THẬT SỰ (sai key, model không tồn tại,
    mất mạng...) sau khi đã thử hết max_retries lần - hàm RAISE lỗi ngay lập tức
    (không chia đôi batch mãi mãi). Chỉ chia đôi batch khi lỗi là LỆCH SỐ DÒNG
    (model trả về không đúng số câu) - vì đó là lỗi có thể cải thiện bằng cách
    thu nhỏ batch, còn lỗi mạng/key thì chia nhỏ không giúp ích gì, chỉ khiến quá
    trình "treo" rất lâu (có thể hàng giờ) mà không có thông báo rõ ràng.
    """
    import requests

    keys = [k.strip() for k in api_keys if k and k.strip()]
    if not keys:
        raise ValueError(
            "translation_method='grok' cần ít nhất 1 Grok API key (xem https://console.x.ai)"
        )

    # --- Bước 0: phân tích ngữ cảnh toàn video (chủ đề/giọng điệu/glossary/category) ---
    video_context: dict = {}
    if use_video_context:
        if progress_cb:
            progress_cb(0.0, "Đang phân tích ngữ cảnh toàn video trước khi dịch...")
        video_context = build_video_context_grok(
            keys, model, segments, source_lang, target_lang,
            timeout=timeout, progress_cb=progress_cb,
        )
    context_block = _format_context_block(video_context)

    SEP = "\n<<<SEG>>>\n"
    _rr_state = {"idx": 0}
    style_block = f"\n{CONTENT_REWRITER_INSTRUCTIONS}\n" + _persona_block(video_context, content_persona)
    if style_notes and style_notes.strip():
        style_block += (
            f"\nYêu cầu thêm về văn phong/kịch bản (BẮT BUỘC tuân theo khi dịch/viết lại):\n"
            f"{style_notes.strip()}\n"
        )

    def _call_grok(prompt: str) -> str:
        """Gọi 1 lần tới Grok, tự xoay vòng qua các key nếu key hiện tại lỗi/hết quota."""
        start = _rr_state["idx"]
        _rr_state["idx"] = (start + 1) % len(keys)   # lô kế tiếp bắt đầu từ key khác
        last_err: Optional[Exception] = None

        for offset in range(len(keys)):
            key_idx = (start + offset) % len(keys)
            key = keys[key_idx]
            try:
                resp = requests.post(
                    GROK_BASE_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "Bạn là biên kịch viết lại lời thoại video ngắn, tự nhiên và cuốn hút."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    timeout=timeout,
                )
                if resp.status_code == 429:
                    # Key này hết quota miễn phí/bị rate-limit - thử ngay key kế tiếp
                    last_err = RuntimeError(f"key #{key_idx + 1} bị rate limit (429)")
                    if progress_cb:
                        progress_cb(0.0, f"⚠ Grok key #{key_idx + 1} hết quota (429) - chuyển key #{(key_idx % len(keys)) + 2 if key_idx + 1 < len(keys) else 1}...")
                    continue
                if resp.status_code in (401, 403):
                    last_err = RuntimeError(f"key #{key_idx + 1} bị từ chối (HTTP {resp.status_code} - sai key hoặc hết quyền)")
                    continue
                if resp.status_code == 404:
                    # Model không tồn tại/không có quyền dùng - đổi key không giúp ích gì,
                    # nhưng vẫn thử các key khác phòng trường hợp chỉ 1 key bị giới hạn model.
                    last_err = RuntimeError(f"model '{model}' không tồn tại hoặc key #{key_idx + 1} không có quyền dùng (HTTP 404)")
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"] or ""
            except Exception as e:
                last_err = e
                continue

        raise RuntimeError(f"Cả {len(keys)} Grok API key đều lỗi/hết quota. Lỗi cuối: {last_err}")

    def _translate_batch(
        texts: List[str], starts: List[float], depth: int = 0,
        is_first_batch: bool = False, is_last_batch: bool = False,
    ) -> List[str]:
        if not texts:
            return []
        pacing_block = _retention_pacing_note()
        hook_cta_block = _hook_cta_note(is_first_batch, is_last_batch)
        lines_with_ts = SEP.join(f"[{s:.0f}s] {t}" for s, t in zip(starts, texts))
        prompt = (
            f"Viết lại hoàn toàn các câu phụ đề sau từ {source_lang} sang {target_lang}. "
            f"Mỗi câu cách nhau bằng dòng '<<<SEG>>>'. Trả về ĐÚNG {len(texts)} câu đã viết lại, "
            f"theo ĐÚNG thứ tự, mỗi câu cách nhau CŨNG bằng dòng '<<<SEG>>>', KHÔNG thêm số thứ tự, "
            f"KHÔNG thêm giải thích, KHÔNG thêm câu thừa nào khác ngoài bản viết lại, KHÔNG in lại "
            f"mốc thời gian '[Ns]' trong kết quả."
            + context_block + style_block + pacing_block + hook_cta_block
            + "\n\nCÁC CÂU CẦN VIẾT LẠI:\n" + lines_with_ts
        )
        last_err: Optional[Exception] = None
        is_mismatch = False
        for attempt in range(max_retries):
            try:
                out_text = (_call_grok(prompt) or "").strip()
                parts = [p.strip() for p in out_text.split("<<<SEG>>>")]
                parts = [p for p in parts if p != ""] if len(parts) > len(texts) else parts
                if len(parts) == len(texts):
                    return parts
                last_err = ValueError(f"Grok trả về {len(parts)} dòng, cần {len(texts)} dòng - không khớp")
                is_mismatch = True
            except Exception as e:
                last_err = e
                is_mismatch = False
            if progress_cb:
                progress_cb(
                    0.0,
                    f"⚠ Grok lỗi (lô {len(texts)} câu, lần thử {attempt + 1}/{max_retries}): {last_err} - đang thử lại...",
                )
            time.sleep(retry_delay * (attempt + 1))

        if is_mismatch and len(texts) > 1:
            # Chỉ chia đôi khi lỗi LỆCH SỐ DÒNG - KHÔNG chia đôi khi lỗi mạng/key/model
            # (chia nhỏ không sửa được lỗi đó, chỉ lặp lại lỗi y hệt hàng trăm lần -> treo
            # rất lâu như đã gặp trước đây).
            if progress_cb:
                progress_cb(0.0, f"Chia đôi lô {len(texts)} câu để thử lại (lệch số dòng)...")
            mid = len(texts) // 2
            return (
                _translate_batch(texts[:mid], starts[:mid], depth + 1,
                                  is_first_batch=is_first_batch, is_last_batch=False)
                + _translate_batch(texts[mid:], starts[mid:], depth + 1,
                                    is_first_batch=False, is_last_batch=is_last_batch)
            )
        if is_mismatch:
            return texts  # batch 1 câu vẫn lệch dòng -> giữ nguyên bản gốc

        # Lỗi THẬT SỰ (key/model/mạng) đã hết số lần thử -> báo lỗi ngay lập tức.
        raise RuntimeError(f"Dịch bằng Grok thất bại sau {max_retries} lần thử (đã xoay vòng {len(keys)} key): {last_err}")

    out: List[SubtitleSegment] = []
    total_batches = max(1, (len(segments) + batch_size - 1) // batch_size)
    for b in range(total_batches):
        chunk = segments[b * batch_size: (b + 1) * batch_size]
        texts = [seg.text.strip() for seg in chunk]
        starts = [seg.start for seg in chunk]
        durations = [max(0.3, seg.end - seg.start) for seg in chunk]
        if progress_cb:
            progress_cb(b / total_batches, f"Đang gửi lô {b + 1}/{total_batches} tới Grok...")
        translated_texts = _translate_batch(
            texts, starts, is_first_batch=(b == 0), is_last_batch=(b == total_batches - 1),
        )
        translated_texts = _enforce_char_budget(translated_texts, durations, target_lang)
        for seg, tr in zip(chunk, translated_texts):
            out.append(SubtitleSegment(
                index=seg.index, start=seg.start, end=seg.end,
                text=tr or seg.text, gender=seg.gender, speaker_id=seg.speaker_id,
            ))
        if progress_cb:
            progress_cb((b + 1) / total_batches, f"Đang dịch (Grok) lô {b + 1}/{total_batches}")

    return out


GEMINI_FASTAPI_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_GEMINI_FASTAPI_MODEL = "gemini-3.6-flash"


def _openai_compatible_error_detail(resp) -> str:
    """Read useful error text from FastAPI-style or OpenAI-style JSON responses."""
    try:
        payload = resp.json()
    except Exception:
        return (getattr(resp, "text", "") or "").strip()[:600]
    if not isinstance(payload, dict):
        return str(payload)[:600]
    if payload.get("detail"):
        return str(payload["detail"])[:600]
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:600]
    if error:
        return str(error)[:600]
    return str(payload)[:600]


def build_video_context_gemini_fastapi(
    base_url: str,
    model: str,
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    api_key: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 3.0,
    max_chars: int = 12000,
    timeout: float = 60.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """Bản Gemini Web2API (server local, wrap Gemini web) của build_video_context: gọi
    1 LẦN ở đầu quá trình dịch để đọc toàn bộ transcript gốc, trả về JSON {"topic",
    "tone", "category", "glossary"} dùng chung cho mọi lô dịch phía sau. Lỗi ở bước này
    KHÔNG raise - trả về {} và để pipeline dịch tiếp bình thường bằng persona mặc định."""
    import requests

    texts = [s.text.strip() for s in segments if s.text.strip()]
    full_text = "\n".join(texts)
    if not full_text:
        return {}
    if len(full_text) > max_chars:
        third = max_chars // 3
        full_text = (
            full_text[:third] + "\n...\n"
            + full_text[len(full_text) // 2 - third // 2: len(full_text) // 2 + third // 2]
            + "\n...\n" + full_text[-third:]
        )

    prompt = (
        f"Đây là toàn bộ (hoặc trích đoạn đại diện) lời thoại gốc ({source_lang}) của 1 video ngắn:\n\n"
        f"{full_text}\n\n"
        f"Trả lời DUY NHẤT 1 JSON hợp lệ (không markdown, không giải thích thêm), đúng cấu trúc:\n"
        '{"topic": "chủ đề chính của video, 1 câu ngắn", '
        '"tone": "giọng điệu/phong cách phù hợp khi thuyết minh lại", '
        '"category": "PHẢI là 1 trong: science, history, psychology, finance, technology, other", '
        f'"glossary": {{"thuật ngữ/tên riêng gốc": "cách dịch sang {target_lang} thống nhất xuyên suốt video"}}, '
        f'"note_title": "1 tiêu đề giật tít bằng {target_lang} để đăng video này (dưới 150 ký tự, KHÔNG chèn hashtag)", '
        f'"note_title_alternatives": ["2-3 tiêu đề khác bằng {target_lang}, mỗi cái 1 hướng khác nhau"], '
        f'"note_description": "1 đoạn mô tả video bằng {target_lang} để đăng kèm video (KHÔNG chèn hashtag vào đây)", '
        f'"note_hashtags": ["5-8 hashtag liên quan bằng {target_lang} hoặc tiếng Anh phổ biến, KHÔNG kèm dấu #"]}}\n'
        "glossary CHỈ liệt kê thuật ngữ chuyên ngành/tên riêng/số liệu quan trọng LẶP LẠI nhiều lần. "
        "Nếu không có, để glossary rỗng {}."
    )

    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Bạn là biên tập viên phân tích nội dung video ngắn."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=timeout,
            )
            if not resp.ok:
                # resp.raise_for_status() một mình chỉ cho ra "502 Bad Gateway" - không nói
                # LÝ DO thật sự phía sau (Gemini Web2API thường trả kèm {"detail": "..."} giải
                # thích lỗi thật từ Gemini web: hết quota, session hỏng, bị chặn...). Đọc thẳng
                # body ở đây để log ra lý do thật thay vì chỉ có mã lỗi HTTP chung chung.
                detail = _openai_compatible_error_detail(resp)
                raise RuntimeError(
                    f"HTTP {resp.status_code} {resp.reason}" + (f" - chi tiết từ server: {detail}" if detail else "")
                )
            out_text = resp.json()["choices"][0]["message"]["content"] or ""
            data = json.loads(_extract_json_block(out_text.strip()))
            if isinstance(data, dict):
                if progress_cb:
                    progress_cb(0.0, f"✓ Đã phân tích ngữ cảnh video: {data.get('topic', '(không rõ)')}")
                return data
        except Exception as e:
            if progress_cb:
                progress_cb(0.0, f"⚠ Lấy ngữ cảnh video (Gemini Web2API) lỗi (lần {attempt + 1}/{max_retries}): {e}")
            err_text = str(e)
            if "429" in err_text or "Too Many Requests" in err_text or "Unknown API error code" in err_text:
                # 429 hoặc sự cố backend tạm thời phía Google (vd lỗi 1096) - chờ lâu hơn
                # hẳn backoff thường, vì báo cáo cộng đồng cho thấy thường tự hết sau vài phút.
                time.sleep(20.0 + attempt * 10.0 + random.uniform(0, 10.0))
            else:
                time.sleep(retry_delay * (attempt + 1))  # backoff tăng dần: 3s, 6s, 9s...

    if progress_cb:
        progress_cb(0.0, "⚠ Bỏ qua bước phân tích ngữ cảnh video (lỗi hết số lần thử) - vẫn tiếp tục dịch")
    return {}


def translate_segments_gemini_fastapi(
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    base_url: str = GEMINI_FASTAPI_DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    model: str = DEFAULT_GEMINI_FASTAPI_MODEL,
    batch_size: int = 18,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    max_retries: int = 4,
    retry_delay: float = 2.0,
    timeout: float = 240.0,
    style_notes: Optional[str] = None,
    use_video_context: bool = True,
    content_persona: Optional[str] = None,
    narrative_style: Optional[str] = None,
    audience: Optional[str] = None,
    speaking_speed: Optional[str] = None,
    creativity: Optional[str] = None,
    hook_level: Optional[str] = None,
    inter_batch_delay_min: float = 10.0,
    inter_batch_delay_max: float = 25.0,
    context_output: Optional[dict] = None,
) -> List[SubtitleSegment]:
    """
    Viết lại hoàn toàn bằng Gemini Web2API (backend gemini-web2api) - 1
    server HTTP local, gọi endpoint OpenAI-compatible '/v1/chat/completions'. Cho
    phép dùng Gemini qua cookie web (miễn phí), không cần API key trả phí của Google.

    Áp dụng ĐẦY ĐỦ hệ thống "Content Rewriter" giống Gemini API/Grok (xem
    CONTENT_REWRITER_INSTRUCTIONS, TOPIC_PERSONAS, hook mở đầu/CTA kết thúc, retention
    hook theo mốc thời gian).

    base_url: địa chỉ server Gemini Web2API đang chạy, vd "http://127.0.0.1:8000".
    api_key: CHỈ cần nếu server bật xác thực (api_keys trong cấu hình Web2API khác
    null) - để trống nếu server không yêu cầu.

    Nếu server KHÔNG kết nối được (chưa chạy) hoặc lỗi liên tục sau max_retries lần,
    hàm RAISE lỗi ngay lập tức với thông báo rõ ràng thay vì "treo" âm thầm.
    """
    import requests

    if not base_url or not base_url.strip():
        raise ValueError("translation_method='gemini_fastapi' cần truyền base_url (vd http://127.0.0.1:8000)")
    base_url = base_url.strip()
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    # --- Bước 0: kiểm tra nhanh server có đang chạy không, báo lỗi rõ ràng ngay từ đầu
    # thay vì để người dùng chờ hết max_retries*batch lần rồi mới biết lý do. ---
    try:
        from core.gemini_fastapi_server import check_server_health
        ok, health_msg = check_server_health(base_url, timeout=5.0)
        if progress_cb:
            progress_cb(0.0, f"Kiểm tra Gemini Web2API: {health_msg}")
        if not ok and "CHƯA CHẠY" in health_msg:
            raise RuntimeError(
                f"Gemini Web2API CHƯA CHẠY tại {base_url}. "
                "Hãy khởi động server (hoặc bật 'Tự khởi động Gemini Web2API cùng app') "
                "rồi bấm 'Test Gemini' để kiểm tra lại trước khi dịch."
            )
    except ImportError:
        pass

    # --- Bước 1: phân tích ngữ cảnh toàn video (chủ đề/giọng điệu/glossary/category) ---
    video_context: dict = {}
    if use_video_context:
        if progress_cb:
            progress_cb(0.0, "Đang phân tích ngữ cảnh toàn video trước khi dịch...")
        video_context = build_video_context_gemini_fastapi(
            base_url, model, segments, source_lang, target_lang,
            api_key=api_key, timeout=timeout, progress_cb=progress_cb,
        )
    context_block = _format_context_block(video_context)

    # Trả context về cho Pipeline nếu caller cung cấp dict (kèm note_title/
    # note_title_alternatives/note_description/note_hashtags nếu AI có trả) -
    # để _build_output_metadata() dùng lại KHÔNG tốn thêm lượt gọi API nào.
    # Không cung cấp thì hành vi cũ giữ nguyên.
    if context_output is not None:
        context_output.clear()
        context_output.update(video_context)

    SEP = "\n<<<SEG>>>\n"
    style_block = f"\n{CONTENT_REWRITER_INSTRUCTIONS}\n" + _persona_block(video_context, content_persona)
    if style_notes and style_notes.strip():
        style_block += (
            f"\nYêu cầu thêm về văn phong/kịch bản (BẮT BUỘC tuân theo khi dịch/viết lại):\n"
            f"{style_notes.strip()}\n"
        )

    def _call_gemini_fastapi(prompt: str) -> str:
        resp = requests.post(
            url,
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=timeout,
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Gemini Web2API từ chối request (HTTP {resp.status_code}) - kiểm tra lại ô 'API Key' "
                "có khớp với api_keys trong cấu hình Web2API của server không."
            )
        if resp.status_code == 404:
            raise RuntimeError(
                f"HTTP 404 tại {url} - kiểm tra lại Base URL, hoặc model '{model}' không được server hỗ trợ."
            )
        if not resp.ok:
            # Cũng như build_video_context_gemini_fastapi: đọc thẳng body thay vì chỉ raise
            # "502 Bad Gateway" chung chung - Gemini Web2API thường trả kèm {"detail": "..."}
            # nói rõ lỗi thật (hết quota, session Gemini web hỏng, bị Google chặn tạm...).
            detail = _openai_compatible_error_detail(resp)
            raise RuntimeError(
                f"HTTP {resp.status_code} {resp.reason} tại {url}"
                + (f" - chi tiết từ server: {detail}" if detail else "")
            )
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""

    def _translate_batch(
        texts: List[str], starts: List[float], durations: List[float], depth: int = 0,
        is_first_batch: bool = False, is_last_batch: bool = False,
    ) -> List[str]:
        if not texts:
            return []
        pacing_block = _retention_pacing_note()
        hook_cta_block = _hook_cta_note(is_first_batch, is_last_batch)
        dial_block = _style_dial_block(narrative_style, audience, speaking_speed, creativity, hook_level)
        # Ước lượng tốc độ nói tiếng Việt tự nhiên (~15 ký tự/giây) để tính NGÂN SÁCH
        # KÝ TỰ cụ thể cho từng dòng NGAY TRONG NGÔN NGỮ ĐÍCH - đây là con số quan
        # trọng nhất giúp model tự canh độ dài, thay vì chỉ dặn suông "80-95% độ dài
        # gốc" (mơ hồ, và tiếng Việt vốn cần NHIỀU ký tự hơn tiếng Anh cho cùng 1 ý,
        # nên so với bản gốc tiếng Anh không phản ánh đúng khung giờ thật). Đây chỉ
        # là ước lượng SƠ BỘ (tốc độ đọc thật đo chính xác hơn ở core/tts.py sau khi
        # đã chọn giọng, không có ở bước dịch này) - đủ để model tự nhắm mục tiêu
        # ngay từ đầu, giảm hẳn số câu phải rút gọn/tăng tốc audio về sau.
        VN_CPS_ESTIMATE = 15.0
        lines_with_ts = SEP.join(
            f"<thời lượng={d:.1f}s, tối đa ~{max(10, int(d * VN_CPS_ESTIMATE))} ký tự tiếng Việt> {t}"
            for s, d, t in zip(starts, durations, texts)
        )

        prompt = f"""
        ========================================================
        ROLE
        ========================================================
        You are an award-winning YouTube Documentary Script Writer, NOT a translator.
        The narration must sound as if it was originally written in {target_lang}.

        ========================================================
        PRESERVE (never violate)
        ========================================================
        Keep every fact, number, name, event, cause/effect exactly as in the source.
        Never invent or exaggerate information.
        You MAY (and should, when needed to fit the time budget below) express the
        SAME facts using FEWER WORDS - shorter phrasing, cutting filler words, merging
        redundant clauses. This is NOT summarizing/removing information as long as
        every fact/number/name is still present - it is just more efficient wording.

        ========================================================
        REWRITE STYLE
        ========================================================
        Rewrite over 90% - different wording/structure, never literal translation.
        Read the whole batch as ONE continuous script (not independent lines) -
        keep smooth transitions and storytelling rhythm between subtitles.
        Write for LISTENING, not reading: conversational, natural rhythm, vary
        sentence length, avoid nested clauses / excessive commas / robotic wording.
        Never sound like Google Translate, ChatGPT, Wikipedia, or a textbook.
        If target language is Vietnamese: use spoken Vietnamese a real YouTube
        narrator would use, not written/formal Vietnamese.

        ========================================================
        RETENTION & HOOK
        ========================================================
        Build curiosity naturally every few subtitles (reveal info progressively,
        never dump everything at once) - without inventing facts or fake suspense.
        {"This is the OPENING of the video - rewrite it into a strong hook (curiosity/question/information gap)." if is_first_batch else ""}
        {"This is the ENDING of the video - finish with a natural, satisfying close (soft CTA if fitting, no new subtitle)." if is_last_batch else ""}

        ========================================================
        TIMING & LENGTH (STRICT - HIGHEST PRIORITY after facts)
        ========================================================
        Each line below is tagged with its EXACT speaking duration and a MAXIMUM
        character budget IN {target_lang.upper()} (already accounting for natural
        speaking speed in {target_lang}, NOT the source language's length).
        Example tag: <thời lượng=3.2s, tối đa ~48 ký tự tiếng Việt>
        Your rewritten line for {target_lang} MUST fit within that character budget.
        Going over the budget forces the audio to be sped up or cut later, which
        sounds unnatural - so when a phrasing would exceed the budget, actively
        choose the shorter equivalent phrasing (see PRESERVE section: cutting words
        is fine, cutting facts is not). Retention/hook flourishes are welcome ONLY
        when they still fit inside the budget - never let them push a line over.

        ========================================================
        {style_block}
        {dial_block}
        {pacing_block}
        {hook_cta_block}

        ========================================================
        VIDEO CONTEXT (for consistency, do not repeat verbatim)
        ========================================================
        {context_block}

        ========================================================
        OUTPUT FORMAT (strict)
        ========================================================
        Return EXACTLY {len(texts)} rewritten subtitles, same order, separated
        ONLY by the line "<<<SEG>>>". Do not merge/split/renumber subtitles.
        Do NOT output timestamps, markdown, numbering, notes, or explanations -
        ONLY the rewritten subtitle text.

        Target language: {target_lang}

        SUBTITLES TO REWRITE:
        {lines_with_ts}
        """
        last_err: Optional[Exception] = None
        is_connection_err = False
        # QUAN TRỌNG: các cờ "any_*" này gộp (OR) lỗi của TẤT CẢ các lần thử trong lô,
        # không chỉ lần thử cuối cùng. Trước đây code chỉ xét is_mismatch/is_connection_err
        # của lần thử CUỐI - nếu 2 lần đầu lệch dòng (mismatch) nhưng 2 lần cuối lại timeout,
        # cờ is_mismatch bị timeout ghi đè mất, nên bỏ lỡ bước "chia đôi lô" và chết cứng
        # bằng lỗi generic dù đáng lẽ có thể tự phục hồi bằng cách chia nhỏ lô.
        any_mismatch = False
        any_retryable = False  # mismatch HOẶC timeout - cả 2 đều đáng thử lại với lô nhỏ hơn
        any_rate_limited = False  # 429 Too Many Requests từ Google - cần backoff dài riêng
        for attempt in range(max_retries):
            is_mismatch = False
            is_timeout = False
            is_rate_limited = False
            try:
                out_text = (_call_gemini_fastapi(prompt) or "").strip()
                parts = [p.strip() for p in out_text.split("<<<SEG>>>")]
                parts = [p for p in parts if p != ""] if len(parts) > len(texts) else parts
                if len(parts) == len(texts):
                    return parts
                last_err = ValueError(f"Gemini Web2API trả về {len(parts)} dòng, cần {len(texts)} dòng - không khớp")
                is_mismatch = True
                is_connection_err = False
            except requests.exceptions.Timeout as e:
                # Timeout riêng: KHÔNG phải là mất kết nối (server vẫn sống, chỉ trả lời
                # chậm hơn timeout hiện tại) - coi như lỗi "đáng thử lô nhỏ hơn", vì lô ít
                # câu hơn = prompt/response ngắn hơn = Gemini web trả lời nhanh hơn hẳn.
                last_err = RuntimeError(
                    f"Gemini Web2API phản hồi quá {timeout:.0f}s (timed out) - server có thể đang xử lý "
                    f"chậm do lô quá dài hoặc Gemini web đang tải nặng: {e}"
                )
                is_timeout = True
                is_connection_err = False
            except requests.exceptions.ConnectionError as e:
                last_err = RuntimeError(f"Mất kết nối tới Gemini Web2API ({base_url}): {e}")
                is_connection_err = True
            except Exception as e:
                last_err = e
                is_connection_err = False
                # Lỗi 429 (Too Many Requests) từ Google, thường được Gemini Web2API bọc lại
                # thành HTTP 502 kèm chi tiết "Status: 429" hoặc "Too Many Requests" trong
                # nội dung lỗi - đây là rate-limit THẬT từ Google, khác hẳn timeout/mismatch:
                # thử lại ngay với backoff ngắn gần như chắc chắn dính lại 429 tiếp, phải chờ
                # LÂU HƠN HẲN (vài chục giây) mới có cơ hội qua được.
                err_text = str(e)
                if "429" in err_text or "Too Many Requests" in err_text or "TemporarilyBlocked" in err_text:
                    is_rate_limited = True
                elif "Unknown API error code" in err_text or "temporary error" in err_text.lower():
                    # VD: "Unknown API error code: 1096" - sự cố backend TẠM THỜI của
                    # chính Google (không phải lỗi từ phía app này), được cộng đồng báo
                    # cáo là thường tự hết sau vài phút - dùng backoff dài như rate-limit
                    # thay vì bỏ cuộc sớm với backoff ngắn.
                    is_rate_limited = True
            any_mismatch = any_mismatch or is_mismatch
            any_retryable = any_retryable or is_mismatch or is_timeout
            any_rate_limited = any_rate_limited or is_rate_limited
            if progress_cb:
                progress_cb(
                    0.0,
                    f"⚠ Gemini Web2API lỗi (lô {len(texts)} câu, lần thử {attempt + 1}/{max_retries}): {last_err} - đang thử lại...",
                )
            # Lỗi mất kết nối hẳn (server chưa chạy/đã tắt) thì thử lại cũng vô ích -
            # dừng sớm luôn thay vì chờ hết max_retries lần rồi mới báo.
            if is_connection_err:
                break
            if is_rate_limited:
                # Backoff RIÊNG cho rate-limit: dài hơn hẳn (30-60s + jitter), vì Google
                # thường cần vài chục giây mới bỏ giới hạn - backoff ngắn như lỗi thường
                # gần như chắc chắn dính 429 lần nữa, chỉ tổ tốn hết max_retries vô ích.
                wait = 30.0 + attempt * 15.0 + random.uniform(0, 15.0)
                if progress_cb:
                    progress_cb(0.0, f"⏳ Bị Google giới hạn tần suất (429) - nghỉ {wait:.0f}s trước khi thử lại...")
                time.sleep(wait)
            else:
                # Backoff tăng dần + jitter ngẫu nhiên (thay vì đúng 2s/4s/6s cố định) để
                # nhịp gọi lại không đều đặn máy móc, giảm khả năng bị nhận diện là bot.
                base_wait = retry_delay * (attempt + 1)
                time.sleep(base_wait + random.uniform(0, base_wait * 0.5))

        if any_retryable and len(texts) > 1:
            reason = "lệch số dòng" if any_mismatch else "phản hồi quá chậm/timeout"
            if progress_cb:
                progress_cb(0.0, f"Chia đôi lô {len(texts)} câu để thử lại ({reason})...")
            mid = len(texts) // 2
            return (
                _translate_batch(texts[:mid], starts[:mid], durations[:mid], depth + 1,
                                  is_first_batch=is_first_batch, is_last_batch=False)
                + _translate_batch(texts[mid:], starts[mid:], durations[mid:], depth + 1,
                                    is_first_batch=False, is_last_batch=is_last_batch)
            )
        if any_mismatch and not is_connection_err:
            return texts  # batch 1 câu vẫn lệch dòng -> giữ nguyên bản gốc

        if is_connection_err:
            raise RuntimeError(
                f"Gemini Web2API CHƯA CHẠY hoặc mất kết nối tại {base_url} "
                f"(đã thử {max_retries} lần). Kiểm tra server rồi bấm 'Test Gemini' lại. Lỗi cuối: {last_err}"
            )
        if any_rate_limited:
            raise RuntimeError(
                f"Bị Google giới hạn tần suất (429) hoặc gặp sự cố backend tạm thời (vd lỗi 1096) "
                f"liên tục sau {max_retries} lần thử, dù đã chờ backoff dài. Nếu là 429: cân nhắc tăng "
                f"inter_batch_delay, thêm tài khoản/proxy riêng. Nếu là lỗi backend tạm thời của Google "
                f"(1096/1095/1099...): đây là sự cố phía Google, không phải lỗi cấu hình - thử lại sau "
                f"vài phút hoặc đổi model. Lỗi cuối: {last_err}"
            )
        raise RuntimeError(f"Dịch bằng Gemini Web2API thất bại sau {max_retries} lần thử. Lỗi cuối: {last_err}")

    out: List[SubtitleSegment] = []
    total_batches = max(1, (len(segments) + batch_size - 1) // batch_size)
    for b in range(total_batches):
        chunk = segments[b * batch_size: (b + 1) * batch_size]
        texts = [seg.text.strip() for seg in chunk]
        starts = [seg.start for seg in chunk]
        durations = [max(0.3, seg.end - seg.start) for seg in chunk]
        # Delay ngẫu nhiên TRƯỚC mỗi lô (trừ lô đầu tiên) để giả lập nhịp gọi tự nhiên,
        # tránh gửi liên tục sát nhau (fingerprint dễ bị Gemini web coi là bot/automation
        # và tạm khoá/giới hạn client). Random thay vì hằng số cố định để nhịp nghỉ không
        # đều đặn máy móc.
        if b > 0 and inter_batch_delay_max > 0:
            delay = random.uniform(inter_batch_delay_min, max(inter_batch_delay_min, inter_batch_delay_max))
            if progress_cb:
                progress_cb(b / total_batches, f"Nghỉ {delay:.1f}s trước khi gửi lô {b + 1}/{total_batches} (tránh bị chặn)...")
            time.sleep(delay)
        # Cứ mỗi 10 lô, nghỉ dài hơn hẳn (60-120s) thay vì chỉ nghỉ ngắn đều đặn - mô
        # phỏng người dùng thật nghỉ giữa chừng, không phải script chạy liên tục không
        # ngừng hàng giờ (pattern rất dễ bị Google nhận diện là automation).
        if b > 0 and b % 10 == 0:
            long_pause = random.uniform(60.0, 120.0)
            if progress_cb:
                progress_cb(b / total_batches, f"⏸ Nghỉ dài {long_pause:.0f}s sau {b} lô liên tục...")
            time.sleep(long_pause)
        if progress_cb:
            progress_cb(b / total_batches, f"Đang gửi lô {b + 1}/{total_batches} tới Gemini Web2API...")
        translated_texts = _translate_batch(
            texts, starts, durations, is_first_batch=(b == 0), is_last_batch=(b == total_batches - 1),
        )
        translated_texts = _enforce_char_budget(translated_texts, durations, target_lang)
        for seg, tr in zip(chunk, translated_texts):
            out.append(SubtitleSegment(
                index=seg.index, start=seg.start, end=seg.end,
                text=tr or seg.text, gender=seg.gender, speaker_id=seg.speaker_id,
            ))
        if progress_cb:
            progress_cb((b + 1) / total_batches, f"Đang dịch (Gemini Web2API) lô {b + 1}/{total_batches}")

    return out


# ============================================================================
# Dịch bằng CLIProxyAPI (https://github.com/router-for-me/CLIProxyAPI) - server
# Go LOCAL bọc các CLI OAuth (Codex/ChatGPT, Claude Code, Gemini CLI, Grok...)
# thành API tương thích OpenAI, method riêng "cliproxy". KHÔNG tái sử dụng
# core.gemini_fastapi_server (module đó chỉ dành riêng cho backend Gemini Web2API,
# health-check/behaviour khác nhau) - toàn bộ logic health-check/gọi API cho
# CLIProxyAPI nằm gọn trong khối này, tách biệt hoàn toàn.
#
# Mặc định model = "gpt-5-codex" (dịch qua GPT/Codex, đăng nhập bằng OAuth ChatGPT
# trong CLIProxyAPI - xem `cli-proxy-api login --type codex` hoặc lệnh tương đương
# của bản CLIProxyAPI bạn đang chạy). Đổi model bằng cách GET {base_url}/v1/models
# để xem danh sách model server đang expose.
# ============================================================================

CLIPROXY_DEFAULT_BASE_URL = "http://127.0.0.1:8317"
DEFAULT_CLIPROXY_MODEL = "gpt-5-codex"


def check_cliproxy_health(
    base_url: str, api_key: Optional[str] = None, timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Health-check RIÊNG cho CLIProxyAPI: GET {base_url}/v1/models. Không raise,
    luôn trả về (ok, message) để UI hiển thị trực tiếp."""
    import requests

    base_url = (base_url or "").strip()
    if not base_url:
        return False, "CHƯA CẤU HÌNH Base URL cho CLIProxyAPI"
    url = base_url.rstrip("/") + "/v1/models"
    headers = {}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except Exception as e:
        return False, f"CHƯA CHẠY hoặc không kết nối được tới CLIProxyAPI tại {base_url} ({e})"
    if resp.status_code in (401, 403):
        return False, (
            f"CLIProxyAPI từ chối truy cập (HTTP {resp.status_code}) - kiểm tra lại 'API Key' "
            "có khớp với api-keys trong config.yaml của CLIProxyAPI không."
        )
    if not resp.ok:
        return False, f"CLIProxyAPI trả lỗi HTTP {resp.status_code} {resp.reason} tại {url}"
    try:
        models = [m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)]
    except Exception:
        models = []
    if models:
        shown = ", ".join(models[:6]) + ("..." if len(models) > 6 else "")
        return True, f"OK - CLIProxyAPI đang chạy tại {base_url} ({len(models)} model: {shown})"
    return True, f"OK - CLIProxyAPI đang chạy tại {base_url}"


def test_cliproxy_chat_completion(
    base_url: str, api_key: Optional[str] = None, model: str = DEFAULT_CLIPROXY_MODEL, timeout: float = 30.0,
) -> Tuple[bool, str]:
    """Gửi 1 request chat/completions ngắn để xác nhận MODEL cụ thể hoạt động thật
    (health-check ở trên chỉ xác nhận server sống, không xác nhận model dùng được)."""
    import requests

    base_url = (base_url or "").strip()
    if not base_url:
        return False, "CHƯA CẤU HÌNH Base URL cho CLIProxyAPI"
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    try:
        resp = requests.post(
            url, headers=headers,
            json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 8, "stream": False},
            timeout=timeout,
        )
    except Exception as e:
        return False, f"Lỗi kết nối tới {url}: {e}"
    if not resp.ok:
        detail = _openai_compatible_error_detail(resp)
        return False, f"HTTP {resp.status_code} {resp.reason}" + (f" - {detail}" if detail else "")
    try:
        content = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return False, "Phản hồi không đúng định dạng OpenAI-compatible (thiếu choices[0].message.content)"
    return True, f"OK - model '{model}' phản hồi được (vd: {content[:80]!r})"


def build_video_context_cliproxy(
    base_url: str,
    model: str,
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    api_key: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 3.0,
    max_chars: int = 12000,
    timeout: float = 60.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """Bản CLIProxyAPI của build_video_context: gọi 1 LẦN ở đầu quá trình dịch để đọc
    toàn bộ transcript gốc, trả về JSON {"topic","tone","category","glossary"} dùng
    chung cho mọi lô dịch phía sau. Lỗi ở bước này KHÔNG raise - trả về {} và để
    pipeline dịch tiếp bình thường bằng persona mặc định."""
    import requests

    texts = [s.text.strip() for s in segments if s.text.strip()]
    full_text = "\n".join(texts)
    if not full_text:
        return {}
    if len(full_text) > max_chars:
        third = max_chars // 3
        full_text = (
            full_text[:third] + "\n...\n"
            + full_text[len(full_text) // 2 - third // 2: len(full_text) // 2 + third // 2]
            + "\n...\n" + full_text[-third:]
        )

    prompt = (
        f"Đây là toàn bộ (hoặc trích đoạn đại diện) lời thoại gốc ({source_lang}) của 1 video ngắn:\n\n"
        f"{full_text}\n\n"
        f"Trả lời DUY NHẤT 1 JSON hợp lệ (không markdown, không giải thích thêm), đúng cấu trúc:\n"
        '{"topic": "chủ đề chính của video, 1 câu ngắn", '
        '"tone": "giọng điệu/phong cách phù hợp khi thuyết minh lại", '
        '"category": "PHẢI là 1 trong: science, history, psychology, finance, technology, other", '
        f'"glossary": {{"thuật ngữ/tên riêng gốc": "cách dịch sang {target_lang} thống nhất xuyên suốt video"}}}}\n'
        "glossary CHỈ liệt kê thuật ngữ chuyên ngành/tên riêng/số liệu quan trọng LẶP LẠI nhiều lần. "
        "Nếu không có, để glossary rỗng {}."
    )

    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                url, headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Bạn là biên tập viên phân tích nội dung video ngắn."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
                timeout=timeout,
            )
            if not resp.ok:
                detail = _openai_compatible_error_detail(resp)
                raise RuntimeError(
                    f"HTTP {resp.status_code} {resp.reason}" + (f" - chi tiết từ server: {detail}" if detail else "")
                )
            out_text = resp.json()["choices"][0]["message"]["content"] or ""
            data = json.loads(_extract_json_block(out_text.strip()))
            if isinstance(data, dict):
                if progress_cb:
                    progress_cb(0.0, f"✓ Đã phân tích ngữ cảnh video (CLIProxyAPI): {data.get('topic', '(không rõ)')}")
                return data
        except Exception as e:
            if progress_cb:
                progress_cb(0.0, f"⚠ Lấy ngữ cảnh video (CLIProxyAPI) lỗi (lần {attempt + 1}/{max_retries}): {e}")
            time.sleep(retry_delay * (attempt + 1))

    if progress_cb:
        progress_cb(0.0, "⚠ Bỏ qua bước phân tích ngữ cảnh video (lỗi hết số lần thử) - vẫn tiếp tục dịch")
    return {}


def translate_segments_cliproxy(
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    base_url: str = CLIPROXY_DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    model: str = DEFAULT_CLIPROXY_MODEL,
    batch_size: int = 18,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    max_retries: int = 4,
    retry_delay: float = 2.0,
    timeout: float = 240.0,
    style_notes: Optional[str] = None,
    use_video_context: bool = True,
    content_persona: Optional[str] = None,
    narrative_style: Optional[str] = None,
    audience: Optional[str] = None,
    speaking_speed: Optional[str] = None,
    creativity: Optional[str] = None,
    hook_level: Optional[str] = None,
    inter_batch_delay_min: float = 5.0,
    inter_batch_delay_max: float = 12.0,
) -> List[SubtitleSegment]:
    """
    Viết lại hoàn toàn bằng CLIProxyAPI (https://github.com/router-for-me/CLIProxyAPI)
    - 1 server HTTP local (viết bằng Go), gọi endpoint OpenAI-compatible
    '/v1/chat/completions'. Cho phép dùng model GPT/Codex (mặc định), Claude, Gemini...
    thông qua đăng nhập OAuth CLI (Codex/ChatGPT, Claude Code, Gemini CLI...) đã cấu
    hình sẵn trong CLIProxyAPI, KHÔNG cần API key trả phí theo token riêng.

    base_url: địa chỉ server CLIProxyAPI đang chạy, vd "http://127.0.0.1:8317".
    api_key: CHỈ cần nếu server bật `api-keys` trong config.yaml - để trống nếu
    server không yêu cầu.
    model: tên model CLIProxyAPI đang expose (vd "gpt-5-codex") - xem đầy đủ danh
    sách bằng GET {base_url}/v1/models.

    Áp dụng ĐẦY ĐỦ hệ thống "Content Rewriter" giống Gemini API/Grok/Gemini Web2API
    (xem CONTENT_REWRITER_INSTRUCTIONS, TOPIC_PERSONAS, hook mở đầu/CTA kết thúc,
    retention hook theo mốc thời gian).

    Nếu server KHÔNG kết nối được (chưa chạy) hoặc lỗi liên tục sau max_retries lần,
    hàm RAISE lỗi ngay lập tức với thông báo rõ ràng thay vì "treo" âm thầm.
    """
    import requests

    if not base_url or not base_url.strip():
        raise ValueError("translation_method='cliproxy' cần truyền base_url (vd http://127.0.0.1:8317)")
    base_url = base_url.strip()
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    # --- Bước 0: kiểm tra nhanh server có đang chạy không, báo lỗi rõ ràng ngay từ
    # đầu thay vì để người dùng chờ hết max_retries*batch lần rồi mới biết lý do. ---
    ok_health, health_msg = check_cliproxy_health(base_url, api_key=api_key, timeout=5.0)
    if progress_cb:
        progress_cb(0.0, f"Kiểm tra CLIProxyAPI: {health_msg}")
    if not ok_health:
        raise RuntimeError(
            f"CLIProxyAPI CHƯA SẴN SÀNG tại {base_url}: {health_msg}. "
            "Hãy khởi động server CLIProxyAPI rồi bấm 'Test CLIProxyAPI' để kiểm tra lại trước khi dịch."
        )

    # --- Bước 1: phân tích ngữ cảnh toàn video (chủ đề/giọng điệu/glossary/category) ---
    video_context: dict = {}
    if use_video_context:
        if progress_cb:
            progress_cb(0.0, "Đang phân tích ngữ cảnh toàn video trước khi dịch...")
        video_context = build_video_context_cliproxy(
            base_url, model, segments, source_lang, target_lang,
            api_key=api_key, timeout=timeout, progress_cb=progress_cb,
        )
    context_block = _format_context_block(video_context)

    SEP = "\n<<<SEG>>>\n"
    style_block = f"\n{CONTENT_REWRITER_INSTRUCTIONS}\n" + _persona_block(video_context, content_persona)
    if style_notes and style_notes.strip():
        style_block += (
            f"\nYêu cầu thêm về văn phong/kịch bản (BẮT BUỘC tuân theo khi dịch/viết lại):\n"
            f"{style_notes.strip()}\n"
        )

    def _call_cliproxy(prompt: str) -> str:
        resp = requests.post(
            url, headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=timeout,
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"CLIProxyAPI từ chối request (HTTP {resp.status_code}) - kiểm tra lại ô 'API Key' "
                "có khớp với api-keys trong config.yaml của CLIProxyAPI không."
            )
        if resp.status_code == 404:
            raise RuntimeError(
                f"HTTP 404 tại {url} - kiểm tra lại Base URL, hoặc model '{model}' không được server hỗ trợ "
                f"(xem GET {base_url}/v1/models)."
            )
        if not resp.ok:
            detail = _openai_compatible_error_detail(resp)
            raise RuntimeError(
                f"HTTP {resp.status_code} {resp.reason} tại {url}"
                + (f" - chi tiết từ server: {detail}" if detail else "")
            )
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""

    def _translate_batch(
        texts: List[str], starts: List[float], durations: List[float], depth: int = 0,
        is_first_batch: bool = False, is_last_batch: bool = False,
    ) -> List[str]:
        if not texts:
            return []
        pacing_block = _retention_pacing_note()
        hook_cta_block = _hook_cta_note(is_first_batch, is_last_batch)
        dial_block = _style_dial_block(narrative_style, audience, speaking_speed, creativity, hook_level)
        VN_CPS_ESTIMATE = 15.0
        lines_with_ts = SEP.join(
            f"<thời lượng={d:.1f}s, tối đa ~{max(10, int(d * VN_CPS_ESTIMATE))} ký tự tiếng Việt> {t}"
            for s, d, t in zip(starts, durations, texts)
        )

        prompt = f"""
        ========================================================
        ROLE
        ========================================================
        You are an award-winning YouTube Documentary Script Writer, NOT a translator.
        The narration must sound as if it was originally written in {target_lang}.

        ========================================================
        PRESERVE (never violate)
        ========================================================
        Keep every fact, number, name, event, cause/effect exactly as in the source.
        Never invent or exaggerate information.
        You MAY (and should, when needed to fit the time budget below) express the
        SAME facts using FEWER WORDS - shorter phrasing, cutting filler words, merging
        redundant clauses. This is NOT summarizing/removing information as long as
        every fact/number/name is still present - it is just more efficient wording.

        ========================================================
        REWRITE STYLE
        ========================================================
        Rewrite over 90% - different wording/structure, never literal translation.
        Read the whole batch as ONE continuous script (not independent lines) -
        keep smooth transitions and storytelling rhythm between subtitles.
        Write for LISTENING, not reading: conversational, natural rhythm, vary
        sentence length, avoid nested clauses / excessive commas / robotic wording.
        Never sound like Google Translate, ChatGPT, Wikipedia, or a textbook.
        If target language is Vietnamese: use spoken Vietnamese a real YouTube
        narrator would use, not written/formal Vietnamese.

        ========================================================
        RETENTION & HOOK
        ========================================================
        Build curiosity naturally every few subtitles (reveal info progressively,
        never dump everything at once) - without inventing facts or fake suspense.
        {"This is the OPENING of the video - rewrite it into a strong hook (curiosity/question/information gap)." if is_first_batch else ""}
        {"This is the ENDING of the video - finish with a natural, satisfying close (soft CTA if fitting, no new subtitle)." if is_last_batch else ""}

        ========================================================
        TIMING & LENGTH (STRICT - HIGHEST PRIORITY after facts)
        ========================================================
        Each line below is tagged with its EXACT speaking duration and a MAXIMUM
        character budget IN {target_lang.upper()} (already accounting for natural
        speaking speed in {target_lang}, NOT the source language's length).
        Example tag: <thời lượng=3.2s, tối đa ~48 ký tự tiếng Việt>
        Your rewritten line for {target_lang} MUST fit within that character budget.
        Going over the budget forces the audio to be sped up or cut later, which
        sounds unnatural - so when a phrasing would exceed the budget, actively
        choose the shorter equivalent phrasing (see PRESERVE section: cutting words
        is fine, cutting facts is not). Retention/hook flourishes are welcome ONLY
        when they still fit inside the budget - never let them push a line over.

        ========================================================
        {style_block}
        {dial_block}
        {pacing_block}
        {hook_cta_block}

        ========================================================
        VIDEO CONTEXT (for consistency, do not repeat verbatim)
        ========================================================
        {context_block}

        ========================================================
        OUTPUT FORMAT (strict)
        ========================================================
        Return EXACTLY {len(texts)} rewritten subtitles, same order, separated
        ONLY by the line "<<<SEG>>>". Do not merge/split/renumber subtitles.
        Do NOT output timestamps, markdown, numbering, notes, or explanations -
        ONLY the rewritten subtitle text.

        Target language: {target_lang}

        SUBTITLES TO REWRITE:
        {lines_with_ts}
        """
        last_err: Optional[Exception] = None
        is_connection_err = False
        any_mismatch = False
        any_retryable = False  # mismatch HOẶC timeout - cả 2 đều đáng thử lại với lô nhỏ hơn
        any_rate_limited = False  # 429 Too Many Requests - cần backoff dài riêng
        for attempt in range(max_retries):
            is_mismatch = False
            is_timeout = False
            is_rate_limited = False
            try:
                out_text = (_call_cliproxy(prompt) or "").strip()
                parts = [p.strip() for p in out_text.split("<<<SEG>>>")]
                parts = [p for p in parts if p != ""] if len(parts) > len(texts) else parts
                if len(parts) == len(texts):
                    return parts
                last_err = ValueError(f"CLIProxyAPI trả về {len(parts)} dòng, cần {len(texts)} dòng - không khớp")
                is_mismatch = True
                is_connection_err = False
            except requests.exceptions.Timeout as e:
                last_err = RuntimeError(
                    f"CLIProxyAPI phản hồi quá {timeout:.0f}s (timed out) - server/model có thể đang xử lý "
                    f"chậm do lô quá dài hoặc backend đang tải nặng: {e}"
                )
                is_timeout = True
                is_connection_err = False
            except requests.exceptions.ConnectionError as e:
                last_err = RuntimeError(f"Mất kết nối tới CLIProxyAPI ({base_url}): {e}")
                is_connection_err = True
            except Exception as e:
                last_err = e
                is_connection_err = False
                err_text = str(e)
                if "429" in err_text or "Too Many Requests" in err_text or "rate limit" in err_text.lower():
                    is_rate_limited = True
                elif "Unknown API error code" in err_text or "temporary error" in err_text.lower():
                    is_rate_limited = True
            any_mismatch = any_mismatch or is_mismatch
            any_retryable = any_retryable or is_mismatch or is_timeout
            any_rate_limited = any_rate_limited or is_rate_limited
            if progress_cb:
                progress_cb(
                    0.0,
                    f"⚠ CLIProxyAPI lỗi (lô {len(texts)} câu, lần thử {attempt + 1}/{max_retries}): {last_err} - đang thử lại...",
                )
            if is_connection_err:
                break
            if is_rate_limited:
                wait = 20.0 + attempt * 10.0 + random.uniform(0, 10.0)
                if progress_cb:
                    progress_cb(0.0, f"⏳ Bị giới hạn tần suất (429) hoặc quota tài khoản OAuth - nghỉ {wait:.0f}s trước khi thử lại...")
                time.sleep(wait)
            else:
                base_wait = retry_delay * (attempt + 1)
                time.sleep(base_wait + random.uniform(0, base_wait * 0.5))

        if any_retryable and len(texts) > 1:
            reason = "lệch số dòng" if any_mismatch else "phản hồi quá chậm/timeout"
            if progress_cb:
                progress_cb(0.0, f"Chia đôi lô {len(texts)} câu để thử lại ({reason})...")
            mid = len(texts) // 2
            return (
                _translate_batch(texts[:mid], starts[:mid], durations[:mid], depth + 1,
                                  is_first_batch=is_first_batch, is_last_batch=False)
                + _translate_batch(texts[mid:], starts[mid:], durations[mid:], depth + 1,
                                    is_first_batch=False, is_last_batch=is_last_batch)
            )
        if any_mismatch and not is_connection_err:
            return texts  # batch 1 câu vẫn lệch dòng -> giữ nguyên bản gốc

        if is_connection_err:
            raise RuntimeError(
                f"CLIProxyAPI CHƯA CHẠY hoặc mất kết nối tại {base_url} "
                f"(đã thử {max_retries} lần). Kiểm tra server rồi bấm 'Test CLIProxyAPI' lại. Lỗi cuối: {last_err}"
            )
        if any_rate_limited:
            raise RuntimeError(
                f"Bị giới hạn tần suất (429) hoặc hết quota tài khoản OAuth liên tục sau {max_retries} lần thử, "
                f"dù đã chờ backoff dài. Cân nhắc tăng inter_batch_delay, thêm tài khoản OAuth khác trong "
                f"CLIProxyAPI (multi-account round-robin), hoặc đổi model. Lỗi cuối: {last_err}"
            )
        raise RuntimeError(f"Dịch bằng CLIProxyAPI thất bại sau {max_retries} lần thử. Lỗi cuối: {last_err}")

    out: List[SubtitleSegment] = []
    total_batches = max(1, (len(segments) + batch_size - 1) // batch_size)
    for b in range(total_batches):
        chunk = segments[b * batch_size: (b + 1) * batch_size]
        texts = [seg.text.strip() for seg in chunk]
        starts = [seg.start for seg in chunk]
        durations = [max(0.3, seg.end - seg.start) for seg in chunk]
        if b > 0 and inter_batch_delay_max > 0:
            delay = random.uniform(inter_batch_delay_min, max(inter_batch_delay_min, inter_batch_delay_max))
            if progress_cb:
                progress_cb(b / total_batches, f"Nghỉ {delay:.1f}s trước khi gửi lô {b + 1}/{total_batches}...")
            time.sleep(delay)
        if progress_cb:
            progress_cb(b / total_batches, f"Đang gửi lô {b + 1}/{total_batches} tới CLIProxyAPI...")
        translated_texts = _translate_batch(
            texts, starts, durations, is_first_batch=(b == 0), is_last_batch=(b == total_batches - 1),
        )
        translated_texts = _enforce_char_budget(translated_texts, durations, target_lang)
        for seg, tr in zip(chunk, translated_texts):
            out.append(SubtitleSegment(
                index=seg.index, start=seg.start, end=seg.end,
                text=tr or seg.text, gender=seg.gender, speaker_id=seg.speaker_id,
            ))
        if progress_cb:
            progress_cb((b + 1) / total_batches, f"Đang dịch (CLIProxyAPI) lô {b + 1}/{total_batches}")

    return out


DEFAULT_GEMINI_WEBAPI_MODEL = "gemini-3-flash"


def build_video_context_gemini_webapi(
    secure_1psid: str,
    secure_1psidts: Optional[str],
    proxy: Optional[str],
    model: str,
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    max_retries: int = 3,
    retry_delay: float = 3.0,
    max_chars: int = 12000,
    timeout: float = 90.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """Bản Gemini-API-master (gemini_webapi, đăng nhập bằng cookie) của
    build_video_context: gọi Gemini 1 LẦN ở đầu quá trình dịch để đọc toàn bộ
    transcript gốc, trả về JSON {"topic", "tone", "category", "glossary"} dùng chung
    cho mọi lô dịch phía sau. Lỗi ở bước này KHÔNG raise - trả về {} và để pipeline
    dịch tiếp bình thường bằng persona mặc định."""
    from core.gemini_webapi_client import generate_text

    texts = [s.text.strip() for s in segments if s.text.strip()]
    full_text = "\n".join(texts)
    if not full_text:
        return {}
    if len(full_text) > max_chars:
        third = max_chars // 3
        full_text = (
            full_text[:third] + "\n...\n"
            + full_text[len(full_text) // 2 - third // 2: len(full_text) // 2 + third // 2]
            + "\n...\n" + full_text[-third:]
        )

    prompt = (
        f"Đây là toàn bộ (hoặc trích đoạn đại diện) lời thoại gốc ({source_lang}) của 1 video ngắn:\n\n"
        f"{full_text}\n\n"
        f"Trả lời DUY NHẤT 1 JSON hợp lệ (không markdown, không giải thích thêm), đúng cấu trúc:\n"
        '{"topic": "chủ đề chính của video, 1 câu ngắn", '
        '"tone": "giọng điệu/phong cách phù hợp khi thuyết minh lại", '
        '"category": "PHẢI là 1 trong: science, history, psychology, finance, technology, other", '
        f'"glossary": {{"thuật ngữ/tên riêng gốc": "cách dịch sang {target_lang} thống nhất xuyên suốt video"}}}}\n'
        "glossary CHỈ liệt kê thuật ngữ chuyên ngành/tên riêng/số liệu quan trọng LẶP LẠI nhiều lần. "
        "Nếu không có, để glossary rỗng {}."
    )

    for attempt in range(max_retries):
        try:
            out_text = generate_text(
                prompt, secure_1psid=secure_1psid, secure_1psidts=secure_1psidts, proxy=proxy,
                model=model, system_prompt="Bạn là biên tập viên phân tích nội dung video ngắn.",
                timeout=timeout, max_retries=1,
            )
            data = json.loads(_extract_json_block(out_text.strip()))
            if isinstance(data, dict):
                if progress_cb:
                    progress_cb(0.0, f"✓ Đã phân tích ngữ cảnh video: {data.get('topic', '(không rõ)')}")
                return data
        except Exception as e:
            if progress_cb:
                progress_cb(0.0, f"⚠ Lấy ngữ cảnh video (Gemini API master) lỗi (lần {attempt + 1}/{max_retries}): {e}")
            err_text = str(e)
            if "429" in err_text or "Too Many Requests" in err_text:
                time.sleep(20.0 + attempt * 10.0 + random.uniform(0, 10.0))
            else:
                time.sleep(retry_delay * (attempt + 1))

    if progress_cb:
        progress_cb(0.0, "⚠ Bỏ qua bước phân tích ngữ cảnh video (lỗi hết số lần thử) - vẫn tiếp tục dịch")
    return {}


def translate_segments_gemini_webapi(
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    secure_1psid: str,
    secure_1psidts: Optional[str] = None,
    proxy: Optional[str] = None,
    model: str = DEFAULT_GEMINI_WEBAPI_MODEL,
    batch_size: int = 18,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    max_retries: int = 4,
    retry_delay: float = 2.0,
    timeout: float = 240.0,
    style_notes: Optional[str] = None,
    use_video_context: bool = True,
    content_persona: Optional[str] = None,
    narrative_style: Optional[str] = None,
    audience: Optional[str] = None,
    speaking_speed: Optional[str] = None,
    creativity: Optional[str] = None,
    hook_level: Optional[str] = None,
    inter_batch_delay_min: float = 10.0,
    inter_batch_delay_max: float = 25.0,
) -> List[SubtitleSegment]:
    """
    Viết lại hoàn toàn bằng "Gemini API master" (gemini_webapi,
    https://github.com/HanaokaYuzu/Gemini-API) - thư viện Python gọi THẲNG
    gemini.google.com bằng cookie trình duyệt (__Secure-1PSID/__Secure-1PSIDTS),
    KHÔNG cần chạy thêm server phụ như Gemini Web2API, và cũng KHÔNG cần API key
    trả phí của Google.

    Áp dụng ĐẦY ĐỦ hệ thống "Content Rewriter" giống Gemini API/Grok/Gemini Web2API
    (xem CONTENT_REWRITER_INSTRUCTIONS, TOPIC_PERSONAS, hook mở đầu/CTA kết thúc,
    retention hook theo mốc thời gian).

    secure_1psid/secure_1psidts: cookie đăng nhập gemini.google.com, lấy từ trình
    duyệt đã đăng nhập (DevTools > Application/Storage > Cookies). secure_1psidts
    không bắt buộc với mọi tài khoản - để trống nếu cookie list không có.

    Nếu KHÔNG đăng nhập được (cookie sai/hết hạn) hoặc lỗi liên tục sau max_retries
    lần, hàm RAISE lỗi ngay lập tức với thông báo rõ ràng thay vì "treo" âm thầm.
    """
    from core.gemini_webapi_client import generate_text, check_credentials

    if not secure_1psid or not secure_1psid.strip():
        raise ValueError(
            "translation_method='gemini_webapi' cần truyền secure_1psid (cookie __Secure-1PSID)"
        )
    secure_1psid = secure_1psid.strip()

    # --- Bước 0: kiểm tra nhanh cookie có đăng nhập được không, báo lỗi rõ ràng ngay
    # từ đầu thay vì để người dùng chờ hết max_retries*batch lần rồi mới biết lý do. ---
    ok, health_msg = check_credentials(secure_1psid, secure_1psidts, proxy, timeout=45.0)
    if progress_cb:
        progress_cb(0.0, f"Kiểm tra Gemini API master: {health_msg}")
    if not ok:
        raise RuntimeError(
            f"Gemini API master CHƯA đăng nhập được bằng cookie: {health_msg}\n"
            "Kiểm tra lại cookie __Secure-1PSID/__Secure-1PSIDTS rồi bấm 'Test Gemini "
            "(API master)' để kiểm tra lại trước khi dịch."
        )

    # --- Bước 1: phân tích ngữ cảnh toàn video (chủ đề/giọng điệu/glossary/category) ---
    video_context: dict = {}
    if use_video_context:
        if progress_cb:
            progress_cb(0.0, "Đang phân tích ngữ cảnh toàn video trước khi dịch...")
        video_context = build_video_context_gemini_webapi(
            secure_1psid, secure_1psidts, proxy, model, segments, source_lang, target_lang,
            timeout=timeout, progress_cb=progress_cb,
        )
    context_block = _format_context_block(video_context)

    SEP = "\n<<<SEG>>>\n"
    style_block = f"\n{CONTENT_REWRITER_INSTRUCTIONS}\n" + _persona_block(video_context, content_persona)
    if style_notes and style_notes.strip():
        style_block += (
            f"\nYêu cầu thêm về văn phong/kịch bản (BẮT BUỘC tuân theo khi dịch/viết lại):\n"
            f"{style_notes.strip()}\n"
        )

    def _call_gemini_webapi(prompt: str) -> str:
        return generate_text(
            prompt, secure_1psid=secure_1psid, secure_1psidts=secure_1psidts, proxy=proxy,
            model=model, system_prompt=SYSTEM_PROMPT, timeout=timeout, max_retries=1,
        )

    def _translate_batch(
        texts: List[str], starts: List[float], durations: List[float], depth: int = 0,
        is_first_batch: bool = False, is_last_batch: bool = False,
    ) -> List[str]:
        if not texts:
            return []
        pacing_block = _retention_pacing_note()
        hook_cta_block = _hook_cta_note(is_first_batch, is_last_batch)
        dial_block = _style_dial_block(narrative_style, audience, speaking_speed, creativity, hook_level)
        VN_CPS_ESTIMATE = 15.0
        lines_with_ts = SEP.join(
            f"<thời lượng={d:.1f}s, tối đa ~{max(10, int(d * VN_CPS_ESTIMATE))} ký tự tiếng Việt> {t}"
            for s, d, t in zip(starts, durations, texts)
        )

        prompt = f"""
        ========================================================
        ROLE
        ========================================================
        You are an award-winning YouTube Documentary Script Writer, NOT a translator.
        The narration must sound as if it was originally written in {target_lang}.

        ========================================================
        PRESERVE (never violate)
        ========================================================
        Keep every fact, number, name, event, cause/effect exactly as in the source.
        Never invent or exaggerate information.
        You MAY (and should, when needed to fit the time budget below) express the
        SAME facts using FEWER WORDS - shorter phrasing, cutting filler words, merging
        redundant clauses. This is NOT summarizing/removing information as long as
        every fact/number/name is still present - it is just more efficient wording.

        ========================================================
        REWRITE STYLE
        ========================================================
        Rewrite over 90% - different wording/structure, never literal translation.
        Read the whole batch as ONE continuous script (not independent lines) -
        keep smooth transitions and storytelling rhythm between subtitles.
        Write for LISTENING, not reading: conversational, natural rhythm, vary
        sentence length, avoid nested clauses / excessive commas / robotic wording.
        Never sound like Google Translate, ChatGPT, Wikipedia, or a textbook.
        If target language is Vietnamese: use spoken Vietnamese a real YouTube
        narrator would use, not written/formal Vietnamese.

        ========================================================
        RETENTION & HOOK
        ========================================================
        Build curiosity naturally every few subtitles (reveal info progressively,
        never dump everything at once) - without inventing facts or fake suspense.
        {"This is the OPENING of the video - rewrite it into a strong hook (curiosity/question/information gap)." if is_first_batch else ""}
        {"This is the ENDING of the video - finish with a natural, satisfying close (soft CTA if fitting, no new subtitle)." if is_last_batch else ""}

        ========================================================
        TIMING & LENGTH (STRICT - HIGHEST PRIORITY after facts)
        ========================================================
        Each line below is tagged with its EXACT speaking duration and a MAXIMUM
        character budget IN {target_lang.upper()} (already accounting for natural
        speaking speed in {target_lang}, NOT the source language's length).
        Example tag: <thời lượng=3.2s, tối đa ~48 ký tự tiếng Việt>
        Your rewritten line for {target_lang} MUST fit within that character budget.
        Going over the budget forces the audio to be sped up or cut later, which
        sounds unnatural - so when a phrasing would exceed the budget, actively
        choose the shorter equivalent phrasing (see PRESERVE section: cutting words
        is fine, cutting facts is not). Retention/hook flourishes are welcome ONLY
        when they still fit inside the budget - never let them push a line over.

        ========================================================
        {style_block}
        {dial_block}
        {pacing_block}
        {hook_cta_block}

        ========================================================
        VIDEO CONTEXT (for consistency, do not repeat verbatim)
        ========================================================
        {context_block}

        ========================================================
        OUTPUT FORMAT (strict)
        ========================================================
        Return EXACTLY {len(texts)} rewritten subtitles, same order, separated
        ONLY by the line "<<<SEG>>>". Do not merge/split/renumber subtitles.
        Do NOT output timestamps, markdown, numbering, notes, or explanations -
        ONLY the rewritten subtitle text.

        Target language: {target_lang}

        SUBTITLES TO REWRITE:
        {lines_with_ts}
        """
        last_err: Optional[Exception] = None
        is_auth_err = False
        any_mismatch = False
        any_retryable = False
        any_rate_limited = False
        for attempt in range(max_retries):
            is_mismatch = False
            is_timeout = False
            is_rate_limited = False
            try:
                out_text = (_call_gemini_webapi(prompt) or "").strip()
                parts = [p.strip() for p in out_text.split("<<<SEG>>>")]
                parts = [p for p in parts if p != ""] if len(parts) > len(texts) else parts
                if len(parts) == len(texts):
                    return parts
                last_err = ValueError(f"Gemini API master trả về {len(parts)} dòng, cần {len(texts)} dòng - không khớp")
                is_mismatch = True
            except Exception as e:
                last_err = e
                err_text = str(e)
                if "Xác thực thất bại" in err_text:
                    is_auth_err = True
                elif "timeout" in err_text.lower() or "quá chậm" in err_text:
                    is_timeout = True
                elif "429" in err_text or "Too Many Requests" in err_text:
                    is_rate_limited = True
            any_mismatch = any_mismatch or is_mismatch
            any_retryable = any_retryable or is_mismatch or is_timeout
            any_rate_limited = any_rate_limited or is_rate_limited
            if progress_cb:
                progress_cb(
                    0.0,
                    f"⚠ Gemini API master lỗi (lô {len(texts)} câu, lần thử {attempt + 1}/{max_retries}): {last_err} - đang thử lại...",
                )
            if is_auth_err:
                break  # cookie sai/hết hạn - thử lại cũng vô ích, dừng sớm
            if is_rate_limited:
                wait = 30.0 + attempt * 15.0 + random.uniform(0, 15.0)
                if progress_cb:
                    progress_cb(0.0, f"⏳ Bị Google giới hạn tần suất (429) - nghỉ {wait:.0f}s trước khi thử lại...")
                time.sleep(wait)
            else:
                base_wait = retry_delay * (attempt + 1)
                time.sleep(base_wait + random.uniform(0, base_wait * 0.5))

        if any_retryable and len(texts) > 1:
            reason = "lệch số dòng" if any_mismatch else "phản hồi quá chậm/timeout"
            if progress_cb:
                progress_cb(0.0, f"Chia đôi lô {len(texts)} câu để thử lại ({reason})...")
            mid = len(texts) // 2
            return (
                _translate_batch(texts[:mid], starts[:mid], durations[:mid], depth + 1,
                                  is_first_batch=is_first_batch, is_last_batch=False)
                + _translate_batch(texts[mid:], starts[mid:], durations[mid:], depth + 1,
                                    is_first_batch=False, is_last_batch=is_last_batch)
            )
        if any_mismatch and not is_auth_err:
            return texts  # batch 1 câu vẫn lệch dòng -> giữ nguyên bản gốc

        if is_auth_err:
            raise RuntimeError(
                f"Gemini API master CHƯA đăng nhập được (cookie sai/hết hạn) - lấy cookie mới rồi "
                f"bấm 'Test Gemini (API master)' lại. Lỗi cuối: {last_err}"
            )
        if any_rate_limited:
            raise RuntimeError(
                f"Bị Google giới hạn tần suất (429) liên tục sau {max_retries} lần thử, dù đã chờ "
                f"backoff dài. Cân nhắc tăng inter_batch_delay, dùng proxy riêng, hoặc thử lại sau "
                f"vài phút. Lỗi cuối: {last_err}"
            )
        raise RuntimeError(f"Dịch bằng Gemini API master thất bại sau {max_retries} lần thử. Lỗi cuối: {last_err}")

    out: List[SubtitleSegment] = []
    total_batches = max(1, (len(segments) + batch_size - 1) // batch_size)
    for b in range(total_batches):
        chunk = segments[b * batch_size: (b + 1) * batch_size]
        texts = [seg.text.strip() for seg in chunk]
        starts = [seg.start for seg in chunk]
        durations = [max(0.3, seg.end - seg.start) for seg in chunk]
        if b > 0 and inter_batch_delay_max > 0:
            delay = random.uniform(inter_batch_delay_min, max(inter_batch_delay_min, inter_batch_delay_max))
            if progress_cb:
                progress_cb(b / total_batches, f"Nghỉ {delay:.1f}s trước khi gửi lô {b + 1}/{total_batches} (tránh bị chặn)...")
            time.sleep(delay)
        if b > 0 and b % 10 == 0:
            long_pause = random.uniform(60.0, 120.0)
            if progress_cb:
                progress_cb(b / total_batches, f"⏸ Nghỉ dài {long_pause:.0f}s sau {b} lô liên tục...")
            time.sleep(long_pause)
        if progress_cb:
            progress_cb(b / total_batches, f"Đang gửi lô {b + 1}/{total_batches} tới Gemini API master...")
        translated_texts = _translate_batch(
            texts, starts, durations, is_first_batch=(b == 0), is_last_batch=(b == total_batches - 1),
        )
        translated_texts = _enforce_char_budget(translated_texts, durations, target_lang)
        for seg, tr in zip(chunk, translated_texts):
            out.append(SubtitleSegment(
                index=seg.index, start=seg.start, end=seg.end,
                text=tr or seg.text, gender=seg.gender, speaker_id=seg.speaker_id,
            ))
        if progress_cb:
            progress_cb((b + 1) / total_batches, f"Đang dịch (Gemini API master) lô {b + 1}/{total_batches}")

    return out


def translate_segments_offline(
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[SubtitleSegment]:
    """
    Dịch offline bằng argos-translate (không cần mạng sau khi đã tải gói ngôn ngữ).
    pip install argostranslate
    """
    import argostranslate.translate as at

    src = LANG_CODE.get(source_lang, source_lang)[:2]
    tgt = LANG_CODE.get(target_lang, target_lang)[:2]

    out: List[SubtitleSegment] = []
    total = max(1, len(segments))
    for i, seg in enumerate(segments, start=1):
        text = seg.text.strip()
        translated = at.translate(text, src, tgt) if text else ""
        out.append(SubtitleSegment(index=seg.index, start=seg.start, end=seg.end, text=translated or text, gender=seg.gender, speaker_id=seg.speaker_id))
        if progress_cb:
            progress_cb(i / total, f"Đang dịch dòng {i}/{total}")
    return out


def translate_segments(
    segments: List[SubtitleSegment],
    source_lang: str,
    target_lang: str,
    method: str = "gemini_fastapi",
    progress_cb: Optional[Callable[[float, str], None]] = None,
    gemini_api_key: Optional[str] = None,
    gemini_api_keys: Optional[List[str]] = None,
    gemini_model: str = DEFAULT_GEMINI_MODEL,
    grok_api_keys: Optional[List[str]] = None,
    grok_model: str = DEFAULT_GROK_MODEL,
    content_persona: Optional[str] = None,
    gemini_fastapi_base_url: Optional[str] = None,
    gemini_fastapi_api_key: Optional[str] = None,
    gemini_fastapi_model: str = DEFAULT_GEMINI_FASTAPI_MODEL,
    gemini_webapi_secure_1psid: Optional[str] = None,
    gemini_webapi_secure_1psidts: Optional[str] = None,
    gemini_webapi_proxy: Optional[str] = None,
    gemini_webapi_model: str = DEFAULT_GEMINI_WEBAPI_MODEL,
    cliproxy_base_url: Optional[str] = None,
    cliproxy_api_key: Optional[str] = None,
    cliproxy_model: str = DEFAULT_CLIPROXY_MODEL,
    narrative_style: Optional[str] = None,
    audience: Optional[str] = None,
    speaking_speed: Optional[str] = None,
    creativity: Optional[str] = None,
    hook_level: Optional[str] = None,
    batch_size: Optional[int] = None,
    context_output: Optional[dict] = None,
) -> List[SubtitleSegment]:
    if method == "offline":
        return translate_segments_offline(segments, source_lang, target_lang, progress_cb)
    if method == "online":
        return translate_segments_online(segments, source_lang, target_lang, progress_cb=progress_cb)
    if method == "gemini":
        keys = list(gemini_api_keys or [])
        if gemini_api_key:
            keys.append(gemini_api_key)
        if not keys:
            raise ValueError("translation_method='gemini' cần truyền ít nhất 1 gemini_api_key")
        return translate_segments_gemini(
            segments, source_lang, target_lang, api_keys=keys,
            model=gemini_model, batch_size=(batch_size if batch_size is not None else 30),
            progress_cb=progress_cb, content_persona=content_persona,
            context_output=context_output,
        )
    if method == "grok":
        if not grok_api_keys:
            raise ValueError("translation_method='grok' cần truyền ít nhất 1 grok_api_key")
        return translate_segments_grok(
            segments, source_lang, target_lang, api_keys=grok_api_keys,
            model=grok_model, progress_cb=progress_cb, content_persona=content_persona,
        )
    if method == "gemini_fastapi":
        if not gemini_fastapi_base_url:
            raise ValueError(
                "translation_method='gemini_fastapi' cần truyền gemini_fastapi_base_url"
            )

        return translate_segments_gemini_fastapi(
            segments,
            source_lang,
            target_lang,
            base_url=gemini_fastapi_base_url,
            api_key=gemini_fastapi_api_key,
            model=gemini_fastapi_model,
            progress_cb=progress_cb,
            content_persona=content_persona,
            narrative_style=narrative_style,
            audience=audience,
            speaking_speed=speaking_speed,
            creativity=creativity,
            hook_level=hook_level,
            context_output=context_output,
        )

    if method == "cliproxy":
        if not cliproxy_base_url:
            raise ValueError(
                "translation_method='cliproxy' cần truyền cliproxy_base_url (vd http://127.0.0.1:8317)"
            )

        return translate_segments_cliproxy(
            segments,
            source_lang,
            target_lang,
            base_url=cliproxy_base_url,
            api_key=cliproxy_api_key,
            model=cliproxy_model,
            progress_cb=progress_cb,
            content_persona=content_persona,
            narrative_style=narrative_style,
            audience=audience,
            speaking_speed=speaking_speed,
            creativity=creativity,
            hook_level=hook_level,
        )

    if method == "gemini_webapi":
        if not gemini_webapi_secure_1psid:
            raise ValueError(
                "translation_method='gemini_webapi' cần truyền gemini_webapi_secure_1psid (cookie __Secure-1PSID)"
            )

        return translate_segments_gemini_webapi(
            segments,
            source_lang,
            target_lang,
            secure_1psid=gemini_webapi_secure_1psid,
            secure_1psidts=gemini_webapi_secure_1psidts,
            proxy=gemini_webapi_proxy,
            model=gemini_webapi_model,
            progress_cb=progress_cb,
            content_persona=content_persona,
            narrative_style=narrative_style,
            audience=audience,
            speaking_speed=speaking_speed,
            creativity=creativity,
            hook_level=hook_level,
        )

    # --------------------------------------------------
    # DEFAULT: method không khớp bất kỳ nhánh nào ở trên (vd giá trị lạ/rỗng) ->
    # rơi về Gemini Web2API như trước đây. "online" và "offline" đã có nhánh riêng
    # ở trên nên KHÔNG còn rơi vào đây nữa.
    # --------------------------------------------------

    return translate_segments_gemini_fastapi(
        segments,
        source_lang,
        target_lang,
        base_url=gemini_fastapi_base_url,
        api_key=gemini_fastapi_api_key,
        model=gemini_fastapi_model,
        progress_cb=progress_cb,
        content_persona=content_persona,
        narrative_style=narrative_style,
        audience=audience,
        speaking_speed=speaking_speed,
        creativity=creativity,
        hook_level=hook_level,
        context_output=context_output,
    )