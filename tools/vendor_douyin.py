"""Đưa mã nguồn tải Douyin (F:\\douyin) vào Reup Studio thành MỘT MODULE trong app.

Cách chạy:  python tools/vendor_douyin.py

Việc làm:
  1. Sao chép các gói cần dùng (auth, config, control, core, storage, utils, tools)
     từ dự án nguồn vào thư mục `douyin_batch/` của Reup Studio.
  2. Đổi các import tuyệt đối (from core..., from utils...) thành import có
     tiền tố `douyin_batch.` để KHÔNG đụng vào package `core` của Reup Studio.
  3. Thêm phần đầu tài liệu tiếng Việt cho từng tệp.
  4. KHÔNG đưa phần CLI / REST server của dự án nguồn vào - Reup Studio dùng
     trực tiếp lớp trong core/, không cần app riêng.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = r"F:\douyin"
DST_DIR = os.path.join(BASE_DIR, "douyin_batch")

# Các gói sẽ đưa vào (thư mục con của douyin_batch)
PACKAGES = ["auth", "config", "control", "core", "storage", "utils", "tools"]

# Tệp không lấy theo (tài liệu, app riêng, dữ liệu cá nhân)
SKIP_NAMES = {"AGENTS.md", "CLAUDE.md", "README.md", "__pycache__"}
SKIP_SUFFIX = (".md", ".yml", ".yaml", ".json", ".db", ".txt", ".jpg", ".png")

# Tên package cũ -> package mới
IMPORT_REWRITES = [
    (re.compile(r"(?m)^(\s*)from\s+(auth|config|control|core|storage|utils|tools)(\s+import\b)"),
     r"\1from douyin_batch.\2\3"),
    (re.compile(r"(?m)^(\s*)from\s+(auth|config|control|core|storage|utils|tools)\."),
     r"\1from douyin_batch.\2."),
    (re.compile(r"(?m)^(\s*)import\s+(auth|config|control|core|storage|utils|tools)\b"),
     r"\1import douyin_batch.\2"),
]

# Mô tả tiếng Việt cho từng tệp (đặt ở đầu file)
DESCRIPTIONS = {
    "__init__.py": "Gói con của Reup Studio: chứa toàn bộ logic tải video Douyin.",
    "auth/cookie_manager.py": "Quản lý cookie Douyin: nạp, lưu và kiểm tra cookie đăng nhập.",
    "auth/ms_token_manager.py": "Sinh và làm mới msToken - tham số bắt buộc của API Douyin.",
    "auth/__init__.py": "Nhóm mã quản lý xác thực (cookie, token) của Douyin.",
    "config/config_loader.py": "Nạp và ghi đè cấu hình tải (gộp cấu hình mặc định, tệp YAML và biến môi trường).",
    "config/default_config.py": "Bảng cấu hình mặc định của bộ tải Douyin.",
    "config/__init__.py": "Nhóm mã cấu hình của bộ tải Douyin.",
    "control/queue_manager.py": "Hàng đợi chạy song song nhiều tác vụ tải video.",
    "control/rate_limiter.py": "Giới hạn số lượng yêu cầu gửi lên API Douyin mỗi giây.",
    "control/retry_handler.py": "Thử lại yêu cầu khi gặp lỗi mạng, có nghỉ giãy dần.",
    "control/__init__.py": "Nhóm mã điều phối (hàng đợi, giới hạn tốc độ, thử lại).",
    "core/api_client.py": "Gọi API Douyin: lấy danh sách bài đăng, chi tiết video, đường dẫn tải và ký chữ ký chống bot.",
    "core/downloader_base.py": "Lớp nền của các bộ tải: tạo tên file, chống tải trùng, thử lại, tải tệp.",
    "core/downloader_factory.py": "Chọn đúng lớp tải dựa trên loại link (video, trang cá nhân, album, nhạc, livestream).",
    "core/ffmpeg.py": "Tìm đường dẫn tới chương trình ffmpeg đã đóng gói kèm app.",
    "core/metadata.py": "Đọc thông tin bài đăng (tác giả, thời gian đăng, mô tả).",
    "core/url_parser.py": "Nhận dạng loại link Douyin và trích xuất mã bài đăng hoặc mã người dùng.",
    "core/user_downloader.py": "Tải toàn bộ bài đăng của một trang cá nhân Douyin.",
    "core/user_mode_registry.py": "Bảng tra cứu các chế độ tải của trang cá nhân (bài đăng, thích, hợp nhất, nhạc, đã lưu).",
    "core/video_downloader.py": "Tải một video Douyin lẻ.",
    "core/mix_downloader.py": "Tải một hợp nhất (mix) của người dùng.",
    "core/music_downloader.py": "Tải các bài đăng gắn với một bản nhạc.",
    "core/live_downloader.py": "Ghi lại livestream của Douyin.",
    "core/live_replay_downloader.py": "Tải bản ghi lại của các buổi livestream đã kết thúc.",
    "core/transcript_manager.py": "Gửi audio lên dịch vụ chuyển văn bản để tạo phụ đề tự động (tùy chọn).",
    "core/audio_extraction.py": "Tách tiếng khỏi video bằng ffmpeg trước khi gửi đi chuyển văn bản.",
    "core/comments_collector.py": "Thu thập bình luận của một bài đăng (tùy chọn).",
    "core/discovery.py": "Tìm kiếm bài đăng theo từ khóa và lấy bảng xếp hạng nóng của Douyin.",
    "core/retry_executor.py": "Bọc lại quy trình tải để tự thử lại nhiều lần khi lỗi.",
    "core/silent_audio.py": "Thêm hoặc bỏ phần âm thanh yên tĩnh trong video.",
    "core/__init__.py": "Nhóm mã lõi của bộ tải Douyin.",
    "core/user_modes/base_strategy.py": "Lớp nền của các chiến lược thu thập bài đăng theo chế độ.",
    "core/user_modes/post_strategy.py": "Chiến lược thu thập bài đăng của trang cá nhân (có dự phòng qua trình duyệt).",
    "core/user_modes/collect_strategy.py": "Chiến lược lấy nội dung trong mục đã lưu của chính tài khoản đang đăng nhập.",
    "core/user_modes/collect_mix_strategy.py": "Chiến lược lấy hợp nhất trong mục đã lưu.",
    "core/user_modes/like_strategy.py": "Chiến lược lấy các bài đã thích.",
    "core/user_modes/mix_strategy.py": "Chiến lược lấy hợp nhất của người dùng.",
    "core/user_modes/music_strategy.py": "Chiến lược lấy bài đăng gắn với bản nhạc.",
    "core/user_modes/post_time_boundary.py": "Tính mốc thời gian để dừng sớm khi tải theo khoảng ngày.",
    "core/user_modes/__init__.py": "Nhóm các chiến lược tải theo chế độ của trang cá nhân.",
    "storage/database.py": "Lưu lịch sử tải vào cơ sở dữ liệu SQLite (tùy chọn).",
    "storage/file_manager.py": "Tạo thư mục, đặt tên file và tải tệp về máy.",
    "storage/metadata_handler.py": "Ghi tệp JSON metadata của bài đăng.",
    "storage/__init__.py": "Nhóm mã lưu trữ (cơ sở dữ liệu, quản lý tệp).",
    "utils/abogus.py": "Sinh chữ ký chống bot (A-Bogus) cho các yêu cầu API Douyin.",
    "utils/cookie_utils.py": "Kiểm tra và làm sạch tên/giá trị cookie, phân tích chuỗi Cookie header.",
    "utils/helpers.py": "Các hàm phụ trợ nhỏ (định dạng kích thước, đổi mốc thời gian).",
    "utils/logger.py": "Thiết lập logger dùng chung cho bộ tải Douyin.",
    "utils/naming.py": "Sinh tên file và tên thư mục theo mẫu có sẵn của người dùng.",
    "utils/notifier.py": "Gửi thông báo khi tải xong (bark, telegram, webhook).",
    "utils/paid_content.py": "Nhận diện nội dung trả phí của Douyin.",
    "utils/validators.py": "Kiểm tra link hợp lệ và làm sạch tên file cho an toàn.",
    "utils/xbogus.py": "Sinh chữ ký X-Bogus cho các yêu cầu API Douyin.",
    "utils/__init__.py": "Nhóm hàm tiện ích dùng chung.",
    "tools/cookie_fetcher.py": "Lấy cookie Douyin bằng trình duyệt tự động (tùy chọn, cần Playwright).",
    "tools/__init__.py": "Nhóm công cụ phụ trợ.",
}


def describe(rel_key: str) -> str:
    return DESCRIPTIONS.get(rel_key, "Mã nguồn của bộ tải Douyin, đã được tích hợp vào Reup Studio.")


_FFMPEG_OLD = '''def resolve_ffmpeg_path(*, fallback_to_path: bool = True) -> str:
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

_FFMPEG_NEW = '''def resolve_ffmpeg_path(*, fallback_to_path: bool = True) -> str:
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


def _patch_douyin_ffmpeg(path: str) -> None:
    """Cho core/ffmpeg.py của mô-đun Douyin dùng chung trình tìm ffmpeg của app."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if _FFMPEG_NEW in text:
        return
    if _FFMPEG_OLD not in text:
        print("  !! không tìm thấy đoạn ffmpeg cần sửa trong core/ffmpeg.py")
        return
    text = text.replace(_FFMPEG_OLD, _FFMPEG_NEW, 1)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("  đã sửa: douyin_batch/core/ffmpeg.py (dùng chung trình tìm ffmpeg)")


def main() -> int:
    if not os.path.isdir(SRC_DIR):
        print(f"Không tìm thấy dự án nguồn {SRC_DIR}")
        return 1

    if os.path.isdir(DST_DIR):
        shutil.rmtree(DST_DIR)
    os.makedirs(DST_DIR, exist_ok=True)

    copied = 0
    rewritten = 0
    for pkg in PACKAGES:
        src_pkg = os.path.join(SRC_DIR, pkg)
        if not os.path.isdir(src_pkg):
            continue
        for dirpath, dirnames, filenames in os.walk(src_pkg):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
            rel_dir = os.path.relpath(dirpath, SRC_DIR)
            out_dir = os.path.join(DST_DIR, rel_dir)
            os.makedirs(out_dir, exist_ok=True)
            for fn in filenames:
                if fn in SKIP_NAMES or fn.lower().endswith(SKIP_SUFFIX):
                    continue
                if not fn.endswith(".py"):
                    continue
                src_file = os.path.join(dirpath, fn)
                dst_file = os.path.join(out_dir, fn)
                rel_key = os.path.join(rel_dir, fn).replace("\\", "/")
                shutil.copy2(src_file, dst_file)
                copied += 1

                with open(dst_file, "r", encoding="utf-8") as fh:
                    text = fh.read()
                for pattern, repl in IMPORT_REWRITES:
                    text = pattern.sub(repl, text)
                if text != open(src_file, "r", encoding="utf-8").read():
                    rewritten += 1

                # Thêm phần đầu tài liệu tiếng Việt.
                # Dùng dạng KHỐI CHÚ THÍCH (không phải docstring) để không phá vỡ
                # quy tắc "from __future__ phải là câu lệnh đầu tiên" của Python.
                header = (
                    f'# ============================================================\n'
                    f'#  {describe(rel_key)}\n'
                    f'#\n'
                    f'#  Tệp này được đưa vào Reup Studio từ bộ tải Douyin\n'
                    f'#  (douyin-downloader 2.0.0).\n'
                    f'# ============================================================\n'
                )
                with open(dst_file, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(header + text)

                # Sửa riêng core/ffmpeg.py cho khớp với core/external_tools.py
                # của Reup Studio (ưu tiên ffmpeg đi kèm trong vendor\bin).
                if rel_key == "core/ffmpeg.py":
                    _patch_douyin_ffmpeg(dst_file)

    # __init__.py cho gói gốc
    with open(os.path.join(DST_DIR, "__init__.py"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            '# ============================================================\n'
            '#  douyin_batch - Mô-đun tải video Douyin tích hợp vào Reup Studio.\n'
            '#\n'
            '#  Toàn bộ mã nguồn tải Douyin (gọi API chính thức, ký chống bot, tải hàng\n'
            '#  loạt theo trang cá nhân, chống tải trùng, tự thử lại) được đóng gói tại đây\n'
            '#  dưới dạng một mô-đun của app, KHÔNG phải một ứng dụng riêng.\n'
            '#\n'
            '#  Điểm vào dùng từ giao diện: douyin_batch.service.DouyinBatchService\n'
            '# ============================================================\n\n'
            '__all__ = ["service"]\n'
        )

    print(f"Đã sao chép {copied} tệp, trong đó {rewritten} tệp được đổi import.")
    print(f"Vị trí: {DST_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
