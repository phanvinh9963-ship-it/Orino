"""Kiểm tra nhanh: trích xuất mã bài đăng (aweme_id) từ trang cá nhân Douyin
bằng trình duyệt, rồi thử gọi API lấy chi tiết video với cookie đang có.

Cách chạy:  python tools/check_douyin_api.py <link_trang_ca_nhan>
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from douyin_batch.service import load_cookies_from_file  # noqa: E402


async def collect_ids(url: str, cookie_file: str) -> list:
    from playwright.async_api import async_playwright

    cookies = load_cookies_from_file(cookie_file)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        if cookies:
            await ctx.add_cookies([
                {"name": k, "value": v, "domain": ".douyin.com", "path": "/"}
                for k, v in cookies.items()
            ])
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(6000)
        html = await page.content()
        await browser.close()

    ids = re.findall(r"aweme_id[\"']?\s*[:=]\s*[\"']?(\d{15,20})", html)
    ids += re.findall(r"/video/(\d{15,20})", html)
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.douyin.com/user/MS4wLjABAAAAtHt29g6xGNqpOXcy87sdTP_KOtb_KVXO6xruGgLCE44"
    cookie_file = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE_DIR, "cookies", "douyin_cookies.txt")

    ids = await collect_ids(url, cookie_file)
    print(f"Tìm thấy {len(ids)} mã bài đăng: {ids[:5]}")
    if not ids:
        return 1

    from douyin_batch.core.api_client import DouyinAPIClient
    cookies = load_cookies_from_file(cookie_file)
    async with DouyinAPIClient(cookies) as client:
        for aid in ids[:3]:
            try:
                detail = await client.get_video_detail(aid)
                print(f"  {aid}: {'OK' if detail else 'KHÔNG có dữ liệu'}")
            except Exception as exc:
                print(f"  {aid}: LỖI {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
