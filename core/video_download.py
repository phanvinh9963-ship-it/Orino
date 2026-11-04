"""
core/video_download.py
Tải video từ LINK BẤT KỲ (YouTube, TikTok, X/Twitter, Instagram, Facebook, Threads, Vimeo, Reddit,
Twitch... và ~1.800 trang khác) bằng thư viện yt-dlp - dùng cho khối "Tải video từ link bất kỳ" ở tab Download.

Ý tưởng lấy từ dự án yoinks (dán link -> chọn chất lượng hoặc chỉ âm thanh mp3 -> tải), viết lại bằng Python
vì app này đã dùng sẵn yt-dlp. Mỗi link chỉ tải 1 video (link danh sách phát -> lấy video đầu tiên).

Không phụ thuộc giao diện: nhận `progress_cb(phần_trăm 0..1, thông_báo)` và `cancel` (threading.Event).
"""
from __future__ import annotations

import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

# ----------------------------------------------------------------------------
# Nhận diện link / nền tảng
# ----------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://[^\s<>\"'“”‘’，。、；;）)\]】]+", re.I)

_PLATFORMS = [
    (("youtube.com", "youtu.be", "music.youtube.com"), "YouTube"),
    (("x.com", "twitter.com"), "X / Twitter"),
    (("instagram.com",), "Instagram"),
    (("threads.net", "threads.com"), "Threads"),
    (("tiktok.com",), "TikTok"),
    (("vimeo.com",), "Vimeo"),
    (("twitch.tv",), "Twitch"),
    (("reddit.com", "redd.it"), "Reddit"),
    (("facebook.com", "fb.watch", "fb.com"), "Facebook"),
    (("bilibili.com", "b23.tv"), "Bilibili"),
    (("dailymotion.com", "dai.ly"), "Dailymotion"),
]
# Douyin / Xiaohongshu đã có khối tải riêng (có cookie + tải cả trang cá nhân) -> khuyên dùng khối đó
_OWN_BLOCK = (("douyin.com", "iesdouyin.com"), ("xiaohongshu.com", "xhslink.com"))


def extract_urls(text: str) -> List[str]:
    """Rút các link http(s) từ đoạn văn bản dán vào (kể cả khi lẫn chữ), bỏ trùng, giữ thứ tự."""
    seen, out = set(), []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,!?:;")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _match(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def detect_platform(url: str) -> str:
    h = _host(url)
    for domains, name in _PLATFORMS:
        if _match(h, domains):
            return name
    return h or "Link"


def is_own_block_site(url: str) -> bool:
    h = _host(url)
    return any(_match(h, d) for d in _OWN_BLOCK)


# ----------------------------------------------------------------------------
# Chất lượng
# ----------------------------------------------------------------------------
QUALITIES = {
    "Tốt nhất": ("video", None),
    "1080p": ("video", 1080),
    "720p": ("video", 720),
    "480p": ("video", 480),
    "360p": ("video", 360),
    "Chỉ âm thanh (mp3)": ("audio", None),
}
DEFAULT_QUALITY = "Tốt nhất"


def build_format_opts(quality: str, has_ffmpeg: bool) -> dict:
    """Tuỳ chọn yt-dlp (format / sort / hậu xử lý) cho mức chất lượng đã chọn."""
    kind, height = QUALITIES.get(quality, QUALITIES[DEFAULT_QUALITY])
    if kind == "audio":
        opts = {"format": "ba/b"}
        if has_ffmpeg:
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}]
        return opts
    if not has_ffmpeg:                                  # không ghép được video + âm thanh rời -> lấy bản gộp sẵn
        cap = f"[height<={height}]" if height else ""
        return {"format": f"b{cap}/b"}
    cap = f"[height<={height}]" if height else ""
    return {
        "format": f"bv*{cap}+ba/b{cap}/b",
        "merge_output_format": "mp4",
        # cùng độ phân giải thì ưu tiên H.264/AAC (mở được ở mọi nơi, kể cả Editor)
        "format_sort": ["res", "vcodec:h264", "acodec:m4a"],
    }


# ----------------------------------------------------------------------------
# Thông báo lỗi dễ hiểu
# ----------------------------------------------------------------------------
def friendly_error(raw: str) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(raw or "")).strip()
    msg = re.sub(r"^ERROR:\s*", "", msg)
    low = msg.lower()
    hint = ""
    if "cookie database" in low or "could not copy" in low or "dpapi" in low or "decrypt" in low or "cookiesfrombrowser" in low:
        hint = ("Không đọc được cookie của trình duyệt (Chrome đang mở/khoá hoặc mã hoá mới). "
                "Hãy ĐÓNG HẲN trình duyệt rồi thử lại, chọn Firefox/Edge, hoặc dùng file cookies.txt.")
    elif "not a bot" in low or "sign in to confirm" in low:
        hint = "Trang yêu cầu đăng nhập để chứng minh không phải bot → chọn mục Cookie (Chrome/Edge/Firefox…) rồi tải lại."
    elif "private" in low or "login" in low or "log in" in low or "cookies" in low or "members-only" in low:
        hint = "Video riêng tư / cần đăng nhập → chọn mục Cookie (trình duyệt đang đăng nhập trang đó) rồi tải lại."
    elif "unsupported url" in low:
        hint = "Link này không được hỗ trợ. Hãy dán đúng link của VIDEO (không phải trang chủ)."
    elif "http error 403" in low or "403" in low and "forbidden" in low:
        hint = "Bị trang chặn (403) dù đã thử nhiều cách. Bấm “Cập nhật yt-dlp”, mở lại app, cài Deno/Node.js (để giải mã YouTube) rồi thử lại."
    elif "player response" in low:
        hint = ("YouTube không trả dữ liệu video. Thường do: mạng/ISP chặn YouTube (thử bật VPN/đổi DNS 1.1.1.1), "
                "thiếu Deno/Node.js, hoặc yt-dlp cũ. Xem dòng “Chi tiết” bên dưới để biết nguyên nhân chính xác.")
    elif "unable to extract" in low or "nsig" in low or "signature" in low:
        hint = "Trang vừa đổi cách phát video. Bấm “Cập nhật yt-dlp” rồi thử lại."
    elif "ffmpeg" in low or "ffprobe" in low:
        hint = "Thiếu ffmpeg để ghép video/âm thanh hoặc đổi sang mp3."
    elif "unavailable" in low or "removed" in low or "not available" in low:
        hint = "Video không còn / bị chặn ở khu vực của bạn."
    elif "urlopen error" in low or "timed out" in low or "getaddrinfo" in low or "connection" in low:
        hint = "Lỗi mạng - kiểm tra kết nối Internet rồi thử lại."
    short = msg.splitlines()[0][:220] if msg else "Lỗi không rõ"
    return f"{short}\n   → {hint}" if hint else short


# ----------------------------------------------------------------------------
# Tải
# ----------------------------------------------------------------------------
@dataclass
class DownloadResult:
    videos: List[str] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    cancelled: bool = False


class _QuietLogger:
    """Không in ra console, nhưng giữ lại các cảnh báo/lỗi gốc của yt-dlp để báo nguyên nhân thật."""

    def __init__(self):
        self.msgs: List[str] = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def _keep(self, msg):
        m = re.sub(r"\x1b\[[0-9;]*m", "", str(msg)).strip()
        m = re.sub(r"; please report this issue on.*$", "", m)
        if m and m not in self.msgs:
            self.msgs.append(m[:240])

    def warning(self, msg):
        self._keep(msg)

    def error(self, msg):
        self._keep(msg)


def _fmt_speed(bps: Optional[float]) -> str:
    if not bps:
        return ""
    return f"{bps / 1048576:.1f} MB/s" if bps >= 1048576 else f"{bps / 1024:.0f} KB/s"


def _fmt_eta(s) -> str:
    if s is None:
        return ""
    s = int(s)
    return f"còn {s // 60}:{s % 60:02d}"


_YT_CLIENT_FALLBACKS = [["tv", "web_safari"], ["android_vr"], ["ios"]]


def _is_cookie_error(low: str) -> bool:
    keys = ("cookie database", "could not copy", "dpapi", "decrypt", "cookiesfrombrowser", "failed to load cookies")
    return any(k in low for k in keys)


def _is_retryable(low: str) -> bool:
    return any(k in low for k in ("403", "forbidden", "sign in to confirm", "not a bot", "po token", "nsig",
                                  "signature", "unable to extract", "requested format is not available",
                                  "unable to download video data", "unable to download webpage"))


def _js_runtimes() -> dict:
    """Bộ chạy JS để yt-dlp giải mã YouTube: ưu tiên deno, không có thì dùng node/bun nếu máy có."""
    out = {}
    for name in ("deno", "node", "bun"):
        if shutil.which(name):
            out[name] = {}
    return out


def download_urls(
    urls: List[str],
    out_dir: str,
    quality: str = DEFAULT_QUALITY,
    ffmpeg_path: Optional[str] = None,
    cookies_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    cancel: Optional[threading.Event] = None,
) -> DownloadResult:
    cancel = cancel or threading.Event()
    say = progress_cb or (lambda p, m: None)
    res = DownloadResult()
    try:
        import yt_dlp
        from yt_dlp.utils import DownloadCancelled
    except Exception:
        res.failed = [(u, "Chưa cài thư viện yt-dlp → chạy: pip install -U yt-dlp") for u in urls]
        return res

    os.makedirs(out_dir, exist_ok=True)
    res.notes.append(f"yt-dlp {getattr(getattr(yt_dlp, 'version', None), '__version__', '?')}"
                     f" · JS runtime: {', '.join(_js_runtimes()) or 'KHÔNG CÓ (nên cài Deno)'}")
    n = max(1, len(urls))
    has_ffmpeg = bool(ffmpeg_path)
    if not has_ffmpeg and QUALITIES.get(quality, ("video",))[0] == "audio":
        res.notes.append("Chưa có ffmpeg nên không đổi sang mp3 được - lưu âm thanh ở định dạng gốc.")
    elif not has_ffmpeg:
        res.notes.append("Chưa có ffmpeg: chỉ tải được bản video đã gộp sẵn (chất lượng có thể thấp hơn).")

    js_rt = _js_runtimes()
    for i, url in enumerate(urls):
        if cancel.is_set():
            res.cancelled = True
            break
        label = detect_platform(url)
        base, span = i / n, 1.0 / n
        state = {"seen": [], "done": False}

        def on_hook(d, base=base, span=span, state=state, label=label):
            if cancel.is_set():
                raise DownloadCancelled("cancelled")
            st = d.get("status")
            if st == "downloading":
                fn = d.get("filename") or ""
                if fn not in state["seen"]:
                    state["seen"].append(fn)
                total_parts = len((d.get("info_dict") or {}).get("requested_formats") or []) or 1
                part = min(len(state["seen"]) - 1, total_parts - 1)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                frac = (got / total) if total else 0.0
                overall = base + span * min(0.97, (part + min(frac, 1.0)) / total_parts)
                eta = d.get("eta") if (frac >= 0.03 and (d.get("eta") or 0) < 86400) else None   # ETA đầu tiên thường sai
                extra = " · ".join(x for x in (_fmt_speed(d.get("speed")), _fmt_eta(eta)) if x)
                tag = f" (phần {part + 1}/{total_parts})" if total_parts > 1 else ""
                say(overall, f"[{label}] Đang tải {frac * 100:.0f}%{tag}" + (f" · {extra}" if extra else ""))

        def on_pp(d, base=base, span=span, label=label):
            if d.get("status") == "started":
                say(base + span * 0.98, f"[{label}] Đang xử lý ({d.get('postprocessor', 'ghép')})…")

        def make_opts(profile, use_browser_cookies, logger):
            opts = {
                "logger": logger,                           # không in gì ra stdout/stderr (app chạy không có console)
                "outtmpl": os.path.join(out_dir, "%(title).90B [%(id)s].%(ext)s"),
                "noplaylist": True, "playlist_items": "1",
                "quiet": True, "no_warnings": True, "noprogress": True,
                "windowsfilenames": True,
                "retries": 5, "fragment_retries": 5, "socket_timeout": 30,
                "progress_hooks": [on_hook], "postprocessor_hooks": [on_pp],
                "remote_components": ["ejs:github"],        # tự tải bộ giải JS của YouTube nếu thiếu
            }
            if js_rt:
                opts["js_runtimes"] = js_rt
            opts.update(build_format_opts(quality, has_ffmpeg))
            if ffmpeg_path:
                opts["ffmpeg_location"] = ffmpeg_path
            if cookies_file and os.path.isfile(cookies_file):
                opts["cookiefile"] = cookies_file           # file cookies.txt: ổn định nhất, ưu tiên hơn cookie trình duyệt
            elif cookies_browser and use_browser_cookies:
                opts["cookiesfrombrowser"] = (cookies_browser,)
            if profile:
                opts["extractor_args"] = {"youtube": {"player_client": profile}}
            return opts

        # Thử lần lượt: mặc định -> các client YouTube khác (né lỗi 403 / yêu cầu PO token)
        profiles = [None] + (_YT_CLIENT_FALLBACKS if label == "YouTube" else [])
        use_browser = True
        first_err, last_err, result_path = "", "", None
        detail: List[str] = []
        say(base, f"[{label}] Đang lấy thông tin video…")
        k = 0
        while k < len(profiles):
            profile = profiles[k]
            qlog = _QuietLogger()
            try:
                with yt_dlp.YoutubeDL(make_opts(profile, use_browser, qlog)) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if info and info.get("_type") == "playlist":
                        res.notes.append(f"{url}: là danh sách phát - chỉ tải video đầu tiên.")
                        entries = [e for e in (info.get("entries") or []) if e]
                        info = entries[0] if entries else None
                    path = None
                    if info:
                        rd = info.get("requested_downloads") or []
                        path = (rd[0].get("filepath") if rd else None) or ydl.prepare_filename(info)
                    if not path or not os.path.isfile(path):
                        raise RuntimeError("Tải xong nhưng không tìm thấy file kết quả.")
                    result_path = path
                    if profile:
                        res.notes.append(f"{url}: tải được nhờ client YouTube “{','.join(profile)}”.")
                    break
            except DownloadCancelled:
                res.cancelled = True
                break
            except Exception as e:                       # lỗi 1 link không làm hỏng các link còn lại
                if cancel.is_set():
                    res.cancelled = True
                    break
                last_err = str(e)
                first_err = first_err or last_err
                detail += [m for m in qlog.msgs if m not in detail]
                low = (last_err + " " + " ".join(qlog.msgs)).lower()
                if use_browser and cookies_browser and not cookies_file and _is_cookie_error(low):
                    use_browser = False                  # không đọc được cookie trình duyệt -> thử lại KHÔNG cookie
                    res.notes.append(f"Không đọc được cookie {cookies_browser} (hãy đóng hẳn trình duyệt hoặc dùng cookies.txt) "
                                     "- đã tự thử lại không dùng cookie.")
                    say(base, f"[{label}] Cookie lỗi, thử lại không dùng cookie…")
                    continue                             # giữ nguyên profile
                if label == "YouTube" and _is_retryable(low) and k + 1 < len(profiles):
                    k += 1
                    say(base, f"[{label}] Bị chặn, thử cách khác ({k}/{len(profiles) - 1})…")
                    continue
                break
        if res.cancelled:
            break
        if result_path:
            res.videos.append(result_path)
            say(base + span, f"[{label}] ✓ {os.path.basename(result_path)}")
        else:
            err = friendly_error(first_err or last_err)
            extra = [d for d in detail if d[:120] not in err][:3]
            if extra:
                err += "\n   Chi tiết: " + " | ".join(extra)
            res.failed.append((url, err))
    return res
