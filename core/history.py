"""
core/history.py
LÆ°u vÃ  Ä‘á»c lá»‹ch sá»­ cÃ¡c job Ä‘Ã£ cháº¡y, phá»¥c vá»¥ trang "Job Center".
Dá»¯ liá»‡u lÆ°u á»Ÿ file JSON Ä‘Æ¡n giáº£n, khÃ´ng cáº§n database.
"""
from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, asdict
from typing import List


@dataclass
class JobRecord:
    timestamp: float
    input_video: str
    output_video: str
    srt_path: str
    source_lang: str
    target_lang: str
    subtitles: bool
    dubbing: bool
    watermark: bool
    status: str = "done"          # done | error
    error_msg: str = ""

    def time_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))


def history_path(work_dir: str) -> str:
    return os.path.join(work_dir, "history.json")


def load_history(work_dir: str) -> List[JobRecord]:
    path = history_path(work_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [JobRecord(**item) for item in raw]
    except Exception:
        return []


def append_history(work_dir: str, record: JobRecord) -> None:
    os.makedirs(work_dir, exist_ok=True)
    records = load_history(work_dir)
    records.append(record)
    # giá»¯ tá»‘i Ä‘a 100 job gáº§n nháº¥t
    records = records[-100:]
    with open(history_path(work_dir), "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, ensure_ascii=False, indent=2)

