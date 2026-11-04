# ============================================================
#  Cầu nối giữa giao diện Reup Studio và mô-đun tải Douyin (douyin_batch).
#  Cung cấp:
#    - load_cookies_from_file(path): nạp cookie từ tệp (JSON hoặc Netscape).
#    - DouyinBatchService: chạy tải hàng loạt, báo tiến trình, cho phép dừng.
# ============================================================
from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from douyin_batch.config import ConfigLoader
from douyin_batch.core.api_client import DouyinAPIClient
from douyin_batch.core.downloader_factory import DownloaderFactory
from douyin_batch.core.url_parser import URLParser
from douyin_batch.storage import Database, FileManager
from douyin_batch.control import QueueManager, RateLimiter, RetryHandler
from douyin_batch.auth import CookieManager
from douyin_batch.utils.logger import setup_logger

logger = setup_logger("DouyinBatchService")


class BatchResult:
    """Kết quả gọn của một phiên tải hàng loạt."""

    def __init__(self):
        self.videos: List[Dict[str, Any]] = []
        self.errors: List[str] = []

    def add_video(self, info: Dict[str, Any]) -> None:
        self.videos.append(info)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def summary(self) -> str:
        parts = [f"video={len(self.videos)}"]
        if self.errors:
            parts.append(f"lỗi={len(self.errors)}")
        return ", ".join(parts)


class _ProgressReporter:
    """Biến đổi callback tiến trình của UI thành giao diện ProgressReporter."""

    def __init__(
        self,
        progress_cb: Optional[Callable[[float, str], None]],
        item_cb: Optional[Callable[[str, str], None]],
    ):
        self._progress_cb = progress_cb
        self._item_cb = item_cb
        self._total_items = 0
        self._done_items = 0

    def update_step(self, step: str, detail: str = "") -> None:
        if self._progress_cb:
            try:
                self._progress_cb(0.0, f"{step}: {detail}" if detail else step)
            except Exception:
                pass

    def set_item_total(self, total: int, detail: str = "") -> None:
        self._total_items = total
        self._done_items = 0
        if self._progress_cb:
            try:
                self._progress_cb(0.0, f"Tổng cộng {total} video - {detail}" if detail else f"Tổng cộng {total} video")
            except Exception:
                pass

    def advance_item(self, status: str, detail: str = "") -> None:
        self._done_items += 1
        if self._item_cb:
            try:
                self._item_cb(status, detail)
            except Exception:
                pass
        if self._progress_cb and self._total_items > 0:
            try:
                self._progress_cb(self._done_items / self._total_items, detail or status)
            except Exception:
                pass


def load_cookies_from_file(path: str) -> Dict[str, str]:
    """Đọc cookie Douyin từ tệp.

    Hỗ trợ 2 định dạng:
      1. JSON: {"cookie_name": "value", ...}  (file *.json hoặc *.txt chứa JSON)
      2. Netscape/HTTP header: "name=value; name2=value2" (file *.txt thuần văn bản)
    """
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        # Thử JSON trước
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items() if isinstance(k, str)}
        except json.JSONDecodeError:
            pass
        # Thử Netscape / HTTP header
        cookies: Dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Netscape format: domain\tflag\tpath\tsecure\texpiration\tname\tvalue
            parts = line.split("\t")
            if len(parts) == 7:
                cookies[parts[5]] = parts[6]
                continue
            # Header format: name=value; name2=value2
            for item in line.split(";"):
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    cookies[k.strip()] = v.strip()
        return cookies
    except Exception as exc:  # noqa: BLE001
        logger.warning("Không đọc được cookie từ %s: %s", path, exc)
        return {}


class DouyinBatchService:
    """Dịch vụ tải hàng loạt Douyin cho giao diện Reup Studio.

    Cách dùng:
        svc = DouyinBatchService(out_dir=r"D:\\Videos", cookies=my_cookies)
        result = svc.run(
            links=["https://www.douyin.com/user/MS4w...", "https://www.douyin.com/video/73..."],
            progress_cb=lambda p, m: print(f"prog={p:.0%} {m}"),
            item_cb=lambda st, lb: print(f"item={st} {lb}"),
        )
        print(result.summary())
    """

    def __init__(self, out_dir: str, cookies: Optional[Dict[str, str]] = None):
        self._out_dir = Path(out_dir)
        self._cookies = cookies or {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._result: Optional[BatchResult] = None
        self._progress_cb: Optional[Callable[[float, str], None]] = None
        self._item_cb: Optional[Callable[[str, str], None]] = None

        # Khởi tạo cấu hình mặc định cho batch
        self._config = ConfigLoader(None)
        self._config.update(path=str(self._out_dir), thread=3)

    def run(
        self,
        links: List[str],
        progress_cb: Optional[Callable[[float, str], None]] = None,
        item_cb: Optional[Callable[[str, str], None]] = None,
    ) -> BatchResult:
        """Chạy tải hàng loạt (blocking cho đến khi xong hoặc bị dừng)."""
        self._progress_cb = progress_cb
        self._item_cb = item_cb
        self._stop_event.clear()
        self._result = BatchResult()

        def runner():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._run_async(links))
            finally:
                self._loop.close()
                self._loop = None

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
        self._thread.join()
        return self._result or BatchResult()

    def stop(self) -> None:
        """Yêu cầu dừng tải (sẽ dọn dẹp nhẹ nhàng)."""
        self._stop_event.set()
        if self._loop and not self._loop.is_closed():
            # Gửi hủy tác vụ đang chạy trong event loop
            for task in asyncio.all_tasks(self._loop):
                task.cancel()

    async def _run_async(self, links: List[str]) -> None:
        reporter = _ProgressReporter(self._progress_cb, self._item_cb)

        # Khởi tạo các thành phần core
        cookie_manager = CookieManager()
        cookie_manager.set_cookies(self._cookies)

        api_client = DouyinAPIClient(cookies=self._cookies, proxy=self._config.get("proxy"))

        file_manager = FileManager(
            base_path=str(self._out_dir),
        )

        database = None  # Tùy chọn, bỏ qua cho batch đơn giản
        rate_limiter = RateLimiter(max_per_second=self._config.get("rate_limit", 2.0))
        retry_handler = RetryHandler(max_retries=self._config.get("retry_times", 3))
        queue_manager = QueueManager(max_workers=self._config.get("thread", 3))

        try:
            # Xử lý từng link
            for link in links:
                if self._stop_event.is_set():
                    break

                parsed = URLParser.parse(link)
                if not parsed:
                    self._result.add_error(f"Link không hợp lệ: {link}")
                    continue

                url_type = parsed.get("type")
                if url_type == "short":
                    # Giải quyết short link trước
                    try:
                        real_url = await api_client.resolve_short_url(link)
                        parsed = URLParser.parse(real_url)
                        if not parsed:
                            self._result.add_error(f"Không giải quyết được short link: {link}")
                            continue
                        url_type = parsed.get("type")
                    except Exception as exc:
                        self._result.add_error(f"Lỗi giải quyết short link {link}: {exc}")
                        continue

                downloader = DownloaderFactory.create(
                    url_type=url_type,
                    config=self._config,
                    api_client=api_client,
                    file_manager=file_manager,
                    cookie_manager=cookie_manager,
                    database=database,
                    rate_limiter=rate_limiter,
                    retry_handler=retry_handler,
                    queue_manager=queue_manager,
                    progress_reporter=reporter,
                )

                if downloader is None:
                    self._result.add_error(f"Không hỗ trợ loại link: {link}")
                    continue

                try:
                    dl_result = await downloader.download(parsed)
                    if dl_result.success > 0:
                        # Thêm thông tin video đã tải vào kết quả
                        for i in range(dl_result.success):
                            self._result.add_video({"url": link, "aweme_id": f"item_{i}"})
                    # Errors are reported via item_cb with status "failed"
                    if dl_result.failed > 0:
                        self._result.add_error(f"{dl_result.failed} video thất bại (xem log chi tiết)")
                except Exception as exc:  # noqa: BLE001
                    self._result.add_error(f"Lỗi tải {link}: {exc}")

        finally:
            await api_client.close()
            if database:
                await database.close()