import os
import time
import json
import subprocess
import traceback

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from datetime import datetime, timedelta, timezone


# ============================================================
# CONFIG
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/youtube"
]

# YouTube Shorts:
# Video <= 3 phút sẽ được xử lý theo metadata Shorts.
SHORT_MAX_SECONDS = 180


# ============================================================
# GET VIDEO DURATION
# ============================================================

def get_video_duration(video_path):
    """
    Lấy thời lượng video bằng ffprobe.

    Trả về:
        float = số giây

    Ví dụ:
        59.8
        125.4
        300.0
    """

    if not os.path.isfile(video_path):
        raise Exception(
            f"Video not found:\n{video_path}"
        )

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path
    ]

    try:

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

    except FileNotFoundError:

        raise Exception(
            "Không tìm thấy ffprobe.\n\n"
            "Hãy kiểm tra FFmpeg/ffprobe đã được cài và "
            "đã có trong PATH của Windows."
        )

    if result.returncode != 0:

        raise Exception(
            "Không thể đọc thời lượng video.\n\n"
            f"Video:\n{video_path}\n\n"
            f"FFprobe error:\n{result.stderr}"
        )

    try:

        duration = float(
            result.stdout.strip()
        )

    except Exception:

        raise Exception(
            "FFprobe trả về thời lượng không hợp lệ:\n"
            f"{result.stdout}"
        )

    if duration <= 0:

        raise Exception(
            f"Video có thời lượng không hợp lệ: {duration}s"
        )

    return duration


# ============================================================
# DETECT SHORT / LONG
# ============================================================

def detect_video_type(video_path):
    """
    Tự xác định loại video dựa trên thời lượng.

    <= 180 giây:
        SHORT

    > 180 giây:
        LONG
    """

    duration = get_video_duration(video_path)

    if duration <= SHORT_MAX_SECONDS:

        video_type = "short"

    else:

        video_type = "long"

    minutes = int(duration // 60)
    seconds = int(duration % 60)

    print()
    print("========== VIDEO TYPE DETECTION ==========")
    print(
        f"[DURATION] {duration:.2f}s "
        f"({minutes:02d}:{seconds:02d})"
    )

    print(
        "[SHORT LIMIT]",
        f"{SHORT_MAX_SECONDS}s (03:00)"
    )

    print(
        "[VIDEO TYPE]",
        video_type.upper()
    )

    print("==========================================")
    print()

    return video_type, duration


# ============================================================
# FORMAT DURATION
# ============================================================

def format_duration(seconds):

    seconds = int(round(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:

        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{secs:02d}"
        )

    return (
        f"{minutes:02d}:"
        f"{secs:02d}"
    )


# ============================================================
# UPLOAD VIDEO
# ============================================================

def upload_video(
    video_path,
    thumbnail_path,
    account,
    day_offset=0,
    **legacy_kwargs
):

    print()
    print("================================================")
    print("          YOUTUBE UPLOAD FUNCTION")
    print("================================================")

    # ========================================================
    # 1. CHECK VIDEO
    # ========================================================

    if not os.path.isfile(video_path):

        raise Exception(
            f"Video not found:\n{video_path}"
        )

    print(
        "[VIDEO]",
        video_path
    )

    # ========================================================
    # 2. AUTO DETECT SHORT / LONG
    # ========================================================

    video_type, duration = detect_video_type(
        video_path
    )

    is_short = (
        video_type == "short"
    )

    print(
        "[AUTO MODE]",
        "SHORT" if is_short else "LONG"
    )

    # ========================================================
    # 3. TOKEN
    # ========================================================

    channel_name = account["youtube"].get(
        "channel_name",
        account.get("name", "channel")
    )

    token_file = os.path.join(
        "youtube_auth",
        f"{channel_name}_token.json"
    )

    if not os.path.isfile(token_file):

        raise Exception(
            f"Token not found:\n{token_file}"
        )

    print(
        "[TOKEN]",
        token_file
    )

    # ========================================================
    # 4. LOAD CREDENTIALS
    # ========================================================

    creds = Credentials.from_authorized_user_file(
        token_file,
        SCOPES
    )

    if not creds.valid:

        if creds.expired and creds.refresh_token:

            print(
                "[REFRESH TOKEN]"
            )

            try:

                creds.refresh(
                    Request()
                )

            except Exception as e:

                raise Exception(
                    f"Token refresh failed:\n"
                    f"{str(e)}\n\n"
                    f"Delete token and login again:\n"
                    f"{token_file}"
                )

        else:

            raise Exception(
                f"Invalid YouTube token:\n"
                f"{token_file}"
            )

    # ========================================================
    # 5. YOUTUBE API
    # ========================================================

    youtube = build(
        "youtube",
        "v3",
        credentials=creds
    )

    # ========================================================
    # 6. SELECT METADATA AUTOMATICALLY
    # ========================================================

    if is_short:

        title_key = "shorts_title"
        description_key = "shorts_description"
        tags_key = "shorts_tags"

        print(
            "[METADATA]",
            "Using SHORTS metadata"
        )

    else:

        title_key = "title"
        description_key = "description"
        tags_key = "tags"

        print(
            "[METADATA]",
            "Using LONG VIDEO metadata"
        )

    # ========================================================
    # TITLE
    # ========================================================

    youtube_config = account["youtube"]

    title = youtube_config.get(
        title_key
    )

    # fallback về title thường nếu Shorts metadata không tồn tại
    if not title:

        title = youtube_config.get(
            "title"
        )

    # fallback cuối cùng = tên file
    if not title:

        title = os.path.splitext(
            os.path.basename(video_path)
        )[0]

    # ========================================================
    # DESCRIPTION
    # ========================================================

    description = youtube_config.get(
        description_key
    )

    if description is None:

        description = youtube_config.get(
            "description",
            ""
        )

    # ========================================================
    # TAGS
    # ========================================================

    tags = youtube_config.get(
        tags_key
    )

    if tags is None:

        tags = youtube_config.get(
            "tags",
            []
        )

    if not isinstance(tags, list):

        tags = [
            str(tags)
        ]

    # ========================================================
    # CATEGORY
    # ========================================================

    category_id = str(
        youtube_config.get(
            "category_id",
            "24"
        )
    )

    # ========================================================
    # SHORTS HASHTAG
    # ========================================================

    if is_short:

        if "#shorts" not in title.lower():

            title = (
                f"{title} #Shorts"
            )

        if "#shorts" not in description.lower():

            description = (
                f"{description.rstrip()}"
                f"\n\n#Shorts"
            )

    # ========================================================
    # PRIVACY
    # ========================================================

    privacy = youtube_config.get(
        "privacy",
        "private"
    )

    # ========================================================
    # SCHEDULE TIME
    # ========================================================

    if is_short:

        hour = youtube_config.get(
            "shorts_publish_hour",
            youtube_config.get(
                "publish_hour",
                19
            )
        )

        minute = youtube_config.get(
            "shorts_publish_minute",
            youtube_config.get(
                "publish_minute",
                0
            )
        )

    else:

        hour = youtube_config.get(
            "publish_hour",
            19
        )

        minute = youtube_config.get(
            "publish_minute",
            0
        )

    # ========================================================
    # START DATE
    # ========================================================

    start_date = youtube_config.get(
        "start_date"
    )

    if not start_date:

        raise Exception(
            f"Không có youtube.start_date "
            f"cho account: {channel_name}"
        )

    base_date = datetime.strptime(
        start_date,
        "%Y-%m-%d"
    )

    publish_time = datetime(
        base_date.year,
        base_date.month,
        base_date.day,
        int(hour),
        int(minute),
        0
    )

    publish_time += timedelta(
        days=day_offset
    )

    # ========================================================
    # VIETNAM UTC+7 -> UTC
    # ========================================================

    publish_time_utc = (
        publish_time
        - timedelta(hours=7)
    ).replace(
        tzinfo=timezone.utc
    )

    publish_at = (
        publish_time_utc.isoformat()
    )

    # ========================================================
    # PRINT SCHEDULE
    # ========================================================

    print()
    print("========== SCHEDULE ==========")

    print(
        "[LOCAL UTC+7]",
        publish_time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print(
        "[UTC]",
        publish_at
    )

    print(
        "[TYPE]",
        "SHORT" if is_short else "LONG"
    )

    print(
        "[TITLE]",
        title
    )

    print(
        "[CATEGORY]",
        category_id
    )

    print(
        "[PRIVACY]",
        privacy
    )

    print(
        "=============================="
    )

    # ========================================================
    # SYNTHETIC MEDIA
    # ========================================================

    contains_synthetic_media = (
        youtube_config.get(
            "contains_synthetic_media",
            False
        )
    )

    # ========================================================
    # BUILD STATUS
    # ========================================================

    if privacy == "private":

        status_body = {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia":
                contains_synthetic_media
        }

    else:

        status_body = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia":
                contains_synthetic_media
        }

    # ========================================================
    # UPLOAD REQUEST
    # ========================================================

    print()
    print(
        "[UPLOADING]",
        title
    )

    request = youtube.videos().insert(

        part="snippet,status",

        body={
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": category_id,
                "tags": tags
            },

            "status": status_body
        },

        media_body=MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=8 * 1024 * 1024
        )
    )

    # ========================================================
    # RESUMABLE UPLOAD
    # ========================================================

    response = None

    retry_count = 0
    max_retry = 30

    while True:

        try:

            status, response = (
                request.next_chunk()
            )

            # ------------------------------------------------
            # Upload progress
            # ------------------------------------------------

            if status:

                progress = int(
                    status.progress() * 100
                )

                print(
                    f"[UPLOAD] {progress}%"
                )

                # Có dữ liệu gửi thành công
                # -> reset retry
                retry_count = 0

            # ------------------------------------------------
            # Upload finished
            # ------------------------------------------------

            if response:

                break

        except Exception as e:

            retry_count += 1

            print(
                f"[UPLOAD ERROR "
                f"{retry_count}/{max_retry}] "
                f"{e}"
            )

            if retry_count >= max_retry:

                print(
                    "[UPLOAD FAILED] "
                    "Max retry reached"
                )

                raise

            print(
                "[WAIT 60s RETRY]"
            )

            time.sleep(60)

    # ========================================================
    # VIDEO ID
    # ========================================================

    video_id = response.get(
        "id"
    )

    if not video_id:

        raise Exception(
            "YouTube returned no video ID"
        )

    print()
    print(
        "[UPLOADED]"
    )

    print(
        f"https://youtu.be/{video_id}"
    )

    # ========================================================
    # THUMBNAIL
    # ========================================================

    print()
    print(
        "========== BEFORE THUMB =========="
    )

    print(
        "THUMB PATH:",
        thumbnail_path
    )

    print(
        "FILE EXISTS:",
        os.path.isfile(
            thumbnail_path
        )
        if thumbnail_path
        else False
    )

    if (
        thumbnail_path
        and
        os.path.isfile(
            thumbnail_path
        )
    ):

        try:

            # ------------------------------------------------
            # Detect thumbnail MIME
            # ------------------------------------------------

            ext = (
                os.path.splitext(
                    thumbnail_path
                )[1]
                .lower()
            )

            if ext == ".png":

                thumbnail_mimetype = (
                    "image/png"
                )

            else:

                thumbnail_mimetype = (
                    "image/jpeg"
                )

            youtube.thumbnails().set(

                videoId=video_id,

                media_body=MediaFileUpload(
                    thumbnail_path,
                    mimetype=thumbnail_mimetype
                )

            ).execute()

            print(
                "[THUMBNAIL UPLOADED]"
            )

        except Exception:

            print(
                "========== THUMB ERROR =========="
            )

            traceback.print_exc()

    else:

        print(
            "[NO THUMBNAIL]"
        )

    # ========================================================
    # FINAL RESULT
    # ========================================================

    print()
    print(
        "================================================"
    )

    print(
        "[UPLOAD COMPLETE]"
    )

    print(
        "[CHANNEL]",
        channel_name
    )

    print(
        "[VIDEO TYPE]",
        "SHORT" if is_short else "LONG"
    )

    print(
        "[DURATION]",
        format_duration(duration)
    )

    print(
        "[VIDEO ID]",
        video_id
    )

    print(
        "[URL]",
        f"https://youtu.be/{video_id}"
    )

    print(
        "[SCHEDULE]",
        publish_time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "UTC+7"
    )

    print(
        "================================================"
    )

    return video_id
