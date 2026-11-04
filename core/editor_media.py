"""
core/editor_media.py
Lớp xử lý media cho Editor: đo thông tin, proxy xem trước, waveform, thumbnail,
đọc khung hình, trộn âm thanh xem trước và XUẤT video bằng ffmpeg.

Chỉ cần ffmpeg (PATH, biến môi trường REUP_FFMPEG, hoặc imageio-ffmpeg đã có trong
requirements) + `av` (PyAV) + Pillow + numpy. Không cần ffprobe.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Callable, Dict, List, Optional, Tuple

from core.editor_model import Project, Clip

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # Windows: không nháy cửa sổ console
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
_FF: Optional[str] = None


def ffmpeg_exe() -> str:
    """Đường dẫn ffmpeg đang dùng (ưu tiên bản đi kèm trong vendor\bin)."""
    global _FF
    if _FF:
        return _FF
    from core.external_tools import find_ffmpeg
    _FF = find_ffmpeg() or "ffmpeg"
    return _FF


def _run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, creationflags=_NOWIN, **kw)


# ----------------------------------------------------------------------------
# Đo thông tin file
# ----------------------------------------------------------------------------
def probe(path: str) -> dict:
    """{duration, w, h, fps, has_audio, has_video, still}. Ném RuntimeError nếu không đọc được."""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        from PIL import Image
        with Image.open(path) as im:
            return dict(duration=0.0, w=im.width, h=im.height, fps=30.0,
                        has_audio=False, has_video=True, still=True)
    r = _run([ffmpeg_exe(), "-hide_banner", "-i", path])
    err = r.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)", err)
    if not m:
        raise RuntimeError(f"Không đọc được file media: {os.path.basename(path)}")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    has_video = bool(re.search(r"Stream #\S+.*?: Video:", err)) and "attached pic" not in err
    has_audio = bool(re.search(r"Stream #\S+.*?: Audio:", err))
    w = h = 0
    fps = 30.0
    vm = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", err)
    if vm:
        w, h = int(vm.group(1)), int(vm.group(2))
        fm = re.search(r"([\d.]+) fps", err)
        if fm:
            fps = float(fm.group(1))
        rot = re.search(r"rotation of (-?[\d.]+) degrees", err)
        if rot and int(round(abs(float(rot.group(1))))) % 180 == 90:
            w, h = h, w
    return dict(duration=dur, w=w, h=h, fps=fps, has_audio=has_audio, has_video=has_video, still=False)


# ----------------------------------------------------------------------------
# Proxy (bản xem trước nhẹ, seek cực nhanh)
# ----------------------------------------------------------------------------
def cache_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "rp_editor_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _key(path: str) -> str:
    st = os.stat(path)
    return hashlib.sha1(f"{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:16]


def proxy_path(src: str) -> str:
    return os.path.join(cache_dir(), f"{_key(src)}_proxy.mp4")


def make_proxy(src: str, height: int = 480) -> Optional[str]:
    dst = proxy_path(src)
    if os.path.isfile(dst) and os.path.getsize(dst) > 0:
        return dst
    tmp = dst + ".part.mp4"
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", src,
           "-vf", f"scale=-2:'min({height},ih)'", "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "30", "-g", "8", "-keyint_min", "8", "-pix_fmt", "yuv420p",
           "-an", "-sn", "-dn", "-movflags", "+faststart", tmp]
    r = _run(cmd)
    if r.returncode == 0 and os.path.isfile(tmp):
        os.replace(tmp, dst)
        return dst
    try:
        os.remove(tmp)
    except OSError:
        pass
    return None


# ----------------------------------------------------------------------------
# Waveform
# ----------------------------------------------------------------------------
WAVE_PER_SEC = 25


def waveform(path: str):
    """Mảng numpy (0..1), WAVE_PER_SEC phần tử / giây - dùng để vẽ sóng âm trên timeline."""
    import numpy as np
    sr = 4000
    r = _run([ffmpeg_exe(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr),
              "-f", "s16le", "-"])
    a = np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768.0
    n = sr // WAVE_PER_SEC
    a = a[: len(a) // n * n].reshape(-1, n)
    if a.size == 0:
        return np.zeros(1, dtype=np.float32)
    peaks = np.abs(a).max(axis=1)
    ref = max(0.08, float(np.percentile(peaks, 99)))
    return np.minimum(1.0, peaks / ref)


# ----------------------------------------------------------------------------
# Đọc khung hình (PyAV)
# ----------------------------------------------------------------------------
class FrameReader:
    """Đọc khung hình theo thời gian. Khi phát liên tục thì giải mã tuần tự (không seek);
    chỉ seek khi nhảy/tua. Dùng trên 1 luồng duy nhất."""

    def __init__(self, path: str):
        import av
        self.c = av.open(path)
        self.s = self.c.streams.video[0]
        try:
            self.s.thread_type = "AUTO"
        except Exception:
            pass
        self.tb = float(self.s.time_base)
        self.t0 = float(self.s.start_time * self.tb) if self.s.start_time is not None else 0.0
        self.w, self.h = self.s.codec_context.width, self.s.codec_context.height
        self.it = None
        self.cur = self.pend = None
        self.cur_t = self.pend_t = -1.0

    def close(self):
        try:
            self.c.close()
        except Exception:
            pass

    def _next(self):
        try:
            f = next(self.it)
        except (StopIteration, Exception):
            return None, None
        pts = f.pts if f.pts is not None else 0
        return f, float(pts * self.tb) - self.t0

    def _seek(self, t: float):
        self.c.seek(int((max(t, 0.0) + self.t0) / self.tb), stream=self.s, backward=True)
        self.it = self.c.decode(self.s)
        prev = None
        while True:
            f, ft = self._next()
            if f is None:
                self.cur, self.cur_t, self.pend = prev[0] if prev else None, prev[1] if prev else -1.0, None
                self.pend_t = -1.0
                return
            if ft > t:
                self.cur, self.cur_t = (prev if prev else (f, ft))
                self.pend, self.pend_t = f, ft
                return
            prev = (f, ft)

    def frame_at(self, t: float, box: Optional[Tuple[int, int]] = None, height: Optional[int] = None):
        """PIL.Image RGB tại thời điểm t (giây, tính từ đầu file). `box` = khung tối đa (w,h),
        giữ nguyên tỉ lệ; hoặc `height` cố định."""
        if self.it is None or self.cur is None or t < self.cur_t - 1e-3 or t > self.cur_t + 1.5:
            self._seek(t)
        else:
            while self.pend is not None and self.pend_t <= t:
                self.cur, self.cur_t = self.pend, self.pend_t
                self.pend, self.pend_t = self._next()
        if self.cur is None:
            return None
        w, h = self.w, self.h
        if box:
            k = min(box[0] / w, box[1] / h)
            w, h = int(w * k), int(h * k)
        elif height:
            w, h = int(w * height / h), height
        w, h = max(2, w // 2 * 2), max(2, h // 2 * 2)
        return self.cur.reformat(width=w, height=h, format="rgb24").to_image()


def make_thumbs(path: str, duration: float, height: int = 52, max_n: int = 300):
    """[(giây, PIL.Image)] đều nhau để lát lên clip video trên timeline."""
    step = max(1.0, duration / max_n)
    out = []
    r = FrameReader(path)
    try:
        t = 0.0
        while t < max(duration, 0.1):
            img = r.frame_at(t, height=height)
            if img is not None:
                out.append((t, img))
            t += step
    finally:
        r.close()
    return out


# ----------------------------------------------------------------------------
# Dựng filter graph (dùng chung cho xem trước âm thanh và xuất video)
# ----------------------------------------------------------------------------
def _atempo(speed: float) -> List[str]:
    if abs(speed - 1.0) < 1e-3:
        return []
    out, s = [], speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    out.append(f"atempo={s:.5f}")
    return out


_A_NORM = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def _amix(labels: List[str], out: str, norm_ok: bool) -> str:
    n = len(labels)
    if n == 1:
        return f"{labels[0]}anull[{out}]"
    tail = ":normalize=0" if norm_ok else f",volume={n}"
    return f"{''.join(labels)}amix=inputs={n}:duration=longest:dropout_transition=0{tail}[{out}]"


DUCK_GAIN = 0.22      # hệ số âm lượng tiếng gốc khi có giọng đọc (~ -13 dB)
_DUCK_RAMP = 0.12     # thời gian giảm/tăng mượt (giây)


def _duck_filters(p: Project) -> str:
    """Chuỗi filter `volume` hạ tiếng gốc đúng lúc có giọng đọc, vào/ra mượt.
    (Không dùng sidechaincompress: ffmpeg dễ bị treo khi xuất cùng lúc video + audio.)"""
    spans = sorted((c.start, c.end) for c in p.lane("voice") if c.vol > 0 and os.path.isfile(c.src))
    merged: List[List[float]] = []
    for a, b in spans:
        if merged and a - merged[-1][1] < 2 * _DUCK_RAMP + 0.1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    r = _DUCK_RAMP
    # `t` có thể là NaN với khung không có timestamp -> khi đó giữ nguyên âm lượng (không tắt tiếng)
    terms = [f"clip(min((t-{a - r:.3f})/{r},({b + r:.3f}-t)/{r}),0,1)" for a, b in merged]
    # các cửa sổ không chồng nhau nên chia nhóm 40 khoảng/filter (giữ biểu thức ngắn) vẫn cho kết quả đúng
    return ",".join(
        f"volume='if(isnan(t),1,1-{1 - DUCK_GAIN:.3f}*({'+'.join(terms[i:i + 40])}))':eval=frame"
        for i in range(0, len(terms), 40)
    )


def build_graph(p: Project, W: int, H: int, fps: float, fit: str, want_video: bool, norm_ok: bool = True):
    """Trả về (inputs, filter_complex, has_video_label). inputs = list các list đối số ffmpeg."""
    ins: List[List[str]] = []
    fs: List[str] = []

    def add_in(args):
        ins.append(args)
        return len(ins) - 1

    vids = p.lane("video")
    seg = []
    for i, c in enumerate(vids):
        if c.still:
            k = add_in(["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{c.dur:.3f}", "-i", c.src])
        else:
            k = add_in(["-ss", f"{c.src_in:.3f}", "-t", f"{c.dur * c.speed:.3f}", "-i", c.src])
        if want_video:
            pts = f"setpts=(PTS-STARTPTS)/{c.speed:.5f}" if abs(c.speed - 1) > 1e-3 else "setpts=PTS-STARTPTS"
            head = f"[{k}:v]{pts},fps={fps:g}"
            if fit == "blur":
                fs.append(f"{head},split=2[bs{i}][fs{i}]")
                fs.append(f"[bs{i}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                          f"scale=trunc({W}/32)*2:trunc({H}/32)*2,boxblur=2:1,scale={W}:{H}[bg{i}]")
                fs.append(f"[fs{i}]scale={W}:{H}:force_original_aspect_ratio=decrease[fg{i}]")
                fs.append(f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v{i}]")
            elif fit == "fill":
                fs.append(f"{head},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                          f"setsar=1,format=yuv420p[v{i}]")
            else:
                fs.append(f"{head},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p[v{i}]")
        if c.has_audio and not c.still and c.vol > 0:
            chain = ",".join([_A_NORM] + _atempo(c.speed) + [f"volume={c.vol:.3f}", "apad",
                                                             f"atrim=0:{c.dur:.3f}", "asetpts=PTS-STARTPTS"])
            fs.append(f"[{k}:a]{chain}[a{i}]")
        else:
            fs.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{c.dur:.3f},asetpts=PTS-STARTPTS[a{i}]")
        seg.append(i)

    if want_video:
        pads = "".join(f"[v{i}][a{i}]" for i in seg)
        fs.append(f"{pads}concat=n={len(seg)}:v=1:a=1[vcat][acat]")
    else:
        pads = "".join(f"[a{i}]" for i in seg)
        fs.append(f"{pads}concat=n={len(seg)}:v=0:a=1[acat]")

    mixes: Dict[str, str] = {}
    for lane in ("voice", "music"):
        labels = []
        for j, c in enumerate(p.lane(lane)):
            if c.vol <= 0 or not os.path.isfile(c.src):
                continue
            k = add_in(["-ss", f"{c.src_in:.3f}", "-t", f"{c.dur * c.speed:.3f}", "-i", c.src])
            ms = int(round(c.start * 1000))
            chain = [_A_NORM] + _atempo(c.speed) + [f"volume={c.vol:.3f}"]
            if ms > 0:
                chain.append(f"adelay={ms}|{ms}")
            fs.append(f"[{k}:a]{','.join(chain)}[{lane[0]}{j}]")
            labels.append(f"[{lane[0]}{j}]")
        if labels:
            fs.append(_amix(labels, f"{lane}mix", norm_ok))
            mixes[lane] = f"[{lane}mix]"

    parts = ["[acat]"]
    if "voice" in mixes:
        duck = _duck_filters(p) if p.duck else ""
        if duck:
            fs.append(f"[acat]{duck}[acatd]")
            parts = ["[acatd]"]
        parts.append(mixes["voice"])
    if "music" in mixes:
        parts.append(mixes["music"])
    fs.append(_amix(parts, "amixed", norm_ok))
    fs.append("[amixed]alimiter=limit=0.97[aout]")
    return ins, ";".join(fs), want_video


# ----------------------------------------------------------------------------
# Phụ đề / chữ -> ASS
# ----------------------------------------------------------------------------
def _ass_rgb(hexstr: str) -> str:
    h = hexstr.lstrip("#")
    h = (h + "000000")[:6]
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(p: Project, W: int, H: int) -> str:
    mx = int(W * 0.05)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Out,{p.font},56,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,5,{mx},{mx},20,1\n"
        f"Style: Box,{p.font},56,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,10,0,5,{mx},{mx},20,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for c in sorted((c for c in p.clips if c.is_caption and c.text.strip()), key=lambda c: c.start):
        fs = max(8, round(c.size * H / 1080))
        bord = max(1, round(fs / 14))
        tags = (f"\\an5\\pos({round(c.x * W)},{round(c.y * H)})\\fs{fs}\\1c{_ass_rgb(c.color)}"
                f"\\3c{_ass_rgb('#000000' if c.box else c.outline)}")
        tags += f"\\bord{round(fs * 0.22)}\\3a&H60&" if c.box else f"\\bord{bord}"
        txt = c.text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},{'Box' if c.box else 'Out'},,0,0,0,,{{{tags}}}{txt}")
    return head + "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Xem trước âm thanh + Xuất video
# ----------------------------------------------------------------------------
def _run_ffmpeg(cmd, cwd=None, total: float = 0.0, progress: Optional[Callable[[float], None]] = None,
                cancel: Optional[threading.Event] = None) -> Tuple[bool, str]:
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=_NOWIN)
    tail: List[str] = []
    for line in proc.stdout:
        line = line.strip()
        if line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                if progress and total > 0:
                    progress(min(1.0, float(line.split("=")[1]) / 1e6 / total))
            except ValueError:
                pass
        elif line and not line.startswith(("bitrate=", "total_size=", "out_time=", "dup_frames=",
                                          "drop_frames=", "speed=", "progress=", "fps=", "stream_",
                                          "frame=")):
            tail.append(line)
            del tail[:-25]
        if cancel is not None and cancel.is_set():
            proc.terminate()
            proc.wait()
            return False, "Đã hủy"
    proc.wait()
    return proc.returncode == 0, "\n".join(tail)


def render_audio_preview(p: Project, out_wav: str, cancel: Optional[threading.Event] = None) -> bool:
    """Trộn toàn bộ âm thanh dự án (tiếng gốc + giọng + nhạc, đã hạ tiếng gốc) -> WAV mono 32kHz."""
    if p.duration <= 0:
        return False
    for norm_ok in (True, False):
        ins, fc, _ = build_graph(p, p.w, p.h, p.fps, "fit", want_video=False, norm_ok=norm_ok)
        cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error"]
        for a in ins:
            cmd += a
        cmd += ["-filter_complex", fc, "-map", "[aout]", "-vn", "-ac", "1", "-ar", "32000",
                "-c:a", "pcm_s16le", "-t", f"{p.duration:.3f}", out_wav]
        ok, msg = _run_ffmpeg(cmd, cancel=cancel)
        if ok or "normalize" not in msg:
            return ok
    return False


ASPECTS = {"Gốc": None, "16:9 (YouTube)": (16, 9), "9:16 (TikTok/Shorts)": (9, 16),
           "1:1 (Vuông)": (1, 1), "4:5 (Feed)": (4, 5)}
QUALITY = {"Cao (CRF 18)": 18, "Chuẩn (CRF 21)": 21, "Nhẹ (CRF 25)": 25}


def output_size(p: Project, aspect: Optional[Tuple[int, int]], short_side: Optional[int]) -> Tuple[int, int]:
    """Kích thước xuất (số chẵn). aspect=None -> giữ tỉ lệ dự án; short_side=None -> giữ độ phân giải.
    Tỉ lệ mới lấy cạnh NGẮN của nguồn làm chuẩn (vd nguồn 1080p: 9:16 -> 1080x1920, 4:5 -> 1080x1350)."""
    if aspect is None:
        w, h = p.w, p.h
    else:
        ar, s = aspect[0] / aspect[1], min(p.w, p.h)
        w, h = (int(s * ar), s) if ar >= 1 else (s, int(s / ar))
    if short_side:
        k = short_side / min(w, h)
        w, h = int(w * k), int(h * k)
    return max(2, w // 2 * 2), max(2, h // 2 * 2)


def export_video(p: Project, out_path: str, size: Tuple[int, int], fit: str = "blur", crf: int = 21,
                 progress: Optional[Callable[[float], None]] = None,
                 cancel: Optional[threading.Event] = None) -> Tuple[bool, str]:
    if p.duration <= 0:
        return False, "Dự án chưa có video."
    W, H = size
    fps = p.fps
    work = tempfile.mkdtemp(prefix="rpedit_")
    try:
        has_caps = any(c.is_caption and c.text.strip() for c in p.clips)
        if has_caps:
            with open(os.path.join(work, "subs.ass"), "w", encoding="utf-8-sig") as f:
                f.write(build_ass(p, W, H))
        msg = ""
        for norm_ok in (True, False):
            ins, fc, _ = build_graph(p, W, H, fps, fit, want_video=True, norm_ok=norm_ok)
            fc += ";[vcat]ass=subs.ass[vout]" if has_caps else ";[vcat]null[vout]"
            cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "warning", "-nostats",
                   "-progress", "pipe:1", "-stats_period", "0.5"]
            for a in ins:
                cmd += a
            cmd += ["-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
                    "-r", f"{fps:g}", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    "-t", f"{p.duration:.3f}", os.path.abspath(out_path)]
            ok, msg = _run_ffmpeg(cmd, cwd=work, total=p.duration, progress=progress, cancel=cancel)
            if ok or "normalize" not in msg:
                return ok, msg
        return False, msg
    finally:
        shutil.rmtree(work, ignore_errors=True)
