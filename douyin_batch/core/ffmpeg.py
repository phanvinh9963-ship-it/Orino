# ============================================================
#  Tìm đường dẫn tới chương trình ffmpeg đã đóng gói kèm app.
#
#  Tệp này được đưa vào Reup Studio từ bộ tải Douyin
#  (douyin-downloader 2.0.0).
# ============================================================
"""Resolve the ffmpeg binary bundled with the packaged sidecar."""

from __future__ import annotations

import os
import shutil


def resolve_ffmpeg_path(*, fallback_to_path: bool = True) -> str:
    """Tìm ffmpeg: ưu tiên bản đi kèm app (vendor\bin), rồi tới imageio-ffmpeg."""
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
