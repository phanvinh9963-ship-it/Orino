"""
core/external_tools.py
Tìm các công cụ ngoài Python (ffmpeg, ffprobe, yt-dlp) mà Reup Studio cần dùng.

Thứ tự ưu tiên:
  1) Biến môi trường do người dùng đặt (REUP_FFMPEG / REUP_FFPROBE)
  2) Thư mục vendor\\bin đi kèm app (bản cài đặt có sẵn, không cần cài thêm)
  3) Thư mục ffmpeg\\bin cạnh app (khi chạy từ mã nguồn)
  4) PATH của hệ thống
  5) imageio-ffmpeg (gói Python đi kèm, luôn có sẵn trong bản cài)
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Optional

_FFMPEG_CACHE: Optional[str] = None
_FFPROBE_CACHE: Optional[str] = None


def app_base_dir() -> str:
    """Thư mục gốc của app (nơi đặt main.py hoặc ReupStudio.exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def vendor_bin_dir() -> str:
    """Thư mục công cụ đi kèm app: vendor\\bin."""
    base = app_base_dir()
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = []
    if meipass:
        candidates.append(os.path.join(meipass, "vendor", "bin"))
    candidates.append(os.path.join(base, "vendor", "bin"))
    for path in candidates:
        if os.path.isdir(path):
            return path
    return os.path.join(base, "vendor", "bin")


def find_ffmpeg() -> str:
    """Đường dẫn tới ffmpeg (trả về chuỗi rỗng nếu không tìm thấy)."""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE:
        return _FFMPEG_CACHE

    env = os.environ.get("REUP_FFMPEG", "").strip()
    if env and (os.path.isfile(env) or shutil.which(env)):
        _FFMPEG_CACHE = env
        return _FFMPEG_CACHE

    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    for folder in (vendor_bin_dir(), os.path.join(app_base_dir(), "ffmpeg", "bin")):
        candidate = os.path.join(folder, exe)
        if os.path.isfile(candidate):
            _FFMPEG_CACHE = candidate
            return _FFMPEG_CACHE

    found = shutil.which("ffmpeg")
    if found:
        _FFMPEG_CACHE = found
        return _FFMPEG_CACHE

    try:
        import imageio_ffmpeg
        bundled = str(imageio_ffmpeg.get_ffmpeg_exe() or "")
        if bundled and os.path.isfile(bundled):
            _FFMPEG_CACHE = bundled
            return _FFMPEG_CACHE
    except Exception:
        pass

    _FFMPEG_CACHE = ""
    return _FFMPEG_CACHE


def find_ffprobe() -> str:
    """Đường dẫn tới ffprobe (trả về chuỗi rỗng nếu không tìm thấy)."""
    global _FFPROBE_CACHE
    if _FFPROBE_CACHE is not None:
        return _FFPROBE_CACHE

    env = os.environ.get("REUP_FFPROBE", "").strip()
    if env and (os.path.isfile(env) or shutil.which(env)):
        _FFPROBE_CACHE = env
        return _FFPROBE_CACHE

    exe = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    for folder in (vendor_bin_dir(), os.path.join(app_base_dir(), "ffmpeg", "bin")):
        candidate = os.path.join(folder, exe)
        if os.path.isfile(candidate):
            _FFPROBE_CACHE = candidate
            return _FFPROBE_CACHE

    found = shutil.which("ffprobe")
    _FFPROBE_CACHE = found or ""
    return _FFPROBE_CACHE


def setup_env() -> None:
    """Đặt biến môi trường REUP_FFMPEG / REUP_FFPROBE trỏ tới bản đi kèm app.

    Gọi 1 lần khi app khởi động để mọi module khác (kể cả tiến trình con)
    đều dùng đúng bản ffmpeg của Reup Studio.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        os.environ.setdefault("REUP_FFMPEG", ffmpeg)
    ffprobe = find_ffprobe()
    if ffprobe:
        os.environ.setdefault("REUP_FFPROBE", ffprobe)


def describe_missing() -> list:
    """Trả về danh sách công cụ còn thiếu (tiếng Việt) để hiển thị cho người dùng."""
    missing = []
    if not find_ffmpeg():
        missing.append("ffmpeg (cần để cắt/ghép/xuất video)")
    return missing
