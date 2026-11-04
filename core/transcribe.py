"""
core/transcribe.py
Tách thoại từ video thành phụ đề (SRT) bằng faster-whisper.
Chạy được trên CPU hoặc GPU (CUDA) nếu máy có sẵn.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class SubtitleSegment:
    index: int
    start: float          # giây
    end: float             # giây
    text: str
    gender: str = ""       # "male" | "female" | "" (chưa xác định) - do core/gender_detect.py hoặc
                            # core/face_speaker_detect.py gán, mang theo xuyên suốt translate/
                            # narration_merge/text_fit để core/tts.py chọn đúng giọng Nam/Nữ.
    speaker_id: str = ""   # "person_0", "person_1"... - do core/face_speaker_detect.py gán khi nhận
                            # diện theo khuôn mặt/khẩu hình, phân biệt TỪNG nhân vật (không chỉ giới
                            # tính) để không gộp nhầm 2 nhân vật cùng giới vào 1 khối lời dẫn.


def _fmt_ts(t: float) -> str:
    """Chuyển giây -> timestamp SRT: HH:MM:SS,mmm"""
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: List[SubtitleSegment]) -> str:
    lines = []
    for seg in segments:
        lines.append(str(seg.index))
        lines.append(f"{_fmt_ts(seg.start)} --> {_fmt_ts(seg.end)}")
        lines.append(seg.text.strip())
        lines.append("")
    return "\n".join(lines)


def transcribe_video(
    video_path: str,
    model_size: str = "small",
    device: str = "auto",       # "auto" | "cpu" | "cuda"
    compute_type: str = "auto",
    language: Optional[str] = None,   # None = auto-detect
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[SubtitleSegment]:
    """
    Tách thoại thành danh sách SubtitleSegment.
    Yêu cầu: pip install faster-whisper
    Model sẽ được tải về ~/.cache/huggingface lần đầu chạy (cần internet).
    """
    from faster_whisper import WhisperModel

    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"

    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"

    if progress_cb:
        progress_cb(0.0, f"Đang tải model whisper ({model_size}, {device})...")

    # Dời cache model (huggingface/CTranslate2) về 1 folder CẠNH nơi đang chạy app,
    # thay vì mặc định vào ~/.cache/huggingface (thường nằm ở ổ C: trên Windows) - để
    # ổ C không tự phình dần theo thời gian khi dùng model lớn hơn (medium/large), và
    # để cache nằm cùng ổ đĩa với dữ liệu làm việc (F: theo cấu hình hiện tại của bạn).
    model_cache_dir = os.path.join(os.getcwd(), "model_cache")
    os.makedirs(model_cache_dir, exist_ok=True)
    model = WhisperModel(model_size, device=device, compute_type=compute_type, download_root=model_cache_dir)

    if progress_cb:
        progress_cb(0.1, "Đang nhận diện thoại...")

    segments_gen, info = model.transcribe(
        video_path,
        language=language,
        vad_filter=True,
        beam_size=5,
    )

    results: List[SubtitleSegment] = []
    duration = getattr(info, "duration", 0) or 1
    for i, seg in enumerate(segments_gen, start=1):
        results.append(SubtitleSegment(index=i, start=seg.start, end=seg.end, text=seg.text))
        if progress_cb:
            pct = min(0.95, 0.1 + 0.85 * (seg.end / duration))
            progress_cb(pct, f"Đã xử lý {seg.end:.1f}s / {duration:.1f}s")

    if progress_cb:
        progress_cb(1.0, "Hoàn tất tách thoại")

    return results


def save_srt(segments: List[SubtitleSegment], out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(segments_to_srt(segments))
    return out_path


def _parse_srt_timestamp(ts: str) -> float:
    """'HH:MM:SS,mmm' hoặc 'HH:MM:SS.mmm' -> số giây (float)."""
    ts = ts.strip().replace(".", ",")
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(srt_path: str) -> List[SubtitleSegment]:
    """
    Đọc 1 file .srt CÓ SẴN (do người dùng tự tải lên, hoặc từ 1 nguồn dịch khác)
    thành danh sách SubtitleSegment - dùng để BỎ QUA bước Transcript (tách thoại
    bằng whisper) và Translate (dịch), khi người dùng đã có sẵn phụ đề đúng ngôn
    ngữ đích muốn dùng thẳng cho phần Lồng tiếng/Export.

    Chấp nhận định dạng SRT chuẩn (số thứ tự, dòng thời gian, 1+ dòng text, dòng
    trống ngăn cách). Khá dễ tính với các biến thể nhỏ (BOM ở đầu file, dòng
    trống thừa, dấu '.' thay ',' trong mili-giây, thiếu số thứ tự...).
    """
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Không tìm thấy file phụ đề: {srt_path}")

    with open(srt_path, "r", encoding="utf-8-sig") as f:
        raw = f.read()

    # Chuẩn hoá xuống dòng, tách thành từng block cách nhau bởi dòng trống.
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip("\n") for b in raw.split("\n\n") if b.strip()]

    segments: List[SubtitleSegment] = []
    idx = 0
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue

        # Dòng đầu có thể là số thứ tự (bỏ qua) hoặc đã là dòng thời gian luôn.
        start_i = 0
        if "-->" not in lines[0]:
            start_i = 1
        if start_i >= len(lines) or "-->" not in lines[start_i]:
            continue  # block không hợp lệ (thiếu dòng thời gian) - bỏ qua thay vì crash cả file

        time_line = lines[start_i]
        try:
            start_str, end_str = [p.strip() for p in time_line.split("-->")]
            start = _parse_srt_timestamp(start_str)
            end = _parse_srt_timestamp(end_str.split(" ")[0])   # bỏ phần config lề (nếu có) sau timestamp
        except Exception:
            continue  # dòng thời gian sai định dạng - bỏ qua block này, không làm hỏng cả file

        text = "\n".join(lines[start_i + 1:]).strip()
        if not text:
            continue

        idx += 1
        segments.append(SubtitleSegment(index=idx, start=start, end=end, text=text))

    if not segments:
        raise ValueError(f"Không đọc được dòng phụ đề hợp lệ nào từ file: {srt_path}")

    return segments
