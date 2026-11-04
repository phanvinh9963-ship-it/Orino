# -*- coding: utf-8 -*-

"""
batch_upload.py V2
------------------

TikTok Batch Upload - RETRY LOG + final_vi STRUCTURE

Cấu trúc video thực tế:

F:\\reup-studio\\reup_output\\
    <TEN_VIDEO_GOC>\\
        final_vi\\
            final_vi.mp4
            note\\
                note.txt


Ví dụ:

F:\\reup-studio\\reup_output\\
    20954545554 - ... [7656799167649484067] = Bạn đang dùng card màn hình gì thế, RTX\\
        final_vi\\
            final_vi.mp4
            note\\
                note.txt


CAPTION TIKTOK:

    TITLE

    #tag1 #tag2 #tag3 #tag4 #tag5


LỊCH:

    Mỗi ngày 19:00

Ví dụ:

    Video 1 -> 19/08/2026 19:00
    Video 2 -> 20/08/2026 19:00
    Video 3 -> 21/08/2026 19:00


Mỗi lần chạy:

    Tối đa 5 video


CHỐNG TRÙNG:

    uploaded_log.json

    video_id:
        [7656799167649484067]

    published:
        KHÔNG đăng lại

    failed:
        ĐƯỢC retry


SAU UPLOAD THÀNH CÔNG:

    -> ghi published vào log
    -> move folder sang da_dang/


QUAN TRỌNG:

    batch_upload.py chỉ coi upload thành công
    khi cli.py trả return code = 0.
"""


from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta


# ============================================================
# CONFIG
# ============================================================

ROOT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

VIDEOS_ROOT = r"F:\reup-studio\reup_output"

DONE_DIR = os.path.join(
    ROOT_DIR,
    "da_dang"
)

LOG_FILE = os.path.join(
    ROOT_DIR,
    "uploaded_log.json"
)

ACCOUNT_NAME = "vipsextoy.nett1"

# ------------------------------------------------------------
# Cấu trúc mới
# ------------------------------------------------------------

FINAL_DIR_NAME = "final_vi"

VIDEO_FILENAME = "final_vi.mp4"

NOTE_DIR_NAME = "note"

# ------------------------------------------------------------
# Batch
# ------------------------------------------------------------

MAX_VIDEOS_PER_RUN = 5

# ------------------------------------------------------------
# Schedule
# ------------------------------------------------------------

UPLOAD_HOUR = 19
UPLOAD_MINUTE = 0

# ------------------------------------------------------------
# TikTok
# ------------------------------------------------------------

VISIBILITY = "0"

ALLOW_COMMENT = "1"

ALLOW_DUET = "0"

ALLOW_STITCH = "0"

# ------------------------------------------------------------
# Hashtag
# ------------------------------------------------------------

MAX_HASHTAGS = 5

# ------------------------------------------------------------
# Retry status
# ------------------------------------------------------------

RETRY_STATUSES = {
    "failed",
    "error",
    "upload_failed",
    "retry",
    "pending",
}

PUBLISHED_STATUS = "published"


# ============================================================
# PRINT
# ============================================================

def print_line(char="-", length=70):
    print(char * length)


# ============================================================
# LOG
# ============================================================

def load_log():

    if not os.path.exists(LOG_FILE):
        print("[LOG] Chua co uploaded_log.json.")
        return {}

    try:

        with open(
            LOG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, dict):

            print(
                f"[LOG] Da load {len(data)} record."
            )

            return data

    except Exception as e:

        print(
            f"[WARNING] Khong doc duoc log: {e}"
        )

    return {}


def save_log(log):

    temp_file = LOG_FILE + ".tmp"

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                log,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temp_file,
            LOG_FILE
        )

        return True

    except Exception as e:

        print(
            f"[ERROR] Khong save duoc log: {e}"
        )

        try:

            if os.path.exists(temp_file):
                os.remove(temp_file)

        except Exception:
            pass

        return False


# ============================================================
# VIDEO ID
# ============================================================

def extract_video_id(folder_name):

    """
    Ví dụ:

    20954545554 - ... [7656799167649484067] = caption

    Kết quả:

    7656799167649484067
    """

    if not folder_name:
        return ""

    match = re.search(
        r"\[([^\]]+)\]",
        folder_name
    )

    if match:

        return match.group(1).strip()

    # Fallback:
    # Nếu không có [] thì dùng tên folder

    return folder_name.strip()


# ============================================================
# CHECK PUBLISHED
# ============================================================

def is_published(log, video_id):

    if video_id not in log:
        return False

    item = log.get(
        video_id
    )

    if not isinstance(item, dict):
        return False

    status = str(
        item.get(
            "status",
            ""
        )
    ).lower().strip()

    return status == PUBLISHED_STATUS


# ============================================================
# CHECK RETRY
# ============================================================

def is_retryable(log, video_id):

    if video_id not in log:
        return False

    item = log.get(
        video_id
    )

    if not isinstance(item, dict):
        return False

    status = str(
        item.get(
            "status",
            ""
        )
    ).lower().strip()

    return status in RETRY_STATUSES


# ============================================================
# FIND FINAL_VI DIRECTORY
# ============================================================

def find_final_vi_dir(folder_path):

    """
    Cấu trúc ưu tiên:

        folder\\final_vi

    Nếu không có thì thử:

        folder\\Final_Vi
        folder\\FINAL_VI

    """

    if not os.path.isdir(folder_path):
        return None

    preferred = [
        FINAL_DIR_NAME,
        "Final_Vi",
        "FINAL_VI",
        "final-VI",
        "finalvi",
    ]

    for dirname in preferred:

        path = os.path.join(
            folder_path,
            dirname
        )

        if os.path.isdir(path):

            return path

    # Fallback tìm folder không phân biệt hoa thường

    try:

        for name in os.listdir(folder_path):

            path = os.path.join(
                folder_path,
                name
            )

            if not os.path.isdir(path):
                continue

            if name.lower() == "final_vi".lower():

                return path

    except Exception:
        pass

    return None


# ============================================================
# FIND VIDEO
# ============================================================

def find_video_file(folder_path):

    """
    Tìm:

        folder\\final_vi\\final_vi.mp4

    Sau đó fallback một số vị trí khác.
    """

    if not os.path.isdir(folder_path):
        return None

    # --------------------------------------------------------
    # 1. Vị trí chính
    # --------------------------------------------------------

    final_dir = find_final_vi_dir(
        folder_path
    )

    if final_dir:

        exact_path = os.path.join(
            final_dir,
            VIDEO_FILENAME
        )

        if os.path.isfile(exact_path):

            return exact_path

        # Không phân biệt hoa thường

        try:

            for fname in os.listdir(
                final_dir
            ):

                if fname.lower() == VIDEO_FILENAME.lower():

                    path = os.path.join(
                        final_dir,
                        fname
                    )

                    if os.path.isfile(path):

                        return path

        except Exception:
            pass

    # --------------------------------------------------------
    # 2. Fallback folder root
    # --------------------------------------------------------

    exact_root = os.path.join(
        folder_path,
        VIDEO_FILENAME
    )

    if os.path.isfile(exact_root):

        return exact_root

    # --------------------------------------------------------
    # 3. Fallback recursive
    # --------------------------------------------------------

    try:

        for root, dirs, files in os.walk(
            folder_path
        ):

            for fname in files:

                if fname.lower() == VIDEO_FILENAME.lower():

                    return os.path.join(
                        root,
                        fname
                    )

    except Exception:
        pass

    return None


# ============================================================
# FIND NOTE FILE
# ============================================================

def find_note_file(folder_path):

    """
    Tìm note theo thứ tự:

        1.
        folder\\final_vi\\note\\note.txt

        2.
        folder\\final_vi\\note\\note.md

        3.
        folder\\final_vi\\note\\*.txt

        4.
        folder\\final_vi\\note\\*.md

        5.
        folder\\final_vi\\note.txt

        6.
        recursive *.txt / *.md
    """

    if not os.path.isdir(folder_path):
        return None

    final_dir = find_final_vi_dir(
        folder_path
    )

    # ========================================================
    # NOTE DIR
    # ========================================================

    note_dirs = []

    if final_dir:

        note_dir = os.path.join(
            final_dir,
            NOTE_DIR_NAME
        )

        if os.path.isdir(note_dir):

            note_dirs.append(
                note_dir
            )

        # Tìm case-insensitive

        try:

            for name in os.listdir(
                final_dir
            ):

                path = os.path.join(
                    final_dir,
                    name
                )

                if not os.path.isdir(path):
                    continue

                if name.lower() == NOTE_DIR_NAME.lower():

                    if path not in note_dirs:
                        note_dirs.append(path)

        except Exception:
            pass

    # Note dir ở root

    root_note_dir = os.path.join(
        folder_path,
        NOTE_DIR_NAME
    )

    if os.path.isdir(root_note_dir):

        note_dirs.append(
            root_note_dir
        )

    # ========================================================
    # TÌM NOTE.TXT / NOTE.MD
    # ========================================================

    preferred = [
        "note.txt",
        "note.md",
        "Note.txt",
        "Note.md",
        "NOTE.TXT",
        "NOTE.MD",
    ]

    for note_dir in note_dirs:

        for name in preferred:

            path = os.path.join(
                note_dir,
                name
            )

            if os.path.isfile(path):

                return path

    # ========================================================
    # TÌM TXT / MD TRONG NOTE DIR
    # ========================================================

    for note_dir in note_dirs:

        try:

            files = sorted(
                os.listdir(note_dir)
            )

            for fname in files:

                if not fname.lower().endswith(
                    (".txt", ".md")
                ):
                    continue

                path = os.path.join(
                    note_dir,
                    fname
                )

                if os.path.isfile(path):

                    return path

        except Exception:
            pass

    # ========================================================
    # FALLBACK: note.txt / note.md NGAY TRONG final_vi
    # ========================================================

    if final_dir:

        for name in preferred:

            path = os.path.join(
                final_dir,
                name
            )

            if os.path.isfile(path):

                return path

    # ========================================================
    # FALLBACK: NOTE NGAY ROOT
    # ========================================================

    for name in preferred:

        path = os.path.join(
            folder_path,
            name
        )

        if os.path.isfile(path):

            return path

    # ========================================================
    # CUỐI CÙNG: RECURSIVE
    # ========================================================

    try:

        for root, dirs, files in os.walk(
            folder_path
        ):

            for fname in sorted(files):

                if not fname.lower().endswith(
                    (".txt", ".md")
                ):
                    continue

                path = os.path.join(
                    root,
                    fname
                )

                if os.path.isfile(path):

                    return path

    except Exception:
        pass

    return None


# ============================================================
# READ TEXT
# ============================================================

def read_text_file(path):

    if not path:
        return ""

    if not os.path.isfile(path):
        return ""

    encodings = [
        "utf-8-sig",
        "utf-8",
        "gb18030",
        "gbk",
    ]

    for encoding in encodings:

        try:

            with open(
                path,
                "r",
                encoding=encoding
            ) as f:

                return f.read().strip()

        except Exception:
            continue

    print(
        f"[WARNING] Khong doc duoc file: {path}"
    )

    return ""


# ============================================================
# NORMALIZE HASHTAGS
# ============================================================

def normalize_hashtags(text):

    if not text:
        return []

    text = text.replace(
        ",",
        " "
    )

    tokens = text.split()

    result = []

    seen = set()

    for token in tokens:

        token = token.strip()

        if not token:
            continue

        # Bỏ #

        token = token.lstrip("#")

        # Bỏ ký tự đặc biệt

        token = re.sub(
            r"[^\wÀ-ỹ]",
            "",
            token,
            flags=re.UNICODE
        )

        if not token:
            continue

        tag = "#" + token

        key = tag.lower()

        if key in seen:
            continue

        seen.add(key)

        result.append(
            tag
        )

        if len(result) >= MAX_HASHTAGS:

            break

    return result


# ============================================================
# PARSE NOTE
# ============================================================

def parse_note(note_text):
    """
    Đọc note.txt theo format:

        TIÊU ĐỀ VIDEO
        Tiêu đề...

        MÔ TẢ VIDEO
        Mô tả...

        HASHTAGS (5)
        #tag1 #tag2 #tag3 #tag4 #tag5

    Return:

        title
        description
        hashtags
    """

    if not note_text:
        return "", "", []

    text = (
        note_text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    lines = text.split("\n")

    title_lines = []
    description_lines = []
    hashtag_lines = []

    section = None

    for raw_line in lines:

        line = raw_line.strip()

        upper = line.upper()

        # ====================================================
        # HEADER: TITLE
        # ====================================================

        if (
            upper == "TIÊU ĐỀ VIDEO"
            or upper.startswith("TIÊU ĐỀ VIDEO")
        ):
            section = "title"
            continue

        # ====================================================
        # HEADER: DESCRIPTION
        # ====================================================

        if (
            upper == "MÔ TẢ VIDEO"
            or upper.startswith("MÔ TẢ VIDEO")
        ):
            section = "description"
            continue

        # ====================================================
        # HEADER: HASHTAGS
        # ====================================================

        if (
            upper.startswith("HASHTAGS")
            or upper.startswith("HASHTAG")
        ):
            section = "hashtags"
            continue

        # ====================================================
        # EMPTY LINE
        # ====================================================

        if not line:
            continue

        # ====================================================
        # TITLE
        # ====================================================

        if section == "title":

            title_lines.append(line)

        # ====================================================
        # DESCRIPTION
        # ====================================================

        elif section == "description":

            description_lines.append(line)

        # ====================================================
        # HASHTAGS
        # ====================================================

        elif section == "hashtags":

            hashtag_lines.append(line)

    # ========================================================
    # BUILD TITLE
    # ========================================================

    title = " ".join(
        title_lines
    ).strip()

    # ========================================================
    # BUILD DESCRIPTION
    # ========================================================

    description = "\n".join(
        description_lines
    ).strip()

    # ========================================================
    # BUILD HASHTAGS
    # ========================================================

    hashtag_text = " ".join(
        hashtag_lines
    )

    hashtags = normalize_hashtags(
        hashtag_text
    )

    return (
        title,
        description,
        hashtags
    )


# ============================================================
# GET TITLE + HASHTAGS
# ============================================================

def get_video_metadata(folder_path):

    note_file = find_note_file(
        folder_path
    )

    if not note_file:

        print("")
        print(
            "[WARNING] Khong tim thay file note."
        )

        print(
            f"          Folder: {folder_path}"
        )

        return "", "", []

    print(
        f"[NOTE] {note_file}"
    )

    note_text = read_text_file(
        note_file
    )

    if not note_text:

        print(
            f"[WARNING] File note rong: {note_file}"
        )

        return "", "", []

    title, description, hashtags = parse_note(
        note_text
    )

    return (
        title,
        description,
        hashtags
    )
# ============================================================
# BUILD CAPTION
# ============================================================

def build_caption(
    folder_path
):

    title, description, hashtags = get_video_metadata(
        folder_path
    )

    if not title:

        return ""

    parts = [
        title
    ]

    if hashtags:

        parts.append(
            " ".join(hashtags)
        )

    caption = "\n\n".join(
        parts
    ).strip()

    return caption[:2190]


# ============================================================
# FIND LATEST SCHEDULE
# ============================================================

def get_latest_schedule_time(log):

    latest_schedule = None

    for video_id, item in log.items():

        if not isinstance(item, dict):
            continue

        value = item.get(
            "scheduled_time"
        )

        if not value:
            continue

        try:

            dt = datetime.strptime(
                value,
                "%Y-%m-%d %H:%M:%S"
            )

            if (
                latest_schedule is None
                or dt > latest_schedule
            ):

                latest_schedule = dt

        except Exception:
            continue

    return latest_schedule


# ============================================================
# GET NEXT SCHEDULE
# ============================================================

def get_next_schedule_time(
    log,
    reserved_times=None
):

    if reserved_times is None:

        reserved_times = []

    now = datetime.now()

    latest_schedule = get_latest_schedule_time(
        log
    )

    # ========================================================
    # ĐÃ CÓ LỊCH
    # ========================================================

    if latest_schedule:

        next_time = (
            latest_schedule
            + timedelta(days=1)
        )

    # ========================================================
    # CHƯA CÓ LỊCH
    # ========================================================

    else:

        next_time = now.replace(
            hour=UPLOAD_HOUR,
            minute=UPLOAD_MINUTE,
            second=0,
            microsecond=0
        )

        if next_time <= now:

            next_time += timedelta(
                days=1
            )

    # ========================================================
    # ĐẢM BẢO 19:00
    # ========================================================

    next_time = next_time.replace(
        hour=UPLOAD_HOUR,
        minute=UPLOAD_MINUTE,
        second=0,
        microsecond=0
    )

    # ========================================================
    # TRÁNH TRÙNG RESERVATION
    # ========================================================

    while next_time in reserved_times:

        next_time += timedelta(
            days=1
        )

    return next_time


# ============================================================
# UPLOAD VIDEO
# ============================================================

def upload_video(
    video_path,
    caption,
    scheduled_time
):

    cli_path = os.path.join(
        ROOT_DIR,
        "cli.py"
    )

    if not os.path.isfile(cli_path):

        print("")
        print(
            f"[ERROR] Khong tim thay cli.py:"
        )

        print(
            f"        {cli_path}"
        )

        return False, "cli.py not found"

    # ========================================================
    # KIỂM TRA VIDEO
    # ========================================================

    if not os.path.isfile(video_path):

        return False, "video file not found"

    # ========================================================
    # COMMAND
    # ========================================================

    cmd = [
        sys.executable,
        cli_path,
        "upload",

        "-u",
        ACCOUNT_NAME,

        "-v",
        video_path,

        "-t",
        caption,

        "-vi",
        VISIBILITY,

        "-ct",
        ALLOW_COMMENT,

        "-d",
        ALLOW_DUET,

        "-st",
        ALLOW_STITCH,
    ]

    print("")
    print(
        "  -> DANG UPLOAD"
    )

    print_line()

    print(
        f"  Python   : {sys.executable}"
    )

    print(
        f"  CLI      : {cli_path}"
    )

    print(
        f"  Account  : {ACCOUNT_NAME}"
    )

    print(
        f"  Video    : {video_path}"
    )

    print(
        f"  Schedule : "
        f"{scheduled_time.strftime('%d/%m/%Y %H:%M')}"
    )

    print(
        f"  Caption  : {len(caption)} ky tu"
    )

    print_line()

    try:

        result = subprocess.run(
            cmd,
            cwd=ROOT_DIR
        )

        return_code = result.returncode

        print(
            f"  Return code: {return_code}"
        )

        if return_code == 0:

            return True, ""

        return False, (
            f"cli.py return code {return_code}"
        )

    except KeyboardInterrupt:

        print(
            "[WARNING] Upload bi huy boi nguoi dung."
        )

        return False, "KeyboardInterrupt"

    except Exception as e:

        print(
            f"[ERROR] Loi khi chay cli.py: {e}"
        )

        return False, str(e)


# ============================================================
# MOVE DONE
# ============================================================

def move_to_done(
    folder_path,
    folder_name
):

    os.makedirs(
        DONE_DIR,
        exist_ok=True
    )

    dest = os.path.join(
        DONE_DIR,
        folder_name
    )

    try:

        # ====================================================
        # Nếu destination đã tồn tại
        # ====================================================

        if os.path.exists(dest):

            base = folder_name

            counter = 2

            while os.path.exists(
                os.path.join(
                    DONE_DIR,
                    f"{base}_{counter}"
                )
            ):

                counter += 1

            dest = os.path.join(
                DONE_DIR,
                f"{base}_{counter}"
            )

        shutil.move(
            folder_path,
            dest
        )

        return True, dest

    except Exception as e:

        return False, str(e)


# ============================================================
# UPDATE FAILED LOG
# ============================================================

def save_failed_record(
    log,
    video_id,
    folder_name,
    video_path,
    title,
    hashtags,
    caption,
    scheduled_time,
    error_message
):

    old = log.get(
        video_id,
        {}
    )

    if not isinstance(old, dict):

        old = {}

    try:

        attempt_count = int(
            old.get(
                "attempt_count",
                0
            )
        )

    except Exception:

        attempt_count = 0

    attempt_count += 1

    now = datetime.now()

    log[video_id] = {

        "folder":
            folder_name,

        "video":
            os.path.basename(
                video_path
            ),

        "video_path":
            video_path,

        "title":
            title,

        "hashtags":
            hashtags,

        "caption":
            caption,

        "scheduled_time":
            scheduled_time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "last_attempt_time":
            now.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "attempt_count":
            attempt_count,

        "status":
            "failed",

        "error":
            str(error_message),

    }

    save_log(
        log
    )


# ============================================================
# SAVE SUCCESS LOG
# ============================================================

def save_success_record(
    log,
    video_id,
    folder_name,
    video_path,
    title,
    hashtags,
    caption,
    scheduled_time,
):

    old = log.get(
        video_id,
        {}
    )

    if not isinstance(old, dict):

        old = {}

    try:

        attempt_count = int(
            old.get(
                "attempt_count",
                0
            )
        )

    except Exception:

        attempt_count = 0

    attempt_count += 1

    now = datetime.now()

    log[video_id] = {

        "folder":
            folder_name,

        "video":
            os.path.basename(
                video_path
            ),

        "video_path":
            video_path,

        "title":
            title,

        "hashtags":
            hashtags,

        "caption":
            caption,

        "scheduled_time":
            scheduled_time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "uploaded_time":
            now.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "attempt_count":
            attempt_count,

        "status":
            "published",

        "error":
            "",

    }

    save_log(
        log
    )


# ============================================================
# PRINT LOG STATUS
# ============================================================

def print_existing_log(
    log,
    video_id,
    folder_name
):

    old = log.get(
        video_id,
        {}
    )

    print("")
    print(
        "[LOG] Video ID da co trong log:"
    )

    print(
        f"      Folder : {folder_name}"
    )

    print(
        f"      ID     : {video_id}"
    )

    if isinstance(old, dict):

        print(
            f"      Status : "
            f"{old.get('status', '')}"
        )

        print(
            f"      Attempt: "
            f"{old.get('attempt_count', 0)}"
        )

        print(
            f"      Schedule: "
            f"{old.get('scheduled_time', '')}"
        )

        print(
            f"      Uploaded: "
            f"{old.get('uploaded_time', '')}"
        )

        error = old.get(
            "error",
            ""
        )

        if error:

            print(
                f"      Error  : {error}"
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 70)
    print(
        " TikTok Batch Upload - V2"
    )
    print("=" * 70)

    print(
        f"Video root : {VIDEOS_ROOT}"
    )

    print(
        f"Account    : {ACCOUNT_NAME}"
    )

    print(
        f"Done       : {DONE_DIR}"
    )

    print(
        f"Log        : {LOG_FILE}"
    )

    print(
        f"Final dir  : {FINAL_DIR_NAME}"
    )

    print(
        f"Video      : {VIDEO_FILENAME}"
    )

    print(
        f"Moi ngay   : "
        f"{UPLOAD_HOUR:02d}:{UPLOAD_MINUTE:02d}"
    )

    print(
        f"Moi lan    : "
        f"{MAX_VIDEOS_PER_RUN} video"
    )

    print("=" * 70)

    # ========================================================
    # CHECK ROOT
    # ========================================================

    if not os.path.isdir(
        VIDEOS_ROOT
    ):

        print("")
        print(
            "[LOI] Khong tim thay VIDEOS_ROOT:"
        )

        print(
            f"      {VIDEOS_ROOT}"
        )

        return

    # ========================================================
    # DONE
    # ========================================================

    os.makedirs(
        DONE_DIR,
        exist_ok=True
    )

    # ========================================================
    # LOAD LOG
    # ========================================================

    log = load_log()

    # ========================================================
    # FIND FOLDERS
    # ========================================================

    try:

        folders = sorted(
            os.listdir(
                VIDEOS_ROOT
            )
        )

    except Exception as e:

        print(
            f"[LOI] Khong doc duoc folder: {e}"
        )

        return

    if not folders:

        print(
            "[INFO] Khong co folder video."
        )

        return

    # ========================================================
    # COUNTERS
    # ========================================================

    total = 0

    success_count = 0

    retry_count = 0

    skip_count = 0

    error_count = 0

    processed_this_run = 0

    reserved_times = []

    # ========================================================
    # LOOP
    # ========================================================

    for folder_name in folders:

        # ====================================================
        # LIMIT
        # ====================================================

        if (
            processed_this_run
            >= MAX_VIDEOS_PER_RUN
        ):

            print("")
            print(
                f"[INFO] Da dat gioi han "
                f"{MAX_VIDEOS_PER_RUN} video / lan chay."
            )

            break

        folder_path = os.path.join(
            VIDEOS_ROOT,
            folder_name
        )

        # ====================================================
        # CHỈ FOLDER
        # ====================================================

        if not os.path.isdir(
            folder_path
        ):

            continue

        # ====================================================
        # SYSTEM FOLDER
        # ====================================================

        if folder_name.lower() in [
            "downloads",
            "download",
            "da_dang",
            "done",
        ]:

            print("")
            print(
                "[BO QUA] Folder he thong:"
            )

            print(
                f"         {folder_name}"
            )

            continue

        total += 1

        # ====================================================
        # VIDEO ID
        # ====================================================

        video_id = extract_video_id(
            folder_name
        )

        if not video_id:

            print("")
            print(
                "[LOI] Khong lay duoc video_id:"
            )

            print(
                f"      {folder_name}"
            )

            error_count += 1

            continue

        # ====================================================
        # CHECK LOG
        # ====================================================

        existing = log.get(
            video_id
        )

        if existing is not None:

            status = ""

            if isinstance(
                existing,
                dict
            ):

                status = str(
                    existing.get(
                        "status",
                        ""
                    )
                ).lower().strip()

            # =================================================
            # PUBLISHED
            # =================================================

            if status == PUBLISHED_STATUS:

                print_existing_log(
                    log,
                    video_id,
                    folder_name
                )

                print(
                    "[BO QUA] Video da PUBLISHED."
                )

                print(
                    "         Khong dang lai."
                )

                skip_count += 1

                continue

            # =================================================
            # FAILED -> RETRY
            # =================================================

            if status in RETRY_STATUSES:

                print_existing_log(
                    log,
                    video_id,
                    folder_name
                )

                print(
                    "[RETRY] Video loi trong log."
                )

                print(
                    "        Se thu dang lai."
                )

                retry_count += 1

            # =================================================
            # UNKNOWN
            # =================================================

            else:

                print_existing_log(
                    log,
                    video_id,
                    folder_name
                )

                print(
                    "[RETRY] Status khong phai published."
                )

                print(
                    "        Se thu dang lai."
                )

                retry_count += 1

        # ====================================================
        # FIND VIDEO
        # ====================================================

        video_path = find_video_file(
            folder_path
        )

        if not video_path:

            print("")
            print(
                "[LOI] Khong tim thay video:"
            )

            print(
                f"      {folder_name}"
            )

            print(
                "      Da tim:"
            )

            print(
                "      - final_vi\\final_vi.mp4"
            )

            print(
                "      - root\\final_vi.mp4"
            )

            print(
                "      - recursive"
            )

            # Không ghi failed nếu chưa có video
            # vì đây là lỗi cấu trúc file.

            error_count += 1

            continue

        # ====================================================
        # TITLE + HASHTAGS
        # ====================================================

        title, hashtags = get_title_and_hashtags(
            folder_path
        )

        if not title:

            print("")
            print(
                "[LOI] Khong lay duoc TIEU DE:"
            )

            print(
                f"      {folder_name}"
            )

            print(
                "      Kiem tra file note."
            )

            error_count += 1

            continue

        # ====================================================
        # CAPTION
        # ====================================================

        caption_parts = [
            title
        ]

        if hashtags:

            caption_parts.append(
                " ".join(
                    hashtags
                )
            )

        caption = "\n\n".join(
            caption_parts
        ).strip()

        caption = caption[:2190]

        # ====================================================
        # SCHEDULE
        # ====================================================

        scheduled_time = get_next_schedule_time(
            log,
            reserved_times
        )

        reserved_times.append(
            scheduled_time
        )

        # ====================================================
        # DISPLAY
        # ====================================================

        print("")
        print("=" * 70)

        print(
            "[DANG XU LY]"
        )

        print(
            f"Folder: {folder_name}"
        )

        print("=" * 70)

        print(
            f"  ID       : {video_id}"
        )

        print(
            f"  Video    : {video_path}"
        )

        print(
            f"  Schedule : "
            f"{scheduled_time.strftime('%d/%m/%Y %H:%M')}"
        )

        print("")
        print(
            "  TITLE:"
        )

        print(
            f"  {title}"
        )

        print("")
        print(
            "  HASHTAGS:"
        )

        print(
            f"  {' '.join(hashtags) if hashtags else '(khong co)'}"
        )

        print("")
        print(
            "  CAPTION TIKTOK:"
        )

        print_line()

        print(
            caption
        )

        print_line()

        # ====================================================
        # UPLOAD
        # ====================================================

        success, error_message = upload_video(
            video_path,
            caption,
            scheduled_time
        )

        processed_this_run += 1

        # ====================================================
        # SUCCESS
        # ====================================================

        if success:

            success_count += 1

            save_success_record(
                log,
                video_id,
                folder_name,
                video_path,
                title,
                hashtags,
                caption,
                scheduled_time,
            )

            # -----------------------------------------------
            # MOVE
            # -----------------------------------------------

            moved, result = move_to_done(
                folder_path,
                folder_name
            )

            print("")
            print(
                "[OK] UPLOAD THANH CONG"
            )

            print(
                f"[OK] Video ID : {video_id}"
            )

            print(
                f"[OK] Schedule  : "
                f"{scheduled_time.strftime('%d/%m/%Y %H:%M')}"
            )

            print(
                f"[OK] Status    : published"
            )

            if moved:

                print(
                    "[OK] Da move folder:"
                )

                print(
                    f"     {result}"
                )

            else:

                print("")
                print(
                    "[WARNING] Upload thanh cong"
                )

                print(
                    "          nhung KHONG move duoc folder."
                )

                print(
                    f"          Ly do: {result}"
                )

                print(
                    "          Video van duoc giu"
                )

                print(
                    "          trong log voi status=published."
                )

        # ====================================================
        # FAIL
        # ====================================================

        else:

            error_count += 1

            # -----------------------------------------------
            # Reservation bị bỏ
            # -----------------------------------------------

            if scheduled_time in reserved_times:

                reserved_times.remove(
                    scheduled_time
                )

            # -----------------------------------------------
            # SAVE FAILED
            # -----------------------------------------------

            save_failed_record(
                log,
                video_id,
                folder_name,
                video_path,
                title,
                hashtags,
                caption,
                scheduled_time,
                error_message,
            )

            print("")
            print(
                "[THAT BAI]"
            )

            print(
                f"Folder: {folder_name}"
            )

            print(
                f"ID    : {video_id}"
            )

            print(
                f"Error : {error_message}"
            )

            print("")
            print(
                "[INFO] Da ghi status=failed vao log."
            )

            print(
                "[INFO] Lan chay sau se TU DONG RETRY."
            )

            print(
                "[INFO] Khong move folder."
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("")
    print("=" * 70)
    print(
        " HOAN TAT"
    )
    print("=" * 70)

    print(
        f"Tong folder       : {total}"
    )

    print(
        f"Upload thanh cong : {success_count}"
    )

    print(
        f"Retry gap          : {retry_count}"
    )

    print(
        f"Bo qua             : {skip_count}"
    )

    print(
        f"Loi                : {error_count}"
    )

    print(
        f"Xu ly lan nay      : {processed_this_run}"
    )

    print("")
    print(
        "Log:"
    )

    print(
        f"  {LOG_FILE}"
    )

    print("")
    print(
        "Done:"
    )

    print(
        f"  {DONE_DIR}"
    )

    print("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
