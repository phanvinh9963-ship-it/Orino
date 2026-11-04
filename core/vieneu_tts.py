"""
core/vieneu_tts.py
Tích hợp VieNeu-TTS (https://github.com/pnnbao97/VieNeu-TTS) làm 1 engine giọng đọc
mới cho core/tts.py, dùng engine="vieneu".

Vì sao thêm engine này (khác với engine="clone" đang có, dùng XTTS-v2):
- Chạy HOÀN TOÀN LOCAL, không cần mạng (khác "online"/edge-tts).
- Chất lượng tiếng Việt tốt hơn hẳn giọng máy "offline" (pyttsx3).
- Clone giọng CHỈ CẦN 1 file audio mẫu 3-5s, KHÔNG cần transcript đi kèm
  (khác XTTS-v2 dùng cho engine="clone", vốn cần cả ref_audio LẪN ref_text).
- Chạy tốt trên CPU (không bắt buộc GPU) nhờ chế độ mặc định "v3turbo":
  torch-free, chạy qua ONNX Runtime khi không có CUDA.

Cài đặt (chỉ cần cài đúng 1 gói, không cần cài thêm torch để chạy CPU):
    pip install vieneu

GIỚI HẠN QUAN TRỌNG: VieNeu-TTS hiện chỉ hỗ trợ TIẾNG VIỆT. Nếu target_lang
khác "Vietnamese", hàm bên dưới sẽ raise lỗi rõ ràng thay vì âm thầm tạo ra
audio đọc sai/đọc ngọng ngôn ngữ khác.

Cách chọn giọng (voice_name) khi engine="vieneu":
  1. Nếu voice_profiles_dir/{voice_name}.json tồn tại (CÙNG thư mục voice_profiles
     đã dùng cho engine="clone") -> clone giọng từ audio mẫu khai báo trong đó.
     File json chỉ cần 1 trong các khóa sau trỏ tới file audio mẫu:
     "ref_audio", "audio_path", "audio", "wav_path", "sample_path", "source".
     (ref_text trong profile, nếu có, sẽ bị BỎ QUA - VieNeu-TTS không cần).
  2. Nếu không có profile trùng tên -> coi voice_name là ID giọng dựng sẵn
     (preset) của VieNeu-TTS. Xem danh sách bằng list_vieneu_preset_voices().
  3. Nếu voice_name để trống ("" hoặc None) -> dùng giọng mặc định của model.

Lồng tiếng NHIỀU NHÂN VẬT (voice_by_gender): nếu video có nhiều nhân vật thoại
và core/gender_detect.py hoặc core/face_speaker_detect.py đã gán seg.gender =
"male"/"female" cho từng câu, có thể truyền thêm voice_by_gender =
{"male": "...", "female": "..."} để MỖI GIỚI TÍNH đọc bằng 1 giọng VieNeu-TTS
riêng (mỗi giá trị cũng là voice_name theo đúng 3 quy tắc ở trên) - giống hệt
cơ chế VOICE_MAP_BY_GENDER đang có sẵn cho engine="online".
"""
from __future__ import annotations
import json
import logging
import os
import threading
from typing import Callable, List, Optional

from core.transcribe import SubtitleSegment

logger = logging.getLogger("ReupStudio.VieNeuTTS")

# Không đổi vị trí cache Hugging Face (giữ nguyên mặc định ~/.cache/huggingface hoặc
# HF_HOME nếu người dùng đã tự set) - đổi sang thư mục khác sẽ khiến app không thấy
# model/giọng ĐÃ TỪNG tải trước đó nữa (tưởng nhầm là "mất giọng"). Chỉ tắt telemetry
# cho gọn, không ảnh hưởng tới việc cache model.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# Cache danh sách giọng dựng sẵn (preset) ra 1 file JSON nhỏ nằm CẠNH main.py (thư mục
# gốc project) - đọc lại gần như tức thời ở các lần mở app SAU, thay vì phải load lại
# FULL model VieNeu-TTS (rất chậm) chỉ để lấy tên giọng.
_PRESET_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".vieneu_preset_cache.json"
)

_engine = None
_engine_lock = threading.Lock()


def _restore_env(key: str, prev_value: Optional[str]):
    """Khôi phục biến môi trường về giá trị TRƯỚC KHI ta tự ý set (hoặc xoá hẳn nếu
    trước đó chưa từng được set) - tránh để HF_HUB_OFFLINE dính lại cho CẢ quá trình
    chạy app, vì việc đó sẽ chặn luôn các lần tải giọng preset/audio mẫu MỚI (chưa có
    trong cache) về sau, gây ra hiện tượng "mất giọng"."""
    if prev_value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = prev_value


def _get_engine():
    """Load model VieNeu-TTS đúng 1 lần (singleton), tái sử dụng cho mọi câu và mọi
    lần chạy pipeline trong cùng tiến trình - load model tốn vài giây, không nên
    load lại cho từng câu thoại hay từng lần bấm "Bắt đầu dịch".

    Chiến lược tải model CHỈ 1 LẦN DUY NHẤT (không tải lại mỗi lần chạy app):
      1. Thử load ở chế độ OFFLINE trước (HF_HUB_OFFLINE=1) - KHÔNG gọi mạng lên
         Hugging Face Hub. Nếu model đã có sẵn trong cache local (do lần chạy
         trước đã tải) thì load thành công ngay, không có warning HF_TOKEN vì
         không hề có request nào gửi đi.
      2. Nếu load offline thất bại (lần đầu tiên chạy, chưa có cache) -> tự động
         bật lại mạng, tải model về cache mặc định đúng 1 lần. Các lần chạy sau sẽ
         luôn rơi vào nhánh (1) và không đụng mạng nữa.
      3. QUAN TRỌNG: chế độ offline CHỈ áp dụng trong lúc gọi Vieneu(...) ở trên -
         ngay sau đó biến môi trường được khôi phục lại bình thường, để các thao
         tác SAU NÀY (vd chọn 1 giọng preset chưa từng tải, hoặc audio mẫu mới)
         vẫn tải mạng được bình thường, không bị khoá cứng offline cả app.
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                try:
                    from vieneu import Vieneu
                except ImportError as e:
                    raise ImportError(
                        "Chưa cài thư viện 'vieneu'. Chạy: pip install vieneu"
                    ) from e

                prev_hf_offline = os.environ.get("HF_HUB_OFFLINE")
                prev_tf_offline = os.environ.get("TRANSFORMERS_OFFLINE")
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                try:
                    logger.info("Đang tải model VieNeu-TTS từ cache local (offline, không gọi mạng)...")
                    _engine = Vieneu(mode="v3turbo", device="cpu")
                    logger.info("VieNeu-TTS đã sẵn sàng (dùng cache có sẵn).")
                except Exception as e:
                    logger.info(
                        f"Chưa có cache local đầy đủ ({e}) - đây là lần đầu tiên, "
                        f"đang tải model VieNeu-TTS về (chỉ tải lần này)..."
                    )
                    _restore_env("HF_HUB_OFFLINE", prev_hf_offline)
                    _restore_env("TRANSFORMERS_OFFLINE", prev_tf_offline)
                    _engine = Vieneu(mode="v3turbo", device="cpu")
                    logger.info(
                        "VieNeu-TTS đã tải xong và lưu cache - các lần chạy sau sẽ KHÔNG cần tải lại."
                    )
                finally:
                    # Luôn khôi phục lại, dù nhánh nào chạy - không được để offline
                    # dính lại cho các lệnh gọi mạng khác sau đó trong cùng tiến trình.
                    _restore_env("HF_HUB_OFFLINE", prev_hf_offline)
                    _restore_env("TRANSFORMERS_OFFLINE", prev_tf_offline)
    return _engine


def list_vieneu_preset_voices(force: bool = False) -> List[tuple[str, str]]:
    """Trả về danh sách (mô tả, id) các giọng dựng sẵn của VieNeu-TTS - dùng để hiển thị
    lên UI (vd đổ vào combo box "Giọng của bạn").

    MẶC ĐỊNH đọc từ cache file (_PRESET_CACHE_PATH) nếu đã có từ lần chạy app TRƯỚC ĐÓ -
    tránh phải load lại FULL model (tốn vài giây tới vài phút) chỉ để liệt kê tên giọng
    mỗi lần mở app / bấm nút - đây chính là nguyên nhân gây "lag" khi bấm nút tải giọng.
    Chỉ khi `force=True` (bấm nút "Làm mới" thủ công) hoặc CHƯA CÓ cache thì mới thực sự
    load model."""
    if not force:
        cached = _read_preset_cache()
        if cached is not None:
            return cached
    try:
        engine = _get_engine()
        presets = engine.list_preset_voices()
        _write_preset_cache(presets)
        return presets
    except Exception as e:
        logger.warning(f"Không lấy được danh sách giọng dựng sẵn VieNeu-TTS: {e}")
        return []


def _read_preset_cache() -> Optional[List[tuple[str, str]]]:
    try:
        with open(_PRESET_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [(item[0], item[1]) for item in data]
    except Exception:
        return None


def _write_preset_cache(presets: List[tuple[str, str]]) -> None:
    try:
        os.makedirs(os.path.dirname(_PRESET_CACHE_PATH), exist_ok=True)
        with open(_PRESET_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(list(presets), f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Không ghi được cache giọng VieNeu-TTS ({_PRESET_CACHE_PATH}): {e}")


def list_all_vieneu_voice_options(profiles_dir: Optional[str] = None, force: bool = False) -> List[tuple[str, str]]:
    """Gộp danh sách voice profile (voice_profiles_dir/*.json) và giọng dựng sẵn của
    VieNeu-TTS thành 1 danh sách (mô tả, id) duy nhất - dùng đổ vào combo box UI cho
    phần "Lồng tiếng · Giọng lồng · Tiếng Việt". Nhờ cache ở list_vieneu_preset_voices(),
    hàm này CHỈ CHẬM ở LẦN ĐẦU TIÊN chạy app (chưa có cache) - các lần mở app sau đọc
    cache gần như tức thời. Vẫn nên gọi trong thread nền phòng trường hợp cache chưa có."""
    options: List[tuple[str, str]] = []
    if profiles_dir and os.path.isdir(profiles_dir):
        for f in sorted(os.listdir(profiles_dir)):
            if f.lower().endswith(".json"):
                name = os.path.splitext(f)[0]
                options.append((f"🎙 {name} (voice profile)", name))
    for desc, vid in list_vieneu_preset_voices(force=force):
        options.append((f"{desc} ({vid})", vid))
    return options


def _load_profile_ref_audio(voice_name: str, profiles_dir: str) -> Optional[str]:
    """Đọc voice_profiles/{voice_name}.json (nếu có), lấy đường dẫn audio mẫu để clone.
    Trả về None nếu không tìm thấy file profile trùng tên (không phải lỗi - lúc đó
    voice_name sẽ được thử như 1 ID giọng dựng sẵn thay vào)."""
    profile_path = os.path.join(profiles_dir, f"{voice_name}.json")
    if not os.path.isfile(profile_path):
        return None
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Không đọc được voice profile '{profile_path}': {e}") from e

    ref_audio = None
    for key in ("ref_audio", "audio_path", "audio", "wav_path", "sample_path", "source"):
        val = data.get(key)
        if val:
            ref_audio = val
            break
    if not ref_audio:
        raise RuntimeError(
            f"Voice profile '{profile_path}' không có khóa audio mẫu hợp lệ "
            f"(cần 1 trong: ref_audio, audio_path, audio, wav_path, sample_path, source)."
        )

    if not os.path.isabs(ref_audio):
        # đường dẫn tương đối trong profile - thử resolve theo thư mục chứa profile trước
        candidate = os.path.join(profiles_dir, ref_audio)
        ref_audio = candidate if os.path.exists(candidate) else ref_audio

    if not os.path.exists(ref_audio):
        raise RuntimeError(
            f"File audio mẫu '{ref_audio}' khai báo trong profile '{profile_path}' không tồn tại."
        )
    return ref_audio


def _resolve_voice_ref(voice_name: str, profiles_dir: Optional[str], engine) -> tuple[Optional[str], Optional[str]]:
    """Quy đổi 1 voice_name (tên voice profile HOẶC ID giọng dựng sẵn) thành cặp
    (ref_audio, voice_arg) để truyền vào engine.infer(). Raise lỗi rõ ràng nếu
    voice_name không khớp cả 2 loại."""
    ref_audio: Optional[str] = None
    voice_arg: Optional[str] = None
    if profiles_dir:
        ref_audio = _load_profile_ref_audio(voice_name, profiles_dir)
    if ref_audio is None:
        # Không có profile trùng tên -> coi voice_name là ID giọng dựng sẵn.
        preset_ids = {vid for _desc, vid in engine.list_preset_voices()}
        if voice_name not in preset_ids:
            raise ValueError(
                f"Không tìm thấy voice profile hoặc giọng dựng sẵn tên '{voice_name}'. "
                f"Giọng dựng sẵn khả dụng: {sorted(preset_ids)}"
            )
        voice_arg = voice_name
    return ref_audio, voice_arg


def synthesize_segments_vieneu(
    segments: List[SubtitleSegment],
    target_lang: str,
    out_dir: str,
    voice_name: Optional[str] = None,
    profiles_dir: Optional[str] = None,
    voice_by_gender: Optional[dict] = None,   # {"male": voice_name, "female": voice_name} - giọng RIÊNG cho
                                                # từng giới tính nhân vật (xem core/gender_detect.py /
                                                # core/face_speaker_detect.py). Segment có seg.gender khớp 1
                                                # khóa trong dict này sẽ ƯU TIÊN dùng giọng đó thay vì voice_name
                                                # (giống cơ chế VOICE_MAP_BY_GENDER của engine="online" trong
                                                # core/tts.py). Segment không có gender riêng (hoặc gender đó
                                                # không có trong dict) thì dùng voice_name làm giọng NỀN.
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[str]:
    """
    Tạo 1 file .wav cho mỗi câu thoại bằng VieNeu-TTS (chạy local, CPU).
    Trả về danh sách đường dẫn file audio theo đúng thứ tự segments.

    KHÔNG có fallback tự động sang engine khác nếu lỗi (giống engine="clone"),
    để tránh video bị lẫn giữa giọng VieNeu-TTS và giọng khác mà không báo trước.
    """
    if target_lang != "Vietnamese":
        raise ValueError(
            f"engine='vieneu' chỉ hỗ trợ tiếng Việt, nhưng target_lang='{target_lang}'. "
            f"Đổi 'Target language' sang Vietnamese, hoặc dùng engine 'online'/'offline'/'clone' "
            f"cho ngôn ngữ khác."
        )

    os.makedirs(out_dir, exist_ok=True)
    engine = _get_engine()

    # Cache theo voice_name để không phải đọc lại profile / kiểm tra preset nhiều lần
    # cho mỗi câu - đặc biệt quan trọng khi dùng voice_by_gender (chỉ có tối đa vài
    # giọng khác nhau cho hàng trăm câu thoại).
    _resolved_cache: dict = {}

    def _resolved(name: str) -> tuple[Optional[str], Optional[str]]:
        if name not in _resolved_cache:
            _resolved_cache[name] = _resolve_voice_ref(name, profiles_dir, engine)
        return _resolved_cache[name]

    default_ref_audio: Optional[str] = None
    default_voice_arg: Optional[str] = None
    if voice_name:
        default_ref_audio, default_voice_arg = _resolved(voice_name)

    def _voice_for(seg: SubtitleSegment) -> tuple[Optional[str], Optional[str]]:
        if voice_by_gender and seg.gender in voice_by_gender and voice_by_gender[seg.gender]:
            return _resolved(voice_by_gender[seg.gender])   # gender riêng của câu - ưu tiên cao nhất
        return default_ref_audio, default_voice_arg

    paths: List[str] = []
    total = max(1, len(segments))
    for i, seg in enumerate(segments, start=1):
        text = seg.text.strip() or "..."
        out_path = os.path.join(out_dir, f"seg_{seg.index:04d}.wav")
        ref_audio, voice_arg = _voice_for(seg)
        try:
            audio = engine.infer(text=text, ref_audio=ref_audio, voice=voice_arg)
            engine.save(audio, out_path)
        except Exception as e:
            raise RuntimeError(f"VieNeu-TTS lỗi ở câu {i} ('{text[:40]}...'): {e}") from e

        paths.append(out_path)
        if progress_cb:
            progress_cb(i / total, f"Đang tạo giọng đọc VieNeu-TTS {i}/{total}")

    return paths

