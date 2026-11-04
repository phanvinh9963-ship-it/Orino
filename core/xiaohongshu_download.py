# -*- coding: utf-8 -*-
"""
core/xiaohongshu_download.py
Tải video từ Xiaohongshu (小红书 - "Tiểu Hồng Thư" / thường gọi tắt "RED"/"XHS")
về máy, dùng thư viện yt-dlp - dùng làm nguồn input đầu vào cho pipeline dịch/lồng
tiếng (core/pipeline.py). Cấu trúc, cách dùng, các tham số GIỐNG HỆT
core/douyin_download.py (cùng 1 tác giả, cố tình đồng nhất API để main.py gọi
được cả 2 module qua cùng 1 đoạn code, chỉ khác module import).

HỖ TRỢ CÁC DẠNG LINK:
  - Link 1 bài viết/video (note)  : vd https://www.xiaohongshu.com/explore/{note_id}
                                    hoặc link rút gọn https://xhslink.com/{code}
  - Link trang cá nhân (profile)  : vd https://www.xiaohongshu.com/user/profile/{user_id}

LƯU Ý QUAN TRỌNG (đã rút kinh nghiệm từ core/douyin_download.py):
yt-dlp có hỗ trợ Xiaohongshu (tên extractor nội bộ thường là "XiaoHongShu"/"XHS"),
NHƯNG (giống hệt tình huống Douyin) khả năng CAO là yt-dlp CHỈ hỗ trợ tải 1
bài/video ĐƠN LẺ, KHÔNG có chức năng liệt kê/tải HÀNG LOẠT theo trang cá nhân
(không phải bug - đơn giản là tính năng đó có thể chưa từng được cài cho
Xiaohongshu trong yt-dlp). Module này vẫn CỐ THỬ với link trang cá nhân (để sẵn
sàng nếu yt-dlp có hỗ trợ), nhưng nếu báo lỗi "Unsupported URL" y hệt kiểu Douyin
từng gặp, đó là do GIỚI HẠN CỦA CÔNG CỤ chứ không phải lỗi link - lúc đó cần
chuyển sang công cụ khác (vd yêu cầu Claude viết thêm nhánh dùng thư viện chuyên
Xiaohongshu, tương tự cách đã làm với "f2" cho Douyin) thay vì cố sửa link.

CÀI ĐẶT:
    pip install -U yt-dlp

COOKIES (RẤT HAY CẦN với Xiaohongshu - nhiều nội dung chỉ xem được khi đã đăng nhập):
Đăng nhập xiaohongshu.com sẵn trên trình duyệt (Chrome/Edge/Firefox...) rồi truyền
`cookies_from_browser="chrome"` (hoặc "edge", "firefox"...) - yt-dlp sẽ tự đọc
cookie từ đúng trình duyệt đó, không cần xuất file cookie thủ công. Nếu gặp lỗi
đọc cookie (Chrome đang mở khoá file SQLite) - ĐÓNG HẲN trình duyệt đó (kể cả tiến
trình chạy ngầm ở khay hệ thống) rồi thử lại, hoặc dùng cookies_file (export bằng
extension "Get cookies.txt LOCALLY") thay thế.

GIỚI HẠN SỐ LƯỢNG:
Trang cá nhân có thể có RẤT NHIỀU bài - dùng `max_videos` để giới hạn (vd chỉ tải
20 bài mới nhất) tránh tải nhầm hàng trăm bài ngoài ý muốn.

ĐẠO ĐỨC / PHÁP LÝ:
Chỉ tải video mà bạn có quyền sử dụng (video của chính bạn, hoặc đã được phép rõ
ràng từ chủ sở hữu) để dịch/lồng tiếng lại. Tôn trọng bản quyền và điều khoản sử
dụng của Xiaohongshu.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class DownloadedVideo:
    url: str            # link gốc của video/bài viết này trên Xiaohongshu
    file_path: str       # đường dẫn file .mp4 đã tải về
    title: str = ""


@dataclass
class XiaohongshuDownloadResult:
    videos: List[DownloadedVideo] = field(default_factory=list)
    failed: List[tuple] = field(default_factory=list)   # (url, lý do lỗi cụ thể) - hiển thị thẳng cho người dùng, không giấu lý do


def _is_probably_profile_link(url: str) -> bool:
    """Nhận biết sơ bộ link là trang cá nhân (nhiều bài) hay 1 bài lẻ - chỉ để hiển thị log rõ hơn,
    KHÔNG ảnh hưởng tới việc tải (yt-dlp tự xử lý, hoặc báo lỗi rõ nếu không hỗ trợ - xem ghi chú ở đầu file)."""
    return "/user/profile/" in url or "/user/" in url


def _normalize_xiaohongshu_url(url: str, progress_cb: Optional[Callable[[float, str], None]] = None) -> str:
    """
    Link rút gọn (xhslink.com/{code}) cần được "đi trước" (resolve redirect) để lấy
    URL đầy đủ dạng xiaohongshu.com/... trước khi đưa cho yt-dlp - y hệt lý do đã
    xử lý với v.douyin.com ở core/douyin_download.py (link rút gọn đôi khi chuyển
    hướng tới dạng URL mà yt-dlp không nhận diện được nếu để nguyên).

    Không resolve được (mất mạng, timeout...) thì trả về URL gốc, để yt-dlp tự thử
    xử lý bình thường (không làm hỏng luồng cũ).
    """
    if "xhslink.com" not in url:
        return url  # đã là link đầy đủ xiaohongshu.com/... - không cần resolve

    try:
        import requests
        resp = requests.head(url, allow_redirects=True, timeout=10)
        final_url = resp.url or url
    except Exception:
        try:
            import requests
            resp = requests.get(url, allow_redirects=True, timeout=10, stream=True)
            final_url = resp.url or url
            resp.close()
        except Exception:
            return url  # không resolve được -> để yt-dlp tự thử với URL gốc

    if progress_cb and final_url != url:
        progress_cb(0.0, f"Link rút gọn đã resolve thành: {final_url}")
    return final_url


def download_from_xiaohongshu(
    urls: List[str],
    out_dir: str,
    max_videos: Optional[int] = 20,
    cookies_from_browser: Optional[str] = None,   # "chrome" | "edge" | "firefox" | "brave" | "opera" | "vivaldi" | "safari"
    cookies_file: Optional[str] = None,             # đường dẫn file cookies.txt (netscape format), thay thế cho cookies_from_browser
    filename_template: str = "%(uploader)s - %(title).80s [%(id)s].%(ext)s",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> XiaohongshuDownloadResult:
    """
    Tải về `out_dir` toàn bộ video ứng với danh sách `urls` (mỗi phần tử có thể là
    link 1 bài/video HOẶC link trang cá nhân - xem LƯU Ý QUAN TRỌNG ở đầu file về
    giới hạn hỗ trợ trang cá nhân của yt-dlp với Xiaohongshu).

    max_videos: giới hạn số video TẢI MỚI cho MỖI link trang cá nhân (không áp
    dụng cho link 1 bài lẻ). None = không giới hạn (cẩn thận nếu trang có hàng
    trăm bài).

    Trả về XiaohongshuDownloadResult gồm danh sách video đã tải thành công (kèm
    đường dẫn file cụ thể) và danh sách url lỗi (nếu có) - KHÔNG raise lỗi giữa
    chừng để 1 video lỗi không làm hỏng cả lượt tải hàng loạt.
    """
    try:
        import yt_dlp
    except ImportError as e:
        raise ImportError(
            "Cần cài đặt: pip install -U yt-dlp để dùng tính năng tải video từ Xiaohongshu."
        ) from e

    if not urls:
        raise ValueError("Chưa có link Xiaohongshu nào để tải.")

    os.makedirs(out_dir, exist_ok=True)
    result = XiaohongshuDownloadResult()

    total_urls = max(1, len(urls))
    for url_i, url in enumerate(urls, start=1):
        url = url.strip()
        if not url:
            continue

        kind = "trang cá nhân (nhiều bài)" if _is_probably_profile_link(url) else "bài/video lẻ"
        if progress_cb:
            progress_cb((url_i - 1) / total_urls, f"Đang xử lý link {url_i}/{total_urls} ({kind})...")

        url = _normalize_xiaohongshu_url(url, progress_cb)
        kind = "trang cá nhân (nhiều bài)" if _is_probably_profile_link(url) else "bài/video lẻ"

        downloaded_this_url: List[DownloadedVideo] = []
        captured_messages: List[str] = []  # lưu lại lỗi/cảnh báo THẬT từ yt-dlp (xem core/douyin_download.py
        # để biết lý do cần cái này - tránh chỉ báo chung chung không rõ nguyên nhân).

        class _CaptureLogger:
            def debug(self, msg):
                pass

            def info(self, msg):
                pass

            def warning(self, msg):
                captured_messages.append(str(msg))

            def error(self, msg):
                captured_messages.append(str(msg))

        def _hook(d, _url=url):
            if d.get("status") == "downloading":
                fn = os.path.basename(d.get("filename", ""))
                pct_str = d.get("_percent_str", "").strip()
                if progress_cb:
                    base = (url_i - 1) / total_urls
                    span = 1.0 / total_urls
                    progress_cb(base + span * 0.5, f"Đang tải: {fn} ({pct_str})")
            elif d.get("status") == "finished":
                fp = d.get("filename", "")
                if fp and os.path.exists(fp):
                    downloaded_this_url.append(DownloadedVideo(url=_url, file_path=fp))

        ydl_opts = {
            "outtmpl": os.path.join(out_dir, filename_template),
            "format": "bv*+ba/b",   # ưu tiên video+audio tốt nhất, fallback file gộp sẵn nếu source không tách track
            "merge_output_format": "mp4",
            "progress_hooks": [_hook],
            "ignoreerrors": True,     # 1 bài lỗi trong playlist không dừng cả lượt tải
            "noplaylist": False,      # cho phép tải cả playlist (trang cá nhân) NẾU yt-dlp hỗ trợ
            "quiet": True,
            "no_warnings": True,
            "logger": _CaptureLogger(),
        }
        if max_videos is not None:
            ydl_opts["playlistend"] = max_videos   # chỉ áp dụng khi url là playlist/trang cá nhân
        if cookies_from_browser:
            ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)
        elif cookies_file:
            ydl_opts["cookiefile"] = cookies_file

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            reason = str(e).strip() or type(e).__name__
            reason_lower = reason.lower()
            is_cookie_lock_error = "cookie" in reason_lower and (
                "could not copy" in reason_lower
                or "permission" in reason_lower
                or "being used" in reason_lower
                or "locked" in reason_lower
            )
            if is_cookie_lock_error and (cookies_from_browser or cookies_file):
                if progress_cb:
                    progress_cb(url_i / total_urls, "⚠ Lỗi đọc cookie trình duyệt - đang thử lại KHÔNG dùng cookie...")
                retry_opts = dict(ydl_opts)
                retry_opts.pop("cookiesfrombrowser", None)
                retry_opts.pop("cookiefile", None)
                try:
                    with yt_dlp.YoutubeDL(retry_opts) as ydl:
                        ydl.download([url])
                    reason = None
                except Exception as e2:
                    reason = str(e2).strip() or type(e2).__name__
                    is_cookie_lock_error = False

            if reason is None:
                pass
            else:
                if is_cookie_lock_error:
                    reason += (
                        "\n   -> Đã tự thử lại không dùng cookie nhưng vẫn cần đăng nhập. Cách sửa lỗi đọc cookie Chrome: "
                        "(1) TẮT HẲN trình duyệt (kể cả icon chạy ngầm ở khay hệ thống, không chỉ đóng cửa sổ), "
                        "rồi tải lại - HOẶC (2) đổi 'Lấy cookie từ trình duyệt' sang trình duyệt khác bạn không "
                        "đang mở (vd 'edge' hoặc 'firefox') - HOẶC (3) export cookies.txt thủ công bằng extension "
                        "'Get cookies.txt LOCALLY' rồi trỏ vào file đó."
                    )
                elif "unsupported url" in reason_lower and _is_probably_profile_link(url):
                    reason += (
                        "\n   -> Đây là link TRANG CÁ NHÂN. yt-dlp có thể KHÔNG hỗ trợ liệt kê hàng loạt bài viết "
                        "của Xiaohongshu (giống tình huống từng gặp với trang cá nhân Douyin) - không phải lỗi link "
                        "sai, mà là giới hạn của công cụ. Thử tải từng link BÀI VIẾT LẺ thay vì link trang cá nhân, "
                        "hoặc báo lại để xem xét dùng công cụ chuyên Xiaohongshu khác."
                    )
                result.failed.append((url, reason))
                if progress_cb:
                    progress_cb(url_i / total_urls, f"✕ Lỗi khi tải link {url_i}/{total_urls}: {reason}")
                continue

        if not downloaded_this_url:
            if captured_messages:
                reason = "Không tải được bài nào - yt-dlp báo: " + " | ".join(captured_messages[-3:])
            else:
                reason = "Không tải được bài nào (có thể nội dung riêng tư/bị giới hạn - thử bật cookie từ trình duyệt)"
            result.failed.append((url, reason))
            if progress_cb:
                progress_cb(url_i / total_urls, f"✕ Link {url_i}/{total_urls}: {reason}")
        else:
            result.videos.extend(downloaded_this_url)
            if progress_cb:
                progress_cb(url_i / total_urls, f"✓ Link {url_i}/{total_urls}: tải xong {len(downloaded_this_url)} bài")

    if progress_cb:
        progress_cb(1.0, f"Hoàn tất: {len(result.videos)} video thành công, {len(result.failed)} link lỗi")

    return result


_URL_RE = re.compile(r"https?://[^\s,，、（）()\[\]'\"]+")


def parse_urls_textbox(raw_text: str) -> List[str]:
    """
    Tách các link Xiaohongshu THẬT từ nội dung người dùng dán vào ô textbox - cùng
    logic với core/douyin_download.py:parse_urls_textbox (xem ghi chú ở đó để biết
    lý do cần regex thay vì split thường: app Xiaohongshu khi "Chia sẻ" cũng copy
    ra cả câu kèm link + chữ Trung dính liền, dấu phẩy toàn-độ-rộng "，" làm hỏng
    cách tách kiểu cũ).
    """
    if not raw_text:
        return []
    urls: List[str] = []
    seen = set()
    for m in _URL_RE.findall(raw_text):
        u = m.rstrip(".,;:!?？！。、」（）\"')]}")
        if "xiaohongshu.com" not in u and "xhslink.com" not in u:
            continue   # không phải link Xiaohongshu -> bỏ qua thay vì coi là lỗi
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls
