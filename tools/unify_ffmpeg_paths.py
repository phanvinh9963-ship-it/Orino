"""Gộp logic tìm ffmpeg/ffprobe của các module về core/external_tools.py.

Mục tiêu: bỏ các đường dẫn cứng cá nhân (E:\\ffmpeg\\...) và ưu tiên bản
ffmpeg đi kèm trong thư mục vendor\\bin của bản cài Reup Studio.
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- editor_media
EDITOR_MEDIA_OLD = '''def ffmpeg_exe() -> str:
    global _FF
    if _FF:
        return _FF
    env = os.environ.get("REUP_FFMPEG")
    path = env if env and os.path.isfile(env) else shutil.which("ffmpeg")
    if not path:                                   # cùng vị trí mà core/render_variant.py đang dùng
        legacy = r"E:\\ffmpeg\\bin\\ffmpeg.exe"
        path = legacy if os.path.isfile(legacy) else None
    if not path:
        try:
            import imageio_ffmpeg
            path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            path = "ffmpeg"
    _FF = path
    return _FF
'''

EDITOR_MEDIA_NEW = '''def ffmpeg_exe() -> str:
    """Đường dẫn ffmpeg đang dùng (ưu tiên bản đi kèm trong vendor\\bin)."""
    global _FF
    if _FF:
        return _FF
    from core.external_tools import find_ffmpeg
    _FF = find_ffmpeg() or "ffmpeg"
    return _FF
'''

# ---------------------------------------------------------------- render_variant
RENDER_OLD = '''_LEGACY_FFMPEG_WIN = r"E:\\ffmpeg\\bin\\ffmpeg.exe"
_LEGACY_FFPROBE_WIN = r"E:\\ffmpeg\\bin\\ffprobe.exe"


def resolve_ffmpeg_binaries():
    ffmpeg_path = os.environ.get("REUP_FFMPEG_QSV") or (
        _LEGACY_FFMPEG_WIN if os.path.isfile(_LEGACY_FFMPEG_WIN) else "ffmpeg"
    )
    ffprobe_path = os.environ.get("REUP_FFPROBE_QSV") or (
        _LEGACY_FFPROBE_WIN if os.path.isfile(_LEGACY_FFPROBE_WIN) else "ffprobe"
    )
    return ffmpeg_path, ffprobe_path
'''

RENDER_NEW = '''def resolve_ffmpeg_binaries():
    """Tìm ffmpeg và ffprobe.

    Ưu tiên bản đi kèm app (vendor\\bin), sau đó mới tới PATH của hệ thống.
    """
    from core.external_tools import find_ffmpeg, find_ffprobe
    ffmpeg_path = os.environ.get("REUP_FFMPEG_QSV") or find_ffmpeg() or "ffmpeg"
    ffprobe_path = os.environ.get("REUP_FFPROBE_QSV") or find_ffprobe() or "ffprobe"
    return ffmpeg_path, ffprobe_path
'''

# ---------------------------------------------------------------- download_card
DOWNLOAD_CARD_OLD = '''def find_ffmpeg() -> Optional[str]:
    """Đường dẫn ffmpeg THẬT (REUP_FFMPEG / PATH / imageio-ffmpeg) hoặc None - không trả chuỗi suông."""
    try:
        from core import editor_media as M
        p = M.ffmpeg_exe()
        if p and (os.path.isfile(p) or shutil.which(p)):
            return p
    except Exception:
        pass
    return shutil.which("ffmpeg")
'''

DOWNLOAD_CARD_NEW = '''def find_ffmpeg() -> Optional[str]:
    """Đường dẫn ffmpeg THẬT (vendor\\bin / REUP_FFMPEG / PATH / imageio-ffmpeg)."""
    try:
        from core.external_tools import find_ffmpeg as _find
        path = _find()
        if path and (os.path.isfile(path) or shutil.which(path)):
            return path
    except Exception:
        pass
    return shutil.which("ffmpeg")
'''

# ---------------------------------------------------------------- douyin_batch
DOUYIN_FFMPEG_OLD = '''def resolve_ffmpeg_path(*, fallback_to_path: bool = True) -> str:
    """Prefer imageio-ffmpeg's bundled binary, then optionally search PATH."""
    try:
        import imageio_ffmpeg

        bundled = str(imageio_ffmpeg.get_ffmpeg_exe() or "")
    except Exception:
        bundled = ""
    if bundled and os.path.isfile(bundled):
        return bundled
    if fallback_to_path:
        return str(shutil.which("ffmpeg") or "")
    return ""
'''

DOUYIN_FFMPEG_NEW = '''def resolve_ffmpeg_path(*, fallback_to_path: bool = True) -> str:
    """Tìm ffmpeg: ưu tiên bản đi kèm app (vendor\\bin), rồi tới imageio-ffmpeg."""
    try:
        from core.external_tools import find_ffmpeg
        path = find_ffmpeg()
        if path:
            return path
    except Exception:
        pass
    try:
        import imageio_ffmpeg

        bundled = str(imageio_ffmpeg.get_ffmpeg_exe() or "")
    except Exception:
        bundled = ""
    if bundled and os.path.isfile(bundled):
        return bundled
    if fallback_to_path:
        return str(shutil.which("ffmpeg") or "")
    return ""
'''

TARGETS = [
    ("core/editor_media.py", EDITOR_MEDIA_OLD, EDITOR_MEDIA_NEW),
    ("core/render_variant.py", RENDER_OLD, RENDER_NEW),
    ("core/download_card.py", DOWNLOAD_CARD_OLD, DOWNLOAD_CARD_NEW),
    ("douyin_batch/core/ffmpeg.py", DOUYIN_FFMPEG_OLD, DOUYIN_FFMPEG_NEW),
]


def main() -> int:
    for rel, old, new in TARGETS:
        path = os.path.join(BASE_DIR, rel)
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            content = fh.read()
        if new in content:
            print(f"  đã cập nhật rồi: {rel}")
            continue
        if old not in content:
            print(f"  !! không tìm thấy đoạn cần sửa trong {rel}")
            continue
        content = content.replace(old, new, 1)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        print(f"  đã sửa: {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
