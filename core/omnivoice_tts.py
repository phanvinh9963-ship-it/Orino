"""
core/omnivoice_tts.py
Tích hợp OmniVoice (https://github.com/k2-fsa/OmniVoice) làm 1 engine TTS mới -
model zero-shot đa ngôn ngữ (600+ ngôn ngữ), chạy LOCAL (không cần mạng sau khi
đã tải model lần đầu), hỗ trợ 2 chế độ:

- VOICE CLONING: nhân bản giọng từ 1 audio mẫu (voice profile trong
  `voice_profiles_dir`, giống engine "clone"/"vieneu"). Chỉ cần audio mẫu; nếu
  không có sẵn transcript (ref_text), OmniVoice tự động dùng Whisper để
  transcribe audio mẫu.
- VOICE DESIGN: mô tả giọng mong muốn bằng văn bản tự nhiên (vd "female, low
  pitch, british accent") thay vì cần audio mẫu - xem `instruct`.

Nếu không truyền `voice_name` LẪN `instruct`, model tự chọn 1 giọng ngẫu nhiên
("auto voice").

Cài đặt: pip install torch torchaudio omnivoice soundfile
(xem thêm https://github.com/k2-fsa/OmniVoice#installation - nhớ cài đúng bản
torch theo GPU/CPU của máy trước khi cài omnivoice).

Quy ước thư mục voice profile (dùng CHUNG với engine "clone"):
    {profiles_dir}/{voice_name}/ref.wav   - audio mẫu (bắt buộc để clone)
    {profiles_dir}/{voice_name}/ref.txt   - transcript audio mẫu (tuỳ chọn,
                                             không có thì OmniVoice tự ASR)
Sau lần chạy ĐẦU TIÊN với 1 voice_name, prompt đã encode được LƯU LẠI vào:
    {profiles_dir}/{voice_name}/omnivoice_prompt.pt
để các lần chạy sau (kể cả video khác) load thẳng, không phải encode lại từ
đầu audio mẫu mỗi lần - nhanh hơn đáng kể khi dùng lại cùng 1 giọng.
"""
from __future__ import annotations
import os
from typing import Callable, Dict, List, Optional

from core.transcribe import SubtitleSegment

MODEL_ID = "k2-fsa/OmniVoice"

# ---------------------------------------------------------------------------
# Voice Design: OmniVoice KHÔNG có sẵn 1 danh sách ~600 giọng đọc cố định như
# edge-tts (đó là hiểu lầm phổ biến) - con số "600+" trong README nói về số
# NGÔN NGỮ hỗ trợ (cho việc CLONE giọng/tự đọc văn bản), không phải số giọng
# dựng sẵn. Thay vào đó, Voice Design "tạo ra" 1 giọng theo các THUỘC TÍNH mô
# tả (giới tính, độ tuổi, cao độ, phong cách, giọng vùng miền...) - mỗi tổ hợp
# thuộc tính khác nhau cho ra 1 giọng khác nhau, nên về lý thuyết có VÔ SỐ giọng
# có thể "chọn" bằng cách phối các thuộc tính dưới đây (xem docs/voice-design.md
# của OmniVoice để biết đầy đủ + bản tiếng Trung).
GENDER_OPTIONS = ["male", "female"]
AGE_OPTIONS = ["child", "teenager", "young adult", "middle-aged", "elderly"]
PITCH_OPTIONS = ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"]
STYLE_OPTIONS = ["whisper"]
# Chỉ có tác dụng khi văn bản tổng hợp là tiếng Anh (target_lang="English").
ACCENT_OPTIONS = [
    "american accent", "british accent", "australian accent", "canadian accent",
    "indian accent", "chinese accent", "korean accent", "japanese accent",
    "portuguese accent", "russian accent",
]
# Chỉ có tác dụng khi văn bản tổng hợp là tiếng Trung (target_lang="Chinese").
DIALECT_OPTIONS = [
    "河南话", "陕西话", "四川话", "贵州话", "云南话", "桂林话",
    "济南话", "石家庄话", "甘肃话", "宁夏话", "青岛话", "东北话",
]


# ---------------------------------------------------------------------------
# Preset gợi ý ("đặt tên" giọng cho dễ chọn, kiểu Adam/Emma...) - đây KHÔNG phải
# giọng cố định (OmniVoice không có khái niệm đó), mà là 1 "công thức" thuộc
# tính có sẵn: chọn preset = tự điền sẵn gender/age/pitch/accent tương ứng. Vẫn
# là model TẠO giọng mới theo đúng công thức mỗi lần chạy (không phải phát lại
# 1 giọng đã ghi âm sẵn), nên chất giọng có thể hơi khác nhau chút giữa các lần
# chạy dù cùng chọn 1 preset - nhưng vẫn giữ đúng đặc điểm đã chọn.
# Mỗi phần tử: (tên, gender, age, pitch, accent)
PRESET_VOICES = [
    ("Adam",   "male",   "young adult", "moderate pitch",  "american accent"),
    ("Ethan",  "male",   "young adult", "low pitch",        "canadian accent"),
    ("James",  "male",   "middle-aged", "low pitch",        "british accent"),
    ("Liam",   "male",   "young adult", "moderate pitch",   "australian accent"),
    ("Marcus", "male",   "elderly",     "very low pitch",   "british accent"),
    ("Noah",   "male",   "teenager",    "high pitch",       "american accent"),
    ("Raj",    "male",   "middle-aged", "moderate pitch",   "indian accent"),
    ("Wei",    "male",   "young adult", "moderate pitch",   "chinese accent"),
    ("Jin",    "male",   "young adult", "moderate pitch",   "korean accent"),
    ("Haruto", "male",   "young adult", "moderate pitch",   "japanese accent"),
    ("Diego",  "male",   "middle-aged", "low pitch",        "portuguese accent"),
    ("Ivan",   "male",   "middle-aged", "low pitch",        "russian accent"),
    ("Emma",   "female", "young adult", "moderate pitch",   "american accent"),
    ("Ava",    "female", "young adult", "high pitch",       "canadian accent"),
    ("Sophia", "female", "young adult", "high pitch",       "british accent"),
    ("Olivia", "female", "young adult", "moderate pitch",   "australian accent"),
    ("Grace",  "female", "elderly",     "low pitch",        "british accent"),
    ("Zoe",    "female", "teenager",    "high pitch",       "american accent"),
    ("Priya",  "female", "young adult", "moderate pitch",   "indian accent"),
    ("Mei",    "female", "young adult", "moderate pitch",   "chinese accent"),
    ("Jiwoo",  "female", "young adult", "moderate pitch",   "korean accent"),
    ("Sakura", "female", "young adult", "high pitch",       "japanese accent"),
    ("Ana",    "female", "young adult", "moderate pitch",   "portuguese accent"),
    ("Katya",  "female", "middle-aged", "moderate pitch",   "russian accent"),
]


def build_instruct(
    gender: Optional[str] = None,
    age: Optional[str] = None,
    pitch: Optional[str] = None,
    style: Optional[str] = None,
    accent: Optional[str] = None,
    dialect: Optional[str] = None,
) -> Optional[str]:
    """Ghép các thuộc tính giọng (mỗi thuộc tính TUỲ CHỌN, để trống = model tự
    quyết định) thành 1 chuỗi `instruct` hợp lệ cho OmniVoice voice design, vd
    build_instruct(gender="female", pitch="high pitch", accent="british accent")
    -> "female, high pitch, british accent"
    Trả về None nếu KHÔNG có thuộc tính nào được chọn (để synthesize_segments_omnivoice
    hiểu là không dùng voice design, rơi về auto voice hoặc voice cloning).
    """
    parts = [p for p in (gender, age, pitch, style, accent, dialect) if p]
    return ", ".join(parts) if parts else None

# Cache model + prompt đã load trong tiến trình hiện tại, để KHÔNG phải nạp lại
# (tốn vài giây tới vài chục giây) cho mỗi câu thoại / mỗi lần gọi hàm - model
# chỉ thật sự nạp 1 lần cho mỗi (model_id, device, dtype) khác nhau.
_MODEL_CACHE: Dict[tuple, object] = {}
_PROMPT_CACHE: Dict[str, object] = {}


def _resolve_device(device: str) -> str:
    """'auto' -> tự chọn GPU CUDA/MPS nếu có, không thì CPU."""
    if device and device != "auto":
        return device
    try:
        from omnivoice.utils.common import get_best_device
        return get_best_device()
    except Exception:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda:0"
            if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"


def _get_model(device: str = "auto"):
    """Nạp (hoặc lấy lại từ cache) model OmniVoice trên đúng device yêu cầu.

    Dùng float16 trên GPU (nhanh hơn, tốn ít VRAM hơn) và float32 trên CPU/MPS
    (float16 không ổn định/hỗ trợ đầy đủ trên CPU và một số bản PyTorch MPS).
    """
    import torch
    from omnivoice import OmniVoice

    resolved = _resolve_device(device)
    dtype = torch.float16 if resolved.startswith("cuda") else torch.float32
    cache_key = (MODEL_ID, resolved, str(dtype))

    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        model = OmniVoice.from_pretrained(MODEL_ID, device_map=resolved, dtype=dtype)
        _MODEL_CACHE[cache_key] = model
    return model


def _profile_paths(voice_name: str, profiles_dir: str) -> tuple[str, str, str]:
    base = os.path.join(profiles_dir, voice_name)
    return (
        os.path.join(base, "ref.wav"),
        os.path.join(base, "ref.txt"),
        os.path.join(base, "omnivoice_prompt.pt"),
    )


def _load_or_build_prompt(model, voice_name: str, profiles_dir: str):
    """Lấy VoiceClonePrompt đã encode sẵn (ưu tiên cache trong RAM, sau đó tới
    file .pt đã lưu từ lần chạy trước); nếu chưa có thì encode mới từ ref.wav
    (+ ref.txt nếu có, không có thì OmniVoice tự ASR) rồi lưu lại để tái sử dụng.
    """
    from omnivoice import VoiceClonePrompt

    cache_key = f"{profiles_dir}::{voice_name}"
    prompt = _PROMPT_CACHE.get(cache_key)
    if prompt is not None:
        return prompt

    ref_wav, ref_txt, prompt_pt = _profile_paths(voice_name, profiles_dir)

    if os.path.exists(prompt_pt):
        try:
            prompt = VoiceClonePrompt.load(prompt_pt)
            _PROMPT_CACHE[cache_key] = prompt
            return prompt
        except Exception:
            pass  # file cache hỏng/không tương thích - encode lại từ audio mẫu bên dưới

    if not os.path.exists(ref_wav):
        raise FileNotFoundError(
            f"Không tìm thấy audio mẫu cho voice profile '{voice_name}': {ref_wav}. "
            f"Chạy 'python setup_voice_clone.py --source ... --name {voice_name}' trước."
        )

    ref_text = None
    if os.path.exists(ref_txt):
        with open(ref_txt, "r", encoding="utf-8") as f:
            ref_text = f.read().strip() or None

    if ref_text is None:
        # Không có transcript sẵn -> để OmniVoice tự ASR (cần load_asr_model trước).
        model.load_asr_model()

    prompt = model.create_voice_clone_prompt(ref_audio=ref_wav, ref_text=ref_text)
    try:
        os.makedirs(os.path.dirname(prompt_pt), exist_ok=True)
        prompt.save(prompt_pt)
    except Exception:
        pass  # lưu cache thất bại (vd disk full) không ảnh hưởng tới lần chạy hiện tại

    _PROMPT_CACHE[cache_key] = prompt
    return prompt


def synthesize_segments_omnivoice(
    segments: List[SubtitleSegment],
    target_lang: str,
    out_dir: str,
    voice_name: Optional[str] = None,      # tên voice profile trong profiles_dir để CLONE giọng
    profiles_dir: Optional[str] = None,    # bắt buộc nếu có voice_name
    instruct: Optional[str] = None,        # mô tả giọng cho VOICE DESIGN (vd "female, low pitch")
    instruct_by_gender: Optional[Dict[str, str]] = None,   # {"male": "...", "female": "..."} - ưu
                                            # tiên hơn `instruct` cho câu ĐÃ có seg.gender riêng
                                            # (do gender_detect.py/face_speaker_detect.py gán)
    device: str = "auto",                  # "auto" | "cpu" | "cuda:0" | "mps"...
    num_step: int = 32,                    # số bước diffusion - cao hơn = chất lượng tốt hơn nhưng chậm hơn (16 = nhanh hơn)
    speed: float = 1.0,                    # hệ số tốc độ đọc (>1.0 nhanh hơn, <1.0 chậm hơn)
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[str]:
    """
    Tạo 1 file wav cho mỗi câu thoại bằng OmniVoice, trả về danh sách đường dẫn
    theo đúng thứ tự segments.

    Ưu tiên chế độ (tính theo từng câu):
      1. Nếu có voice_name -> VOICE CLONING bằng voice profile đó (bỏ qua instruct).
      2. Ngược lại, nếu câu có seg.gender khớp instruct_by_gender -> VOICE DESIGN
         bằng mô tả riêng cho giới tính đó.
      3. Ngược lại, nếu có instruct (mô tả chung) -> VOICE DESIGN bằng mô tả đó.
      4. Không có gì cả -> AUTO VOICE (model tự chọn 1 giọng ngẫu nhiên, giữ
         NGUYÊN 1 giọng xuyên suốt video vì dùng lại đúng 1 model instance,
         không phải mỗi câu lại random 1 giọng khác nhau).

    KHÔNG fallback tự động sang engine khác nếu lỗi (giống engine "clone" và
    "vieneu"), để tránh lẫn giọng OmniVoice với giọng khác trong cùng 1 video
    mà không báo trước.
    """
    import soundfile as sf

    if voice_name and not profiles_dir:
        raise ValueError("Cần truyền profiles_dir khi có voice_name (engine='omnivoice')")

    os.makedirs(out_dir, exist_ok=True)
    model = _get_model(device)

    voice_clone_prompt = None
    if voice_name:
        voice_clone_prompt = _load_or_build_prompt(model, voice_name, profiles_dir)

    paths: List[str] = []
    total = max(1, len(segments))

    for i, seg in enumerate(segments, start=1):
        text = seg.text.strip() or "..."

        gen_kwargs = dict(
            text=text,
            num_step=num_step,
            speed=speed,
        )
        if voice_clone_prompt is not None:
            gen_kwargs["voice_clone_prompt"] = voice_clone_prompt
        else:
            seg_instruct = None
            if instruct_by_gender and seg.gender in instruct_by_gender:
                seg_instruct = instruct_by_gender[seg.gender]
            elif instruct:
                seg_instruct = instruct
            if seg_instruct:
                gen_kwargs["instruct"] = seg_instruct
            # Không có voice_clone_prompt lẫn instruct -> auto voice (model tự chọn giọng)

        audios = model.generate(**gen_kwargs)

        out_path = os.path.join(out_dir, f"seg_{seg.index:04d}.wav")
        sf.write(out_path, audios[0], model.sampling_rate)
        paths.append(out_path)

        if progress_cb:
            progress_cb(i / total, f"Đang tạo giọng đọc OmniVoice {i}/{total}")

    return paths
