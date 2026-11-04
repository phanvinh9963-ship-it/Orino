"""
core/speed_adjust.py
Äá»•i tá»‘c Ä‘á»™ phÃ¡t cá»§a Cáº¢ video (hÃ¬nh) láº«n audio (tiáº¿ng), dÃ¹ng ffmpeg.

Táº I SAO Cáº¦N FILE NÃ€Y:
Ká»¹ thuáº­t trÃ¡nh "chá»“ng tiáº¿ng" (giá»ng Ä‘á»c bá»‹ nÃ©n/tÄƒng tá»‘c máº¡nh vÃ¬ cÃ¢u dá»‹ch dÃ i
hÆ¡n khung giá» gá»‘c) mÃ  khÃ´ng cáº§n cáº¯t bá»›t ná»™i dung nhiá»u: LÃ€M CHáº¬M video gá»‘c láº¡i
(vd 0.7x) TRÆ¯á»šC khi cháº¡y transcript/dá»‹ch/TTS - viá»‡c nÃ y giÃ£n háº¿t má»i má»‘c thá»i
gian ra ~1.43 láº§n, nÃªn bÆ°á»›c fit_segments_to_timing (core/text_fit.py) cÃ³ nhiá»u
"chá»— trá»‘ng" hÆ¡n Ä‘á»ƒ giá»ng Ä‘á»c Ä‘á»c háº¿t cÃ¢u á»Ÿ tá»‘c Ä‘á»™ tá»± nhiÃªn, Ã­t pháº£i rÃºt gá»n/
tÄƒng tá»‘c audio. Sau khi ghÃ©p xong video hoÃ n chá»‰nh (hÃ¬nh + giá»ng má»›i), TÄ‚NG Tá»C
láº¡i cáº£ video Ä‘Ã³ lÃªn (vd 1.3x) Ä‘á»ƒ nhá»‹p phim khÃ´ng bá»‹ Ã¬ quÃ¡ so vá»›i gá»‘c.

ÄÃ¢y chÃ­nh lÃ  cÃ¡ch lÃ m thá»§ cÃ´ng quen thuá»™c trÃªn CapCut: giáº£m tá»‘c Ä‘á»™ video gá»‘c
vá» 0.7x -> lá»“ng tiáº¿ng -> tÄƒng tá»‘c video output lÃªn 1.3x.

CÃCH DÃ™NG (tá»« core/pipeline.py):
    from core.speed_adjust import change_video_speed
    slowed_path = change_video_speed(video_path, 0.7, "slowed.mp4")   # lÃ m cháº­m
    final_path  = change_video_speed(dubbed_path, 1.3, "final.mp4")   # tÄƒng tá»‘c láº¡i

LÆ¯U Ã Ká»¸ THUáº¬T:
- speed_factor < 1.0  -> lÃ m CHáº¬M láº¡i (video dÃ i ra)
- speed_factor > 1.0  -> TÄ‚NG Tá»C (video ngáº¯n láº¡i)
- speed_factor = 1.0  -> giá»¯ nguyÃªn, hÃ m sáº½ bÃ¡o lá»—i vÃ¬ khÃ´ng cÃ³ gÃ¬ Ä‘á»ƒ lÃ m (gá»i
  lÃ m gÃ¬ cho tá»‘n thá»i gian encode láº¡i)
- Video (setpts): khÃ´ng giá»›i háº¡n khoáº£ng giÃ¡ trá»‹.
- Audio (atempo): filter atempo cá»§a ffmpeg chá»‰ nháº­n 1 giÃ¡ trá»‹ há»£p lá»‡ trong
  khoáº£ng [0.5, 2.0] cho Má»–I láº§n Ã¡p - náº¿u speed_factor náº±m ngoÃ i khoáº£ng nÃ y
  (vd Ä‘á»•i tá»‘c Ä‘á»™ 3x, 0.3x...), hÃ m sáº½ tá»± Ä‘á»™ng CHAIN nhiá»u atempo liÃªn tiáº¿p
  (vd atempo=2.0,atempo=1.5 cho tá»•ng 3.0x) Ä‘á»ƒ váº«n ra Ä‘Ãºng tá»‰ lá»‡ mong muá»‘n.
- atempo giá»¯ nguyÃªn CAO Äá»˜ giá»ng nÃ³i (khÃ´ng bá»‹ "chuá»™t kÃªu" hay "tráº§m giá»ng"
  nhÆ° khi chá»‰ Ä‘á»•i sample rate thÃ´).
- Cáº§n ffmpeg cÃ³ sáºµn trong PATH (project nÃ y Ä‘Ã£ phá»¥ thuá»™c ffmpeg á»Ÿ nhiá»u chá»—
  khÃ¡c rá»“i - core/voice_sample.py, core/export.py...).
"""
from __future__ import annotations
import os
import subprocess
from typing import Callable, List, Optional


def _atempo_chain(speed_factor: float) -> str:
    """
    Chia speed_factor thÃ nh chuá»—i cÃ¡c atempo=X (má»—i X trong [0.5, 2.0]) ná»‘i báº±ng dáº¥u pháº©y,
    vÃ¬ filter atempo cá»§a ffmpeg khÃ´ng nháº­n giÃ¡ trá»‹ ngoÃ i khoáº£ng nÃ y trong 1 láº§n Ã¡p.
    """
    if speed_factor <= 0:
        raise ValueError(f"speed_factor pháº£i > 0, nháº­n Ä‘Æ°á»£c: {speed_factor}")

    factors: List[float] = []
    remaining = speed_factor
    # TÃ¡ch dáº§n cÃ¡c há»‡ sá»‘ 2.0 (náº¿u remaining > 2.0) hoáº·c 0.5 (náº¿u remaining < 0.5)
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={f:.6f}" for f in factors)


def change_video_speed(
    input_path: str,
    speed_factor: float,
    output_path: str,
    keep_audio: bool = True,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Äá»•i tá»‘c Ä‘á»™ phÃ¡t cá»§a cáº£ video láº«n audio báº±ng Ä‘Ãºng 1 há»‡ sá»‘ `speed_factor`.

    speed_factor < 1.0 : lÃ m CHáº¬M (vd 0.7 = phÃ¡t á»Ÿ 70% tá»‘c Ä‘á»™ gá»‘c, dÃ i ra ~1.43x)
    speed_factor > 1.0 : TÄ‚NG Tá»C (vd 1.3 = phÃ¡t á»Ÿ 130% tá»‘c Ä‘á»™ gá»‘c, ngáº¯n láº¡i)

    keep_audio=False: chá»‰ Ä‘á»•i tá»‘c Ä‘á»™ hÃ¬nh, bá» track audio gá»‘c (dÃ¹ng khi báº¡n sáº½
    tá»± ghÃ©p giá»ng Ä‘á»c má»›i sau, khÃ´ng cáº§n giá»¯ audio gá»‘c Ä‘Ã£ Ä‘á»•i tá»‘c Ä‘á»™ lÃ m gÃ¬).

    Tráº£ vá» output_path náº¿u thÃ nh cÃ´ng.
    """
    if speed_factor <= 0:
        raise ValueError(f"speed_factor pháº£i > 0, nháº­n Ä‘Æ°á»£c: {speed_factor}")
    if abs(speed_factor - 1.0) < 1e-6:
        raise ValueError("speed_factor = 1.0 nghÄ©a lÃ  khÃ´ng Ä‘á»•i gÃ¬ - khÃ´ng cáº§n gá»i hÃ m nÃ y.")
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"KhÃ´ng tÃ¬m tháº¥y file input: {input_path}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # setpts: há»‡ sá»‘ nhÃ¢n PTS (presentation timestamp). Muá»‘n phÃ¡t á»Ÿ speed_factor láº§n tá»‘c
    # Ä‘á»™ gá»‘c thÃ¬ PTS má»›i = PTS_gá»‘c / speed_factor (vd cháº­m 0.7x -> PTS *1/0.7 -> dÃ i ra).
    setpts_factor = 1.0 / speed_factor
    video_filter = f"setpts={setpts_factor:.6f}*PTS"

    if progress_cb:
        direction = "lÃ m cháº­m" if speed_factor < 1.0 else "tÄƒng tá»‘c"
        progress_cb(0.0, f"Äang {direction} video ({speed_factor}x)...")

    if keep_audio:
        audio_filter = _atempo_chain(speed_factor)
        filter_complex = f"[0:v]{video_filter}[v];[0:a]{audio_filter}[a]"
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-filter:v", video_filter,
            "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            output_path,
        ]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0 or not os.path.exists(output_path):
        raise RuntimeError(f"ffmpeg Ä‘á»•i tá»‘c Ä‘á»™ video tháº¥t báº¡i:\n{proc.stdout[-2000:]}")

    if progress_cb:
        progress_cb(1.0, f"ÄÃ£ Ä‘á»•i tá»‘c Ä‘á»™ video xong ({speed_factor}x)")

    return output_path

