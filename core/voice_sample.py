"""
core/voice_sample.py
Trích xuất và làm sạch một mẫu giọng (reference clip) từ file audio/video gốc,
để dùng làm "voice profile" cho việc nhân bản giọng nói (voice cloning) bằng XTTS-v2.

Quy trình:
  1. (Tuỳ chọn, khuyến nghị) Tách vocal khỏi nhạc nền bằng demucs.
     -> Cần chạy ở máy có internet để tải model lần đầu (~80-300MB tuỳ model).
  2. Cắt ra đoạn liên tục, không có khoảng lặng dài, không nhạc nền.
  3. Chuẩn hoá âm lượng (loudnorm) + resample về 24000Hz mono (chuẩn input của XTTS-v2).

LƯU Ý ĐẠO ĐỨC / PHÁP LÝ:
Chỉ nên trích xuất và nhân bản giọng nói của chính bạn, hoặc giọng của người
đã đồng ý rõ ràng cho việc này. Không dùng để giả giọng người khác mà không
có sự cho phép của họ.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from typing import Callable, List, Optional, Tuple


@dataclass
class VoiceProfile:
    name: str
    reference_wav: str          # đường dẫn file mẫu giọng đã làm sạch
    source_file: str            # file gốc đã trích xuất từ đó
    start_sec: float
    duration_sec: float
    vocals_separated: bool      # đã tách nhạc nền hay chưa
    sample_rate: int = 24000
    consent_confirmed: bool = False   # người dùng đã xác nhận đây là giọng của họ / được phép dùng


def _run(cmd: List[str]) -> Tuple[int, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode, p.stdout


def detect_silences(audio_path: str, noise_db: str = "-30dB", min_dur: float = 0.4) -> List[Tuple[float, float]]:
    """Trả về danh sách (start, end) các khoảng lặng, dùng ffmpeg silencedetect."""
    code, out = _run([
        "ffmpeg", "-y", "-i", audio_path,
        "-af", f"silencedetect=noise={noise_db}:d={min_dur}",
        "-f", "null", "-",
    ])
    silences = []
    start = None
    for line in out.splitlines():
        if "silence_start" in line:
            try:
                start = float(line.strip().split("silence_start:")[1].strip())
            except (IndexError, ValueError):
                start = None
        elif "silence_end" in line and start is not None:
            try:
                end_part = line.strip().split("silence_end:")[1].strip()
                end = float(end_part.split("|")[0].strip())
                silences.append((start, end))
            except (IndexError, ValueError):
                pass
            start = None
    return silences


def measure_volume(audio_path: str, start: float, duration: float) -> Tuple[float, float]:
    """Trả về (mean_volume_db, max_volume_db) cho 1 đoạn audio."""
    code, out = _run([
        "ffmpeg", "-y", "-ss", str(start), "-t", str(duration), "-i", audio_path,
        "-af", "volumedetect", "-f", "null", "-",
    ])
    mean_db, max_db = -100.0, -100.0
    for line in out.splitlines():
        if "mean_volume:" in line:
            try:
                mean_db = float(line.split("mean_volume:")[1].replace("dB", "").strip())
            except ValueError:
                pass
        elif "max_volume:" in line:
            try:
                max_db = float(line.split("max_volume:")[1].replace("dB", "").strip())
            except ValueError:
                pass
    return mean_db, max_db


def separate_vocals(audio_path: str, out_dir: str,
                     progress_cb: Optional[Callable[[float, str], None]] = None) -> str:
    """
    Tách vocal khỏi nhạc nền bằng demucs (htdemucs model).
    pip install demucs
    Lần chạy đầu cần internet để tải model (~80MB).
    Trả về đường dẫn file vocal (.wav) đã tách.

    LƯU Ý: dùng sys.executable (Python đang chạy script này) thay vì gọi cứng
    "python3" — trên Windows thường KHÔNG có python3.exe (chỉ có python.exe),
    gọi cứng "python3" sẽ bị App Execution Alias của Microsoft Store chặn và
    báo "Python was not found...". Dùng sys.executable đảm bảo luôn đúng
    interpreter đang cài demucs, bất kể tên lệnh trên PATH là gì.
    """
    if progress_cb:
        progress_cb(0.0, "Đang tách vocal khỏi nhạc nền (demucs)...")

    os.makedirs(out_dir, exist_ok=True)
    code, out = _run([
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-o", out_dir,
        audio_path,
    ])
    if code != 0:
        raise RuntimeError(f"demucs lỗi (cần: pip install demucs, và internet cho lần chạy đầu):\n{out[-1500:]}")

    # demucs xuất ra: out_dir/htdemucs/<ten_file_khong_duoi>/vocals.wav
    base = os.path.splitext(os.path.basename(audio_path))[0]
    vocals_path = os.path.join(out_dir, "htdemucs", base, "vocals.wav")
    if not os.path.exists(vocals_path):
        raise RuntimeError(f"Không tìm thấy file vocal sau khi tách: {vocals_path}")

    if progress_cb:
        progress_cb(1.0, "Đã tách xong vocal")
    return vocals_path


def find_best_clip(audio_path: str, clip_duration: float = 18.0,
                    step: float = 15.0) -> Tuple[float, float]:
    """
    Quét toàn bộ file theo từng cửa sổ `clip_duration` giây, chọn đoạn có:
      - mean_volume cao nhất (giọng rõ, không quá nhỏ)
      - không rơi đúng vào khoảng lặng dài đầu/cuối
    Trả về (start_sec, mean_volume_db) của đoạn tốt nhất.
    """
    code, out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", audio_path])
    try:
        total_dur = float(out.strip())
    except ValueError:
        total_dur = clip_duration

    silences = detect_silences(audio_path)

    best_start, best_score = 0.0, -999.0
    t = 0.0
    while t + clip_duration <= total_dur:
        # bỏ qua nếu đoạn này chồng lấn > 30% với 1 khoảng lặng đã biết
        overlap = 0.0
        for s, e in silences:
            ov_start = max(t, s)
            ov_end = min(t + clip_duration, e)
            if ov_end > ov_start:
                overlap += ov_end - ov_start
        if overlap / clip_duration < 0.3:
            mean_db, _ = measure_volume(audio_path, t, clip_duration)
            if mean_db > best_score:
                best_score = mean_db
                best_start = t
        t += step

    return best_start, best_score


def extract_reference_clip(
    source_path: str,
    voice_name: str,
    out_dir: str,
    start_sec: Optional[float] = None,
    duration_sec: float = 18.0,
    separate_music: bool = True,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> VoiceProfile:
    """
    Trích xuất + làm sạch 1 đoạn mẫu giọng từ file audio/video gốc.

    - Nếu separate_music=True: chạy demucs tách vocal trước khi cắt đoạn mẫu
      (khuyến nghị mạnh nếu nguồn có nhạc nền, ví dụ video TikTok).
    - Nếu start_sec=None: tự động quét để chọn đoạn rõ giọng nhất.
    """
    os.makedirs(out_dir, exist_ok=True)
    work_source = source_path
    vocals_separated = False

    if separate_music:
        try:
            work_source = separate_vocals(source_path, os.path.join(out_dir, "_demucs_tmp"), progress_cb)
            vocals_separated = True
        except Exception as e:
            if progress_cb:
                progress_cb(0.3, f"⚠ Không tách được nhạc nền ({e}) - dùng audio gốc")
            work_source = source_path
            vocals_separated = False

    if start_sec is None:
        if progress_cb:
            progress_cb(0.5, "Đang quét tìm đoạn giọng rõ nhất...")
        start_sec, _ = find_best_clip(work_source, clip_duration=duration_sec)

    if progress_cb:
        progress_cb(0.7, f"Đang cắt & chuẩn hoá đoạn mẫu (bắt đầu {start_sec:.1f}s)...")

    ref_path = os.path.join(out_dir, f"{voice_name}_reference.wav")
    # Cắt đoạn, chuẩn hoá loudness (EBU R128), resample 24000Hz mono, fade in/out nhẹ để tránh click
    code, out = _run([
        "ffmpeg", "-y",
        "-ss", str(start_sec), "-t", str(duration_sec),
        "-i", work_source,
        "-af", (
            f"afade=t=in:st=0:d=0.15,"
            f"afade=t=out:st={max(0, duration_sec - 0.15)}:d=0.15,"
            f"loudnorm=I=-20:TP=-1.5:LRA=11"
        ),
        "-ac", "1", "-ar", "24000",
        ref_path,
    ])
    if code != 0 or not os.path.exists(ref_path):
        raise RuntimeError(f"Cắt/chuẩn hoá mẫu giọng thất bại:\n{out[-1500:]}")

    if progress_cb:
        progress_cb(1.0, "Đã tạo xong mẫu giọng tham chiếu")

    profile = VoiceProfile(
        name=voice_name,
        reference_wav=ref_path,
        source_file=source_path,
        start_sec=start_sec,
        duration_sec=duration_sec,
        vocals_separated=vocals_separated,
        consent_confirmed=False,   # phải được set True tường minh ở bước lưu profile, xem save_voice_profile
    )
    return profile


def save_voice_profile(profile: VoiceProfile, profiles_dir: str, consent_confirmed: bool) -> str:
    """
    Lưu voice profile ra JSON. Bắt buộc phải truyền consent_confirmed=True
    (người dùng xác nhận đây là giọng của họ hoặc họ có quyền dùng) mới lưu được.
    Đây là bước chặn tường minh, không tự động hoá ngầm.
    """
    if not consent_confirmed:
        raise ValueError(
            "Không thể lưu voice profile: cần xác nhận rõ ràng (consent_confirmed=True) "
            "rằng đây là giọng của chính người dùng hoặc họ được phép sử dụng."
        )
    profile.consent_confirmed = True
    os.makedirs(profiles_dir, exist_ok=True)
    out_path = os.path.join(profiles_dir, f"{profile.name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(profile), f, ensure_ascii=False, indent=2)
    return out_path


def load_voice_profile(profiles_dir: str, name: str) -> VoiceProfile:
    path = os.path.join(profiles_dir, f"{name}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy voice profile '{name}' tại {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return VoiceProfile(**data)