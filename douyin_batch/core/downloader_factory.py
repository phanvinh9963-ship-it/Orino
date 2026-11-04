# ============================================================
#  Chọn đúng lớp tải dựa trên loại link (video, trang cá nhân, album, nhạc, livestream).
#
#  Tệp này được đưa vào Reup Studio từ bộ tải Douyin
#  (douyin-downloader 2.0.0).
# ============================================================
from typing import Any, Optional

from douyin_batch.auth import CookieManager
from douyin_batch.config import ConfigLoader
from douyin_batch.control import QueueManager, RateLimiter, RetryHandler
from douyin_batch.core.api_client import DouyinAPIClient
from douyin_batch.core.downloader_base import BaseDownloader
from douyin_batch.core.live_downloader import LiveDownloader
from douyin_batch.core.live_replay_downloader import LiveReplayDownloader
from douyin_batch.core.mix_downloader import MixDownloader
from douyin_batch.core.music_downloader import MusicDownloader
from douyin_batch.core.user_downloader import UserDownloader
from douyin_batch.core.video_downloader import VideoDownloader
from douyin_batch.storage import Database, FileManager
from douyin_batch.utils.logger import setup_logger

logger = setup_logger("DownloaderFactory")


class DownloaderFactory:
    @staticmethod
    def create(
        url_type: str,
        config: ConfigLoader,
        api_client: DouyinAPIClient,
        file_manager: FileManager,
        cookie_manager: CookieManager,
        database: Optional[Database] = None,
        rate_limiter: Optional[RateLimiter] = None,
        retry_handler: Optional[RetryHandler] = None,
        queue_manager: Optional[QueueManager] = None,
        progress_reporter: Optional[Any] = None,
        job_id: Optional[str] = None,
    ) -> Optional[BaseDownloader]:

        common_args = {
            "config": config,
            "api_client": api_client,
            "file_manager": file_manager,
            "cookie_manager": cookie_manager,
            "database": database,
            "rate_limiter": rate_limiter,
            "retry_handler": retry_handler,
            "queue_manager": queue_manager,
            "progress_reporter": progress_reporter,
            "job_id": job_id,
        }

        if url_type == "video":
            return VideoDownloader(**common_args)
        elif url_type == "user":
            return UserDownloader(**common_args)
        elif url_type == "gallery":
            return VideoDownloader(**common_args)
        elif url_type == "collection":
            return MixDownloader(**common_args)
        elif url_type == "music":
            return MusicDownloader(**common_args)
        elif url_type == "live":
            return LiveDownloader(**common_args)
        elif url_type == "live_replay":
            return LiveReplayDownloader(**common_args)
        elif url_type == "short":
            logger.error(
                "Short URL was not resolved before dispatching. "
                "Please call api_client.resolve_short_url() first."
            )
            return None
        else:
            logger.error("Unsupported URL type: %s", url_type)
            return None
