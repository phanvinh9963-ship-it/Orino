# ============================================================
#  Chiến lược lấy các bài đã thích.
#
#  Tệp này được đưa vào Reup Studio từ bộ tải Douyin
#  (douyin-downloader 2.0.0).
# ============================================================
from douyin_batch.core.user_modes.base_strategy import BaseUserModeStrategy


class LikeUserModeStrategy(BaseUserModeStrategy):
    mode_name = "like"
    api_method_name = "get_user_like"
