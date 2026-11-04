"""Quét toàn bộ import của dự án và dựng danh sách thư viện cần cài.

Cách chạy:
    python tools/scan_requirements.py            # in ra danh sách gợi ý
    python tools/scan_requirements.py --write    # ghi vào requirements.txt

Nguồn quét: main.py, core/, douyin_batch/, gemini_fastapi_server/,
gemini_web2api_server/, workers/, TiktokAuto/ (phần Python chạy được).
"""
from __future__ import annotations

import ast
import io
import os
import sys
from importlib import metadata

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCAN_ROOTS = [
    ("main.py", None),
    ("core", None),
    ("douyin_batch", None),
    ("gemini_fastapi_server/app", None),
    ("gemini_fastapi_server/scripts", None),
    ("gemini_web2api_server", None),
    ("workers", None),
]

# Thư mục con không quét (mã ví dụ, test, công cụ dev)
SKIP_SUBDIRS = {
    "__pycache__", "node_modules", ".git", "tests", "test", "examples",
    "example", "docs", "docker", "webapp", "novnc", ".github",
}

LOCAL_PACKAGES = {
    "core", "douyin_batch", "workers", "tools", "auth", "config", "control",
    "storage", "utils", "cli", "server", "app", "api", "scheduler", "webapp",
    "docker", "novnc", "tiktok_uploader",
}

# Tên module -> tên gói trên PyPI (trường hợp importlib.metadata không tìm thấy)
MANUAL_MAP = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "fitz": "PyMuPDF",
    "docx": "python-docx",
    "Crypto": "pycryptodome",
    "attr": "attrs",
    "jwt": "PyJWT",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "google": "google-api-python-client",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "magic": "python-magic",
    "vieneu": "vieneu-tts",
    "edge_tts": "edge-tts",
    "pyttsx3": "pyttsx3",
    "pydub": "pydub",
    "soundfile": "soundfile",
    "sounddevice": "sounddevice",
    "librosa": "librosa",
    "mediapipe": "mediapipe",
    "torch": "torch",
    "torchaudio": "torchaudio",
    "omnivoice": "omnivoice",
    "argostranslate": "argostranslate",
    "faster_whisper": "faster-whisper",
    "gemini_webapi": "gemini-webapi",
    "yt_dlp": "yt-dlp",
    "customtkinter": "customtkinter",
    "ttkbootstrap": "ttkbootstrap",
    "tkinterdnd2": "tkinterdnd2",
    "huggingface_hub": "huggingface-hub",
    "imageio_ffmpeg": "imageio-ffmpeg",
    "aiohttp": "aiohttp",
    "aiofiles": "aiofiles",
    "aiosqlite": "aiosqlite",
    "gmssl": "gmssl",
    "httpx": "httpx",
    "rich": "rich",
    "playwright": "playwright",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "starlette": "starlette",
    "sse_starlette": "sse-starlette",
    "lmdb": "lmdb",
    "loguru": "loguru",
    "moviepy": "moviepy",
    "selenium": "selenium",
    "undetected_chromedriver": "undetected-chromedriver",
    "requests": "requests",
    "numpy": "numpy",
    "PIL": "pillow",
    "aiohttp": "aiohttp",
    "tqdm": "tqdm",
    "psutil": "psutil",
    "cryptography": "cryptography",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "googleapiclient": "google-api-python-client",
    "google_auth_httplib2": "google-auth-httplib2",
    "tkinterdnd2": "tkinterdnd2",
    "pytest": "pytest",
    "pytest_asyncio": "pytest-asyncio",
}


def collect_module_names() -> set[str]:
    found: set[str] = set()
    for rel, _ in SCAN_ROOTS:
        path = os.path.join(BASE_DIR, rel)
        if os.path.isfile(path):
            files = [path]
        elif os.path.isdir(path):
            files = []
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = [d for d in dirnames if d not in SKIP_SUBDIRS]
                for fn in filenames:
                    if fn.endswith(".py"):
                        files.append(os.path.join(dirpath, fn))
        else:
            continue
        for file_path in files:
            try:
                with open(file_path, "r", encoding="utf-8-sig", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        found.add(node.module.split(".")[0])
    return found


def main() -> int:
    modules = collect_module_names()
    stdlib = set(sys.stdlib_module_names)
    third_party = sorted(m for m in modules if m not in stdlib and m not in LOCAL_PACKAGES
                          and not m.startswith("_"))

    # Ánh xạ module -> gói đã cài
    try:
        dist_map = metadata.packages_distributions()
    except Exception:
        dist_map = {}

    rows = []
    for mod in third_party:
        dists = dist_map.get(mod) or []
        pkg = MANUAL_MAP.get(mod)
        if not pkg and dists:
            pkg = dists[0]
        if not pkg:
            pkg = mod
        version = ""
        for candidate in {pkg, mod.replace("_", "-")}:
            try:
                version = metadata.version(candidate)
                pkg = candidate
                break
            except Exception:
                continue
        rows.append((mod, pkg, version))

    print(f"Tìm thấy {len(rows)} thư viện ngoài:\n")
    print(f"{'MODULE':<26} {'GÓI PYPI':<34} PHIÊN BẢN")
    print("-" * 78)
    for mod, pkg, version in rows:
        flag = "" if version else "   <-- CHƯA CÀI (cần kiểm tra)"
        print(f"{mod:<26} {pkg:<34} {version or '-'}{flag}")

    if "--write" in sys.argv:
        out_path = os.path.join(BASE_DIR, "requirements.txt")
        lines = [
            "# ============================================================",
            "#  Reup Studio - danh sách thư viện cần cài để chạy app.",
            "#  Sinh tự động bằng tools/scan_requirements.py --write",
            "#  Phiên bản được ghim (==) theo đúng môi trường đã chạy thử.",
            "# ============================================================",
            "",
        ]
        for mod, pkg, version in rows:
            if version:
                lines.append(f"{pkg}=={version}")
            else:
                lines.append(f"# {pkg}   # chưa cài trong môi trường - kiểm tra trước khi đóng gói")
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"\nĐã ghi {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
