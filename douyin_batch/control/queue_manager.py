# ============================================================
#  Hàng đợi chạy song song nhiều tác vụ tải video.
#
#  Tệp này được đưa vào Reup Studio từ bộ tải Douyin
#  (douyin-downloader 2.0.0).
# ============================================================
import asyncio
from typing import Any, Callable, List, TypeVar

from douyin_batch.utils.logger import setup_logger

logger = setup_logger("QueueManager")

T = TypeVar("T")


class QueueManager:
    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers
        self.semaphore = asyncio.Semaphore(max_workers)

    async def process_tasks(self, tasks: List[Callable], *args, **kwargs) -> List[Any]:
        # Failures surface as exception instances in the result list (via
        # return_exceptions=True). Callers can filter with isinstance(r, BaseException).
        async def _task_wrapper(task):
            async with self.semaphore:
                try:
                    return await task(*args, **kwargs)
                except Exception:
                    logger.exception("Task failed")
                    raise

        return await asyncio.gather(
            *[_task_wrapper(task) for task in tasks], return_exceptions=True
        )

    async def download_batch(self, download_func: Callable, items: List[Any]) -> List[Any]:
        async def _download_wrapper(item):
            async with self.semaphore:
                try:
                    return await download_func(item)
                except Exception:
                    logger.exception("Download failed for item: %r", item)
                    raise

        return await asyncio.gather(
            *[_download_wrapper(item) for item in items], return_exceptions=True
        )
