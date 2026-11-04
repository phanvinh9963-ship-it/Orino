# =====================================================
# RENDER BIẾN THỂ (chống trùng nội dung) - FFmpeg Intel Quick Sync
# Đặt file này tại: core/render_variant.py
# Optimized for i3-1115G4 / Intel UHD, tự fallback sang CPU (libx264)
# nếu máy không hỗ trợ QSV.
#
# Adapted từ render.py do người dùng cung cấp - GIỮ NGUYÊN toàn bộ logic
# random hoá màu sắc/zoom/pan/grain/bitrate, chỉ thêm 2 điểm để tích hợp
# gọn vào main.py:
#   1) resolve_ffmpeg_binaries(): tự dò FFMPEG/FFPROBE thay vì hard-code
#      cứng đường dẫn Windows (vẫn ưu tiên đường dẫn QSV cũ nếu có sẵn).
#   2) log_cb: cho phép GUI (main.py) nhận log tiến trình thay vì chỉ print().
# =====================================================

import os
import random
import subprocess
import uuid
import json


# =====================================================
# FFMPEG PATH
# Ưu tiên theo thứ tự:
#   1) Biến môi trường REUP_FFMPEG_QSV / REUP_FFPROBE_QSV (nếu người dùng set)
#   2) Đường dẫn build FFmpeg có Intel Quick Sync cũ (Windows, nếu tồn tại trên máy)
#   3) "ffmpeg" / "ffprobe" lấy từ PATH hệ thống (fallback an toàn nếu chạy máy khác)
# =====================================================

def resolve_ffmpeg_binaries():
    """Tìm ffmpeg và ffprobe.

    Ưu tiên bản đi kèm app (vendor\bin), sau đó mới tới PATH của hệ thống.
    """
    from core.external_tools import find_ffmpeg, find_ffprobe
    ffmpeg_path = os.environ.get("REUP_FFMPEG_QSV") or find_ffmpeg() or "ffmpeg"
    ffprobe_path = os.environ.get("REUP_FFPROBE_QSV") or find_ffprobe() or "ffprobe"
    return ffmpeg_path, ffprobe_path


FFMPEG, FFPROBE = resolve_ffmpeg_binaries()

# Long-form (video ngang / mặc định)
TARGET_W = 1920
TARGET_H = 1080

# =====================================================
# SHORTS CONFIG
# Video dọc 9:16 cho YouTube Shorts
# =====================================================

SHORT_W = 1080
SHORT_H = 1920

# YouTube tính là Shorts nếu <= 60s, để dư an toàn
SHORT_MAX_DURATION = 120

RENDER_TARGETS = {
    "long": (TARGET_W, TARGET_H),
    "short": (SHORT_W, SHORT_H),
}


def _emit(msg: str, log_cb=None):
    """In ra console (như bản gốc) và, nếu có, gửi thêm cho GUI qua log_cb -
    để main.py hiện được tiến trình render biến thể lên ô log thay vì chỉ
    thấy im lặng cho tới khi xong."""
    print(msg)
    if log_cb:
        try:
            log_cb(msg)
        except Exception:
            pass


# =====================================================
# RANDOM ENGINE
# Very small changes - natural looking
# =====================================================

def random_state(account):
    style = account.get("style", {})

    base_sat = style.get("sat_mul", 1.0)
    base_contrast = style.get("contrast_mul", 1.0)
    base_zoom = style.get("zoom_mul", 1.0)
    base_grain = style.get("grain_mul", 2)

    state = {
        # Màu sắc thay đổi rõ hơn
        "saturation": round(base_sat * random.uniform(0.96, 1.06), 3),

        # Tăng giảm độ tương phản
        "contrast": round(base_contrast * random.uniform(0.97, 1.05), 3),

        # Thay đổi vùng sáng tối
        "gamma": round(random.uniform(0.97, 1.03), 3),

        # Rất khó nhận ra bằng mắt
        "brightness": round(random.uniform(-0.015, 0.015), 3),

        # Dịch màu nhẹ (FFmpeg hue dùng radian)
        "hue": round(random.uniform(-0.15, 0.15), 2),

        # Zoom nhẹ, không làm mất bố cục
        "zoom": round(base_zoom * random.uniform(0.97, 1.06), 3),

        # Thêm texture nhẹ
        "grain": max(1, min(5, int(round(base_grain + random.uniform(-1.5, 1.5))))),

        # Âm thanh thay đổi rất nhẹ
        "volume": round(random.uniform(0.995, 1.005), 3),

        # Bitrate ngẫu nhiên
        "bitrate": random.randint(2800, 5000),
    }

    return state


# =====================================================
# GET VIDEO INFORMATION
# =====================================================

def random_temporal():
    return {
        "hue_wave": round(random.uniform(0.02, 0.06), 3),
        "bright_wave": round(random.uniform(0.0005, 0.002), 4),
        "gamma_wave": round(random.uniform(0.001, 0.003), 4),
        "contrast_wave": round(random.uniform(0.001, 0.0025), 4),
        "zoom_wave": round(random.uniform(0.002, 0.006), 4),
        "pan_speed_x": random.randint(1, 3),
        "pan_speed_y": random.randint(1, 3),
        "speed": random.uniform(20, 45),
    }


def get_video_info(video):
    cmd = [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", video]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    if result.returncode != 0:
        raise Exception(
            f"Cannot read video info (ffprobe: {FFPROBE}). Kiểm tra ffprobe đã cài "
            f"và trong PATH, hoặc set biến môi trường REUP_FFPROBE_QSV."
        )

    data = json.loads(result.stdout)

    video_stream = None
    for stream in data["streams"]:
        if stream["codec_type"] == "video":
            video_stream = stream
            break

    if not video_stream:
        raise Exception("No video stream found")

    width = int(video_stream["width"])
    height = int(video_stream["height"])
    duration = float(data.get("format", {}).get("duration", video_stream.get("duration", 0)))

    return {"width": width, "height": height, "duration": duration}


# =====================================================
# CREATE RANDOM OUTPUT NAME
# =====================================================

def create_output_name(mode="long"):
    suffix = "_short" if mode == "short" else ""
    return uuid.uuid4().hex[:20] + suffix + ".mp4"


# =====================================================
# BUILD VIDEO FILTER
# All effects are extremely light
# =====================================================

def build_video_filter(info, state, target_w=TARGET_W, target_h=TARGET_H):
    temporal = random_temporal()

    width = info["width"]
    height = info["height"]

    filters = []

    # Chỉnh hướng video cho khớp target:
    # - Target ngang (long-form): nếu nguồn đang dọc -> xoay lại ngang
    # - Target dọc (Shorts): giữ nguyên, không xoay, phần dư crop ở bước dưới
    target_is_landscape = target_w >= target_h

    if target_is_landscape and height > width:
        filters.append("transpose=2")
        width, height = height, width

    # Zoom nền, có dư khoảng để pan
    base_zoom = max(1.05, state["zoom"])

    # Dynamic Color
    filters.append(
        "eq="
        f"saturation={state['saturation']}:"
        f"contrast='{state['contrast']}+"
        f"{temporal['contrast_wave']}*cos(t/{temporal['speed']})':"
        f"gamma='{state['gamma']}+"
        f"{temporal['gamma_wave']}*sin(t/{temporal['speed']})':"
        f"brightness='{state['brightness']}+"
        f"{temporal['bright_wave']}*sin(t/{temporal['speed']})'"
    )

    # Dynamic Hue
    filters.append(
        "hue="
        f"h='{state['hue']}+"
        f"{temporal['hue_wave']}*sin(t/{temporal['speed']})'"
    )

    # Scale lớn hơn để có khoảng di chuyển
    scale_ratio = max(target_w / width, target_h / height)

    new_w = int(width * scale_ratio * (base_zoom + temporal["zoom_wave"]))
    new_h = int(height * scale_ratio * (base_zoom + temporal["zoom_wave"]))

    # Khoảng pan
    move_x = max(0, new_w - target_w)
    move_y = max(0, new_h - target_h)

    center_x = move_x // 2
    center_y = move_y // 2

    pan_x = min(6, move_x // 4)
    pan_y = min(6, move_y // 4)

    # Dynamic Crop - camera movement nhiều tầng
    filters.append(f"scale={new_w}:{new_h},crop={target_w}:{target_h}:{center_x}:{center_y}")

    # Film grain temporal
    if state["grain"] > 0:
        filters.append(f"noise=alls={state['grain']}:allf=t+u")

    # Giữ texture sắc nét
    filters.append("unsharp=3:3:0.2:3:3:0.0")

    # Intel QuickSync compatible
    filters.append("format=nv12")

    return ",".join(filters)


def random_audio_temporal():
    return {
        "volume_wave": round(random.uniform(0.001, 0.003), 4),
        "eq_gain": round(random.uniform(-0.4, 0.4), 2),
        "eq_freq": random.randint(3000, 9000),
        "stereo": round(random.uniform(0.01, 0.03), 3),
        "delay": random.randint(0, 2),
    }


def build_audio_filter(state):
    audio = []

    audio.append(f"volume={state['volume']}")

    temporal = random_audio_temporal()

    audio.append(
        f"equalizer=f={temporal['eq_freq']}:width_type=h:width=2000:g={temporal['eq_gain']}"
    )

    audio.append(f"stereotools=mlev=1:slev={1 + temporal['stereo']}")

    return ",".join(audio)


def print_state(state, log_cb=None):
    lines = [
        "\n========== RENDER PROFILE ==========",
        f"SATURATION : {state['saturation']}",
        f"CONTRAST   : {state['contrast']}",
        f"GAMMA      : {state['gamma']}",
        f"HUE        : {state['hue']}",
        f"ZOOM       : {state['zoom']}",
        f"GRAIN      : {state['grain']}",
        f"VOLUME     : {state['volume']}",
        f"BITRATE    : {state['bitrate']}k",
        "====================================\n",
    ]
    for line in lines:
        _emit(line, log_cb)


# =====================================================
# BUILD FFMPEG COMMAND - Intel QuickSync H264
# =====================================================

def build_ffmpeg_command(
    input_video, output_video, info, state,
    target_w=TARGET_W, target_h=TARGET_H, start_time=None, duration=None,
):
    video_filter = build_video_filter(info, state, target_w, target_h)
    audio_filter = build_audio_filter(state)

    cmd = [FFMPEG, "-y"]

    # Cắt đoạn (dùng cho Shorts) - -ss đặt trước -i để seek nhanh
    if start_time:
        cmd.extend(["-ss", f"{start_time:.2f}"])

    cmd.extend(["-i", input_video])

    if duration:
        cmd.extend(["-t", f"{duration}"])

    cmd.extend([
        "-vf", video_filter,
        "-af", audio_filter,

        # Intel Quick Sync Encoder
        "-r", "30",
        "-c:v", "h264_qsv",
        "-preset", "veryfast",
        "-global_quality", "24",
        "-b:v", f"{state['bitrate']}k",
        "-profile:v", "high",

        # Audio
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",

        # Metadata cleanup
        "-map_metadata", "-1",
        "-movflags", "+faststart",

        output_video,
    ])

    return cmd


# =====================================================
# RUN FFMPEG
# =====================================================

def run_ffmpeg(cmd, log_cb=None):
    _emit("\n🚀 START FFMPEG RENDER", log_cb)
    _emit(" ".join(cmd), log_cb)

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="ignore",
    )

    while True:
        line = process.stdout.readline()

        if not line and process.poll() is not None:
            break

        if line:
            # Log chi tiết từng dòng ffmpeg CHỈ ra console (không đẩy hết lên
            # GUI để tránh spam ô log) - GUI chỉ nhận các mốc quan trọng qua
            # _emit() ở render_video().
            print(line.strip())

    process.wait()

    if process.returncode != 0:
        raise Exception(f"FFmpeg failed with code {process.returncode}")

    _emit("✅ VIDEO RENDER DONE", log_cb)


# =====================================================
# FALLBACK CPU - nếu Intel QSV lỗi sẽ tự chuyển libx264
# =====================================================

def fallback_cpu_encode(cmd, log_cb=None):
    _emit("\n⚠ Intel QuickSync failed", log_cb)
    _emit("🔄 Switching to CPU x264...", log_cb)

    new_cmd = []
    skip_next = False

    for item in cmd:
        if skip_next:
            skip_next = False
            continue

        if item == "-c:v":
            new_cmd.extend(["-c:v", "libx264"])
            skip_next = True
        elif item == "-preset":
            new_cmd.extend(["-preset", "faster"])
            skip_next = True
        elif item == "-global_quality":
            skip_next = True
            continue
        else:
            new_cmd.append(item)

    run_ffmpeg(new_cmd, log_cb=log_cb)


# =====================================================
# CREATE THUMBNAIL - lấy frame đầu
# =====================================================

def create_thumbnail(video_path, log_cb=None):
    thumb = os.path.splitext(video_path)[0] + ".jpg"

    cmd = [FFMPEG, "-y", "-i", video_path, "-frames:v", "1", "-q:v", "2", thumb]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if os.path.isfile(thumb):
        _emit("✅ THUMBNAIL DONE", log_cb)
        return thumb

    _emit("❌ THUMBNAIL FAILED", log_cb)
    return None


# =====================================================
# MAIN RENDER FUNCTION - Compatible with main.py
# =====================================================

def render_video(
    input_video, account, index, mode="long", log_cb=None,
    target_size=None, crop_short=True,
):
    """
    target_size: (w, h) tuỳ chọn - nếu truyền vào sẽ dùng ĐÚNG kích thước này thay vì
        lấy theo RENDER_TARGETS[mode] (dùng khi muốn giữ nguyên kích thước gốc của
        video, tránh bị "long" ép về 1920x1080 rồi lỡ xoay video dọc thành ngang).
    crop_short: mặc định True (giữ hành vi cũ - mode="short" tự cắt ngẫu nhiên còn
        SHORT_MAX_DURATION giây nếu nguồn dài hơn). Đặt False khi chỉ muốn áp hiệu
        ứng màu/zoom/grain lên TOÀN BỘ video mà KHÔNG được phép cắt bớt thời lượng
        (vd bước "chỉnh sửa nhẹ 1 lần" ở main.py - phải giữ đúng 1:1 với phụ đề).
    """
    if mode not in RENDER_TARGETS:
        raise Exception(f"Unknown render mode: {mode} (chỉ hỗ trợ 'long' hoặc 'short')")

    _emit("\n" + "=" * 60, log_cb)
    _emit(f"START VIDEO {index} [{mode.upper()}]", log_cb)
    _emit("=" * 60, log_cb)

    output_folder = account["output"]
    os.makedirs(output_folder, exist_ok=True)

    output_video = os.path.join(output_folder, create_output_name(mode))

    # random profile
    state = random_state(account)
    print_state(state, log_cb=log_cb)

    # get video info
    info = get_video_info(input_video)
    _emit(
        f"VIDEO INFO: {info['width']} x {info['height']} | duration: {round(info.get('duration', 0), 2)} s",
        log_cb,
    )

    target_w, target_h = target_size if target_size else RENDER_TARGETS[mode]

    start_time = None
    duration = None

    if mode == "short" and crop_short:
        duration = SHORT_MAX_DURATION
        src_duration = info.get("duration", 0)

        if src_duration > SHORT_MAX_DURATION:
            # chọn 1 đoạn ngẫu nhiên trong video để làm short
            max_start = src_duration - SHORT_MAX_DURATION
            start_time = round(random.uniform(0, max_start), 2)
        else:
            # video nguồn ngắn hơn giới hạn short -> lấy hết
            duration = None

        _emit(f"[SHORT CLIP] start={start_time} duration={duration or src_duration}", log_cb)

    cmd = build_ffmpeg_command(
        input_video, output_video, info, state,
        target_w=target_w, target_h=target_h, start_time=start_time, duration=duration,
    )

    # Render
    try:
        run_ffmpeg(cmd, log_cb=log_cb)
    except Exception as e:
        _emit(str(e), log_cb)
        _emit("Trying CPU fallback...", log_cb)
        fallback_cpu_encode(cmd, log_cb=log_cb)
        if not os.path.isfile(output_video):
            raise Exception("CPU fallback failed")

    # Check output
    if not os.path.isfile(output_video):
        raise Exception("Output video missing")

    _emit(f"✅ OUTPUT: {output_video}", log_cb)

    # Thumbnail
    create_thumbnail(output_video, log_cb=log_cb)

    _emit("\n🎉 RENDER COMPLETE", log_cb)

    return output_video
