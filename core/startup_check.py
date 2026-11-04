"""
core/startup_check.py
Kiểm tra (và tự cài nếu được) các thành phần mà Reup Studio cần khi khởi động.

Có 2 nhóm:
  1. Thư viện Python  - kiểm tra bằng cách thử import từng module.
  2. Công cụ ngoài     - ffmpeg / ffprobe (đi kèm trong vendor\\bin).

Khi app chạy từ mã nguồn hoặc từ bản .exe đã đóng gói kèm pip, script sẽ tự
chạy `pip install` cho các gói còn thiếu và báo tiến trình bằng tiếng Việt.
"""
from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Tuple

# Danh sách thư viện bắt buộc: (module để import, tên gói trên PyPI, mô tả tiếng Việt)
REQUIRED_MODULES: List[Tuple[str, str, str]] = [
    ("customtkinter", "customtkinter", "giao diện của app"),
    ("PIL", "pillow", "xử lý ảnh và logo"),
    ("requests", "requests", "gọi API Gemini/Google"),
    ("yaml", "PyYAML", "đọc cấu hình"),
    ("numpy", "numpy", "tính toán số"),
    ("av", "av", "giải mã video"),
    ("pydub", "pydub", "xử lý âm thanh"),
    ("faster_whisper", "faster-whisper", "tách lời thoại"),
    ("ctranslate2", "ctranslate2", "tăng tốc nhận dạng giọng nói"),
    ("yt_dlp", "yt-dlp", "tải video từ nhiều nền tảng"),
    ("httpx", "httpx", "giao tiếp HTTP"),
    ("aiohttp", "aiohttp", "gọi API Douyin"),
    ("aiofiles", "aiofiles", "đọc/ghi tệp bất đồng bộ"),
    ("aiosqlite", "aiosqlite", "lịch sử tải Douyin"),
    ("gmssl", "gmssl", "ký chống bot của Douyin"),
    ("fastapi", "fastapi", "server Gemini FastAPI"),
    ("uvicorn", "uvicorn", "chạy server Gemini FastAPI"),
    ("lmdb", "lmdb", "lưu hội thoại Gemini"),
    ("loguru", "loguru", "ghi log của server Gemini"),
    ("orjson", "orjson", "xử lý JSON nhanh"),
    ("gemini_webapi", "gemini-webapi", "kết nối Gemini bằng cookie web"),
    ("googleapiclient", "google-api-python-client", "đăng video YouTube"),
    ("google_auth_oauthlib", "google-auth-oauthlib", "đăng nhập Google"),
    ("edge_tts", "edge-tts", "giọng đọc online"),
    ("tkinterdnd2", "tkinterdnd2", "kéo-thả file vào app"),
]

# Các thư viện tùy chọn (tính năng nâng cao) - thiếu cũng không ảnh hưởng app
OPTIONAL_MODULES: List[Tuple[str, str, str]] = [
    ("cv2", "opencv-python", "nhận diện người nói theo khuôn mặt"),
    ("librosa", "librosa", "nhận diện giọng nam/nữ"),
    ("mediapipe", "mediapipe", "nhận diện người nói theo khuôn mặt"),
    ("argostranslate", "argostranslate", "dịch offline không cần mạng"),
    ("playwright", "playwright", "dự phòng khi Douyin chặn API"),
]

ProgressCb = Optional[Callable[[str], None]]


def _module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def check_modules(modules: List[Tuple[str, str, str]]) -> Tuple[List[str], Dict[str, str]]:
    """Trả về (danh sách gói còn thiếu, module -> lý do thiếu)."""
    missing_packages: List[str] = []
    reasons: Dict[str, str] = {}
    for module_name, package_name, description in modules:
        if _module_available(module_name):
            continue
        missing_packages.append(package_name)
        reasons[package_name] = description
    return missing_packages, reasons


def check_external_tools() -> List[str]:
    """Trả về danh sách công cụ ngoài còn thiếu (tiếng Việt)."""
    missing = []
    try:
        from core.external_tools import describe_missing
        missing.extend(describe_missing())
    except Exception:
        if not _which("ffmpeg"):
            missing.append("ffmpeg (cần để cắt/ghép/xuất video)")
    return missing


def _which(exe: str) -> Optional[str]:
    import shutil
    return shutil.which(exe)


def pip_available() -> bool:
    """Kiểm tra app có thể tự chạy `pip install` hay không."""
    try:
        import pip  # noqa: F401
        return True
    except Exception:
        return False


def install_packages(packages: List[str], progress_cb: ProgressCb = None) -> bool:
    """Cài các gói còn thiếu bằng pip. Trả về True nếu cài thành công."""
    if not packages:
        return True
    if not pip_available():
        if progress_cb:
            progress_cb("Không có pip trong bản cài - không thể tự cài thư viện.")
        return False

    if progress_cb:
        progress_cb(f"Đang cài {len(packages)} thư viện còn thiếu: {', '.join(packages)}")
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    cmd.extend(packages)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
    except Exception as exc:
        if progress_cb:
            progress_cb(f"Không chạy được pip: {exc}")
        return False

    if proc.returncode == 0:
        if progress_cb:
            progress_cb(f"✓ Đã cài xong: {', '.join(packages)}")
        return True

    tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-3:]
    if progress_cb:
        progress_cb("✕ Không cài được: " + " | ".join(tail))
    return False


def ensure_dependencies(progress_cb: ProgressCb = None, allow_install: bool = True) -> dict:
    """Kiểm tra toàn bộ thành phần cần thiết.

    Trả về dict:
        {"thiếu_thư_viện": [...], "thiếu_công_cụ": [...], "đã_cài": bool,
         "thông_điệp": "..."}
    """
    result = {
        "thiếu_thư_viện": [],
        "thiếu_công_cụ": [],
        "tùy_chọn_thiếu": [],
        "đã_cài": False,
        "thông_điệp": "",
    }

    missing, reasons = check_modules(REQUIRED_MODULES)
    result["thiếu_thư_viện"] = missing
    result["thiếu_công_cụ"] = check_external_tools()

    optional_missing, _ = check_modules(OPTIONAL_MODULES)
    result["tùy_chọn_thiếu"] = optional_missing

    if missing and allow_install:
        if progress_cb:
            progress_cb(
                "Phát hiện thiếu thư viện: " + ", ".join(
                    f"{p} ({reasons.get(p, '')})" for p in missing
                )
            )
        ok = install_packages(missing, progress_cb)
        result["đã_cài"] = ok
        if ok:
            missing_after, _ = check_modules(REQUIRED_MODULES)
            result["thiếu_thư_viện"] = missing_after

    if result["thiếu_thư_viện"]:
        result["thông_điệp"] = (
            "Thiếu thư viện: " + ", ".join(result["thiếu_thư_viện"])
            + ". Một số tính năng sẽ không dùng được."
        )
    elif result["thiếu_công_cụ"]:
        result["thông_điệp"] = (
            "Thiếu công cụ: " + ", ".join(result["thiếu_công_cụ"])
            + ". Video sẽ không xuất được."
        )
    else:
        result["thông_điệp"] = "✓ Mọi thành phần cần thiết đều đã sẵn sàng."

    if progress_cb:
        progress_cb(result["thông_điệp"])
    return result
