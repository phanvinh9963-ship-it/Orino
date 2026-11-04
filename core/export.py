"""
core/export.py
Ghép mọi thứ lại thành video hoàn chỉnh bằng ffmpeg (subprocess trực tiếp, không cần lib phụ).
Yêu cầu: ffmpeg đã cài trong PATH.
"""
from __future__ import annotations
import os
import random
import re
import subprocess
from typing import Callable, Optional, Tuple
FONT = r"C\:/Windows/Fonts/arial.ttf"

# Arial KHONG co glyph cho Nhat/Han/Trung -> hien thi thanh o vuong (tofu) neu nguoi
# dung go tieng Nhat/Han/Trung vao watermark. Windows khong co 1 font duy nhat phu
# het moi ngon ngu, nen TU DONG chon dung font he thong theo bang chu cai phat hien
# duoc trong chinh doan text (uu tien phat hien theo thu tu Hangul -> Kana (Nhat) ->
# Han/Trung -> con lai dung Arial nhu cu, du cho Latin/Tieng Viet Arial da co san).
_FONT_HANGUL = r"C\:/Windows/Fonts/malgun.ttf"    # Malgun Gothic - tieng Han Quoc
_FONT_JAPANESE = r"C\:/Windows/Fonts/YuGothM.ttc"  # Yu Gothic Medium - tieng Nhat (kana + kanji)
_FONT_CJK = r"C\:/Windows/Fonts/msyh.ttc"          # Microsoft YaHei - tieng Trung (han tu)


def _pick_font_for_text(text: str) -> str:
    """Tu dong chon file font .ttf/.ttc phu hop nhat de ve TEXT nay bang ffmpeg
    drawtext, dua theo bang chu cai xuat hien trong text - tranh loi hien o vuong
    (tofu) khi go tieng Nhat/Han/Trung ma van dung font Arial mac dinh (Arial
    khong co glyph cho cac ngon ngu nay). Vietnamese/Latin van dung Arial nhu cu."""
    if not text:
        return FONT
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF:   # Hangul
            return _FONT_HANGUL
        if 0x3040 <= code <= 0x30FF:   # Hiragana/Katakana - CHAC CHAN la tieng Nhat
            return _FONT_JAPANESE
    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:   # Han tu (dung chung Nhat/Han/Trung, kiem tra SAU
            return _FONT_CJK           # kana/hangul o tren de uu tien dung neu la tieng Nhat/Han)
    return FONT

STYLE_PRESETS = {
    # tên: (màu chữ ASS &HBBGGRR&, viền, cỡ chữ, kiểu)
    "Neon":     dict(color="&H00FFFF&", outline="&H00000000&", size=22, bold=1),
    "Classic":  dict(color="&HFFFFFF&", outline="&H00000000&", size=20, bold=0),
    "Minimal":  dict(color="&HFFFFFF&", outline="&H00000000&", size=18, bold=0),
    "Bold":     dict(color="&H00D4FF&", outline="&H00000000&", size=24, bold=1),
    "Mint":     dict(color="&HB6E4C6&", outline="&H00000000&", size=20, bold=0),
    "Rose":     dict(color="&HB1A0F7&", outline="&H00000000&", size=20, bold=0),
}


def _run(cmd: list[str], cwd: Optional[str] = None):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi:\n{proc.stdout}")
    return proc.stdout


def _srt_ts_to_ms(ts: str) -> int:
    """'00:01:02,345' -> tổng số mili-giây."""
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return ((int(h) * 3600 + int(m) * 60 + int(s)) * 1000) + int(ms)


def _ms_to_ass_ts(ms: int) -> str:
    """mili-giây -> 'H:MM:SS.CC' (centigiây) theo định dạng ASS."""
    ms = max(0, int(ms))
    cs = round(ms / 10)  # centiseconds
    h = cs // 360000
    cs -= h * 360000
    m = cs // 6000
    cs -= m * 6000
    s = cs // 100
    cs -= s * 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _parse_srt_cues(srt_path: str) -> list[dict]:
    """Đọc file .srt -> list các cue {start_ms, end_ms, text}."""
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        raw = f.read()

    blocks = re.split(r"\r?\n\r?\n+", raw.strip())
    cues = []
    ts_re = re.compile(
        r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})"
    )
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if not lines:
            continue
        ts_line_idx = None
        for i, ln in enumerate(lines):
            if ts_re.search(ln):
                ts_line_idx = i
                break
        if ts_line_idx is None:
            continue
        m = ts_re.search(lines[ts_line_idx])
        start_ms = _srt_ts_to_ms(m.group(1))
        end_ms = _srt_ts_to_ms(m.group(2))
        text = "\n".join(lines[ts_line_idx + 1:]).strip()
        if not text:
            continue
        cues.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})
    return cues


def _ass_escape(text: str) -> str:
    # {} có ý nghĩa đặc biệt (bọc override tag) trong ASS -> thay bằng ngoặc thường
    # để tránh nội dung phụ đề vô tình phá cú pháp; xuống dòng -> \N.
    text = text.replace("{", "(").replace("}", ")")
    return text.replace("\r\n", "\\N").replace("\n", "\\N")


def _hex6(color: str) -> str:
    """Chuẩn hoá chuỗi màu kiểu '&H2D2D2D&' / '2D2D2D' -> '2D2D2D' (6 hex, BBGGRR)."""
    s = color.strip().upper()
    s = s.lstrip("&").lstrip("H").rstrip("&")
    s = re.sub(r"[^0-9A-F]", "", s)
    if len(s) >= 6:
        s = s[-6:]
    else:
        s = s.zfill(6)
    return s


_POSITION_ALIGNMENT = {"top": 8, "middle": 5, "bottom": 2}


def _effect_override_tags(effect: str) -> str:
    """Trả về override-tag ASS áp cho mỗi dòng/chữ, tuỳ hiệu ứng xuất hiện đã chọn."""
    if effect == "fade":
        return r"\fad(250,120)"
    if effect == "zoom":
        return r"\fscx60\fscy60\t(0,220,\fscx100\fscy100)"
    if effect == "bounce":
        return r"\fscx55\fscy55\t(0,150,\fscx115\fscy115)\t(150,260,\fscx100\fscy100)"
    return ""


def burn_subtitles(
    video_path: str,
    srt_path: str,
    out_path: str,
    preset: str = "Classic",
    font_size: int = 20,
    display_mode: str = "sentence",
    font_name: str = "Arial",
    position: str = "bottom",   # "top" | "middle" | "bottom" | "custom" (dùng kèm x_frac/y_frac)
    x_frac: Optional[float] = None,   # dùng khi position="custom": tỉ lệ 0..1 tính TỪ TÂM chữ, mép TRÁI khung hình
    y_frac: Optional[float] = None,   # dùng khi position="custom": tỉ lệ 0..1 tính TỪ TÂM chữ, mép TRÊN khung hình
    box_enabled: bool = False,
    box_color: str = "&H000000&",
    box_opacity: float = 0.6,
    effect: str = "none",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Hardsub: ghi phụ đề trực tiếp vào khung hình video.

    Thay vì dùng filter 'subtitles=' + force_style (chỉ áp được 1 style tĩnh cho
    toàn bộ phụ đề), hàm này TỰ DỰNG một file .ass với override-tag riêng cho
    từng dòng/chữ, để hỗ trợ: vị trí (trên/giữa/dưới HOẶC tuỳ chỉnh theo toạ độ
    %, xem position="custom"), nền phía sau chữ (màu + độ mờ riêng), hiệu ứng
    xuất hiện (mờ dần/phóng to/nảy nhẹ), và kiểu hiển thị từng-chữ-một
    (TikTok-style) bằng cách chia đều thời lượng mỗi cue cho các từ.

    position="custom": đặt phụ đề tại ĐÚNG toạ độ do người dùng tự chọn (kéo-thả
    trên UI, hoặc lấy theo vùng che mờ đã vẽ) thay vì chỉ 3 vị trí cố định -
    dùng ASS override tag \\pos(x,y) cho TỪNG dòng thay vì Alignment/MarginV
    tĩnh trong Style. x_frac/y_frac là toạ độ TÂM chữ, tính theo tỉ lệ 0..1 của
    chiều rộng/cao khung hình (0,0 = góc trên-trái, 1,1 = góc dưới-phải).

    LƯU Ý QUAN TRỌNG (Windows): filter ffmpeg parse dấu ':' làm ký tự phân tách
    trong filter-graph, nên đường dẫn kiểu 'F:\\...' hoặc có dấu cách (rất phổ
    biến trên Windows, vd 'C:\\Users\\Ngo Tu\\...') rất dễ làm ffmpeg đọc sai
    đường dẫn -> phụ đề không được nạp vào video output dù không báo lỗi rõ ràng.
    Cách né triệt để: KHÔNG nhét full path vào chuỗi filter - chỉ truyền đúng
    TÊN FILE (không path), đồng thời chạy ffmpeg với cwd = đúng thư mục chứa
    file đó. video_path/out_path vẫn dùng path tuyệt đối (không qua filter-graph
    nên không bị lỗi escape này).
    """
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Không tìm thấy file phụ đề: {srt_path}")

    style = STYLE_PRESETS.get(preset, STYLE_PRESETS["Classic"])
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if progress_cb:
        progress_cb(0.05, "Đang dựng style phụ đề...")

    cues = _parse_srt_cues(srt_path)
    if not cues:
        raise RuntimeError(f"burn_subtitles: không đọc được cue nào từ '{srt_path}'")

    # position="custom": neo Style tại TÂM chữ (Alignment=5) rồi dùng \pos(x,y) cho
    # TỪNG dòng để đặt đúng toạ độ người dùng chọn - khác 3 vị trí cố định (dùng
    # Alignment gắn theo mép khung hình qua MarginV cố định trong style_line).
    custom_pos_tag = ""
    if position == "custom" and x_frac is not None and y_frac is not None:
        alignment = 5
        pos_x = max(0, min(1280, round(x_frac * 1280)))
        pos_y = max(0, min(720, round(y_frac * 720)))
        custom_pos_tag = f"\\pos({pos_x},{pos_y})"
    else:
        alignment = _POSITION_ALIGNMENT.get(position, 2)
    primary_colour = f"&H00{_hex6(style['color'])}&"
    outline_colour = f"&H00{_hex6(style['outline'])}&"
    if box_enabled:
        alpha = max(0, min(255, round((1 - box_opacity) * 255)))
        back_colour = f"&H{alpha:02X}{_hex6(box_color)}&"
        border_style = 3
    else:
        # BorderStyle=1: viền chữ mỏng, không có nền -> BackColour để trong suốt
        back_colour = f"&HFF{_hex6(box_color)}&"
        border_style = 1

    style_line = (
        "Style: Default,{font},{size},{primary},&H000000FF&,{outline},{back},"
        "{bold},0,0,0,100,100,0,0,{border_style},2,0,{align},20,20,40,1"
    ).format(
        font=font_name or "Arial",
        size=font_size,
        primary=primary_colour,
        outline=outline_colour,
        back=back_colour,
        bold=style["bold"],
        border_style=border_style,
        align=alignment,
    )

    fx_tags = custom_pos_tag + _effect_override_tags(effect)

    events = []
    for cue in cues:
        text = _ass_escape(cue["text"])
        start_ms, end_ms = cue["start_ms"], cue["end_ms"]
        duration = max(1, end_ms - start_ms)

        if display_mode == "word":
            words = text.replace("\\N", " ").split()
            if not words:
                continue
            # Chia thời lượng theo TỈ LỆ ĐỘ DÀI từng từ (không chia đều nữa) - từ dài tự
            # nhiên đọc lâu hơn từ ngắn, nên cách này bám sát nhịp đọc thật hơn hẳn so với
            # chia đều (chia đều là nguyên nhân phụ đề "chạy" lệch dần so với audio, nhất
            # là với các khối câu dài sau khi gộp câu - core/narration_merge.py). Cộng thêm
            # hằng số nhỏ (+2) cho mỗi từ để mô phỏng khoảng ngắt hơi tự nhiên giữa các từ
            # ngắn (nếu chỉ tính đúng số ký tự, các từ 1-2 ký tự như "và", "là" sẽ bị cấp
            # thời lượng gần như 0, hiện lên rồi biến mất quá nhanh, không tự nhiên).
            weights = [len(w) + 2 for w in words]
            total_w = sum(weights)
            cum = 0
            for i, w in enumerate(words):
                w_start = start_ms + int(duration * cum / total_w)
                cum += weights[i]
                w_end = start_ms + int(duration * cum / total_w) if i < len(words) - 1 else end_ms
                tag = f"{{{fx_tags}}}" if fx_tags else ""
                events.append(
                    f"Dialogue: 0,{_ms_to_ass_ts(w_start)},{_ms_to_ass_ts(w_end)},"
                    f"Default,,0,0,0,,{tag}{w}"
                )
        else:
            tag = f"{{{fx_tags}}}" if fx_tags else ""
            events.append(
                f"Dialogue: 0,{_ms_to_ass_ts(start_ms)},{_ms_to_ass_ts(end_ms)},"
                f"Default,,0,0,0,,{tag}{text}"
            )

    ass_content = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "PlayResX: 1280\n"
        "PlayResY: 720\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_line}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(events) + "\n"
    )

    srt_abs = os.path.abspath(srt_path)
    srt_dir = os.path.dirname(srt_abs)
    ass_name = os.path.splitext(os.path.basename(srt_abs))[0] + "_styled.ass"
    ass_abs = os.path.join(srt_dir, ass_name)
    with open(ass_abs, "w", encoding="utf-8") as f:
        f.write(ass_content)

    video_abs = os.path.abspath(video_path)
    out_abs = os.path.abspath(out_path)

    vf = f"ass=filename={ass_name}"

    if progress_cb:
        progress_cb(0.1, "Đang ghi phụ đề vào video...")

    cmd = [
        "ffmpeg", "-y", "-i", video_abs,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_abs,
    ]
    # cwd=srt_dir: để ffmpeg tìm được đúng file .ass chỉ bằng tên file (né hoàn toàn
    # lỗi escape ổ đĩa/dấu cách nêu trên). video_abs/out_abs là path tuyệt đối nên
    # không phụ thuộc cwd.
    _run(cmd, cwd=srt_dir)

    if not os.path.exists(out_abs) or os.path.getsize(out_abs) == 0:
        raise RuntimeError(
            f"burn_subtitles: ffmpeg chạy xong nhưng KHÔNG tạo ra file output "
            f"({out_abs}) - kiểm tra lại style '{style_line}' hoặc quyền ghi file."
        )

    if progress_cb:
        progress_cb(1.0, "Hoàn tất ghi phụ đề")
    return out_abs


def mux_dubbed_audio(
    video_path: str,
    dubbed_audio_path: str,
    out_path: str,
    keep_original_audio: bool = False,
    original_volume: float = 0.15,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Thay (hoặc trộn) audio gốc bằng track lồng tiếng đã tạo."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if progress_cb:
        progress_cb(0.1, "Đang ghép giọng lồng tiếng vào video...")

    if keep_original_audio:
        filter_complex = (
            f"[0:a]volume={original_volume}[a0];[1:a]volume=1.0[a1];"
            f"[a0][a1]amix=inputs=2:duration=first[aout]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", dubbed_audio_path,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            out_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", dubbed_audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest",
            out_path,
        ]
    _run(cmd)

    if progress_cb:
        progress_cb(1.0, "Hoàn tất ghép giọng lồng tiếng")
    return out_path


def add_watermark(
    video_path: str,
    text: str,
    out_path: str,
    opacity: float = 0.6,
    font_size: int = 16,
    position: str = "top-right",   # "top-left" | "top-right" | "bottom-left" | "bottom-right" | "custom"
    x_frac: Optional[float] = None,
    y_frac: Optional[float] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Watermark CHỮ ĐỨNG YÊN 1 chỗ (đối lập với add_moving_watermark_text)."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, "Đang thêm watermark...")

    margin = 10
    pos_map = {
        "top-left": (f"{margin}", f"{margin}"),
        "top-right": (f"w-tw-{margin}", f"{margin}"),
        "bottom-left": (f"{margin}", f"h-th-{margin}"),
        "bottom-right": (f"w-tw-{margin}", f"h-th-{margin}"),
    }
    if position == "custom" and x_frac is not None and y_frac is not None:
        video_w, video_h = _probe_wh(video_path)
        ox = f"{video_w}*{x_frac:.4f}-tw/2"
        oy = f"{video_h}*{y_frac:.4f}-th/2"
    else:
        ox, oy = pos_map.get(position, pos_map["top-right"])

    text_escaped = (
        text.replace("\\", "\\\\\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")
        .replace("%", "\\%")
    )
    opacity = max(0.05, min(1.0, opacity))
    font_path = _pick_font_for_text(text)

    drawtext = (
        f"drawtext=fontfile='{font_path}':"
        f"text='{text_escaped}':fontcolor=white@{opacity:.2f}:fontsize={font_size}:"
        f"borderw=1:bordercolor=black@0.7:x={ox}:y={oy}"
    )
    video_abs = os.path.abspath(video_path)
    out_abs = os.path.abspath(out_path)
    cmd = [
        "ffmpeg", "-y", "-i", video_abs,
        "-vf", drawtext,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_abs,
    ]
    _run(cmd)

    if not os.path.exists(out_abs) or os.path.getsize(out_abs) == 0:
        raise RuntimeError(f"add_watermark: ffmpeg không tạo ra file output ({out_abs}).")

    if progress_cb:
        progress_cb(1.0, "Hoàn tất watermark")
    return out_abs


def _probe_wh(video_path: str) -> tuple[int, int]:
    """Lấy đúng (width, height) hiện tại của video bằng ffprobe - dùng để tính
    toán các phép scale/pad/crop bằng SỐ PIXEL CỤ THỂ thay vì công thức ký hiệu
    (main_w, ow, iw...) của ffmpeg - nhiều biến trong số đó rất dễ hiểu nhầm
    ngữ cảnh (tự tham chiếu chính nó, hoặc trỏ nhầm sang input khác) tuỳ filter
    và tuỳ bản ffmpeg, từng gây lỗi 'self-referencing' / 'Padded dimensions
    cannot be smaller than input' trước đây."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", video_path,
    ]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    try:
        w_str, h_str = out.stdout.strip().split(",")[:2]
        return int(w_str), int(h_str)
    except Exception as e:
        raise RuntimeError(f"Không đọc được kích thước video từ ffprobe: {out.stdout}") from e


def _even(n: float) -> int:
    """Làm tròn xuống số chẵn gần nhất (libx264 bắt buộc width/height là số chẵn)."""
    n = int(n)
    return n if n % 2 == 0 else n - 1


def add_watermark_image(
    video_path: str,
    logo_path: str,
    out_path: str,
    position: str = "top-right",   # "top-left" | "top-right" | "bottom-left" | "bottom-right" | "custom"
    x_frac: Optional[float] = None,   # dùng khi position="custom": tỉ lệ 0..1 tính từ mép TRÁI khung hình
    y_frac: Optional[float] = None,   # dùng khi position="custom": tỉ lệ 0..1 tính từ mép TRÊN khung hình
    scale_width_frac: float = 0.18,   # logo rộng bằng bao nhiêu % chiều rộng video (giữ tỉ lệ khung logo)
    opacity: float = 1.0,             # 0..1
    margin_px: int = 16,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Chèn logo/ảnh watermark lên video, ở 1 trong 4 góc hoặc vị trí tuỳ ý (custom,
    theo tỉ lệ x_frac/y_frac lấy từ khung hình mẫu người dùng đã kéo-thả trên UI).
    """
    if not os.path.exists(logo_path):
        raise FileNotFoundError(f"Không tìm thấy file logo: {logo_path}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if progress_cb:
        progress_cb(0.1, "Đang chèn logo watermark...")

    video_w, video_h = _probe_wh(video_path)
    logo_target_w = _even(max(2, video_w * scale_width_frac))

    pos_map = {
        "top-left": (f"{margin_px}", f"{margin_px}"),
        "top-right": (f"W-w-{margin_px}", f"{margin_px}"),
        "bottom-left": (f"{margin_px}", f"H-h-{margin_px}"),
        "bottom-right": (f"W-w-{margin_px}", f"H-h-{margin_px}"),
    }
    if position == "custom":
        if x_frac is None or y_frac is None:
            raise ValueError("position='custom' cần truyền x_frac và y_frac (0..1)")
        ox = f"{video_w}*{x_frac:.4f}-w/2"
        oy = f"{video_h}*{y_frac:.4f}-h/2"
    else:
        ox, oy = pos_map.get(position, pos_map["top-right"])

    opacity = max(0.0, min(1.0, opacity))
    # Tính SẴN kích thước logo đích bằng số pixel cụ thể (logo_target_w) thay vì
    # dùng scale2ref với biểu thức main_w/ow - những biến này đã 2 lần gây lỗi
    # "self-referencing"/sai kích thước do ngữ nghĩa main_w trong scale2ref không
    # nhất quán như tài liệu mô tả (đã kiểm chứng thực tế bằng test riêng).
    filter_complex = (
        f"[1:v]scale={logo_target_w}:-2,format=rgba,colorchannelmixer=aa={opacity:.3f}[wm];"
        f"[0:v][wm]overlay=x={ox}:y={oy}"
    )

    video_abs = os.path.abspath(video_path)
    out_abs = os.path.abspath(out_path)
    cmd = [
        "ffmpeg", "-y", "-i", video_abs, "-i", os.path.abspath(logo_path),
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_abs,
    ]
    _run(cmd)

    if not os.path.exists(out_abs) or os.path.getsize(out_abs) == 0:
        raise RuntimeError(f"add_watermark_image: ffmpeg không tạo ra file output ({out_abs}).")

    if progress_cb:
        progress_cb(1.0, "Hoàn tất chèn logo")
    return out_abs


def detect_hardsub_band(
    video_path: str,
    sample_count: int = 24,
    search_zone: str = "bottom",   # "bottom" | "top" | "full" - vùng khung hình để dò (mặc định "bottom" vì hardsub gần như luôn nằm ở dưới)
    brightness_thresh: int = 200,
    min_frames_with_text: int = 3,
    margin_px: int = 6,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """
    TỰ ĐỘNG dò vùng nhiều khả năng là PHỤ ĐỀ HARDSUB GỐC trong video, thay cho việc
    người dùng phải tự vẽ tay ("Vẽ vùng cần che"). Cần: pip install opencv-python

    NGUYÊN LÝ (heuristic hình ảnh, KHÔNG phải OCR đọc hiểu nội dung chữ):
    Chữ phụ đề hardsub gần như luôn có đặc điểm: PIXEL SÁNG (trắng/gần trắng) VIỀN
    ĐEN tương phản mạnh để dễ đọc trên mọi nền - tức vừa SÁNG vừa nằm trên CẠNH
    (edge) mật độ cao. Quét nhiều frame rải đều khắp video, ở mỗi frame tìm KHỐI
    CHỮ NHẬT NHỎ (không phải cả dải ngang) chứa cụm pixel vừa sáng vừa là cạnh -
    đặc trưng của 1 dòng chữ. Vì phụ đề hardsub luôn xuất hiện quanh CÙNG 1 vị trí
    (x, y) cố định xuyên suốt video (chỉ nội dung/độ dài dòng đổi), vị trí phát
    hiện được sẽ LẶP LẠI ổn định qua nhiều frame khác nhau - dùng percentile
    (5%-95%) trên các khối phát hiện được để lấy ra 1 khung ĐẠI DIỆN, đáng tin
    cậy, không bị lệch bởi 1-2 frame nhiễu bất thường.

    CẬP NHẬT (fix lỗi che quá to): bản trước LUÔN trả về full chiều rộng khung
    hình (chỉ giới hạn chiều cao), với mục đích che được mọi dòng dài/ngắn khác
    nhau. Nhưng với các video mà chữ hardsub vốn NGẮN/nằm giữa (vd 1 watermark
    nhỏ kiểu "neo."), cách làm đó khiến vùng che TO HƠN RẤT NHIỀU so với chữ thật,
    lấn cả vào cảnh quay xung quanh (đặc biệt video có nền phức tạp - sóng nước,
    dây xích... cũng đủ sáng+có cạnh, càng dễ làm dải bị kéo giãn sai). Giờ dò
    ÔM SÁT theo cả 2 chiều (x lẫn y) dựa trên vị trí chữ thực tế phát hiện được,
    không mặc định full-width nữa - đúng ý "ôm sát chữ sub" hơn. Đánh đổi: nếu
    video có dòng phụ đề NGẮN lúc này, DÀI lúc khác (kiểu phụ đề nói thông thường,
    không phải watermark cố định), khung dò được sẽ vừa khít với chữ hầu hết các
    lúc, nhưng có thể hơi hẹp so với 1 vài dòng bất thường dài hơn mức trung bình
    - lúc đó nên mở "Vẽ vùng cần che" nới thêm ra 1 chút cho chắc.

    Trả về (x, y, w, h) tính bằng pixel theo đúng độ phân giải gốc, hoặc None nếu
    không dò đủ tin cậy (vd video không có hardsub, hoặc chữ không đủ tương phản)
    - lúc đó nên dùng lại cách vẽ tay.

    GIỚI HẠN: đây là heuristic hình ảnh, không phân biệt được phụ đề GỐC với chữ
    khác vô tình xuất hiện trong video (tên kênh, watermark có sẵn, chữ trong cảnh
    quay...) nếu chúng cũng đủ sáng/có cạnh và rơi vào đúng vùng được dò.
    """
    import cv2
    import numpy as np

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Không tìm thấy file video: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Không mở được video để dò hardsub (thiếu codec, hoặc file lỗi): {video_path}")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if total_frames <= 0 or width <= 0 or height <= 0:
            raise RuntimeError("Không đọc được thông tin video (số frame/độ phân giải) để dò hardsub.")

        if search_zone == "bottom":
            zone_y0, zone_y1 = int(height * 0.65), height   # chỉ quét 35% đáy khung hình (thay vì 55% trước
                                                              # đây) - hardsub gần như luôn sát đáy, thu hẹp
                                                              # vùng quét giúp giảm hẳn nhiễu từ cảnh quay ở
                                                              # giữa khung hình (thuyền, sóng, dây xích...)
        elif search_zone == "top":
            zone_y0, zone_y1 = 0, int(height * 0.35)
        else:
            zone_y0, zone_y1 = 0, height

        sample_indices = sorted(set(
            idx for idx in (int(total_frames * (i + 0.5) / sample_count) for i in range(sample_count))
            if 0 <= idx < total_frames
        ))
        if not sample_indices:
            return None

        # Mỗi frame có tín hiệu, lưu lại khung CHỮ NHẬT NHỎ NHẤT ôm trọn cụm chữ
        # phát hiện được trong frame đó (x0,y0,x1,y1) - KHÔNG lưu cả dải full-width.
        boxes = []
        for n, idx in enumerate(sample_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            zone = gray[zone_y0:zone_y1, :]

            bright_mask = zone > brightness_thresh
            edges = cv2.Canny(zone, 80, 160) > 0
            candidate = bright_mask & edges

            row_counts = candidate.sum(axis=1)
            # NGƯỠNG TUYỆT ĐỐI (số pixel cố định), KHÔNG tính theo % chiều rộng khung
            # hình - nếu tính theo %, chữ NGẮN (vd watermark nhỏ "neo.") không bao giờ
            # đủ ngưỡng dù rõ ràng có chữ, vì độ rộng chữ không tỉ lệ với độ rộng khung
            # hình. 6px là đủ để lọc nhiễu lẻ tẻ mà không bỏ sót chữ ngắn.
            active_rows = np.where(row_counts >= 6)[0]
            if active_rows.size == 0:
                continue

            # Lấy dải hàng LIÊN TỤC dài nhất (tránh nhiễu rải rác không thành khối chữ thật)
            gaps = np.where(np.diff(active_rows) > 5)[0]
            runs = np.split(active_rows, gaps + 1)
            best_run = max(runs, key=len)
            if len(best_run) < 6:   # dải quá mỏng, khó phải là 1 dòng chữ thật
                continue

            row_y0, row_y1 = int(best_run[0]), int(best_run[-1])

            # Trong ĐÚNG dải hàng vừa xác định, chiếu tiếp theo CỘT để tìm chiều
            # rộng THẬT của cụm chữ trong frame này - đây là điểm khác biệt chính
            # so với bản cũ (bản cũ bỏ qua bước này, mặc định lấy full-width luôn).
            col_slice = candidate[row_y0:row_y1 + 1, :]
            col_counts = col_slice.sum(axis=0)
            active_cols = np.where(col_counts > 0)[0]
            if active_cols.size == 0:
                continue
            col_x0, col_x1 = int(active_cols[0]), int(active_cols[-1])
            if col_x1 - col_x0 < 4:   # cụm quá hẹp, khó phải là chữ thật
                continue

            boxes.append((col_x0, zone_y0 + row_y0, col_x1, zone_y0 + row_y1))

            if progress_cb:
                progress_cb(n / len(sample_indices), f"Đang dò vùng phụ đề gốc (frame {n + 1}/{len(sample_indices)})...")

        if len(boxes) < min_frames_with_text:
            if progress_cb:
                progress_cb(1.0, f"Không dò đủ tin cậy vùng phụ đề gốc ({len(boxes)}/{len(sample_indices)} frame có tín hiệu).")
            return None

        x0s = np.array([b[0] for b in boxes])
        y0s = np.array([b[1] for b in boxes])
        x1s = np.array([b[2] for b in boxes])
        y1s = np.array([b[3] for b in boxes])

        # percentile 5%-95% cho CẢ x lẫn y: lấy khung ĐẠI DIỆN đủ rộng để phủ hầu hết
        # các frame có chữ, mà không bị 1-2 frame ngoại lệ (nhiễu, hoặc 1 dòng dài bất
        # thường) kéo khung phình to hẳn ra full-width như bản cũ.
        x0 = max(0, int(np.percentile(x0s, 5)) - margin_px)
        y0 = max(0, int(np.percentile(y0s, 5)) - margin_px)
        x1 = min(width, int(np.percentile(x1s, 95)) + margin_px)
        y1 = min(height, int(np.percentile(y1s, 95)) + margin_px)

        if progress_cb:
            progress_cb(1.0, f"Đã dò xong vùng phụ đề gốc ({len(boxes)}/{len(sample_indices)} frame có tín hiệu)")

        return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))
    finally:
        cap.release()


def delogo_region(
    video_path: str,
    out_path: str,
    x: int,
    y: int,
    w: int,
    h: int,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    XOÁ (không chỉ làm mờ) 1 vùng hình chữ nhật cố định xuyên suốt video, dùng
    filter `delogo` có sẵn của ffmpeg - NỘI SUY nội dung vùng đó từ pixel viền
    xung quanh (giống các công cụ "remove logo/watermark" thương mại), cho kết
    quả tự nhiên hơn hẳn so với blur_region (blur vẫn để lộ 1 vùng mờ nhìn rõ là
    "có che gì đó", delogo cố gắng làm nó BIẾN MẤT/hoà vào nền xung quanh).

    Đánh đổi: delogo hoạt động tốt nhất khi NỀN XUNG QUANH vùng che tương đối đơn
    giản/ít chi tiết (nội suy từ viền dễ hơn) - với logo/sub đè lên nền phức tạp
    (nhiều chi tiết, chuyển động nhanh), kết quả có thể hơi "nhoè" ở vùng đó,
    nhưng vẫn tự nhiên hơn 1 khối blur rõ rệt.

    x, y, w, h tính bằng PIXEL theo đúng độ phân giải gốc của video_path.
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # LỚP AN TOÀN CUỐI: luôn kẹp lại toạ độ trong đúng biên khung hình THẬT (đo bằng
    # ffprobe) trước khi đưa cho ffmpeg - phòng trường hợp nguồn tính toạ độ (tự động
    # dò HOẶC người dùng tự nhập tay) lỡ tính dư vài pixel ra ngoài mép, khiến filter
    # delogo từ chối xử lý ("Logo area is outside of the frame") và làm HỎNG CẢ FILE
    # OUTPUT thay vì chỉ mỗi bước xoá logo bị bỏ qua.
    vid_w, vid_h = _probe_wh(video_path)
    if vid_w > 0 and vid_h > 0:
        x = max(0, min(x, vid_w - 1))
        y = max(0, min(y, vid_h - 1))
        w = max(1, min(w, vid_w - x))
        h = max(1, min(h, vid_h - y))

    if progress_cb:
        progress_cb(0.1, "Đang xoá vùng logo/phụ đề gốc...")

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"delogo=x={x}:y={y}:w={w}:h={h}:show=0",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_path,
    ]
    _run(cmd)

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"delogo_region: ffmpeg không tạo ra file output ({out_path}).")

    if progress_cb:
        progress_cb(1.0, "Đã xoá xong vùng logo/phụ đề gốc")
    return out_path


def detect_logo_region(
    video_path: str,
    sample_count: int = 15,
    corner_frac: float = 0.28,     # mỗi góc chiếm bao nhiêu % chiều rộng/cao khung hình để dò (logo hầu như luôn nằm trong 1 trong 4 góc)
    static_std_thresh: float = 6.0,   # độ lệch chuẩn (theo thời gian) tối đa cho 1 pixel được coi là "tĩnh" (logo không đổi qua từng frame)
    min_edge_ratio: float = 0.02,  # tỉ lệ tối thiểu pixel có cạnh (edge) trong vùng tĩnh - logo/chữ luôn có viền rõ, phân biệt với nền tĩnh đơn giản (vd trời/tường 1 màu)
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """
    TỰ ĐỘNG dò vùng nhiều khả năng là LOGO/WATERMARK tĩnh của kênh gốc (khác hẳn
    detect_hardsub_band vốn để dò PHỤ ĐỀ - phụ đề đổi nội dung liên tục theo lời
    thoại, còn logo/watermark gần như LUÔN Y HỆT xuyên suốt cả video, tại đúng 1
    vị trí cố định, thường nằm ở 1 trong 4 góc khung hình). Cần: pip install opencv-python

    NGUYÊN LÝ: lấy mẫu nhiều frame rải đều khắp video, với MỖI GÓC trong 4 góc
    khung hình, tính ĐỘ LỆCH CHUẨN theo thời gian của từng pixel (qua các frame đã
    lấy mẫu) - logo/watermark tĩnh sẽ có độ lệch chuẩn RẤT THẤP (gần như không đổi
    màu qua các frame) trong khi nội dung video xung quanh (chuyển động, thay đổi
    ánh sáng...) có độ lệch chuẩn cao hơn hẳn. Trong số các pixel "tĩnh" đó, lọc
    tiếp bằng mật độ CẠNH (Canny edge) để loại các vùng tĩnh nhưng đơn giản (vd
    bầu trời, tường 1 màu tình cờ tĩnh) - logo/watermark luôn có hình dạng/chữ rõ
    ràng nên mật độ cạnh cao hơn hẳn nền tĩnh trơn.

    Trả về (x, y, w, h) của góc có khả năng cao nhất là logo, hoặc None nếu không
    góc nào đủ tin cậy (vd video không có logo/watermark).

    GIỚI HẠN: chỉ dò được logo TĨNH (không đổi vị trí/nội dung) nằm gần góc khung
    hình - không dò được logo động (có hiệu ứng chuyển động/mờ dần) hay logo nằm
    giữa khung hình.
    """
    import cv2
    import numpy as np

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Không tìm thấy file video: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Không mở được video để dò logo (thiếu codec, hoặc file lỗi): {video_path}")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if total_frames <= 0 or width <= 0 or height <= 0:
            raise RuntimeError("Không đọc được thông tin video (số frame/độ phân giải) để dò logo.")

        sample_indices = sorted(set(
            idx for idx in (int(total_frames * (i + 0.5) / sample_count) for i in range(sample_count))
            if 0 <= idx < total_frames
        ))
        if len(sample_indices) < 5:
            return None

        frames_gray = []
        for n, idx in enumerate(sample_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            frames_gray.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            if progress_cb:
                progress_cb(n / len(sample_indices) * 0.7, f"Đang dò logo (frame {n + 1}/{len(sample_indices)})...")

        if len(frames_gray) < 5:
            return None

        stack = np.stack(frames_gray, axis=0).astype(np.float32)   # (n_frames, H, W)
        std_map = stack.std(axis=0)         # độ lệch chuẩn theo thời gian - THẤP = tĩnh
        mean_map = stack.mean(axis=0).astype(np.uint8)
        edge_map = cv2.Canny(mean_map, 60, 140) > 0

        static_mask = std_map <= static_std_thresh
        candidate_mask = static_mask & edge_map

        cw = int(width * corner_frac)
        ch = int(height * corner_frac)
        corners = {
            "top-left": (0, 0, cw, ch),
            "top-right": (width - cw, 0, cw, ch),
            "bottom-left": (0, height - ch, cw, ch),
            "bottom-right": (width - cw, height - ch, cw, ch),
        }

        best_name, best_box, best_score = None, None, 0.0
        for name, (cx, cy, cw_, ch_) in corners.items():
            region = candidate_mask[cy:cy + ch_, cx:cx + cw_]
            ratio = region.sum() / max(1, region.size)
            if ratio < min_edge_ratio:
                continue
            ys, xs = np.where(region)
            if xs.size == 0:
                continue
            x0, x1 = int(xs.min()), int(xs.max())
            y0, y1 = int(ys.min()), int(ys.max())
            box_x = cx + x0
            box_y = cy + y0
            box_w = max(1, x1 - x0 + 4)
            box_h = max(1, y1 - y0 + 4)
            # KẸP lại trong biên khung hình - phần đệm +4px ở trên có thể đẩy vùng logo
            # vượt ra ngoài mép phải/dưới nếu logo nằm sát biên (rất hay gặp, vì logo/
            # watermark thường được đặt sát góc) - trước đây KHÔNG kẹp, khiến ffmpeg
            # filter delogo từ chối xử lý ("Logo area is outside of the frame") và làm
            # HỎNG CẢ FILE OUTPUT (không phải chỉ mất mỗi bước xoá logo).
            box_w = min(box_w, width - box_x)
            box_h = min(box_h, height - box_y)
            if box_w < 1 or box_h < 1:
                continue   # sau khi kẹp không còn vùng hợp lệ nào - bỏ qua góc này
            box = (box_x, box_y, box_w, box_h)
            if ratio > best_score:
                best_score, best_name, best_box = ratio, name, box

        if progress_cb:
            progress_cb(1.0, f"Đã dò xong logo - {'tìm thấy ở góc ' + best_name if best_box else 'không phát hiện logo nào đủ tin cậy'}")

        return best_box
    finally:
        cap.release()


def blur_region(
    video_path: str,
    out_path: str,
    x: int,
    y: int,
    w: int,
    h: int,
    strength: int = 20,          # độ mạnh làm mờ (sigma của gblur), càng cao càng mờ
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Làm mờ 1 VÙNG HÌNH CHỮ NHẬT CỐ ĐỊNH xuyên suốt cả video (dùng để che phụ đề
    gốc đã hardsub sẵn trong video, khi người dùng tự chọn khung vùng chữ trên
    khung hình mẫu ở UI). x, y, w, h tính bằng PIXEL theo đúng độ phân giải gốc
    của video_path (KHÔNG phải tỉ lệ %).
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, "Đang làm mờ vùng phụ đề gốc...")

    # Cắt đúng vùng [x,y,w,h] ra làm mờ riêng, rồi overlay đè lại đúng chỗ cũ lên video gốc.
    filter_complex = (
        f"[0:v]crop={w}:{h}:{x}:{y},gblur=sigma={strength}[blurred];"
        f"[0:v][blurred]overlay=x={x}:y={y}"
    )
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_path,
    ]
    _run(cmd)

    if progress_cb:
        progress_cb(1.0, "Hoàn tất làm mờ vùng phụ đề gốc")
    return out_path


def mux_audio_advanced(
    video_path: str,
    dubbed_audio_path: Optional[str],
    out_path: str,
    keep_original_audio: bool = False,
    original_volume: float = 0.15,
    dub_volume: float = 1.0,
    background_music_path: Optional[str] = None,
    bg_music_volume: float = 0.25,
    bg_music_loop: bool = True,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Bản mở rộng của mux_dubbed_audio: trộn tối đa 3 nguồn âm thanh - audio gốc
    (tuỳ chọn giữ lại, âm lượng thấp), giọng lồng tiếng mới, và nhạc nền tuỳ chọn
    (lặp nếu ngắn hơn video), mỗi nguồn chỉnh âm lượng riêng.

    Nếu dubbed_audio_path=None: không lồng tiếng, chỉ tắt/giữ audio gốc + (tuỳ
    chọn) thêm nhạc nền - dùng cho trường hợp chỉ cần đổi nhạc nền mà không dịch
    giọng đọc.
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, "Đang trộn âm thanh (giọng lồng / audio gốc / nhạc nền)...")

    inputs = ["-i", video_path]
    labels = []   # danh sách (đoạn filter, nhãn output) sẽ mix, vd "[a1]"

    # QUAN TRỌNG: 2 biến đếm này PHẢI tách riêng, không được dùng chung 1 biến -
    # đây chính là bug gây lỗi "Invalid file index N in filtergraph description":
    #   - next_input_idx: input thứ mấy trong danh sách `-i` truyền cho ffmpeg
    #     (0 = video, các -i sau đó tăng dần 1, 2, 3... theo ĐÚNG SỐ LƯỢNG -i thật)
    #   - label_counter: số thứ tự nhãn OUTPUT tạm trong filter-graph (a1, a2, a3...)
    # 2 con số này KHÔNG nhất thiết trùng nhau (vd bật "giữ audio gốc" dùng thẳng
    # [0:a] không cần thêm -i mới, nhưng vẫn cần 1 nhãn output a1 riêng) - gộp
    # chung 1 biến khiến input thật bị đếm lệch, ffmpeg báo "Invalid file index".
    next_input_idx = 1
    label_counter = 1

    if keep_original_audio:
        labels.append((f"[0:a]volume={original_volume}[a{label_counter}]", f"[a{label_counter}]"))
        label_counter += 1

    if dubbed_audio_path:
        inputs += ["-i", dubbed_audio_path]
        dub_input_idx = next_input_idx
        next_input_idx += 1
        labels.append((f"[{dub_input_idx}:a]volume={dub_volume}[a{label_counter}]", f"[a{label_counter}]"))
        label_counter += 1

    if background_music_path:
        loop_flag = ["-stream_loop", "-1"] if bg_music_loop else []
        inputs += loop_flag + ["-i", background_music_path]
        bg_input_idx = next_input_idx
        next_input_idx += 1
        labels.append((f"[{bg_input_idx}:a]volume={bg_music_volume}[a{label_counter}]", f"[a{label_counter}]"))
        label_counter += 1

    if not labels:
        # Không có nguồn audio nào được chọn -> chỉ copy video, bỏ audio hẳn
        cmd = ["ffmpeg", "-y", "-i", video_path, "-map", "0:v", "-an", "-c:v", "copy", out_path]
        _run(cmd)
        if progress_cb:
            progress_cb(1.0, "Hoàn tất (video không có audio)")
        return out_path

    filter_chain = ";".join(f for f, _ in labels)
    out_labels = "".join(lbl for _, lbl in labels)
    if len(labels) > 1:
        filter_complex = f"{filter_chain};{out_labels}amix=inputs={len(labels)}:duration=first:dropout_transition=2[aout]"
        map_audio = "[aout]"
    else:
        filter_complex = filter_chain
        map_audio = out_labels

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", map_audio,
        "-c:v", "copy", "-c:a", "aac",
        "-shortest",
        out_path,
    ]
    _run(cmd)

    if progress_cb:
        progress_cb(1.0, "Hoàn tất trộn âm thanh")
    return out_path


def flip_video(
    video_path: str,
    out_path: str,
    horizontal: bool = False,
    vertical: bool = False,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Lật video theo chiều ngang (trái-phải) và/hoặc chiều dọc (trên-dưới)."""
    if not horizontal and not vertical:
        raise ValueError("Cần bật ít nhất 1 trong 2: horizontal hoặc vertical")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, "Đang lật video...")

    filters = []
    if horizontal:
        filters.append("hflip")
    if vertical:
        filters.append("vflip")
    vf = ",".join(filters)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_path,
    ]
    _run(cmd)

    if progress_cb:
        progress_cb(1.0, "Hoàn tất lật video")
    return out_path


def apply_filters(
    video_path: str,
    out_path: str,
    blur: float = 0.0,          # 0 = tắt; >0 = sigma cho gblur (vd 3-8 là mờ nhẹ-vừa)
    sharpen: float = 0.0,       # 0 = tắt; >0 = độ nét thêm (vd 0.5-1.5), dùng unsharp
    brightness: float = 0.0,    # -1.0..1.0, 0 = giữ nguyên
    contrast: float = 1.0,      # 0.0..2.0, 1.0 = giữ nguyên
    saturation: float = 1.0,    # 0.0..3.0, 1.0 = giữ nguyên, 0 = đen trắng
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Áp 1 chuỗi filter hình ảnh: làm mờ/làm nét + chỉnh độ sáng/tương phản/bão hoà màu."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, "Đang áp filter hình ảnh...")

    parts = []
    if blur and blur > 0:
        parts.append(f"gblur=sigma={blur}")
    if sharpen and sharpen > 0:
        parts.append(f"unsharp=5:5:{sharpen}:5:5:0.0")
    if brightness != 0.0 or contrast != 1.0 or saturation != 1.0:
        parts.append(f"eq=brightness={brightness}:contrast={contrast}:saturation={saturation}")

    if not parts:
        raise ValueError("Chưa bật filter nào (blur/sharpen/brightness/contrast/saturation đều ở giá trị mặc định)")

    vf = ",".join(parts)
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_path,
    ]
    _run(cmd)

    if progress_cb:
        progress_cb(1.0, "Hoàn tất áp filter")
    return out_path


ASPECT_RATIOS = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "1:1": (1, 1),
}


def change_aspect_ratio(
    video_path: str,
    out_path: str,
    ratio: str = "9:16",
    mode: str = "crop",     # "crop" | "pad" | "blur_pad" | "blur_pad_zoom" - xem giải thích dưới
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Đổi tỉ lệ khung hình video (vd 16:9 ngang -> 9:16 dọc cho TikTok/Reels).

    4 CÁCH XỬ LÝ (đúng các kỹ thuật phổ biến giới edit video hay dùng khi
    convert ngang -> dọc):

    mode="crop": phóng to vừa khung rồi cắt bớt 2 bên/trên-dưới - lấp đầy hoàn
    toàn khung hình mới, KHÔNG viền, nhưng MẤT một phần nội dung 2 mép (khi
    16:9 -> 9:16 sẽ mất 2 bên trái/phải, giữ dải giữa). Hợp khi chủ thể chính
    luôn nằm giữa khung hình.

    mode="pad": THU NHỎ video lại để vừa lọt trong khung mới, giữ TRỌN VẸN toàn
    bộ nội dung gốc, thêm viền ĐEN (letterbox) ở phần còn trống. Không mất nội
    dung, nhưng viền đen trơ trọi nhìn hơi "video cũ", ít dùng trong nội dung
    giải trí/review hiện đại.

    mode="blur_pad": GIỐNG "pad" (giữ trọn nội dung, không mất góc nào) nhưng
    thay viền đen bằng CHÍNH video gốc đó phóng to lấp đầy + làm mờ làm nền -
    đây là kỹ thuật phổ biến NHẤT hiện nay trên TikTok/Reels/Shorts khi convert
    ngang sang dọc (CapCut gọi là "Background blur", đúng tên bạn hay thấy).
    Nhìn mượt, liền mạch, không bị hụt hẫng như viền đen, mà vẫn không mất bất
    kỳ góc/cạnh nào của nội dung gốc.

    mode="blur_pad_zoom": GIỐNG "blur_pad" nhưng phần nội dung CHÍNH ở giữa được
    PHÓNG TO thêm 1 chút (mặc định 8%) trước khi đặt vào giữa - vẫn giữ được gần
    như toàn bộ nội dung (chỉ crop rất nhẹ 2 mép do phóng to) nhưng nhìn choán
    khung hình dọc hơn hẳn "blur_pad" thuần (dải nền mờ 2 bên/trên-dưới sẽ hẹp
    lại), thường được ưa dùng hơn "blur_pad" vì trông "đầy đặn" hơn mà vẫn gần
    như không mất nội dung - đây cũng là setting mặc định của CapCut/Cap khi
    chọn "Background blur".

    Toàn bộ kích thước được tính SẴN bằng số pixel cụ thể qua ffprobe (không
    dùng công thức ký hiệu iw/ow/main_w của ffmpeg) - tránh lặp lại các lỗi
    "self-referencing"/"Padded dimensions cannot be smaller than input" đã gặp
    trước đây do các biến đó dễ bị hiểu sai ngữ cảnh tuỳ filter/tuỳ bản ffmpeg.
    """
    if ratio not in ASPECT_RATIOS:
        raise ValueError(f"Tỉ lệ không hỗ trợ: {ratio}. Chọn 1 trong: {list(ASPECT_RATIOS)}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, f"Đang đổi tỉ lệ khung hình sang {ratio}...")

    src_w, src_h = _probe_wh(video_path)
    rw, rh = ASPECT_RATIOS[ratio]

    # Khung hình đích (canvas) giữ xấp xỉ ĐỘ PHÂN GIẢI của video gốc (không tự ý
    # tăng/giảm chất lượng) - chỉ đổi HÌNH DẠNG khung theo đúng tỉ lệ yêu cầu.
    if (rw / rh) < (src_w / src_h):
        canvas_h = src_h
        canvas_w = _even(canvas_h * rw / rh)
    else:
        canvas_w = src_w
        canvas_h = _even(canvas_w * rh / rw)

    filter_complex: Optional[str] = None

    if mode == "crop":
        # Scale sao cho phủ kín canvas (có thể tràn ra ngoài 1 chiều), rồi crop bớt phần tràn.
        scale_factor = max(canvas_w / src_w, canvas_h / src_h)
        scaled_w = _even(src_w * scale_factor)
        scaled_h = _even(src_h * scale_factor)
        vf = f"scale={scaled_w}:{scaled_h},crop={canvas_w}:{canvas_h}"
    elif mode == "pad":
        # Scale sao cho vừa lọt trong canvas (không chiều nào tràn ra), rồi pad viền đen cho đủ canvas.
        scale_factor = min(canvas_w / src_w, canvas_h / src_h)
        scaled_w = _even(src_w * scale_factor)
        scaled_h = _even(src_h * scale_factor)
        pad_x = _even((canvas_w - scaled_w) / 2)
        pad_y = _even((canvas_h - scaled_h) / 2)
        vf = f"scale={scaled_w}:{scaled_h},pad={canvas_w}:{canvas_h}:{pad_x}:{pad_y}:color=black"
    elif mode in ("blur_pad", "blur_pad_zoom"):
        # fg = nội dung CHÍNH, giữ nguyên tỉ lệ, đặt giữa khung.
        # zoom_extra: "blur_pad_zoom" phóng to thêm 8% (crop nhẹ 2 mép) cho đầy khung hơn.
        zoom_extra = 1.08 if mode == "blur_pad_zoom" else 1.0
        scale_factor = min(canvas_w / src_w, canvas_h / src_h) * zoom_extra
        scaled_w = _even(src_w * scale_factor)
        scaled_h = _even(src_h * scale_factor)
        # Nếu phóng to (zoom_extra>1) khiến fg tràn ra ngoài canvas, cắt bớt phần tràn
        # (crop nhẹ, tương tự "crop" nhưng chỉ tràn rất ít vì zoom_extra nhỏ).
        fg_crop_w = min(scaled_w, canvas_w)
        fg_crop_h = min(scaled_h, canvas_h)
        pad_x = _even((canvas_w - fg_crop_w) / 2)
        pad_y = _even((canvas_h - fg_crop_h) / 2)
        # bg = chính video gốc, phóng to LẤP ĐẦY canvas (có thể mất mép, không sao vì
        # đây chỉ là NỀN đã làm mờ, không phải nội dung chính) + làm mờ mạnh + tối nhẹ
        # để dải nền không chói/lấn át phần nội dung chính ở giữa.
        filter_complex = (
            f"[0:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,"
            f"crop={canvas_w}:{canvas_h},gblur=sigma=25,eq=brightness=-0.06[bg];"
            f"[0:v]scale={scaled_w}:{scaled_h},crop={fg_crop_w}:{fg_crop_h}[fg];"
            f"[bg][fg]overlay=x={pad_x}:y={pad_y}[outv]"
        )
        vf = None
    else:
        raise ValueError("mode phải là 'crop', 'pad', 'blur_pad' hoặc 'blur_pad_zoom'")

    video_abs = os.path.abspath(video_path)
    out_abs = os.path.abspath(out_path)
    if filter_complex is not None:
        cmd = [
            "ffmpeg", "-y", "-i", video_abs,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "copy",
            out_abs,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", video_abs,
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "copy",
            out_abs,
        ]
    _run(cmd)

    if not os.path.exists(out_abs) or os.path.getsize(out_abs) == 0:
        raise RuntimeError(f"change_aspect_ratio: ffmpeg không tạo ra file output ({out_abs}).")

    if progress_cb:
        progress_cb(1.0, f"Hoàn tất đổi tỉ lệ khung hình sang {ratio}")
    return out_abs


RESOLUTION_PRESETS = {
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "1440p": 1440,
    "4k": 2160,
}


def change_resolution(
    video_path: str,
    out_path: str,
    resolution: str = "1080p",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Đổi độ phân giải video (theo chiều CAO đích, ví dụ '1080p' -> cao 1080px),
    giữ nguyên tỉ lệ khung hình gốc (chiều rộng tự tính, luôn làm tròn số chẵn).
    """
    if resolution not in RESOLUTION_PRESETS:
        raise ValueError(f"Độ phân giải không hỗ trợ: {resolution}. Chọn 1 trong: {list(RESOLUTION_PRESETS)}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, f"Đang đổi độ phân giải sang {resolution}...")

    target_h = RESOLUTION_PRESETS[resolution]
    vf = f"scale=-2:{target_h}"

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_path,
    ]
    _run(cmd)

    if progress_cb:
        progress_cb(1.0, f"Hoàn tất đổi độ phân giải sang {resolution}")
    return out_path


def build_hook_intro_clip(
    video_path: str,
    start_sec: float,
    end_sec: float,
    hook_text: str,
    out_path: str,
    font_size: int = 42,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Cắt 1 đoạn (start_sec..end_sec) từ video ĐÃ XUẤT HOÀN CHỈNH (đã có phụ đề/lồng
    tiếng/watermark - dùng nguyên video cuối cùng để cắt, KHÔNG xử lý lại từ đầu) rồi
    đè thêm 1 dòng chữ "hook" giật tít lớn, căn giữa màn hình, lên TOÀN BỘ đoạn cắt
    này - dùng làm đoạn INTRO mở đầu kiểu "cold open".

    Tự động chọn đúng font hỗ trợ Nhật/Hàn/Trung cho hook_text (xem _pick_font_for_text)
    - tránh lỗi hiện ô vuông (tofu) như phần watermark.
    """
    if progress_cb:
        progress_cb(0.0, f"Đang cắt đoạn intro hook ({start_sec:.1f}s-{end_sec:.1f}s)...")

    duration = max(0.1, end_sec - start_sec)
    text_escaped = (
        hook_text.replace("\\", "\\\\\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")
        .replace("%", "\\%")
    )
    font_path = _pick_font_for_text(hook_text)
    drawtext = (
        f"drawtext=fontfile='{font_path}':text='{text_escaped}':"
        f"fontsize={font_size}:fontcolor=white:borderw=3:bordercolor=black@0.9:"
        f"x=(w-text_w)/2:y=h*0.12:box=1:boxcolor=black@0.35:boxborderw=14"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(max(0.0, start_sec)), "-i", os.path.abspath(video_path),
        "-t", str(duration),
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        os.path.abspath(out_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"Cắt đoạn intro hook thất bại:\n{result.stdout[-1500:]}")

    if progress_cb:
        progress_cb(1.0, "Hoàn tất cắt đoạn intro hook")
    return out_path


def concat_intro_and_main(
    intro_path: str,
    main_path: str,
    out_path: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Ghép nối intro_path + main_path (PHÁT ĐẦY ĐỦ TỪ ĐẦU, không cắt bỏ đoạn đã
    dùng làm intro) thành 1 video output duy nhất. Dùng filter 'concat' (không phải
    concat demuxer) để re-encode đồng bộ, an toàn kể cả khi 2 clip lệch nhẹ codec/
    tham số do được xuất ở 2 lệnh ffmpeg khác nhau."""
    if progress_cb:
        progress_cb(0.0, "Đang ghép đoạn intro vào đầu video...")

    cmd = [
        "ffmpeg", "-y",
        "-i", os.path.abspath(intro_path),
        "-i", os.path.abspath(main_path),
        "-filter_complex", "[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        os.path.abspath(out_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"Ghép intro vào video chính thất bại:\n{result.stdout[-1500:]}")

    if progress_cb:
        progress_cb(1.0, "Hoàn tất ghép intro")
    return out_path


def add_moving_watermark_text(
    video_path: str,
    text: str,
    out_path: str,
    opacity: float = 0.6,
    font_size: int = 28,
    speed: float = 0.5,
    pattern: str = "bounce",   # "bounce" | "zigzag" | "random_jump" | "four_corners"
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Watermark CHỮ TỰ DI CHUYỂN khắp khung hình xuyên suốt video - khó bị
    crop/che mất 1 góc cố định hơn watermark đứng yên. Có 4 kiểu quỹ đạo:

    - "bounce": kiểu logo DVD nảy tường, chạy liên tục mượt mà theo 1 đường
      chéo dội biên (tốc độ ngang/dọc lệch nhau nên đường đi trông ngẫu nhiên,
      không lặp lại theo chu kỳ ngắn).
    - "zigzag": chạy chéo góc-tới-góc rõ rệt hơn (tốc độ ngang/dọc đồng bộ),
      tạo hình chữ V/zigzag rõ nét khi nảy biên.
    - "random_jump": đứng yên 1 chỗ vài giây rồi NHẢY tới vị trí khác (giả lập
      ngẫu nhiên bằng công thức toán, không lặp lại vị trí cũ theo mẫu dễ đoán).
    - "four_corners": nhảy lần lượt qua đúng 4 góc màn hình theo chu kỳ.

    Vị trí xuất phát (và với "bounce"/"zigzag" là cả hướng chạy ban đầu) được
    NGẪU NHIÊN HOÁ mỗi lần gọi hàm - mỗi lần render ra 1 kiểu chạy khác nhau.
    Toàn bộ chuyển động tính bằng biểu thức toán học ngay trong filter
    'drawtext' của ffmpeg (không overlay nhiều lớp), vẫn chỉ encode 1 lượt.

    speed: hệ số tốc độ / tần suất đổi vị trí. Gợi ý: 0.3-0.6 chậm rãi dễ chịu,
    1.0+ nhanh hơn (với random_jump/four_corners, speed cao = đổi vị trí dày hơn).
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    margin = 12

    if pattern == "zigzag":
        phase = random.uniform(0, 500)
        spd = max(4.0, 42.0 * speed)
        # Cùng 1 tốc độ cho x và y (chỉ lệch pha) -> quỹ đạo chéo góc-tới-góc rõ
        # rệt (hình zigzag) thay vì đường lượn "ngẫu nhiên" như bounce.
        x_expr = f"abs(mod((t+{phase:.2f})*{spd:.2f}\\,2*(w-tw))-(w-tw))"
        y_expr = f"abs(mod((t+{phase:.2f}+3)*{spd:.2f}\\,2*(h-th))-(h-th))"

    elif pattern == "random_jump":
        interval = max(0.8, 3.5 / max(0.1, speed))   # tốc độ cao -> đổi vị trí dày hơn
        seed = random.uniform(0, 1000)
        seg = f"floor(t/{interval:.2f})"
        # Nhân với hằng số lệch nhau (không phải bội số của nhau) rồi mod theo đúng
        # khoảng di chuyển được -> vị trí mỗi đoạn trông rời rạc/ngẫu nhiên, không
        # theo mẫu dễ đoán, dù về bản chất vẫn là công thức xác định (deterministic).
        x_expr = f"mod(({seg}+{seed:.1f})*197.31\\,(w-tw))"
        y_expr = f"mod(({seg}+{seed:.1f})*281.77\\,(h-th))"

    elif pattern == "four_corners":
        interval = max(0.8, 3.0 / max(0.1, speed))
        start_offset = random.randint(0, 3)   # góc xuất phát ngẫu nhiên, không luôn bắt đầu từ góc trên-trái
        corner = f"mod(floor(t/{interval:.2f})+{start_offset}\\,4)"
        x_expr = f"if(lt({corner}\\,2)\\,{margin}\\,w-tw-{margin})"
        y_expr = f"if(eq(mod({corner}\\,2)\\,0)\\,{margin}\\,h-th-{margin})"

    else:  # "bounce" (mặc định)
        phase_x = random.uniform(0, 500)
        phase_y = random.uniform(0, 500)
        speed_x = max(4.0, 42.0 * speed)
        speed_y = max(3.0, 29.0 * speed)   # tốc độ dọc khác tốc độ ngang -> đường đi không lặp lại theo chu kỳ ngắn
        x_expr = f"abs(mod((t+{phase_x:.2f})*{speed_x:.2f}\\,2*(w-tw))-(w-tw))"
        y_expr = f"abs(mod((t+{phase_y:.2f})*{speed_y:.2f}\\,2*(h-th))-(h-th))"

    # Escape ký tự đặc biệt trong text theo đúng quy tắc của drawtext filter.
    text_escaped = (
        text.replace("\\", "\\\\\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")   # đổi dấu nháy đơn thành dấu nháy kiểu (an toàn hơn escape 3-4 lớp dễ lỗi)
        .replace("%", "\\%")
    )
    opacity = max(0.05, min(1.0, opacity))
    border_opacity = min(1.0, opacity + 0.2)
    font_path = _pick_font_for_text(text)

    vf = (
        f"drawtext=fontfile='{font_path}':"
        f"text='{text_escaped}':fontsize={font_size}:"
        f"fontcolor=white@{opacity:.2f}:borderw=2:bordercolor=black@{border_opacity:.2f}:"
        f"x='{x_expr}':y='{y_expr}'"
    )

    if progress_cb:
        progress_cb(0.1, "Đang chèn watermark chữ chạy...")

    video_abs = os.path.abspath(video_path)
    out_abs = os.path.abspath(out_path)
    cmd = [
        "ffmpeg", "-y", "-i", video_abs,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out_abs,
    ]
    _run(cmd)

    if not os.path.exists(out_abs) or os.path.getsize(out_abs) == 0:
        raise RuntimeError(f"add_moving_watermark_text: ffmpeg không tạo ra file output ({out_abs}).")

    if progress_cb:
        progress_cb(1.0, "Hoàn tất watermark chữ chạy")
    return out_abs


def probe_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def extend_video_tail(
    video_path: str,
    out_path: str,
    extra_sec: float,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Kéo dài ĐUÔI video thêm `extra_sec` giây bằng cách LẶP LẠI khung hình CUỐI CÙNG
    (freeze frame - hình đứng yên, không có chuyển động) - dùng khi audio lồng tiếng
    (thường do thêm lời kêu gọi hành động ở cuối: "để lại bình luận, bấm theo dõi
    kênh"...) dài hơn thời lượng video gốc còn lại, để KHÔNG cắt mất phần audio đó,
    thay vì ép âm thanh nhét vừa khung giờ có sẵn (mất chữ) hay tăng tốc dồn dập.

    extra_sec <= 0: trả về nguyên video gốc, không xử lý gì (khỏi tốn công re-encode).
    """
    extra_sec = max(0.0, extra_sec or 0.0)
    if extra_sec <= 0.05:
        return video_path

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, f"Đang kéo dài đuôi video thêm {extra_sec:.2f}s (giữ khung hình cuối)...")

    # tpad=stop_mode=clone: lặp lại khung hình CUỐI CÙNG (không phải đen/trắng) trong
    # đúng stop_duration giây. apad: kéo dài track audio GỐC (nếu có) tương ứng, để
    # tránh lệch/khớp khi bước mux sau này còn dùng tới audio gốc (vd trộn nhạc nền).
    cmd = [
        "ffmpeg", "-y", "-i", os.path.abspath(video_path),
        "-vf", f"tpad=stop_mode=clone:stop_duration={extra_sec:.3f}",
        "-af", f"apad=pad_dur={extra_sec:.3f}",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-c:a", "aac",
        os.path.abspath(out_path),
    ]
    _run(cmd)

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"extend_video_tail: ffmpeg không tạo ra file output ({out_path}).")

    if progress_cb:
        progress_cb(1.0, f"Đã kéo dài đuôi video thêm {extra_sec:.2f}s")
    return os.path.abspath(out_path)


def trim_video(
    video_path: str,
    out_path: str,
    trim_start_sec: float = 0.0,
    trim_end_sec: float = 0.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Cắt bớt ĐẦU và/hoặc ĐUÔI video theo số giây tuỳ chỉnh, PHẢI chạy TRƯỚC MỌI
    bước khác (transcribe/dịch/lồng tiếng/phụ đề...) trong pipeline, vì việc cắt
    làm thay đổi timeline gốc - nếu cắt sau khi đã có phụ đề/audio dựa theo
    timestamp cũ, mọi thứ sẽ bị lệch giờ hoàn toàn.

    trim_start_sec: số giây cắt bỏ ở ĐẦU video (0 = không cắt đầu).
    trim_end_sec: số giây cắt bỏ ở ĐUÔI video (0 = không cắt đuôi).
    """
    trim_start_sec = max(0.0, trim_start_sec or 0.0)
    trim_end_sec = max(0.0, trim_end_sec or 0.0)
    if trim_start_sec <= 0.0 and trim_end_sec <= 0.0:
        return video_path  # không cắt gì cả - trả lại nguyên input, khỏi tốn công re-encode

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    total = probe_duration(video_path)
    if total <= 0.0:
        raise RuntimeError(f"trim_video: không đọc được thời lượng video ({video_path}).")

    new_duration = total - trim_start_sec - trim_end_sec
    if new_duration <= 0.5:
        raise ValueError(
            f"trim_video: cắt đầu {trim_start_sec}s + cắt đuôi {trim_end_sec}s "
            f">= thời lượng video ({total:.1f}s) - không còn gì để xuất."
        )

    if progress_cb:
        progress_cb(0.1, f"Đang cắt video (bỏ {trim_start_sec}s đầu, {trim_end_sec}s cuối)...")

    cmd = ["ffmpeg", "-y"]
    if trim_start_sec > 0:
        cmd += ["-ss", f"{trim_start_sec:.3f}"]
    cmd += ["-i", os.path.abspath(video_path), "-t", f"{new_duration:.3f}"]
    # Re-encode (không dùng "-c copy") vì "-ss" đặt SAU "-i" cùng "-c copy" hay cắt
    # sai vị trí lệch tới keyframe gần nhất - re-encode cho vị trí cắt CHÍNH XÁC.
    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-c:a", "aac", os.path.abspath(out_path)]
    _run(cmd)

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"trim_video: ffmpeg không tạo ra file output ({out_path}).")

    if progress_cb:
        progress_cb(1.0, "Hoàn tất cắt video")
    return os.path.abspath(out_path)


def apply_voice_transform(
    audio_path: str,
    out_path: str,
    pitch_semitones: float = 0.0,
    speed: float = 1.0,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Biến đổi giọng đọc ĐÃ TẠO XONG (dub_track): đổi CAO ĐỘ (pitch, tính bằng
    semitone, +/- ví dụ +3 = giọng cao/trẻ hơn, -3 = giọng trầm/già hơn) VÀ/HOẶC
    TỐC ĐỘ ĐỌC (speed, vd 1.15 = đọc nhanh hơn 15%) - dùng filter 'rubberband'
    của ffmpeg, đổi ĐỘC LẬP pitch và tempo (không như atempo thường, đổi tốc độ
    sẽ kéo theo đổi cao độ giọng nghe "chuột rít"/"trầm mo").

    Yêu cầu: bản ffmpeg cài sẵn có bật '--enable-librubberband' (bản ffmpeg-full/
    essentials của gyan.dev đã có sẵn). Nếu build ffmpeg của bạn KHÔNG có
    rubberband, hàm sẽ raise lỗi rõ ràng thay vì âm thầm bỏ qua.
    """
    pitch_semitones = max(-12.0, min(12.0, pitch_semitones or 0.0))
    speed = max(0.5, min(2.0, speed or 1.0))
    if abs(pitch_semitones) < 0.01 and abs(speed - 1.0) < 0.01:
        return audio_path  # không đổi gì - khỏi tốn công re-encode

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if progress_cb:
        progress_cb(0.1, f"Đang biến đổi giọng đọc (pitch={pitch_semitones:+.1f} semitone, tốc độ={speed:.2f}x)...")

    pitch_ratio = 2.0 ** (pitch_semitones / 12.0)
    af = f"rubberband=tempo={speed:.4f}:pitch={pitch_ratio:.4f}"

    cmd = [
        "ffmpeg", "-y", "-i", os.path.abspath(audio_path),
        "-af", af,
        os.path.abspath(out_path),
    ]
    try:
        _run(cmd)
    except RuntimeError as e:
        raise RuntimeError(
            f"apply_voice_transform: ffmpeg lỗi khi biến đổi giọng đọc (có thể bản "
            f"ffmpeg đang dùng KHÔNG có filter 'rubberband' - kiểm tra bằng lệnh "
            f"'ffmpeg -filters | findstr rubberband'): {e}"
        ) from e

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"apply_voice_transform: ffmpeg không tạo ra file output ({out_path}).")

    if progress_cb:
        progress_cb(1.0, "Hoàn tất biến đổi giọng đọc")
    return os.path.abspath(out_path)
