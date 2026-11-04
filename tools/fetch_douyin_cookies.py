"""Lấy cookie Douyin mới bằng trình duyệt và lưu vào tệp cố định của Reup Studio.

Cách chạy:
    python tools/fetch_douyin_cookies.py

Cách hoạt động:
  1. Mở cửa sổ Chromium (có giao diện) tới trang douyin.com.
  2. Bạn đăng nhập bằng tài khoản của mình (quét mã QR hoặc số điện thoại).
  3. Script tự phát hiện đã đăng nhập (qua cookie "sessionid") rồi lưu toàn bộ
     cookie vào <thư mục app>\\cookies\\douyin_cookies.txt.

Nếu bạn không đăng nhập trong thời gian chờ, script sẽ lưu cookie ẩn danh
(đủ để tải video công khai) và thoát.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

TARGET_URL = "https://www.douyin.com/"
DEFAULT_OUT = os.path.join(BASE_DIR, "cookies", "douyin_cookies.txt")
TIMEOUT_SECONDS = 300


def cookie_file_path() -> str:
    """Đường dẫn tệp cookie cố định mà app đọc."""
    env = os.environ.get("REUP_STUDIO_DATA_DIR", "").strip()
    if env:
        base = env
    else:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    app_cookie = os.path.join(BASE_DIR, "cookies", "douyin_cookies.txt")
    parent = os.path.dirname(app_cookie)
    try:
        os.makedirs(parent, exist_ok=True)
        probe = os.path.join(parent, ".write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return app_cookie
    except Exception:
        fallback = os.path.join(base, "ReupStudio", "cookies")
        os.makedirs(fallback, exist_ok=True)
        return os.path.join(fallback, "douyin_cookies.txt")


def to_netscape(cookies: list) -> str:
    """Chuyển cookie của Playwright sang định dạng Netscape cookies.txt."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# Được tạo bởi Reup Studio - công cụ lấy cookie Douyin.",
        "",
    ]
    for c in cookies:
        domain = c.get("domain", "")
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = str(int(c.get("expires", -1) or 0))
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append("\t".join([domain, include_sub, path, secure, expires, name, value]))
    return "\n".join(lines) + "\n"


async def main() -> int:
    out_path = cookie_file_path()
    print(f"Tệp cookie sẽ lưu tại: {out_path}")
    print("Đang mở trình duyệt...")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("!! Chưa cài Playwright. Chạy: pip install playwright && playwright install chromium")
        return 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )
        page = await context.new_page()
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        print("-" * 66)
        print("Cửa sổ trình duyệt đã mở. Hãy ĐĂNG NHẬP Douyin trong cửa sổ đó.")
        print("Script sẽ tự lưu cookie ngay khi nhận ra bạn đã đăng nhập.")
        print("-" * 66)

        deadline = time.time() + TIMEOUT_SECONDS
        logged_in = False
        while time.time() < deadline:
            await page.wait_for_timeout(2000)
            try:
                cookies = await context.cookies()
            except Exception:
                continue
            names = {c.get("name") for c in cookies}
            if {"sessionid", "sid_tt"} & names:
                logged_in = True
                break
            remaining = int(deadline - time.time())
            if remaining % 30 < 3:
                print(f"  ... còn {remaining}s để đăng nhập")

        try:
            cookies = await context.cookies()
        finally:
            await browser.close()

    if not cookies:
        print("!! Không lấy được cookie nào.")
        return 2

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(to_netscape(cookies))
    # Lưu thêm bản JSON để tiện tra cứu
    json_path = os.path.splitext(out_path)[0] + ".json"
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({c.get("name"): c.get("value") for c in cookies}, fh, ensure_ascii=False, indent=2)

    print(f"\n{'✓ Đã đăng nhập' if logged_in else '⚠ Chưa đăng nhập (chỉ lấy cookie ẩn danh)'}")
    print(f"Đã lưu {len(cookies)} cookie vào:\n  {out_path}\n  {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
