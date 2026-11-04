"""Đổi toàn bộ thương hiệu cũ sang "Reup Studio" trong dự án.

Cách chạy:  python tools/rename_brand.py
Sau khi chạy, kiểm tra lại bằng:  python tools/scan_brand.py
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Các cặp thay thế - thứ tự quan trọng (cụ thể trước, chung sau)
REPLACEMENTS: list[tuple[str, str]] = [
    # 1) Biến môi trường
    ("ORINO_FFMPEG_QSV", "REUP_FFMPEG_QSV"),
    ("ORINO_FFPROBE_QSV", "REUP_FFPROBE_QSV"),
    ("ORINO_FFMPEG", "REUP_FFMPEG"),
    # 2) Tên hiệu vật / lớp / tệp
    ("OrinoStudio", "ReupStudio"),
    ("OrinoApp", "ReupStudioApp"),
    ("orino_settings", "reup_studio_settings"),
    ("orino_output", "reup_output"),
    ("orino_autodetect_", "reup_autodetect_"),
    ("Orino.VieNeuTTS", "ReupStudio.VieNeuTTS"),
    (".rp_studio_audio.json", ".reup_studio_audio.json"),
    # 3) Tên hiển thị
    ("Orino Studio", "Reup Studio"),
    ("RP-Studio", "Reup Studio"),
    ("RP Studio", "Reup Studio"),
    ("ORINO", "REUP STUDIO"),
    # 4) Đường dẫn cũ trong tài liệu
    ("orino1-main", "reup-studio"),
    ("orino1", "reup-studio"),
    ("orino", "reup-studio"),
    ("Orino", "Reup Studio"),
]

TEXT_EXT = {
    ".py", ".md", ".txt", ".json", ".spec", ".bat", ".yml", ".yaml",
    ".ini", ".cfg", ".ps1", ".html", ".js", ".ts", ".toml", ".env",
}

SKIP_DIRS = {
    "venv_build", "build", "dist", "__pycache__", "node_modules", ".git",
    "model_cache", "backup", "site-packages", "DLLs", "Lib", "tcl",
    "ensurepip", "idlelib", "turtledemo", "distutils", "lib2to3",
    "python312_embed", "chrome_profile_data", "assets", "docs",
}

# Tệp dữ liệu cá nhân - KHÔNG đổi nội dung, sẽ xoá ở bước dọn thông tin cá nhân
SKIP_FILES = {
    "reup_studio_settings.json",
    "reup_studio_settingsJP.json",
    "tiktok_schedule_queue.json",
    "uploaded_log.json",
    "tiktok_uploaded_log.json",
    "youtube_uploaded_log.json",
    "tiktok_accounts.json",
    "youtube_accounts.json",
}

# Không tự sửa chính mình (tránh làm hỏng bộ quy tắc thay thế)
SELF_FILES = {"rename_brand.py", "scan_brand.py"}


def iter_text_files():
    for dirpath, dirnames, filenames in os.walk(BASE_DIR):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                continue
            if fn in SKIP_FILES or fn in SELF_FILES:
                continue
            yield os.path.join(dirpath, fn)


def main() -> int:
    changed_files = 0
    changed_lines = 0
    for path in iter_text_files():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                original = fh.read()
        except Exception:
            continue
        low = original.lower()
        if "orino" not in low and "rp studio" not in low and "rp-studio" not in low \
                and "rp_studio" not in low:
            continue

        new = original
        for old, repl in REPLACEMENTS:
            new = new.replace(old, repl)

        if new != original:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new)
            n = sum(
                1 for a, b in zip(original.splitlines(), new.splitlines()) if a != b
            )
            changed_files += 1
            changed_lines += n
            print(f"  đã sửa: {os.path.relpath(path, BASE_DIR)}  (~{n} dòng)")

    print(f"\nĐã cập nhật {changed_files} tệp, khoảng {changed_lines} dòng.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
