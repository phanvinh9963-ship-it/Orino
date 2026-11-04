"""Tra cứu phiên bản mới nhất của các gói PyPI cần dùng (để ghim requirements).

Cách chạy:  python tools/pypi_versions.py
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PACKAGES = [
    "opencv-python", "edge-tts", "pyttsx3", "sounddevice", "soundfile",
    "tkinterdnd2", "aiohttp", "aiofiles", "aiosqlite", "gmssl", "playwright",
    "argostranslate", "librosa", "mediapipe", "torch", "vietnormalizer",
    "rich", "imageio", "moviepy", "numpy", "pyinstaller", "loguru", "orjson",
    "pydantic-settings", "lmdb", "gemini-webapi", "yt-dlp", "customtkinter",
    "ttkbootstrap", "faster-whisper", "ctranslate2", "onnxruntime", "av",
    "tokenizers", "huggingface-hub", "pillow", "pydub", "requests", "httpx",
    "PyYAML", "google-api-python-client", "google-auth-oauthlib", "google-auth",
    "google-auth-httplib2", "sse-starlette", "uvicorn", "fastapi", "starlette",
    "python-multipart", "sqlalchemy", "sqlmodel", "gspread", "google-genai",
    "cryptography", "selenium", "undetected-chromedriver", "beautifulsoup4",
    "curl_cffi", "fake-useragent", "prompt_toolkit", "proglog", "wcwidth",
    "win32_setctime", "PySocks", "websocket-client", "websockets", "tqdm",
    "tenacity", "packaging", "filelock", "fsspec", "setuptools", "wheel",
    "six", "python-dateutil", "typing_extensions", "typing-inspection",
    "annotated-types", "pydantic", "pydantic_core", "python-dotenv",
    "flatbuffers", "protobuf", "hf-xet", "httpcore", "h11", "urllib3", "idna",
    "certifi", "charset-normalizer", "cffi", "requests-oauthlib", "oauthlib",
    "pycparser", "pyasn1", "pyasn1_modules", "colorama", "click",
    "darkdetect", "trio", "trio-websocket", "sortedcontainers", "outcome",
    "sniffio", "wsproto", "httptools", "watchfiles", "imageio-ffmpeg",
    "google-auth-httplib2", "soundfile",
]


def main() -> int:
    for pkg in PACKAGES:
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=25) as resp:
                data = json.load(resp)
            print(f"{pkg}=={data['info']['version']}")
        except Exception as exc:
            print(f"# {pkg}: khong lay duoc ({exc})")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
