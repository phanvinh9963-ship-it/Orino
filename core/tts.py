"""
core/tts.py
Tạo giọng lồng tiếng (dubbing) từ phụ đề đã dịch.

4 engine:
- "online"  : edge-tts (chất lượng cao, cần internet, đôi khi server Microsoft
              trả lỗi "No audio was received" tạm thời -> có retry tự động)
- "offline" : pyttsx3 (giọng máy tính có sẵn trong OS - Windows/macOS/Linux,
              không cần mạng, luôn chạy được, chất lượng thấp hơn edge-tts)
- "clone"   : giọng nhân bản bằng XTTS-v2 (xem core/voice_clone.py), cần cả
              audio mẫu LẪN transcript của audio mẫu (ref_text).
- "vieneu"  : VieNeu-TTS (xem core/vieneu_tts.py) - giọng tiếng Việt chạy LOCAL,
              không cần mạng, chạy tốt trên CPU, clone giọng chỉ cần audio mẫu
              (không cần ref_text). CHỈ hỗ trợ target_lang="Vietnamese".
              Cài đặt: pip install vieneu
- "omnivoice": OmniVoice (xem core/omnivoice_tts.py) - model zero-shot chạy
              LOCAL, hỗ trợ 600+ ngôn ngữ. 2 chế độ: CLONE giọng từ audio mẫu
              (voice_name, giống engine "clone") hoặc VOICE DESIGN mô tả giọng
              bằng văn bản (omnivoice_instruct, vd "female, low pitch, british
              accent") - không cần audio mẫu. Chạy tốt hơn nhiều trên GPU (CUDA)
              so với CPU. Cài đặt: pip install torch torchaudio omnivoice
"""
from __future__ import annotations
import asyncio
import os
import time
from dataclasses import replace
from typing import Callable, List, Optional, Tuple

from core.transcribe import SubtitleSegment

VOICE_MAP = {
    "English": "en-US-AriaNeural",
    "Vietnamese": "vi-VN-HoaiMyNeural",
    "Chinese": "zh-CN-XiaoxiaoNeural",
    "Japanese": "ja-JP-NanamiNeural",
    "Korean": "ko-KR-SunHiNeural",
    "French": "fr-FR-DeniseNeural",
    "Spanish": "es-ES-ElviraNeural",
}

# Giọng riêng theo GIỚI TÍNH cho từng ngôn ngữ - dùng khi core/gender_detect.py đã
# gán nhãn "male"/"female" cho từng câu (video có nhiều nhân vật thoại). Tên giọng
# đã kiểm tra đúng theo danh sách giọng neural chính thức của edge-tts.
VOICE_MAP_BY_GENDER = {
    "English":    {"male": "en-US-GuyNeural",    "female": "en-US-AriaNeural"},
    "Vietnamese": {"male": "vi-VN-NamMinhNeural", "female": "vi-VN-HoaiMyNeural"},
    "Chinese":    {"male": "zh-CN-YunxiNeural",   "female": "zh-CN-XiaoxiaoNeural"},
    "Japanese":   {"male": "ja-JP-KeitaNeural",   "female": "ja-JP-NanamiNeural"},
    "Korean":     {"male": "ko-KR-InJoonNeural",  "female": "ko-KR-SunHiNeural"},
    "French":     {"male": "fr-FR-HenriNeural",   "female": "fr-FR-DeniseNeural"},
    "Spanish":    {"male": "es-ES-AlvaroNeural",  "female": "es-ES-ElviraNeural"},
}

# Bo giong Edge MO RONG - nhieu lua chon Nam/Nu cho tung ngon ngu, de nguoi dung
# TU CHON dung 1 giong cu the cho tung nhan vat (thay vi chi 1 cap co dinh duy
# nhat o VOICE_MAP_BY_GENDER o tren) - dung de do UI (main.py) cho dropdown
# "Giọng Nam"/"Giọng Nữ" giong het pattern cua vieneu_voice_male/female. Tat ca
# ten giong deu la giong Neural chinh thuc cua Microsoft edge-tts.
EDGE_VOICE_OPTIONS = {
    "English": {
        "male":   ["en-US-GuyNeural", "en-US-DavisNeural", "en-US-TonyNeural", "en-GB-RyanNeural"],
        "female": ["en-US-AriaNeural", "en-US-JennyNeural", "en-US-SaraNeural", "en-GB-SoniaNeural"],
    },
    "Vietnamese": {
        "male":   ["vi-VN-NamMinhNeural"],
        "female": ["vi-VN-HoaiMyNeural"],
    },
    "Chinese": {
        "male":   ["zh-CN-YunxiNeural", "zh-CN-YunjianNeural", "zh-CN-YunyangNeural"],
        "female": ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural", "zh-CN-XiaomengNeural"],
    },
    "Japanese": {
        "male":   ["ja-JP-KeitaNeural"],
        "female": ["ja-JP-NanamiNeural"],
    },
    "Korean": {
        "male":   ["ko-KR-InJoonNeural"],
        "female": ["ko-KR-SunHiNeural"],
    },
    "French": {
        "male":   ["fr-FR-HenriNeural"],
        "female": ["fr-FR-DeniseNeural"],
    },
    "Spanish": {
        "male":   ["es-ES-AlvaroNeural"],
        "female": ["es-ES-ElviraNeural"],
    },
}


def list_edge_voice_options(target_lang: str) -> dict:
    """Tra ve {"male": [...], "female": [...]} danh sach ten giong Edge co san cho
    1 ngon ngu - dung de do dropdown UI (main.py). Fallback ve VOICE_MAP_BY_GENDER
    (1 giong/gioi tinh) neu ngon ngu khong co trong EDGE_VOICE_OPTIONS."""
    if target_lang in EDGE_VOICE_OPTIONS:
        return EDGE_VOICE_OPTIONS[target_lang]
    fallback = VOICE_MAP_BY_GENDER.get(target_lang)
    if fallback:
        return {"male": [fallback["male"]], "female": [fallback["female"]]}
    return {"male": [], "female": []}


def fetch_all_edge_voices() -> dict:
    """Lay TOAN BO danh sach giong Edge THAT tu server Microsoft (khong gioi han
    theo EDGE_VOICE_OPTIONS curated o tren) - vai tram giong, du moi ngon ngu/vung
    mien edge-tts ho tro. Can mang + thu vien edge-tts. Ham nay CHAY DONG BO (blocking)
    - goi tu 1 thread nen trong UI (xem main.py:_reload_edge_voice_options_full), vi
    edge_tts.list_voices() la ham async, can 1 event loop rieng de chay o day.

    Tra ve {"male": [...], "female": [...]} - moi phan tu dang
    "<ShortName> — <Locale/ten ngon ngu than thien>" de nguoi dung de nhan biet
    ngon ngu/vung mien cua tung giong khi danh sach rat dai (400+ giong), nhung
    PHAN TRUOC dau "—" van la ShortName goc dung duoc thang cho edge_voice_male/
    female (xem main.py: tach lay phan truoc dau '—' truoc khi luu vao PipelineConfig).
    """
    import asyncio
    import edge_tts

    async def _fetch():
        return await edge_tts.list_voices()

    loop = asyncio.new_event_loop()
    try:
        voices = loop.run_until_complete(_fetch())
    finally:
        loop.close()

    male, female = [], []
    for v in sorted(voices, key=lambda v: (v.get("Locale", ""), v.get("ShortName", ""))):
        short_name = v.get("ShortName", "")
        gender = (v.get("Gender") or "").lower()
        locale = v.get("Locale", "")
        friendly = v.get("FriendlyName", "") or locale
        label = f"{short_name} — {friendly}"
        if gender == "male":
            male.append(label)
        elif gender == "female":
            female.append(label)
    return {"male": male, "female": female}

# Mã ngôn ngữ ngắn dùng để pyttsx3 lọc giọng phù hợp trên máy (dựa vào espeak/SAPI)
LANG_SHORT = {
    "English": "en", "Vietnamese": "vi", "Chinese": "zh",
    "Japanese": "ja", "Korean": "ko", "French": "fr", "Spanish": "es",
}


async def _synth_one_edge(text: str, voice: str, out_path: str, rate: str = "+0%", retries: int = 4, timeout: float = 35.0):
    """Gọi edge-tts, tự retry nếu gặp lỗi tạm thời (No audio was received, timeout, mất mạng...).

    `rate`: tốc độ đọc GỐC do chính giọng AI tạo ra (vd "+8%", "-5%"), theo cú
    pháp SSML prosody rate của edge-tts. Nghe TỰ NHIÊN hơn nhiều so với tăng
    tốc hậu kỳ bằng ffmpeg atempo (core/tts.py:_speed_up_audio) vì ngữ điệu,
    chỗ ngắt hơi được chính model TTS tính lại theo tốc độ mới, không phải chỉ
    kéo giãn/nén sóng âm có sẵn. "+0%" = tốc độ đọc trung bình mặc định của
    giọng đó (khuyến nghị dùng mặc định, chỉnh nhẹ +5%~+10% nếu muốn phong
    cách dẫn chuyện dứt khoát hơn kiểu review phim).

    `timeout`: nâng lên 35s (trước 20s) - server edge-tts đôi khi phản hồi chậm
    hơn bình thường vài giây, timeout quá ngắn dễ bị coi là lỗi oan trong khi
    thực ra chỉ cần đợi thêm.
    `retries`: nâng lên 4 lần (trước 3) với backoff SÂU hơn (3s, 6s, 9s, 12s
    thay vì 1.5s, 3s, 4.5s) - cho server đủ thời gian hồi phục nếu đang bị
    rate-limit/nghẽn tạm thời, thay vì dồn dập thử lại quá nhanh.
    """
    import edge_tts

    last_err: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            # Dọn file dở dang từ lần thử TRƯỚC (nếu có) - tránh trường hợp hiếm
            # gặp edge-tts ghi được 1 phần rồi mới lỗi, để lại file .mp3 rỗng/vỡ
            # nằm sai vị trí, dễ gây nhầm lẫn khi debug thủ công sau này.
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass

            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await asyncio.wait_for(communicate.save(out_path), timeout=timeout)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return
            raise RuntimeError("File audio rỗng (edge-tts trả về nhưng không có dữ liệu âm thanh)")
        except Exception as e:
            last_err = e
            if attempt < retries:
                await asyncio.sleep(3.0 * attempt)   # backoff sâu hơn: 3s, 6s, 9s...

    raise RuntimeError(f"edge-tts lỗi sau {retries} lần thử: {_describe_exception(last_err, timeout)}")


def _describe_exception(e: Optional[BaseException], timeout: float = 0.0) -> str:
    """Trả về mô tả lỗi LUÔN có nội dung, kể cả với các loại exception mà
    str(e) rỗng theo THIẾT KẾ của Python (không phải bug) - vd TimeoutError,
    asyncio.CancelledError đều có str() = "" nếu không truyền message cụ thể
    lúc raise. Trước đây dùng thẳng f"{last_err}" nên những trường hợp này
    hiện ra thành chuỗi RỖNG trong log ("edge-tts lỗi sau 4 lần thử: ") -
    trông như lỗi không rõ nguyên nhân, dù thực chất luôn XÁC ĐỊNH được (hầu
    hết là do server edge-tts phản hồi chậm hơn timeout đang đặt, hoặc mạng
    chập chờn ngay lúc đó)."""
    if e is None:
        return "(không xác định được lỗi cụ thể)"

    msg = str(e).strip()
    type_name = type(e).__name__

    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return f"{type_name}: server edge-tts không phản hồi trong {timeout:.0f}s (mạng chậm/server quá tải tạm thời)"
    if isinstance(e, asyncio.CancelledError):
        return f"{type_name}: yêu cầu bị huỷ giữa chừng (có thể do mất kết nối mạng đột ngột)"
    if msg:
        return f"{type_name}: {msg}"
    return f"{type_name} (không có thông tin chi tiết kèm theo từ thư viện edge-tts)"


def _synth_silence(duration_sec: float, out_path: str):
    """Phao cứu CUỐI CÙNG - tạo 1 đoạn audio im lặng đúng bằng thời lượng cue gốc,
    dùng khi CẢ edge-tts lẫn offline (pyttsx3) đều lỗi cho 1 câu cụ thể. Mục đích:
    không để 1 câu lỗi làm SẬP TOÀN BỘ job (mất công mọi câu đã lồng xong trước đó) -
    thà thiếu tiếng 1 câu (rồi tự lồng tay lại sau, xem cảnh báo cuối log) còn hơn
    phải chạy lại từ đầu cả video."""
    import subprocess
    dur = max(0.3, duration_sec)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
         "-t", f"{dur:.3f}", out_path],
        check=True, capture_output=True,
    )


def _synth_one_offline(text: str, lang: str, out_path: str):
    """Dùng giọng máy tính (pyttsx3) - chỉ dùng khi máy có sẵn giọng đúng ngôn ngữ.

    Nếu không tìm thấy giọng phù hợp trên máy, raise lỗi rõ ràng thay vì
    âm thầm dùng giọng mặc định (thường là tiếng Anh) -> đây chính là
    nguyên nhân gây ra hiện tượng "câu tiếng Việt bị đọc bằng giọng tiếng Anh".
    """
    try:
        import pyttsx3
    except ImportError as e:
        raise RuntimeError(
            "Thiếu thư viện 'pyttsx3' (giọng offline dự phòng) - chạy lệnh sau rồi thử lại: "
            "pip install pyttsx3"
        ) from e

    engine = pyttsx3.init()
    short = LANG_SHORT.get(lang, "en")

    matched_id = None
    for v in engine.getProperty("voices"):
        langs = [str(l).lower() for l in getattr(v, "languages", [])]
        vid = v.id.lower()
        vname = str(getattr(v, "name", "")).lower()
        if short in langs or short in vid or short in vname:
            matched_id = v.id
            break

    if matched_id is None:
        engine.stop()
        raise RuntimeError(
            f"Không tìm thấy giọng offline (pyttsx3) cho ngôn ngữ '{lang}' trên máy này. "
            f"Cần cài thêm gói giọng đọc '{short}' cho hệ điều hành, "
            f"hoặc dùng lại engine online (edge-tts)."
        )

    engine.setProperty("voice", matched_id)
    engine.save_to_file(text, out_path)
    engine.runAndWait()
    engine.stop()


def synthesize_segments(
    segments: List[SubtitleSegment],
    target_lang: str,
    out_dir: str,
    engine: str = "online",       # "online" (edge-tts) | "offline" (pyttsx3) | "clone" (XTTS-v2) | "vieneu" (VieNeu-TTS, local)
    voice_name: Optional[str] = None,     # bắt buộc nếu engine="clone"
    profiles_dir: Optional[str] = None,   # bắt buộc nếu engine="clone"
    clone_device: str = "auto",
    speech_rate: str = "+0%",     # tốc độ đọc gốc (chỉ áp dụng cho engine="online"), vd "+8%" cho nhịp dứt khoát hơn
    voice_gender: Optional[str] = None,   # "male" | "female" | None - chọn TAY 1 giọng cố định cho
                                            # CẢ VIDEO (ghi đè VOICE_MAP mặc định). Segment nào ĐÃ có
                                            # `gender` riêng (do auto-detect gán) vẫn ưu tiên dùng gender
                                            # riêng của câu đó - voice_gender chỉ là giá trị NỀN dùng cho
                                            # các câu không có gender riêng (vd auto-detect đang tắt).
    vieneu_voice_male: Optional[str] = None,     # engine="vieneu" only: giọng VieNeu-TTS RIÊNG cho các
                                            # câu có seg.gender="male" (tên voice profile hoặc ID giọng
                                            # dựng sẵn) - xem "Lồng tiếng · Giọng lồng · Tiếng Việt" ở UI.
    vieneu_voice_female: Optional[str] = None,   # tương tự, cho seg.gender="female"
    edge_voice_male: Optional[str] = None,       # engine="online" only: TỰ CHỌN 1 giọng Edge cụ thể cho
                                            # câu có seg.gender="male" (vd "en-US-DavisNeural"), GHI ĐÈ
                                            # VOICE_MAP_BY_GENDER mặc định - xem list_edge_voice_options().
    edge_voice_female: Optional[str] = None,     # tương tự, cho seg.gender="female".
    omnivoice_instruct: Optional[str] = None,    # engine="omnivoice" only: mô tả giọng cho VOICE DESIGN
                                            # (vd "female, low pitch, british accent") - dùng khi KHÔNG
                                            # truyền voice_name (voice_name có thì ưu tiên CLONE giọng đó).
    omnivoice_instruct_male: Optional[str] = None,    # tương tự vieneu_voice_male nhưng cho OmniVoice
                                            # voice design: mô tả giọng RIÊNG cho câu có seg.gender="male".
    omnivoice_instruct_female: Optional[str] = None,  # tương tự, cho seg.gender="female".
    omnivoice_device: str = "auto",        # engine="omnivoice" only: "auto" | "cpu" | "cuda:0" | "mps"
    omnivoice_num_step: int = 32,          # engine="omnivoice" only: số bước diffusion (16 = nhanh hơn, thấp chất lượng hơn)
    omnivoice_speed: float = 1.0,          # engine="omnivoice" only: hệ số tốc độ đọc
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[str]:
    """
    Tạo 1 file mp3/wav cho mỗi câu thoại. Trả về danh sách đường dẫn file audio theo đúng thứ tự.

    LƯU Ý QUAN TRỌNG:
    Mỗi câu tự thử engine online riêng biệt. Nếu 1 câu bị lỗi tạm thời (mất mạng,
    server nghẽn...) thì CHỈ câu đó mới rơi xuống giọng offline; các câu sau vẫn
    tiếp tục thử online bình thường. Trước đây có 1 bug khiến chỉ cần 1 câu lỗi
    là toàn bộ phần còn lại của video bị khoá cứng sang offline -> nếu máy không
    có sẵn giọng tiếng Việt, pyttsx3 lặng lẽ dùng giọng mặc định (thường là tiếng Anh),
    gây ra hiện tượng nghe "xen kẽ" Việt/Anh giữa các câu.

    engine="clone": dùng giọng đã nhân bản của chính bạn (XTTS-v2) thay vì giọng
    có sẵn. KHÔNG có fallback tự động sang engine khác nếu lỗi, để tránh việc
    video bị lẫn giữa giọng thật của bạn và giọng máy khác mà không báo trước.

    engine="vieneu": dùng VieNeu-TTS (core/vieneu_tts.py) - chạy LOCAL trên CPU,
    không cần mạng. CHỈ hỗ trợ target_lang="Vietnamese" (raise lỗi rõ ràng nếu
    khác). voice_name có thể là 1 voice profile trong voice_profiles_dir (clone
    giọng từ audio mẫu, không cần ref_text) hoặc 1 ID giọng dựng sẵn của
    VieNeu-TTS; để trống thì dùng giọng mặc định của model. Cũng KHÔNG fallback
    tự động sang engine khác nếu lỗi. Nếu vieneu_voice_male/vieneu_voice_female
    được truyền, câu nào có gender riêng (auto-detect) sẽ dùng ĐÚNG giọng theo
    giới tính đó thay vì voice_name - giống cơ chế NHIỀU GIỌNG THEO GIỚI TÍNH
    TỰ ĐỘNG mô tả bên dưới (vốn trước đây chỉ áp dụng cho engine="online").

    CHỌN TAY NAM/NỮ CHO CẢ VIDEO (voice_gender, engine="online" only):
    Dùng khi bạn đã tự xem trước video và biết rõ nên dùng giọng Nam hay Nữ,
    KHÔNG cần auto-detect (vốn dễ sai với video review/thuyết minh cắt cảnh
    nhanh nhiều nhân vật - xem thảo luận trước). Đây là lựa chọn CỐ ĐỊNH, áp
    dụng đồng nhất cho MỌI câu không có gender riêng.

    NHIỀU GIỌNG THEO GIỚI TÍNH TỰ ĐỘNG (engine="online" only):
    Nếu segment có `gender` = "male"/"female" (do core/gender_detect.py hoặc
    core/face_speaker_detect.py TỰ ĐỘNG gán khi video có nhiều nhân vật thoại),
    dùng đúng giọng Nam/Nữ tương ứng cho câu đó - ƯU TIÊN CAO HƠN voice_gender
    (vì gender riêng của câu chi tiết hơn 1 lựa chọn chung cho cả video). Segment
    không có gender riêng (rỗng, "") thì dùng voice_gender (nếu có) hoặc VOICE_MAP
    mặc định (nếu voice_gender cũng không truyền) - tương thích ngược hoàn toàn.
    Giọng Nam/Nữ dùng mặc định lấy từ VOICE_MAP_BY_GENDER (1 cặp cố định/ngôn ngữ);
    truyền edge_voice_male/edge_voice_female để TỰ CHỌN đúng 1 giọng cụ thể khác
    trong nhiều giọng Edge khả dụng (xem list_edge_voice_options()) - giống hệt cơ
    chế vieneu_voice_male/vieneu_voice_female bên trên nhưng cho engine="online".
    """
    if engine == "clone":
        from core.voice_clone import synthesize_segments_cloned
        if not voice_name or not profiles_dir:
            raise ValueError("engine='clone' yêu cầu phải truyền voice_name và profiles_dir")
        return synthesize_segments_cloned(
            segments, target_lang, voice_name, profiles_dir, out_dir,
            device=clone_device, progress_cb=progress_cb,
        )

    if engine == "vieneu":
        from core.vieneu_tts import synthesize_segments_vieneu
        voice_by_gender = None
        if vieneu_voice_male or vieneu_voice_female:
            voice_by_gender = {}
            if vieneu_voice_male:
                voice_by_gender["male"] = vieneu_voice_male
            if vieneu_voice_female:
                voice_by_gender["female"] = vieneu_voice_female
        return synthesize_segments_vieneu(
            segments, target_lang, out_dir,
            voice_name=voice_name, profiles_dir=profiles_dir,
            voice_by_gender=voice_by_gender,
            progress_cb=progress_cb,
        )

    if engine == "omnivoice":
        from core.omnivoice_tts import synthesize_segments_omnivoice
        instruct_by_gender = None
        if omnivoice_instruct_male or omnivoice_instruct_female:
            instruct_by_gender = {}
            if omnivoice_instruct_male:
                instruct_by_gender["male"] = omnivoice_instruct_male
            if omnivoice_instruct_female:
                instruct_by_gender["female"] = omnivoice_instruct_female
        return synthesize_segments_omnivoice(
            segments, target_lang, out_dir,
            voice_name=voice_name, profiles_dir=profiles_dir,
            instruct=omnivoice_instruct, instruct_by_gender=instruct_by_gender,
            device=omnivoice_device, num_step=omnivoice_num_step, speed=omnivoice_speed,
            progress_cb=progress_cb,
        )

    os.makedirs(out_dir, exist_ok=True)
    # Chọn voice mặc định theo ngôn ngữ
    gender_voices = dict(VOICE_MAP_BY_GENDER.get(target_lang) or {})
    # GHI ĐÈ bằng lựa chọn TAY của người dùng (edge_voice_male/female) nếu có -
    # cho phép chọn ĐÚNG 1 giọng cụ thể trong nhiều giọng Edge khả dụng cho mỗi
    # giới tính, thay vì luôn dùng đúng 1 cặp cố định của VOICE_MAP_BY_GENDER.
    if edge_voice_male:
        gender_voices["male"] = edge_voice_male
    if edge_voice_female:
        gender_voices["female"] = edge_voice_female

    if voice_gender and gender_voices and voice_gender in gender_voices:
        default_voice = gender_voices[voice_gender]
    else:
        default_voice = VOICE_MAP.get(target_lang, "vi-VN-HoaiMyNeural")

    def _voice_for(seg: SubtitleSegment) -> str:
        if gender_voices and seg.gender in gender_voices:
            return gender_voices[seg.gender]   # gender riêng của câu (auto-detect) - ưu tiên cao nhất
        return default_voice

    paths: List[str] = []
    total = max(1, len(segments))
    failed_indices: List[int] = []  # các câu phải chèn khoảng lặng (lỗi CẢ edge-tts lẫn offline)
    # MỚI: các câu đã tạm dùng offline do edge-tts lỗi ở LƯỢT ĐẦU - lưu lại để THỬ LẠI
    # edge-tts 1 LẦN NỮA sau khi đã xử lý xong HẾT các câu còn lại (xem đoạn "lượt 2"
    # bên dưới, sau vòng lặp chính). Lý do: lỗi edge-tts thường do server NGHẼN TẠM
    # THỜI (rate-limit/quá tải theo đợt) - thử lại NGAY LẬP TỨC (như code cũ) rất hay
    # rơi đúng vào lúc server vẫn còn nghẽn, nên vẫn lỗi tiếp. Đợi tới cuối video (đã
    # trôi qua vài chục giây - vài phút xử lý các câu khác) rồi mới thử lại thì server
    # gần như chắc chắn đã hồi phục, tỉ lệ thành công cao hơn hẳn - giảm mạnh số câu
    # phải dùng giọng offline (nghe khác hẳn giọng chính, gây "xen kẽ" khó chịu).
    pending_retry: List[dict] = []   # [{"list_idx": int, "seg": SubtitleSegment, "voice": str, "old_offline_path": str}, ...]

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        for i, seg in enumerate(segments, start=1):
            text = seg.text.strip() or "..."
            used_offline = False

            if engine == "offline":
                out_path = os.path.join(out_dir, f"seg_{seg.index:04d}.wav")
                _synth_one_offline(text, target_lang, out_path)
                used_offline = True
            else:
                out_path_mp3 = os.path.join(out_dir, f"seg_{seg.index:04d}.mp3")
                voice = _voice_for(seg)
                try:
                    loop.run_until_complete(_synth_one_edge(text, voice, out_path_mp3, rate=speech_rate))
                    out_path = out_path_mp3
                except Exception as e:
                    # THEO YÊU CẦU: KHÔNG rơi xuống offline ngay - DỪNG LẠI CHỜ rồi thử
                    # lại edge-tts LIÊN TỤC cho tới khi thành công mới đi tiếp, để giữ
                    # ĐÚNG 1 GIỌNG xuyên suốt cả video, không xen kẽ offline/online nữa.
                    # Backoff tăng dần (15s -> 30s -> 60s -> 60s...) để không dồn dập
                    # request vào đúng lúc server đang nghẽn, nhưng vẫn tự động thử lại
                    # đều đặn KHÔNG CẦN can thiệp tay. Có 1 TRẦN AN TOÀN ~8 phút (có thể
                    # chỉnh qua edge_tts_max_wait_sec) - nếu edge-tts sập/mất mạng THẬT
                    # SỰ dài hạn, job vẫn phải đi tiếp (dùng offline làm phao cứu bất đắc
                    # dĩ CUỐI CÙNG) thay vì treo cứng vô thời hạn, có thể khiến cả job kẹt
                    # qua đêm không ai hay biết.
                    if progress_cb:
                        progress_cb(i / total, f"⚠ edge-tts lỗi ở câu {i} ({e}) - đang DỪNG LẠI chờ rồi thử lại...")

                    wait_backoffs = [15, 30, 60, 60, 60, 60, 60, 60]   # tổng ~7.25 phút nếu lỗi hết cả 8 lần
                    out_path = None
                    for wait_i, wait_sec in enumerate(wait_backoffs, start=1):
                        if progress_cb:
                            progress_cb(i / total, f"   ...chờ {wait_sec}s rồi thử lại edge-tts (lần chờ {wait_i}/{len(wait_backoffs)})")
                        time.sleep(wait_sec)
                        try:
                            loop.run_until_complete(_synth_one_edge(text, voice, out_path_mp3, rate=speech_rate, retries=2))
                            out_path = out_path_mp3
                            if progress_cb:
                                progress_cb(i / total, f"✓ Câu {i}: edge-tts đã sống lại sau {wait_i} lần chờ, tiếp tục bình thường")
                            break
                        except Exception:
                            continue

                    if out_path is None:
                        # Hết hạn mức chờ (~8 phút) mà edge-tts VẪN lỗi - đây là dấu hiệu
                        # sự cố THẬT SỰ (mất mạng hẳn, hoặc server sập diện rộng), không
                        # còn là "nghẽn tạm thời" nữa - bất đắc dĩ dùng offline để job vẫn
                        # đi tiếp được, không treo cứng vô thời hạn.
                        if progress_cb:
                            progress_cb(i / total, f"❌ Câu {i}: edge-tts vẫn lỗi sau ~8 phút chờ - bất đắc dĩ dùng giọng offline")
                        out_path_wav = os.path.join(out_dir, f"seg_{seg.index:04d}.wav")
                        try:
                            _synth_one_offline(text, target_lang, out_path_wav)
                            out_path = out_path_wav
                            used_offline = True
                            pending_retry.append({
                                "list_idx": len(paths), "seg": seg, "voice": voice,
                                "old_offline_path": out_path_wav, "display_i": i,
                            })
                        except Exception as e2:
                            if progress_cb:
                                progress_cb(
                                    i / total,
                                    f"❌ Câu {i} lỗi CẢ edge-tts lẫn offline ({e2}) - đã chèn khoảng "
                                    f"lặng thay thế, cần tự lồng tay lại câu này sau: \"{text[:60]}\"",
                                )
                            out_path_sil = os.path.join(out_dir, f"seg_{seg.index:04d}.wav")
                            _synth_silence(max(0.5, seg.end - seg.start), out_path_sil)
                            out_path = out_path_sil
                            failed_indices.append(i)
                else:
                    time.sleep(0.4)  # nghỉ nhẹ giữa mỗi câu online để tránh dồn request gây rate-limit

            paths.append(out_path)
            if progress_cb:
                progress_cb(i / total, f"Đang tạo giọng đọc {i}/{total}" + (" (offline)" if used_offline else ""))

        # LƯỢT 2 - thử lại edge-tts cho các câu đã tạm dùng offline ở lượt đầu, SAU KHI
        # đã xử lý xong toàn bộ video (server có đủ thời gian hồi phục nếu lỗi trước đó
        # là do nghẽn tạm thời). Câu nào thành công lần này sẽ THAY THẾ file offline tạm
        # bằng giọng edge-tts thật - giữ đồng nhất giọng đọc xuyên suốt cả video.
        if pending_retry and engine != "offline":
            if progress_cb:
                progress_cb(1.0, f"Đang thử lại edge-tts cho {len(pending_retry)} câu trước đó lỗi tạm thời...")
            for item in pending_retry:
                seg = item["seg"]
                text = seg.text.strip() or "..."
                retry_path = os.path.join(out_dir, f"seg_{seg.index:04d}_retry.mp3")
                try:
                    loop.run_until_complete(_synth_one_edge(text, item["voice"], retry_path, rate=speech_rate, retries=2))
                    paths[item["list_idx"]] = retry_path
                    try:
                        os.remove(item["old_offline_path"])
                    except OSError:
                        pass
                    if progress_cb:
                        progress_cb(1.0, f"✓ Câu {item['display_i']}: thử lại edge-tts thành công, đã thay thế giọng offline tạm")
                except Exception:
                    if progress_cb:
                        progress_cb(1.0, f"— Câu {item['display_i']}: vẫn giữ giọng offline (edge-tts vẫn chưa hồi phục)")
                time.sleep(0.4)
    finally:
        loop.close()
    if failed_indices and progress_cb:
        progress_cb(
            1.0,
            f"⚠ TỔNG KẾT: {len(failed_indices)} câu bị chèn khoảng lặng (lỗi cả edge-tts lẫn "
            f"offline) ở vị trí {failed_indices} - video vẫn xuất được bình thường, nhưng nên "
            f"lồng tay lại các câu này.",
        )
    return paths


CALIBRATION_SAMPLE_TEXT = {
    "Vietnamese": (
        "Đây là một câu mẫu để đo tốc độ đọc thực tế của giọng nói này, "
        "giúp khớp thời lượng đọc chính xác hơn cho toàn bộ video, tránh "
        "bị tăng tốc hoặc chồng tiếng khi ghép vào timeline."
    ),
    "English": (
        "This is a sample sentence used to measure the actual reading speed "
        "of this voice, so the narration timing can be matched accurately "
        "across the whole video without needing extra speed-up."
    ),
}


def measure_actual_cps(
    sample_text: str,
    target_lang: str,
    engine: str = "online",
    voice_name: Optional[str] = None,
    profiles_dir: Optional[str] = None,
    clone_device: str = "auto",
    speech_rate: str = "+0%",
    omnivoice_instruct: Optional[str] = None,
    omnivoice_device: str = "auto",
    omnivoice_num_step: int = 32,
    omnivoice_speed: float = 1.0,
    fixed_overhead_sec: float = 0.35,
) -> Optional[float]:
    """
    Đo tốc độ đọc THỰC TẾ (ký tự/giây) của chính engine/giọng SẼ dùng để tạo audio,
    bằng cách tổng hợp thử 1 câu mẫu rồi đo thời lượng file audio thực tế - thay vì
    dựa vào bảng CHARS_PER_SEC tĩnh (core/text_fit.py), vốn chỉ là số liệu tham khảo
    hiệu chỉnh theo giọng edge-tts mặc định.

    QUAN TRỌNG: giọng nhân bản (engine="clone", XTTS-v2/viXTTS) hay giọng offline
    (pyttsx3) thường có tốc độ đọc khác hẳn edge-tts - nếu core/text_fit.py vẫn ước
    lượng theo bảng cũ trong khi audio thật lại tạo bằng giọng khác, phần chênh lệch
    này chính là nguyên nhân câu vẫn bị tăng tốc (atempo) dù văn bản đã "rút gọn cho
    vừa" theo ước lượng sai - vì ước lượng và thực tế lệch nhau ngay từ đầu.

    Trả về None nếu đo thất bại (engine lỗi, thiếu voice profile...) - lúc đó
    core/pipeline.py sẽ tự động dùng lại bảng CHARS_PER_SEC tĩnh như cũ.
    """
    import shutil
    import tempfile
    from core.transcribe import SubtitleSegment
    from pydub import AudioSegment

    n_chars = len(sample_text.strip())
    if n_chars == 0:
        return None

    tmp_dir = tempfile.mkdtemp(prefix="cps_calib_")
    try:
        dummy_seg = SubtitleSegment(index=1, start=0.0, end=n_chars / 10.0 + 5.0, text=sample_text)
        paths = synthesize_segments(
            [dummy_seg], target_lang, tmp_dir,
            engine=engine, voice_name=voice_name, profiles_dir=profiles_dir,
            clone_device=clone_device, speech_rate=speech_rate,
            omnivoice_instruct=omnivoice_instruct, omnivoice_device=omnivoice_device,
            omnivoice_num_step=omnivoice_num_step, omnivoice_speed=omnivoice_speed,
        )
        if not paths:
            return None
        clip = AudioSegment.from_file(paths[0])
        dur_sec = len(clip) / 1000.0
        if dur_sec <= fixed_overhead_sec:
            return None
        return n_chars / (dur_sec - fixed_overhead_sec)
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _speed_up_audio(path: str, ratio: float):
    """
    Tăng tốc audio bằng ffmpeg 'atempo' (giữ nguyên cao độ giọng nói, không bị
    méo tiếng như khi tua nhanh thô kiểu resample). atempo chỉ nhận giá trị
    trong khoảng [0.5, 2.0] mỗi lần áp dụng, nên nếu ratio lớn/nhỏ hơn phải
    chain nhiều bước lại (vd ratio=3.0 -> atempo=2.0,atempo=1.5).
    """
    import subprocess
    import tempfile
    from pydub import AudioSegment

    r = ratio
    filters = []
    while r > 2.0:
        filters.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        filters.append("atempo=0.5")
        r /= 0.5
    filters.append(f"atempo={r:.4f}")
    filter_str = ",".join(filters)

    fd, tmp_out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        cmd = ["ffmpeg", "-y", "-i", path, "-filter:a", filter_str, tmp_out]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg atempo lỗi:\n{proc.stdout}")
        return AudioSegment.from_file(tmp_out)
    finally:
        if os.path.exists(tmp_out):
            os.remove(tmp_out)


def build_dubbed_track_from_real_audio(
    segments: List[SubtitleSegment],
    audio_paths: List[str],
    out_path: str,
    min_gap_sec: float = 0.12,
    max_gap_sec: float = 1.2,
    keep_original_start: bool = True,
    total_duration_sec: Optional[float] = None,
    max_speedup: float = 1.15,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Tuple[str, List[SubtitleSegment]]:
    """
    FIX TRIỆT ĐỂ nạn "cắt bớt đuôi câu": build_dubbed_track (bản cũ) đặt clip theo
    timeline đã ƯỚC LƯỢNG TRƯỚC (từ core/rewrite_srt.py:retime_segments - dựa theo số
    ký tự × tốc độ đọc đo được), rồi mới tạo audio - nên clip THẬT (luôn có sai số nhỏ
    so với ước lượng, do ngữ điệu/dấu câu/cách ngắt hơi của từng câu khác nhau) có thể
    dài hơn đúng cái khung giờ đã ước lượng sẵn cho nó, dẫn tới phải cắt.

    Hàm này ĐẢO THỨ TỰ: nhận vào audio ĐÃ SINH XONG (audio_paths - biết chính xác độ
    dài THẬT), rồi mới XẾP TIMELINE dựa trên độ dài THẬT đó. Vị trí đặt luôn khớp đúng
    100% với clip thật -> KHÔNG BAO GIỜ cần cắt bớt clip nào cả.

    Logic xếp (giống hệt tinh thần retime_segments, nhưng dùng SỐ ĐO THẬT thay vì ước
    lượng):
      1. Nếu tổng thời lượng (clip thật + khoảng nghỉ mong muốn) đã NẰM VỪA trong
         total_duration_sec (hoặc không giới hạn) -> xếp tuần tự, khoảng nghỉ giữ
         nguyên như mong muốn (dựa theo khoảng lặng gốc, kẹp giữa min/max_gap_sec).
      2. Nếu VƯỢT total_duration_sec -> nén khoảng nghỉ về min_gap_sec trước.
      3. Nén hết khoảng nghỉ vẫn vượt -> tăng tốc ĐỀU (1 hệ số DUY NHẤT áp cho TẤT
         CẢ clip, giữ cao độ qua atempo) tối đa `max_speedup` - nhịp đọc nhanh hơn
         bình thường một chút nhưng ĐỀU xuyên suốt, không có câu nào bị xử ép riêng,
         và QUAN TRỌNG NHẤT: không mất chữ nào cả, vì atempo giữ nguyên toàn bộ audio,
         chỉ nén thời gian phát lại, không cắt bớt phần nào.
      4. Nếu tăng tốc hết max_speedup mà VẪN vượt (cực hiếm - kịch bản viết quá dài
         so với khung giờ dù đã qua bước char_budgets ở rewrite) -> CHẤP NHẬN video
         dài hơn total_duration_sec một chút (báo cảnh báo rõ ràng), còn hơn mất chữ.

    Trả về (out_path, segments_mới) - segments_mới có start/end THẬT đã xếp, dùng để
    đồng bộ phụ đề hiển thị (subtitle_segments = segments_mới khi sync_subtitle_to_dub).
    """
    from pydub import AudioSegment

    if not segments or not audio_paths or len(segments) != len(audio_paths):
        raise ValueError("segments và audio_paths phải khớp số lượng, không được rỗng")

    n = len(segments)
    clips = [AudioSegment.from_file(p) for p in audio_paths]
    real_durs = [len(c) / 1000.0 for c in clips]  # giây, ĐO THẬT từ file audio đã sinh

    wanted_gaps = []
    for i in range(1, n):
        original_gap = segments[i].start - segments[i - 1].end
        capped = min(max(original_gap, 0.0), max_gap_sec) if original_gap > 0 else 0.0
        wanted_gaps.append(max(capped, min_gap_sec))

    start0 = segments[0].start if keep_original_start else 0.0
    gaps = wanted_gaps
    speed_ratio = 1.0

    if total_duration_sec is not None:
        budget = max(0.0, total_duration_sec - start0)
        total_natural = sum(real_durs) + sum(wanted_gaps)

        if total_natural > budget:
            min_gap_total = min_gap_sec * (n - 1) if n > 1 else 0.0
            total_dur_only = sum(real_durs)
            if total_dur_only + min_gap_total <= budget:
                extra = budget - total_dur_only - min_gap_total
                extra_each = extra / (n - 1) if n > 1 else 0.0
                gaps = [min_gap_sec + extra_each for _ in wanted_gaps]
            else:
                gaps = [min_gap_sec for _ in wanted_gaps]
                budget_for_durs = max(0.0, budget - min_gap_total)
                needed_ratio = total_dur_only / budget_for_durs if budget_for_durs > 0 else 999.0
                speed_ratio = min(needed_ratio, max_speedup)
                if speed_ratio > 1.01:
                    if progress_cb:
                        progress_cb(
                            0.0,
                            f"Kịch bản hơi dài hơn khung giờ gốc - tăng tốc ĐỀU {speed_ratio:.2f}x "
                            f"cho toàn bộ {n} câu (không mất chữ câu nào).",
                        )
                    sped = []
                    for i, path in enumerate(audio_paths):
                        try:
                            sped.append(_speed_up_audio(path, speed_ratio))
                        except Exception:
                            sped.append(clips[i])
                        if progress_cb:
                            progress_cb((i + 1) / n, f"Đang tăng tốc đều clip {i + 1}/{n}")
                    clips = sped
                    real_durs = [len(c) / 1000.0 for c in clips]
                    if needed_ratio > max_speedup and progress_cb:
                        progress_cb(
                            1.0,
                            f"⚠ Đã tăng tốc tối đa ({max_speedup}x) nhưng kịch bản vẫn hơi dài hơn "
                            f"video gốc (~{(needed_ratio / max_speedup - 1) * 100:.1f}% dư) - video "
                            f"output sẽ dài hơn gốc một chút, KHÔNG mất chữ câu nào.",
                        )

    # ĐẶT VỊ TRÍ: ưu tiên NEO mỗi câu về đúng timestamp gốc của nó (segments[i].start -
    # khớp với đúng lúc nội dung/hình ảnh tương ứng xuất hiện trên màn hình, giống SRT gốc)
    # - CHỈ đẩy lùi bằng cursor nối đuôi khi thật sự bị CHỒNG LẤN với câu trước (audio câu
    # trước đọc dài hơn thời lượng gốc của nó, lấn sang giờ của câu này). Trước đây LUÔN
    # nối đuôi thuần tuý (kể cả khi audio đọc XONG SỚM hơn nhiều so với khung giờ gốc) -
    # khiến vị trí trôi dần về TRƯỚC so với timestamp gốc qua từng câu, làm giọng đọc chạy
    # trước nội dung/hình ảnh càng lúc càng xa, đúng hiện tượng "đọc nhanh không khớp".
    new_segments: List[SubtitleSegment] = []
    positions_ms: List[int] = []
    cursor = start0
    for i in range(n):
        anchor = segments[i].start if keep_original_start else None
        if i == 0:
            s = cursor
        elif anchor is not None and anchor >= cursor + gaps[i - 1]:
            # Còn kịp neo về đúng timestamp gốc (không chồng lấn câu trước) - khớp
            # đúng với SRT gốc hiển thị trên màn hình tại đúng thời điểm đó.
            s = anchor
        else:
            # Bị chồng lấn (câu trước đọc dài hơn khung giờ gốc của nó, lấn sang) -
            # đành nối đuôi, không còn cách nào khác để tránh 2 câu đè lên nhau.
            s = cursor + gaps[i - 1]
        e = s + real_durs[i]
        new_segments.append(replace(segments[i], start=s, end=e))
        positions_ms.append(int(s * 1000))
        cursor = e

    total_ms = int(cursor * 1000) + 500
    track = AudioSegment.silent(duration=total_ms)
    for i, (clip, pos_ms) in enumerate(zip(clips, positions_ms)):
        track = track.overlay(clip, position=pos_ms)
        if progress_cb:
            progress_cb((i + 1) / n, f"Đang ghép track {i + 1}/{n}")

    track.export(out_path, format="wav")
    return out_path, new_segments


def build_dubbed_track(
    segments: List[SubtitleSegment],
    audio_paths: List[str],
    out_path: str,
    max_speedup: float = 1.15,
    emergency_max_speedup: float = 1.6,
    min_speedup_ratio: float = 1.03,
    min_gap_ms: int = 80,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Ghép các đoạn audio đã tạo vào đúng vị trí thời gian gốc (theo timestamp của segment)
    để tạo 1 track lồng tiếng hoàn chỉnh, dùng pydub.
    pip install pydub  (cần ffmpeg đã cài sẵn trong hệ thống)

    QUAN TRỌNG: câu dịch (vd tiếng Việt) thường DÀI HƠN câu gốc. TRƯỚC KHI gọi
    hàm này, pipeline (core/pipeline.py) đã chạy core/text_fit.fit_segments_to_timing
    với tolerance THẤP (mặc định 1.08) để RÚT NGẮN VĂN BẢN hầu hết các câu dự kiến
    đọc lâu hơn khoảng trống gốc - đó mới là giải pháp chính, không đổi tốc độ đọc.
    atempo ở đây CHỈ còn là lưới an toàn cho phần lệch RẤT NHỎ còn sót lại (do ước
    lượng tốc độ đọc không thể chính xác 100%), nên:
      - max_speedup mặc định hạ xuống 1.15x (trước là 1.25x, cộng với tolerance
        1.25 ở text_fit khiến GẦN NHƯ CÂU NÀO CŨNG bị đổi tốc độ với tỉ lệ dao
        động lung tung 1.01x~1.25x - đây chính là nguyên nhân nghe "không lọt
        tai" vì nhịp đọc bị đổi liên tục, không đều giữa các câu).
      - min_speedup_ratio (mặc định 1.03): nếu phần lệch cần xử lý NHỎ HƠN mức
        này (vd chỉ cần tăng tốc 1.01x, 1.02x) thì BỎ QUA, không chạy atempo -
        phần lệch quá nhỏ này thường vẫn nằm gọn trong khoảng đệm min_gap_ms,
        chạy atempo cho những trường hợp này chỉ tạo thêm dao động tốc độ không
        cần thiết mà tai gần như không phân biệt được, không đáng đánh đổi.
      1. Tính khoảng trống cho phép = thời điểm bắt đầu câu kế tiếp - seg.start
         (trừ thêm min_gap_ms để 2 câu không dính sát nhau).
      2. Nếu clip dài hơn khoảng trống đó QUÁ mức min_speedup_ratio -> tăng tốc
         bằng atempo (giữ cao độ) tối đa max_speedup lần. Lệch nhỏ hơn mức đó thì
         giữ nguyên tốc độ gốc.
      3. Nếu tăng tốc tới max_speedup vẫn còn dư -> tăng tốc THÊM một nấc "khẩn
         cấp" (uncapped tới emergency_max_speedup, mặc định 1.6x) TRƯỚC KHI cắt -
         vì MẤT CHỮ (cắt đuôi câu) luôn tệ hơn nghe hơi nhanh 1 chút, và atempo/
         rubberband vẫn giữ nguyên cao độ nên không bị "chuột rít" dù nén khá sâu.
         CHỈ khi đã tăng tốc tới emergency_max_speedup mà vẫn còn dư (cực hiếm,
         nghĩa là câu quá dài không tưởng so với khung giờ gốc) mới cắt bớt phần
         đuôi clip để đảm bảo KHÔNG BAO GIỜ chồng lấn - và báo CẢNH BÁO RIÊNG,
         khác hẳn cảnh báo "đã tăng tốc" bình thường, để bạn biết chính xác câu
         nào thực sự bị MẤT CHỮ cần rút gọn lại thủ công.
    """
    from pydub import AudioSegment

    if not segments:
        raise ValueError("Không có segment nào để ghép audio")

    total_ms = int(segments[-1].end * 1000) + 500
    track = AudioSegment.silent(duration=total_ms)

    total = max(1, len(segments))
    for i, (seg, path) in enumerate(zip(segments, audio_paths), start=1):
        clip = AudioSegment.from_file(path)
        pos_ms = int(seg.start * 1000)

        next_start_ms = int(segments[i].start * 1000) if i < len(segments) else total_ms
        available_ms = max(200, next_start_ms - pos_ms - min_gap_ms)

        if len(clip) > available_ms:
            needed_ratio = len(clip) / available_ms

            if needed_ratio <= min_speedup_ratio:
                # Lệch quá nhỏ (vd 1.01x-1.03x) - bỏ qua, không đáng đổi tốc độ đọc,
                # phần dư nhỏ này thường vẫn nằm gọn trong khoảng đệm min_gap_ms.
                pass
            else:
                speed_ratio = min(needed_ratio, max_speedup)
                try:
                    clip = _speed_up_audio(path, speed_ratio)
                except Exception:
                    pass  # nếu atempo lỗi (thiếu ffmpeg filter...) thì vẫn xử lý tiếp bên dưới
                applied_ratio = speed_ratio

                if len(clip) > available_ms and emergency_max_speedup > max_speedup:
                    # Vẫn còn dư sau max_speedup - tăng tốc THÊM thay vì cắt ngay, để
                    # không mất nội dung. Đây là lưới an toàn thứ 2, chỉ kích hoạt khi
                    # lưới thứ 1 (max_speedup) chưa đủ.
                    emergency_ratio = min(needed_ratio, emergency_max_speedup)
                    if emergency_ratio > speed_ratio:
                        try:
                            clip = _speed_up_audio(path, emergency_ratio)
                            applied_ratio = emergency_ratio
                        except Exception:
                            pass

                if len(clip) > available_ms:
                    # Đã tăng tốc hết mức (kể cả nấc khẩn cấp) mà vẫn còn dư - CỰC HIẾM.
                    # Chỉ lúc này mới cắt bớt đuôi clip, và báo CẢNH BÁO RIÊNG (mất chữ),
                    # khác hẳn cảnh báo "đã tăng tốc" thông thường bên dưới.
                    clip = clip[:available_ms]
                    if progress_cb:
                        preview = seg.text.strip().replace("\n", " ")
                        if len(preview) > 60:
                            preview = preview[:57] + "..."
                        progress_cb(
                            i / total,
                            f"✂ Câu {i} vẫn dài hơn khoảng trống dù đã tăng tốc {applied_ratio:.2f}x "
                            f"- đã CẮT BỚT đuôi câu (MẤT CHỮ cuối câu) - nên rút gọn lại câu này thủ công: \"{preview}\"",
                        )
                elif progress_cb:
                    preview = seg.text.strip().replace("\n", " ")
                    if len(preview) > 60:
                        preview = preview[:57] + "..."
                    progress_cb(
                        i / total,
                        f"⚠ Câu {i} dài hơn khoảng trống gốc -> đã tăng tốc {applied_ratio:.2f}x để tránh chồng tiếng: \"{preview}\"",
                    )

        track = track.overlay(clip, position=pos_ms)
        if progress_cb:
            progress_cb(i / total, f"Đang ghép track {i}/{total}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    track.export(out_path, format="mp3")
    return out_path
