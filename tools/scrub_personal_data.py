"""Dọn sạch thông tin cá nhân khỏi dự án Reup Studio.

Việc làm:
  1. Chuyển các tệp dữ liệu người dùng (cấu hình, log đăng, tài khoản) sang
     thư mục dữ liệu người dùng (%APPDATA%\\ReupStudio) - nơi app đã được sửa
     để đọc/ghi. Nhờ vậy bản phát hành không còn chứa dữ liệu của người dùng.
  2. Xoá các tệp rác sinh ra do gõ nhầm lệnh (et, tatus, backup/).
  3. Xoá log, cache, __pycache__.
  4. Làm sạch các đường dẫn tuyệt đối (F:\\..., C:\\Users\\...) và tên hiệu vật
     còn sót trong tệp cấu hình.
  5. Đưa cookie Douyin về đúng vị trí cố định <app>\\cookies\\douyin_cookies.txt
     và tạo kèm file MẪU trống cho bản phát hành.

Cách chạy:  python tools/scrub_personal_data.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR_NAME = "ReupStudio"


def user_data_dir() -> str:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(appdata, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def remove_path(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        print(f"  xoá thư mục: {os.path.relpath(path, BASE_DIR)}")
    elif os.path.isfile(path):
        os.remove(path)
        print(f"  xoá tệp:     {os.path.relpath(path, BASE_DIR)}")


def move_to_user_data(rel_path: str, new_name: str | None = None, clean_paths: bool = True) -> None:
    """Chuyển 1 tệp sang thư mục dữ liệu người dùng (nếu có), kèm làm sạch
    các đường dẫn tuyệt đối bên trong."""
    src = os.path.join(BASE_DIR, rel_path)
    if not os.path.isfile(src):
        return
    dst_dir = user_data_dir()
    dst = os.path.join(dst_dir, new_name or os.path.basename(rel_path))
    try:
        if clean_paths and dst.lower().endswith(".json"):
            _clean_json_paths(src, dst)
        else:
            shutil.copy2(src, dst)
            os.remove(src)
    except Exception as exc:
        print(f"  !! Không chuyển được {rel_path}: {exc}")
        return
    print(f"  chuyển sang thư mục người dùng: {rel_path} -> {dst}")


def _clean_json_paths(src: str, dst: str) -> None:
    """Làm sạch tệp JSON: bỏ đường dẫn tuyệt đối, bỏ giá trị cá nhân."""
    try:
        with open(src, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        shutil.copy2(src, dst)
        os.remove(src)
        return

    if not isinstance(data, dict):
        shutil.copy2(src, dst)
        os.remove(src)
        return

    ud = user_data_dir()
    app_dir = BASE_DIR

    # Đường dẫn phải trỏ về thư mục app / thư mục dữ liệu người dùng
    data["gemini_web2api_cookie_file"] = ""
    data["douyin_cookies_file_var"] = os.path.join(app_dir, "cookies", "douyin_cookies.txt")
    data["tiktok_tool_dir_var"] = os.path.join(app_dir, "TiktokAuto")
    data["tiktok_python_cmd_var"] = os.path.join(app_dir, "TiktokAuto", "python312_embed", "python.exe")
    data["work_dir_var"] = os.path.join(ud, "output")
    data["youtube_client_secret_var"] = os.path.join(ud, "client_secret.json")

    # Giá trị cá nhân của người dùng
    data["tiktok_new_account_var"] = ""
    data["youtube_active_account_var"] = ""
    data["watermark_text"] = "Reup Studio"
    data["tiktok_schedule_date_var"] = ""
    data["tiktok_schedule_time_var"] = ""
    data["youtube_schedule_date_var"] = ""
    data["youtube_schedule_time_var"] = ""
    data["douyin_max_videos"] = "20"
    data["douyin_cookies_browser"] = "(không dùng)"
    data["gemini_fastapi_api_key"] = ""
    data["cliproxy_api_key"] = ""

    # Dọn mọi giá trị còn sót đường dẫn tuyệt đối
    def _scrub(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = _scrub(v)
            return obj
        if isinstance(obj, list):
            return [_scrub(v) for v in obj]
        if isinstance(obj, str):
            if len(obj) > 3 and (":\\" in obj or ":/" in obj) and not obj.startswith("http"):
                return ""
            if "AIza" in obj:
                return ""
            return obj
        return obj

    data = _scrub(data)

    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.remove(src)


def make_douyin_cookie_sample() -> None:
    """Tạo file MẪU cookie Douyin (trống) kèm hướng dẫn tiếng Việt."""
    cookies_dir = os.path.join(BASE_DIR, "cookies")
    os.makedirs(cookies_dir, exist_ok=True)
    sample = os.path.join(cookies_dir, "douyin_cookies_MAU.txt")
    content = """# ============================================================
#  FILE COOKIE DOUYIN - FILE MẪU (để trống)
#  Reup Studio đọc cookie từ đúng file này:
#      <thư mục app>\\cookies\\douyin_cookies.txt
#  Bạn chỉ cần dán nội dung cookie thật vào file
#  "douyin_cookies.txt" cùng thư mục, không cần sửa gì trong app.
#
#  CÁCH LẤY COOKIE (3 bước):
#    1. Mở trình duyệt Chrome/Edge, đăng nhập tài khoản Douyin của bạn.
#    2. Cài extension "Get cookies.txt LOCALLY" (miễn phí trên Chrome Web Store).
#    3. Bấm vào biểu tượng extension ở góc trên bên phải -> chọn
#       "Export cookies" -> chọn định dạng "Netscape" -> lưu file.
#    4. Đổi tên file vừa lưu thành "douyin_cookies.txt" rồi chép vào
#       thư mục "cookies" cạnh file .exe của Reup Studio.
#
#  LƯU Ý:
#    - Cookie có thời hạn (vài ngày). Hết hạn thì tải trang cá nhân sẽ báo lỗi,
#      chỉ cần lấy cookie mới và thay lại file là được.
#    - Video công khai thường tải được KHÔNG cần cookie; cookie chỉ cần khi
#      tải trang cá nhân hoặc nội dung bị giới hạn.
#    - File này chứa thông tin đăng nhập của bạn - đỪNG chia sẻ cho ai khác.
#
#  Định dạng file (giống hệt file do yt-dlp xuất ra), mỗi dòng một cookie:
#      domain<TAB>include_subdomains<TAB>path<TAB>secure<TAB>expires<TAB>name<TAB>value
#  Ví dụ (dòng mẫu, KHÔNG dùng được - cần cookie thật của bạn):
#      # Netscape HTTP Cookie File
#      .douyin.com\tTRUE\t/\tTRUE\t1792676957\tttwid\tGIÁ_TRỊ_COOKIE_CỦA_BẠN
# ============================================================
"""
    with open(sample, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    print(f"  tạo file mẫu: {os.path.relpath(sample, BASE_DIR)}")


def main() -> int:
    print("== 1. Chuyển dữ liệu người dùng sang thư mục dữ liệu người dùng ==")
    for rel, new_name in [
        ("reup_studio_settings.json", "reup_studio_settings.json"),
        ("client_secret.json", "client_secret.json"),
        ("tiktok_uploaded_log.json", "tiktok_uploaded_log.json"),
        ("youtube_uploaded_log.json", "youtube_uploaded_log.json"),
        ("tiktok_schedule_queue.json", "tiktok_schedule_queue.json"),
        ("tiktok_accounts.json", "tiktok_accounts.json"),
        ("youtube_accounts.json", "youtube_accounts.json"),
        ("youtube_account_emails.json", "youtube_account_emails.json"),
        ("TiktokAuto/uploaded_log.json", "tiktok_auto_uploaded_log.json"),
    ]:
        move_to_user_data(rel, new_name)

    print("\n== 2. Xoá tệp rác, log, cache ==")
    for rel in [
        "et",                      # gõ nhầm "git log > et" - chứa email người dùng
        "tatus",                   # gõ nhầm "git log > tatus"
        "backup",                  # bản sao lưu cũ của main.py/export.py
        "logs",                    # log runtime
        ".vieneu_preset_cache.json",
        "cookies.txt",             # cookie cũ (định dạng Netscape) không còn dùng
        "gemini_fastapi_server/gemini_fastapi_server.log",
        "gemini_fastapi_server/data/lmdb",   # cache LMDB 256 MB - app tự tạo lại
    ]:
        remove_path(os.path.join(BASE_DIR, rel))

    print("\n== 3. Xoá mọi thư mục __pycache__ ==")
    count = 0
    for dirpath, dirnames, _filenames in os.walk(BASE_DIR):
        for d in list(dirnames):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)
                count += 1
    print(f"  đã xoá {count} thư mục __pycache__")

    print("\n== 4. Cookie Douyin: đưa về vị trí cố định + tạo file mẫu ==")
    real = os.path.join(BASE_DIR, "douyin_cookies.txt")
    cookies_dir = os.path.join(BASE_DIR, "cookies")
    os.makedirs(cookies_dir, exist_ok=True)
    target = os.path.join(cookies_dir, "douyin_cookies.txt")
    if os.path.isfile(real):
        if not os.path.isfile(target):
            shutil.copy2(real, target)
            print(f"  copy cookie thật -> {target}")
        else:
            print("  file cookie thật đã tồn tại ở vị trí mới, giữ nguyên")
        os.remove(real)
        print("  xoá bản cũ ở thư mục gốc")
    make_douyin_cookie_sample()

    print("\nHoàn tất dọn thông tin cá nhân.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
