"""Dọn thư mục `core/` - chỉ giữ lại đúng các module ứng dụng của Reup Studio.

Lý do: thư mục `core/` trong dự án cũ bị lẫn MỘT BẢN CÀI ĐẶT PYTHON 3.11 đầy đủ
(147 MB: python.exe, DLLs, Lib, Scripts, site-packages...) cùng các BẢN SAO của
module ứng dụng nằm rải trong `core/encodings`, `core/dbm`, `core/xml`...
Những thứ đó không được app dùng tới nhưng lại bị đóng gói vào bản phát hành,
làm gói phình to và gây rối khi PyInstaller quét module.

Cách chạy:  python tools/clean_core_dir.py [--apply]
"""
from __future__ import annotations

import io
import os
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(BASE_DIR, "core")

# Đúng những module ứng dụng cần giữ lại trong `core/`
KEEP_FILES = {
    "__init__.py",
    "audioop.py",
    "blur_detect.py",
    "douyin_download.py",
    "download_card.py",
    "editor_ai.py",
    "editor_audio.py",
    "editor_media.py",
    "editor_model.py",
    "editor_ui.py",
    "export.py",
    "face_speaker_detect.py",
    "gemini_fastapi_server.py",
    "gemini_webapi_client.py",
    "gender_detect.py",
    "history.py",
    "llm_shorten.py",
    "narration_merge.py",
    "omnivoice_tts.py",
    "pipeline.py",
    "render_variant.py",
    "rewrite_srt.py",
    "rewrite_srt_cli.py",
    "speed_adjust.py",
    "text_fit.py",
    "transcribe.py",
    "translate.py",
    "tts.py",
    "ui_helpers.py",
    "video_download.py",
    "vieneu_tts.py",
    "voice_clone.py",
    "voice_sample.py",
    "xiaohongshu_download.py",
    "youtube_upload.py",
}


def main() -> int:
    apply = "--apply" in sys.argv
    if not os.path.isdir(CORE_DIR):
        print(f"Không tìm thấy {CORE_DIR}")
        return 1

    removed_files = 0
    removed_dirs = 0
    freed = 0

    for entry in os.listdir(CORE_DIR):
        path = os.path.join(CORE_DIR, entry)
        if os.path.isdir(path):
            size = 0
            for dirpath, _dirnames, filenames in os.walk(path):
                for fn in filenames:
                    try:
                        size += os.path.getsize(os.path.join(dirpath, fn))
                    except OSError:
                        pass
            freed += size
            removed_dirs += 1
            print(f"  [thư mục] xoá {entry}  ({size / 1048576:.1f} MB)")
            if apply:
                shutil.rmtree(path, ignore_errors=True)
        elif entry not in KEEP_FILES:
            size = os.path.getsize(path)
            freed += size
            removed_files += 1
            print(f"  [tệp]     xoá {entry}")
            if apply:
                try:
                    os.remove(path)
                except OSError:
                    pass

    print(
        f"\nSẽ xoá {removed_files} tệp và {removed_dirs} thư mục "
        f"(~{freed / 1048576:.1f} MB)."
        + ("  ĐÃ XOÁ." if apply else "  Chạy lại với --apply để thực hiện.")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
