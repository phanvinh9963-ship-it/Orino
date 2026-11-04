"""Chuyển các tệp dữ liệu người dùng sang thư mục dữ liệu riêng (%APPDATA%\\ReupStudio).

Lý do: bản phát hành công khai không được chứa dữ liệu cá nhân, và thư mục cài
đặt có thể không ghi được. Cấu hình / key / lịch sử / token nên nằm ở thư mục dữ liệu
người dùng.

Cách chạy:  python tools/relocate_user_data.py
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = os.path.join(BASE_DIR, "main.py")

REPLACEMENTS = [
    ('return os.path.join(get_app_base_dir(), "tiktok_uploaded_log.json")',
     'return os.path.join(get_user_data_dir(), "tiktok_uploaded_log.json")'),
    ('return os.path.join(get_app_base_dir(), "tiktok_schedule_queue.json")',
     'return os.path.join(get_user_data_dir(), "tiktok_schedule_queue.json")'),
    ('return os.path.join(get_app_base_dir(), "tiktok_accounts.json")',
     'return os.path.join(get_user_data_dir(), "tiktok_accounts.json")'),
    ('return os.path.join(get_app_base_dir(), "tiktok_account_emails.json")',
     'return os.path.join(get_user_data_dir(), "tiktok_account_emails.json")'),
    ('return os.path.join(get_app_base_dir(), "youtube_accounts.json")',
     'return os.path.join(get_user_data_dir(), "youtube_accounts.json")'),
    ('return os.path.join(get_app_base_dir(), "youtube_account_emails.json")',
     'return os.path.join(get_user_data_dir(), "youtube_account_emails.json")'),
    ('return os.path.join(get_app_base_dir(), "youtube_uploaded_log.json")',
     'return os.path.join(get_user_data_dir(), "youtube_uploaded_log.json")'),
    ('_SETTINGS_FILE = os.path.join(get_app_base_dir(), "reup_studio_settings.json")',
     '_SETTINGS_FILE = os.path.join(get_user_data_dir(), "reup_studio_settings.json")'),
    ('base_dir = os.path.dirname(cs) if cs else get_app_base_dir()',
     'base_dir = os.path.dirname(cs) if cs else get_user_data_dir()'),
]


def main() -> int:
    with open(MAIN_PY, "r", encoding="utf-8") as fh:
        src = fh.read()

    for old, new in REPLACEMENTS:
        if old in src:
            src = src.replace(old, new)
            print(f"  OK  {old[:70]}")
        else:
            print(f"  BỎ QUA (không tìm thấy): {old[:70]}")

    with open(MAIN_PY, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    print("Hoàn tất.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
