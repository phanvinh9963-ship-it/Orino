"""Kiểm thử tải thật từ Douyin bằng mô-đun douyin_batch (chạy ngoài giao diện).

Cách chạy:
    python tools/test_douyin_download.py --url <link> --limit 3
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from douyin_batch.service import DouyinBatchService, load_cookies_from_file  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="link trang cá nhân hoặc video Douyin")
    ap.add_argument("--limit", type=int, default=3, help="số video tối đa")
    ap.add_argument("--out", default=os.path.join(BASE_DIR, "build", "dl_test"))
    ap.add_argument("--cookie", default=os.path.join(BASE_DIR, "cookies", "douyin_cookies.txt"))
    args = ap.parse_args()

    cookies = load_cookies_from_file(args.cookie)
    print(f"Đọc được {len(cookies)} cookie từ {args.cookie}")

    service = DouyinBatchService(
        out_dir=args.out, cookies=cookies, max_videos=args.limit, thread=3, retry_times=2,
    )

    started = time.time()

    def on_progress(pct: float, msg: str) -> None:
        print(f"  [{pct * 100:5.1f}%] {msg}")

    def on_item(status: str, label: str) -> None:
        print(f"  -> {status}: {label}")

    result = service.run([args.url], progress_cb=on_progress, item_cb=on_item)

    print("\n" + "=" * 60)
    print(result.summary())
    print(f"Thời gian: {time.time() - started:.1f}s")
    if result.videos:
        print("Các video đã tải:")
        for v in result.videos:
            size = os.path.getsize(v["path"]) / 1048576 if os.path.isfile(v["path"]) else 0
            print(f"  - {v['path']}  ({size:.1f} MB)")
    if result.errors:
        print("Lỗi:")
        for e in result.errors:
            print(f"  ! {e}")
    return 0 if result.videos else 1


if __name__ == "__main__":
    raise SystemExit(main())
