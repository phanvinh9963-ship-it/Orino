"""
core/editor_model.py
Mô hình dữ liệu của Editor (kiểu CapCut) - KHÔNG phụ thuộc giao diện, để dễ test.

Dự án gồm 5 "lane" (track) cố định, từ trên xuống dưới:
    sub    Phụ đề     (chữ theo thời gian, có danh sách riêng để sửa nhanh)
    text   Chữ        (chữ tự do: tiêu đề, watermark chữ...)
    voice  Giọng đọc  (âm thanh lồng tiếng - tự "hạ tiếng gốc" khi có giọng)
    music  Âm thanh   (nhạc nền, hiệu ứng)
    video  Hình       (track chính, "nam châm": các clip luôn nối liền từ 0s)

Mọi thao tác sửa nên bọc trong `with project.edit():` (hoặc begin()/commit()
khi kéo chuột) để Ctrl+Z / Ctrl+Y hoạt động.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict, fields
from typing import Dict, List, Optional, Tuple

LANES = ("sub", "text", "voice", "music", "video")
LANE_LABEL = {"sub": "Phụ đề", "text": "Chữ", "voice": "Giọng đọc", "music": "Âm thanh", "video": "Hình"}
MEDIA_LANES = ("video", "voice", "music")
MIN_DUR = 0.1
STILL_DEFAULT_DUR = 5.0
_UNDO_LIMIT = 100
_STYLE_KEYS = ("size", "color", "outline", "x", "y", "box")


@dataclass
class Clip:
    lane: str
    start: float
    dur: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    # --- media (video / voice / music) ---
    src: str = ""
    src_in: float = 0.0        # điểm bắt đầu trong file nguồn (giây)
    src_len: float = 0.0       # tổng độ dài file nguồn (0 = không giới hạn, vd ảnh)
    speed: float = 1.0
    vol: float = 1.0           # 1.0 = 100%
    has_audio: bool = True
    still: bool = False        # ảnh tĩnh
    name: str = ""
    # --- chữ (sub / text) ---
    text: str = ""
    size: int = 56             # tính theo khung cao 1080, tự co theo độ phân giải xuất
    color: str = "#FFFFFF"
    outline: str = "#000000"
    x: float = 0.5             # vị trí tâm chữ (0..1 theo chiều rộng / cao khung hình)
    y: float = 0.86
    box: bool = False          # nền hộp mờ sau chữ

    @property
    def end(self) -> float:
        return self.start + self.dur

    @property
    def is_media(self) -> bool:
        return self.lane in MEDIA_LANES

    @property
    def is_caption(self) -> bool:
        return self.lane in ("sub", "text")

    @property
    def src_out(self) -> float:
        return self.src_in + self.dur * self.speed

    def max_dur(self) -> float:
        """Độ dài tối đa trên timeline khi kéo dài đuôi (giới hạn bởi file nguồn)."""
        if not self.is_media or self.still or self.src_len <= 0:
            return float("inf")
        return max(MIN_DUR, (self.src_len - self.src_in) / max(self.speed, 0.01))


def _clip_from_dict(d: dict) -> Clip:
    names = {f.name for f in fields(Clip)}
    return Clip(**{k: v for k, v in d.items() if k in names})


# ----------------------------------------------------------------------------
# SRT
# ----------------------------------------------------------------------------
_TS = re.compile(
    r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})"
)


def parse_srt(text: str) -> List[Tuple[float, float, str]]:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.split("\n")]
        for i, line in enumerate(lines):
            m = _TS.search(line)
            if m:
                g = m.groups()
                s = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3].ljust(3, "0")) / 1000
                e = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7].ljust(3, "0")) / 1000
                body = "\n".join(lines[i + 1:]).strip()
                if body and e > s:
                    out.append((s, e, body))
                break
    return out


def _srt_time(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_srt(items) -> str:
    parts = []
    for i, (s, e, txt) in enumerate(items, 1):
        parts.append(f"{i}\n{_srt_time(s)} --> {_srt_time(e)}\n{txt}\n")
    return "\n".join(parts)


# ----------------------------------------------------------------------------
# Project
# ----------------------------------------------------------------------------
class Project:
    def __init__(self):
        self.clips: List[Clip] = []
        self.w, self.h, self.fps = 1920, 1080, 30.0
        self.duck = True               # tự hạ tiếng gốc khi có giọng đọc
        self.font = "Arial"
        self.path: Optional[str] = None
        self.dirty = False
        self.rev = 0                   # tăng mỗi khi nội dung đổi (UI/cache dùng để biết cần làm mới)
        self._undo: List[str] = []
        self._redo: List[str] = []
        self._pending: Optional[str] = None

    # ---------- trạng thái / undo ----------
    def _state(self) -> str:
        return json.dumps(
            {"w": self.w, "h": self.h, "fps": self.fps, "duck": self.duck, "font": self.font,
             "clips": [asdict(c) for c in self.clips]},
            ensure_ascii=False,
        )

    def _restore(self, s: str):
        d = json.loads(s)
        self.w, self.h, self.fps = d["w"], d["h"], d["fps"]
        self.duck, self.font = d.get("duck", True), d.get("font", "Arial")
        self.clips = [_clip_from_dict(c) for c in d["clips"]]

    def begin(self):
        if self._pending is None:
            self._pending = self._state()

    def commit(self) -> bool:
        before, self._pending = self._pending, None
        if before is None or before == self._state():
            return False
        self._undo.append(before)
        del self._undo[:-_UNDO_LIMIT]
        self._redo.clear()
        self.dirty = True
        self.rev += 1
        return True

    @contextmanager
    def edit(self):
        self.begin()
        try:
            yield self
        finally:
            self.commit()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._state())
        self._restore(self._undo.pop())
        self.dirty, self.rev = True, self.rev + 1
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._state())
        self._restore(self._redo.pop())
        self.dirty, self.rev = True, self.rev + 1
        return True

    # ---------- truy vấn ----------
    def lane(self, name: str) -> List[Clip]:
        return sorted((c for c in self.clips if c.lane == name), key=lambda c: (c.start, c.id))

    def get(self, cid: Optional[str]) -> Optional[Clip]:
        for c in self.clips:
            if c.id == cid:
                return c
        return None

    @property
    def duration(self) -> float:
        v = self.lane("video")
        return v[-1].end if v else 0.0

    def video_at(self, t: float):
        """(clip, thời điểm tương ứng trong file nguồn) tại thời điểm t của timeline."""
        vids = self.lane("video")
        for c in vids:
            if c.start - 1e-6 <= t < c.end:
                return c, c.src_in + (t - c.start) * c.speed
        if vids and t >= vids[-1].end:
            c = vids[-1]
            return c, c.src_out
        return None, 0.0

    def captions_at(self, t: float) -> List[Clip]:
        return [c for c in self.clips if c.is_caption and c.start <= t < c.end]

    def missing_media(self) -> List[str]:
        return sorted({c.src for c in self.clips if c.is_media and c.src and not os.path.isfile(c.src)})

    # ---------- thêm ----------
    def add_video(self, path: str, info: dict) -> Clip:
        """Nối thêm 1 video/ảnh vào CUỐI track Hình. `info`: xem core.editor_media.probe()."""
        if not self.lane("video"):
            self.w, self.h = int(info["w"]) // 2 * 2, int(info["h"]) // 2 * 2
            self.fps = min(60.0, max(10.0, float(info.get("fps") or 30.0)))
        still = bool(info.get("still"))
        dur = STILL_DEFAULT_DUR if still else max(MIN_DUR, float(info["duration"]))
        c = Clip("video", self.duration, dur, src=path, src_len=0.0 if still else dur,
                 has_audio=bool(info.get("has_audio")) and not still, still=still,
                 name=os.path.basename(path))
        self.clips.append(c)
        return c

    def add_audio(self, lane: str, path: str, info: dict, at: float = 0.0) -> Clip:
        assert lane in ("voice", "music")
        dur = max(MIN_DUR, float(info["duration"]))
        c = Clip(lane, max(0.0, at), dur, src=path, src_len=dur, name=os.path.basename(path))
        self.clips.append(c)
        return c

    def add_text(self, at: float, text: str = "Chữ mới", dur: float = 3.0, lane: str = "text") -> Clip:
        c = Clip(lane, max(0.0, at), dur, text=text, y=0.5 if lane == "text" else 0.86)
        self.clips.append(c)
        return c

    def set_subs(self, items: List[Tuple[float, float, str]]):
        self.clips = [c for c in self.clips if c.lane != "sub"]
        self.clips += [Clip("sub", s, e - s, text=t) for s, e, t in items]

    # ---------- sửa ----------
    def relayout_video(self, dragged_id: Optional[str] = None):
        """Track Hình luôn liền mạch từ 0s (kiểu nam châm). Clip đang kéo được xếp theo TÂM
        của nó, các clip khác theo điểm đầu - kéo qua nửa clip bên cạnh là hoán đổi chỗ."""
        vids = [c for c in self.clips if c.lane == "video"]
        vids.sort(key=lambda c: (c.start + (c.dur / 2 if c.id == dragged_id else 0.0), c.id))
        t = 0.0
        for c in vids:
            c.start = t
            t += c.dur

    def split(self, cid: str, t: float) -> Optional[Clip]:
        c = self.get(cid)
        if not c or not (c.start + MIN_DUR < t < c.end - MIN_DUR):
            return None
        right = _clip_from_dict(asdict(c))
        right.id = uuid.uuid4().hex[:8]
        right.start = t
        right.dur = c.end - t
        if c.is_media:
            right.src_in = c.src_in + (t - c.start) * c.speed
        c.dur = t - c.start
        self.clips.append(right)
        if c.lane == "video":
            self.relayout_video()
        return right

    def delete(self, cid: str, ripple_all: bool = True):
        c = self.get(cid)
        if not c:
            return
        self.clips.remove(c)
        if c.lane == "video":
            if ripple_all:
                self.ripple_cut(c.start, c.end)
            self.relayout_video()

    def ripple_cut(self, s: float, e: float):
        """Cắt bỏ khoảng [s, e) khỏi MỌI track không phải Hình: clip nằm trọn trong khoảng
        bị xoá, clip nằm sau được dồn lại, clip gối lên biên được cắt gọn - phụ đề/giọng đọc
        vẫn khớp với hình sau khi cắt."""
        gap = e - s
        for c in list(self.clips):
            if c.lane == "video":
                continue
            cs, ce = c.start, c.end
            if ce <= s:
                continue
            if cs >= e:
                c.start = cs - gap
            elif cs >= s and ce <= e:
                self.clips.remove(c)
            elif cs < s and ce <= e:          # đuôi bị cắt
                c.dur = s - cs
            elif cs >= s and ce > e:          # đầu bị cắt
                if c.is_media:
                    c.src_in += (e - cs) * c.speed
                c.start, c.dur = s, ce - e
            else:                             # bao trùm khoảng cắt
                c.dur -= gap

    def cut_range(self, s: float, e: float) -> float:
        """Cắt bỏ khoảng [s, e) khỏi TOÀN BỘ dự án (hình + phụ đề + giọng + nhạc) và dồn
        phần sau lên - dùng cho "AI rút gọn". Trả về số giây thật sự đã cắt (0 nếu không
        có gì để cắt). Gọi trong `with project.edit():` để hoàn tác được bằng 1 lần Ctrl+Z.
        Khi cắt nhiều đoạn, hãy cắt từ CUỐI timeline về ĐẦU để mốc thời gian của các đoạn
        trước không bị lệch."""
        s, e = max(0.0, s), min(self.duration, e)
        if e - s < 0.05:
            return 0.0
        for t in (e, s):                                  # tách tại e trước, rồi tại s
            for c in self.lane("video"):
                if c.start + MIN_DUR < t < c.end - MIN_DUR:
                    self.split(c.id, t)
                    break
        victims = [c for c in self.lane("video") if c.start >= s - 0.05 and c.end <= e + 0.05]
        if not victims:
            return 0.0
        a, b = min(c.start for c in victims), max(c.end for c in victims)
        for c in victims:
            self.clips.remove(c)
        self.ripple_cut(a, b)
        self.relayout_video()
        return b - a

    def apply_style_to_all(self, cid: str, lane: str = "sub"):
        src = self.get(cid)
        if not src:
            return
        for c in self.clips:
            if c.lane == lane:
                for k in _STYLE_KEYS:
                    setattr(c, k, getattr(src, k))

    # ---------- xuất / lưu ----------
    def captions_as_srt(self, lane: str = "sub") -> str:
        return format_srt([(c.start, c.end, c.text) for c in self.lane(lane)])

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"version": 1, **json.loads(self._state())}, ensure_ascii=False, indent=1))
        self.path, self.dirty = path, False

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        p = cls()
        p._restore(json.dumps(d))
        p.path = path
        return p
