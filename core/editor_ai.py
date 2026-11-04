"""
core/editor_ai.py
AI gợi ý ĐOẠN THỪA để cắt rút gọn video (giữ chân người xem) - dùng cho tab "✨ AI" của Editor.

Cách làm: gửi cho Gemini (qua Gemini Web2API chạy sẵn ở http://127.0.0.1:8000, chuẩn
OpenAI /v1/chat/completions) LỜI THOẠI có mốc thời gian + vài KHUNG HÌNH mẫu của video,
yêu cầu trả về danh sách đoạn nên cắt (JSON). Kết quả được làm sạch: kẹp trong độ dài
video, gộp đoạn chồng nhau, căn mép theo ranh giới câu thoại (không cắt ngang câu),
bỏ đoạn rơi vào 3 giây đầu (hook) và giới hạn tổng lượng cắt theo mức đã chọn.

Nếu server không nhận hình (lỗi HTTP) thì tự thử lại chỉ với lời thoại.
Chỉ dùng thư viện chuẩn + ffmpeg (đã có trong dự án), không cần cài thêm gì.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from core import editor_media as M
from core.editor_model import Project, parse_srt

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_MODEL = "gemini-3.6-flash"

HEAD_PROTECT = 3.0        # giây đầu video (hook) - không đề xuất cắt
MIN_CUT = 0.8             # đoạn cắt ngắn hơn mức này thì bỏ qua
WINDOW = 600.0            # video dài hơn ~12 phút thì chia cửa sổ 10 phút
MAX_FRAMES = 20           # số khung hình tối đa gửi cho mỗi cửa sổ
FRAME_W = 384

# mức rút gọn: (nhãn, % mong muốn cho prompt, trần % tổng lượng cắt)
LEVELS = {
    "Nhẹ (~5-10%)":   ("5-10%", 0.12),
    "Vừa (~10-20%)":  ("10-20%", 0.25),
    "Mạnh (~20-30%)": ("20-30%", 0.38),
}
KIND_LABEL = {
    "repeat": "Lặp ý",
    "filler": "Dông dài",
    "dead_air": "Khoảng lặng",
    "slow": "Chậm/lê thê",
    "off_topic": "Lạc đề",
    "redundant_visual": "Cảnh lặp",
}


class AIError(RuntimeError):
    pass


class AICancelled(Exception):
    pass


@dataclass
class Suggestion:
    start: float
    end: float
    kind: str = "slow"
    reason: str = ""
    priority: int = 2          # 1 = nên cắt nhất / an toàn nhất

    @property
    def dur(self) -> float:
        return self.end - self.start


@dataclass
class Result:
    suggestions: List[Suggestion]
    summary: str = ""
    used_frames: bool = False
    note: str = ""


def _ts(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:04.1f}"


# ----------------------------------------------------------------------------
# Nguồn lời thoại
# ----------------------------------------------------------------------------
def collect_subs(p: Project, video_hint: Optional[str] = None) -> List[Tuple[float, float, str]]:
    """Lời thoại theo timeline: ưu tiên track Phụ đề của dự án; nếu trống (vd video đã
    đốt phụ đề nên không nạp .srt) thì đọc translated.srt nằm cạnh file video."""
    subs = [(c.start, c.end, c.text.replace("\n", " ").strip()) for c in p.lane("sub") if c.text.strip()]
    if subs:
        return subs
    vids = p.lane("video")
    src = video_hint or (vids[0].src if vids else "")
    if src:
        cand = os.path.join(os.path.dirname(src), "translated.srt")
        if os.path.isfile(cand):
            try:
                with open(cand, "r", encoding="utf-8-sig", errors="replace") as f:
                    return [(s, e, t.replace("\n", " ").strip()) for s, e, t in parse_srt(f.read())]
            except Exception:
                pass
    return []


# ----------------------------------------------------------------------------
# Khung hình mẫu
# ----------------------------------------------------------------------------
def sample_frames(p: Project, t0: float, t1: float, n: int,
                  cancel: Optional[threading.Event] = None) -> List[Tuple[float, bytes]]:
    """Lấy n khung hình JPEG nhỏ, cách đều trong [t0, t1) của timeline."""
    out: List[Tuple[float, bytes]] = []
    n = max(1, n)
    step = (t1 - t0) / n
    for i in range(n):
        if cancel is not None and cancel.is_set():
            raise AICancelled()
        t = t0 + step * (i + 0.5)
        clip, src_t = p.video_at(t)
        if clip is None or clip.still or not clip.src or not os.path.isfile(clip.src):
            continue
        cmd = [M.ffmpeg_exe(), "-v", "error", "-ss", f"{max(0.0, src_t):.3f}", "-i", clip.src,
               "-frames:v", "1", "-vf", f"scale={FRAME_W}:-2", "-q:v", "6",
               "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        try:
            r = M._run(cmd, timeout=40)
        except Exception:
            continue
        if r.returncode == 0 and r.stdout:
            out.append((t, r.stdout))
    return out


# ----------------------------------------------------------------------------
# Prompt
# ----------------------------------------------------------------------------
def build_prompt(w0: float, w1: float, duration: float, level_text: str,
                 subs: List[Tuple[float, float, str]], frame_times: List[float]) -> str:
    lines = [f"[{s:.1f}-{e:.1f}] {t}" for s, e, t in subs if e > w0 and s < w1]
    transcript = "\n".join(lines) if lines else "(không có lời thoại - hãy dựa vào khung hình)"
    frames = ", ".join(f"{t:.0f}s" for t in frame_times) if frame_times else "(không có)"
    return f"""You are a video retention editor. Tighten this video so viewers do not drop off, WITHOUT losing the story or key information.

Video length: {duration:.1f}s. Analyse ONLY the window {w0:.1f}s - {w1:.1f}s.
Target: remove about {level_text} of this window.

Find segments to REMOVE. Allowed types:
- repeat: the same idea or information said again
- filler: rambling, filler phrases, unnecessary explanation
- dead_air: silence, or a static picture with nothing happening
- slow: slow, drawn-out parts that add little
- off_topic: tangents that do not serve the main story
- redundant_visual: repeated or near-identical shots

Rules:
- NEVER cut the first {HEAD_PROTECT:.0f} seconds (the hook) or the final call-to-action / ending line.
- Never cut key facts, punchlines, twists or the emotional peak.
- Cut on sentence boundaries: use the subtitle timestamps below. Every cut must be at least {MIN_CUT:.0f} second.
- All cuts must lie inside the window. Cuts must not overlap.
- If nothing is worth removing, return an empty list.

Dialogue with timestamps in seconds:
{transcript}

Attached images are sample frames taken at these seconds: {frames}.

Reply with ONLY this JSON (no markdown, no commentary):
{{"cuts":[{{"start":12.5,"end":18.0,"type":"repeat","reason":"<Vietnamese, max 15 words>","priority":1}}],"summary":"<Vietnamese, one sentence>"}}
priority: 1 = most recommended / safest to cut, 3 = optional."""


# ----------------------------------------------------------------------------
# Gọi server (OpenAI-compatible)
# ----------------------------------------------------------------------------
def _endpoint(base_url: str) -> str:
    b = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    return b + ("/chat/completions" if b.endswith("/v1") else "/v1/chat/completions")


def chat(base_url: str, api_key: Optional[str], model: str, prompt: str,
         frames: List[Tuple[float, bytes]], timeout: float = 240.0) -> str:
    if frames:
        content = [{"type": "text", "text": prompt}]
        for t, jpg in frames:
            content.append({"type": "text", "text": f"Frame at {t:.0f}s:"})
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode("ascii")}})
    else:
        content = prompt
    body = json.dumps({"model": model or DEFAULT_MODEL, "temperature": 0.2,
                       "messages": [{"role": "user", "content": content}]}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(_endpoint(base_url), data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise AIError(f"Server trả lỗi HTTP {e.code}. {detail}".strip())
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise AIError(f"Không kết nối được tới {base_url or DEFAULT_BASE_URL} ({e}). "
                      f"Gemini Web2API đã chạy chưa? (bật ở tab Translate)")
    try:
        return data["choices"][0]["message"]["content"] or ""
    except Exception:
        raise AIError("Server trả về dữ liệu không đúng định dạng OpenAI.")


def parse_cuts(text: str) -> Tuple[List[dict], str]:
    """Rút JSON từ câu trả lời (chịu được ```json ... ``` hoặc chữ thừa quanh JSON)."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    obj = None
    pairs = [(t.find(o), o, c) for o, c in (("{", "}"), ("[", "]")) if t.find(o) != -1]
    for i, opener, closer in sorted(pairs):          # thử ký tự xuất hiện TRƯỚC (list trần hay {"cuts":..})
        j = t.rfind(closer)
        if j > i:
            try:
                obj = json.loads(t[i:j + 1])
                break
            except Exception:
                continue
    if obj is None:
        raise AIError("AI trả lời không phải JSON hợp lệ. Thử bấm phân tích lại.")
    if isinstance(obj, list):
        return obj, ""
    if "cuts" not in obj and "segments" not in obj and "start" in obj and "end" in obj:
        return [obj], ""                                # AI chỉ trả đúng 1 đoạn
    cuts = obj.get("cuts") or obj.get("segments") or []
    return (cuts if isinstance(cuts, list) else []), str(obj.get("summary") or "")


# ----------------------------------------------------------------------------
# Làm sạch kết quả
# ----------------------------------------------------------------------------
def normalize(raw: List[dict], duration: float, subs: List[Tuple[float, float, str]],
              max_ratio: float, window: Optional[Tuple[float, float]] = None) -> List[Suggestion]:
    w0, w1 = window if window else (0.0, duration)
    items: List[Suggestion] = []
    for d in raw:
        try:
            s, e = float(d["start"]), float(d["end"])
        except Exception:
            continue
        if e < s:
            s, e = e, s
        s, e = max(s, w0, 0.0), min(e, w1, duration)
        if e <= HEAD_PROTECT:
            continue
        for a, b, _ in subs:                       # không cắt ngang câu: mở rộng ra mép câu
            if a < s < b:
                s = a
            if a < e < b:
                e = b
        s, e = max(0.0, s), min(duration, e)
        if e - s < MIN_CUT:
            continue
        kind = str(d.get("type") or "slow")
        kind = kind if kind in KIND_LABEL else "slow"
        try:
            pr = min(3, max(1, int(d.get("priority", 2))))
        except Exception:
            pr = 2
        items.append(Suggestion(s, e, kind, str(d.get("reason") or "").strip(), pr))

    items.sort(key=lambda x: x.start)              # gộp các đoạn chồng / sát nhau
    merged: List[Suggestion] = []
    for it in items:
        if merged and it.start <= merged[-1].end + 0.3:
            m = merged[-1]
            if it.dur > m.dur:
                m.kind, m.reason = it.kind, it.reason
            m.end, m.priority = max(m.end, it.end), min(m.priority, it.priority)
        else:
            merged.append(it)

    cap = duration * max_ratio                     # trần tổng lượng cắt
    if sum(m.dur for m in merged) > cap:
        kept, total = [], 0.0
        for m in sorted(merged, key=lambda x: (x.priority, -x.dur)):
            if total + m.dur <= cap:
                kept.append(m)
                total += m.dur
        merged = sorted(kept, key=lambda x: x.start)
    return merged


def _windows(duration: float) -> List[Tuple[float, float]]:
    if duration <= WINDOW * 1.2:
        return [(0.0, duration)]
    out, t = [], 0.0
    while t < duration:
        out.append((t, min(duration, t + WINDOW)))
        t += WINDOW
    if len(out) > 1 and out[-1][1] - out[-1][0] < 120:
        last = out.pop()
        out[-1] = (out[-1][0], last[1])
    return out


# ----------------------------------------------------------------------------
# Chạy phân tích
# ----------------------------------------------------------------------------
def analyze(p: Project, base_url: str, api_key: Optional[str], model: str, level: str,
            use_frames: bool = True, progress: Optional[Callable[[float, str], None]] = None,
            cancel: Optional[threading.Event] = None) -> Result:
    cancel = cancel or threading.Event()
    say = progress or (lambda f, m: None)
    duration = p.duration
    if duration <= 0:
        raise AIError("Chưa có video trong dự án.")
    level_text, max_ratio = LEVELS.get(level, LEVELS["Vừa (~10-20%)"])
    subs = collect_subs(p)
    if not subs and not use_frames:
        raise AIError("Video chưa có lời thoại/phụ đề. Bật 'Gửi kèm khung hình' hoặc nhập phụ đề trước.")

    wins = _windows(duration)
    all_raw: List[Suggestion] = []
    summaries: List[str] = []
    used_frames, note = False, ""
    frames_ok = use_frames

    for wi, (w0, w1) in enumerate(wins):
        base = wi / len(wins)
        span = 1.0 / len(wins)
        frames: List[Tuple[float, bytes]] = []
        if frames_ok:
            say(base, f"Đang lấy khung hình mẫu ({wi + 1}/{len(wins)})...")
            n = int(min(MAX_FRAMES, max(6, (w1 - w0) / 12)))
            frames = sample_frames(p, w0, w1, n, cancel)
        if cancel.is_set():
            raise AICancelled()
        prompt = build_prompt(w0, w1, duration, level_text, subs, [t for t, _ in frames])
        say(base + span * 0.4, f"AI đang xem video ({wi + 1}/{len(wins)})...")
        try:
            text = chat(base_url, api_key, model, prompt, frames)
            if frames:
                used_frames = True
        except AIError as e:
            if not frames or not subs or "kết nối" in str(e):
                raise
            note = "Server không nhận hình - đã phân tích bằng lời thoại."
            frames_ok = False
            say(base + span * 0.5, "Thử lại chỉ bằng lời thoại...")
            text = chat(base_url, api_key, model, build_prompt(w0, w1, duration, level_text, subs, []), [])
        if cancel.is_set():
            raise AICancelled()
        raw, summary = parse_cuts(text)
        if summary:
            summaries.append(summary)
        all_raw += normalize(raw, duration, subs, 1.0, (w0, w1))
        say(base + span, f"Xong {wi + 1}/{len(wins)}")

    final = normalize([dict(start=x.start, end=x.end, type=x.kind, reason=x.reason, priority=x.priority)
                       for x in all_raw], duration, subs, max_ratio)
    return Result(final, " ".join(summaries[:2]), used_frames, note)
