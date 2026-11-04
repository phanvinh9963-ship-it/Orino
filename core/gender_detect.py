"""
core/gender_detect.py
Tá»± Ä‘á»™ng nháº­n diá»‡n GIá»šI TÃNH ngÆ°á»i nÃ³i (Nam/Ná»¯) cho tá»«ng cÃ¢u thoáº¡i, dá»±a trÃªn cao
Ä‘á»™ giá»ng (pitch/F0 - táº§n sá»‘ cÆ¡ báº£n), Ä‘á»ƒ core/tts.py chá»n Ä‘Ãºng giá»ng Ä‘á»c AI
tÆ°Æ¡ng á»©ng khi video cÃ³ nhiá»u nhÃ¢n váº­t (vd 1 nam + 1 ná»¯ Ä‘á»‘i thoáº¡i).

Táº I SAO DÃ™NG PITCH THAY VÃŒ SPEAKER DIARIZATION (vd pyannote.audio):
Diarization "Ä‘Ãºng nghÄ©a" (tÃ¡ch danh tÃ­nh Tá»ªNG ngÆ°á»i nÃ³i, vd Speaker A/Speaker B)
cáº§n model gated trÃªn HuggingFace (pháº£i xin token + Ä‘á»“ng Ã½ Ä‘iá»u khoáº£n), táº£i model
náº·ng, vÃ  váº«n KHÃ”NG tá»± biáº¿t ai lÃ  Nam ai lÃ  Ná»¯ (chá»‰ biáº¿t "khÃ¡c giá»ng nhau", muá»‘n
suy ra Nam/Ná»¯ váº«n pháº£i phÃ¢n tÃ­ch pitch thÃªm 1 bÆ°á»›c sau). VÃ¬ má»¥c tiÃªu cá»§a báº¡n lÃ 
"nháº­n biáº¿t lá»i thoáº¡i Nam vÃ  Ná»¯" (khÃ´ng cáº§n tÃ¡ch Ä‘Ãºng Tá»ªNG cÃ¡ nhÃ¢n náº¿u cÃ³ >2
ngÆ°á»i cÃ¹ng giá»›i), pitch-based lÃ  Ä‘á»§, nháº¹, cháº¡y offline hoÃ n toÃ n (khÃ´ng cáº§n
internet/token), vÃ  trá»±c tiáº¿p cho ra Ä‘Ãºng nhÃ£n Nam/Ná»¯ cáº§n dÃ¹ng.

CÃCH HOáº T Äá»˜NG:
  1. TrÃ­ch Ã¢m thanh gá»‘c cá»§a video ra 1 file wav (dÃ¹ng láº¡i Ä‘Ãºng file audio mÃ 
     transcribe.py Ä‘Ã£ tÃ¡ch thoáº¡i tá»« Ä‘Ã³ - CÃ™NG timeline, Ä‘á»ƒ khá»›p timestamp).
  2. Vá»›i má»—i cÃ¢u thoáº¡i (SubtitleSegment), cáº¯t Ä‘Ãºng Ä‘oáº¡n audio [start, end],
     tÃ­nh cao Ä‘á»™ trung bÃ¬nh (median F0) báº±ng thuáº­t toÃ¡n pYIN (qua librosa).
  3. Gom Táº¤T Cáº¢ giÃ¡ trá»‹ F0 trung bÃ¬nh cá»§a má»i cÃ¢u láº¡i, cháº¡y 1 vÃ²ng k-means
     Ä‘Æ¡n giáº£n (k=2, tá»± viáº¿t báº±ng numpy, khÃ´ng cáº§n thÃªm thÆ° viá»‡n) Ä‘á»ƒ tá»± Ä‘á»™ng
     tÃ¬m ra 2 "cá»¥m" cao Ä‘á»™ trong CHÃNH video nÃ y (thay vÃ¬ dÃ¹ng 1 ngÆ°á»¡ng cá»‘
     Ä‘á»‹nh cá»©ng nháº¯c nhÆ° 165Hz - vÃ¬ má»—i video/mic cÃ³ thá»ƒ lá»‡ch tÃ´ng khÃ¡c nhau).
  4. Cá»¥m cÃ³ centroid F0 CAO HÆ N -> gÃ¡n nhÃ£n "female", cá»¥m THáº¤P HÆ N -> "male"
     (Ä‘Ãºng Ä‘áº·c Ä‘iá»ƒm sinh lÃ½: giá»ng ná»¯ trung bÃ¬nh cao hÆ¡n giá»ng nam ~1 quÃ£ng
     8, theo cÃ¡c nghiÃªn cá»©u vá» giá»ng nÃ³i).
  5. CÃ¢u nÃ o khÃ´ng Ä‘o Ä‘Æ°á»£c pitch rÃµ rÃ ng (quÃ¡ ngáº¯n, nhiá»…u, khÃ´ng cÃ³ giá»ng nÃ³i
     rÃµ - vd tiáº¿ng Ä‘á»™ng ná»n) -> gÃ¡n táº¡m theo nhÃ£n cá»§a cÃ¢u liá»n trÆ°á»›c (thÆ°á»ng
     Ä‘Ãºng vÃ¬ 1 ngÆ°á»i hay nÃ³i liá»n nhiá»u cÃ¢u).

GIá»šI Háº N Cáº¦N BIáº¾T:
- Chá»‰ phÃ¢n biá»‡t Ä‘Æ°á»£c NAM/Ná»®, khÃ´ng phÃ¢n biá»‡t Ä‘Æ°á»£c 2 ngÆ°á»i CÃ™NG giá»›i tÃ­nh (vd
  2 nhÃ¢n váº­t nam) - trÆ°á»ng há»£p Ä‘Ã³ cáº§n diarization tháº­t (pyannote.audio) má»›i
  tÃ¡ch Ä‘Æ°á»£c, ngoÃ i pháº¡m vi module nÃ y.
- Náº¿u video cÃ³ nháº¡c ná»n to hoáº·c nhiá»u tiáº¿ng á»“n, pitch cÃ³ thá»ƒ Ä‘o sai - nÃªn cháº¡y
  SAU bÆ°á»›c tÃ¡ch vocal (demucs) náº¿u cháº¥t lÆ°á»£ng Ã¢m thanh gá»‘c khÃ´ng tá»‘t (xem
  core/voice_sample.py:separate_vocals - cÃ³ thá»ƒ tÃ¡i sá»­ dá»¥ng á»Ÿ bÆ°á»›c tÃ¡ch audio
  bÃªn dÆ°á»›i náº¿u cáº§n, hiá»‡n táº¡i module nÃ y dÃ¹ng tháº³ng audio gá»‘c cho Ä‘Æ¡n giáº£n/nhanh).

CÃ€I Äáº¶T:
    pip install librosa numpy
(librosa kÃ©o theo scipy, soundfile - Ä‘á»u lÃ  thÆ° viá»‡n thuáº§n Python/C phá»• biáº¿n,
khÃ´ng cáº§n GPU, khÃ´ng cáº§n táº£i model gÃ¬ thÃªm).
"""
from __future__ import annotations
import os
import subprocess
import tempfile
from typing import Callable, List, Optional

from core.transcribe import SubtitleSegment

MIN_F0_HZ = 65.0    # dÆ°á»›i má»©c giá»ng nÃ³i ngÆ°á»i tháº¥p nháº¥t (nam tráº§m) - loáº¡i nhiá»…u
MAX_F0_HZ = 400.0   # trÃªn má»©c giá»ng nÃ³i ngÆ°á»i cao nháº¥t (ná»¯ cao/tráº» em) - loáº¡i nhiá»…u
MIN_VOICED_FRAMES = 5   # cáº§n Ã­t nháº¥t chá»«ng nÃ y frame "cÃ³ giá»ng" má»›i tin káº¿t quáº£ pitch


def _extract_audio(video_path: str, out_wav: str, sr: int = 16000) -> str:
    """TrÃ­ch audio gá»‘c ra wav mono, dÃ¹ng ffmpeg (Ä‘Ã£ lÃ  dependency sáºµn cÃ³ cá»§a project)."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", str(sr),
        out_wav,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0 or not os.path.exists(out_wav):
        raise RuntimeError(f"ffmpeg trÃ­ch audio tháº¥t báº¡i:\n{proc.stdout[-1500:]}")
    return out_wav


def _median_pitch(y, sr: int) -> Optional[float]:
    """TÃ­nh cao Ä‘á»™ (F0) trung bÃ¬nh (median) cá»§a 1 Ä‘oáº¡n audio báº±ng pYIN. None náº¿u khÃ´ng Ä‘á»§ tin cáº­y."""
    import numpy as np
    import librosa

    if len(y) < sr * 0.15:  # Ä‘oáº¡n quÃ¡ ngáº¯n (<150ms) - khÃ´ng Ä‘á»§ Ä‘á»ƒ Ä‘o pitch Ä‘Ã¡ng tin cáº­y
        return None

    try:
        f0, voiced_flag, _ = librosa.pyin(
            y, fmin=MIN_F0_HZ, fmax=MAX_F0_HZ, sr=sr,
            frame_length=2048, hop_length=256,
        )
    except Exception:
        return None

    if f0 is None:
        return None

    voiced_f0 = f0[voiced_flag] if voiced_flag is not None else f0[~np.isnan(f0)]
    voiced_f0 = voiced_f0[~np.isnan(voiced_f0)]
    if len(voiced_f0) < MIN_VOICED_FRAMES:
        return None

    return float(np.median(voiced_f0))


def _kmeans_1d_2clusters(values: List[float], n_iter: int = 50):
    """
    K-means Ä‘Æ¡n giáº£n (k=2) trÃªn máº£ng 1 chiá»u, tá»± viáº¿t báº±ng numpy - Ä‘á»§ dÃ¹ng cho
    bÃ i toÃ¡n tÃ¡ch 2 cá»¥m cao Ä‘á»™ (nam/ná»¯), khÃ´ng cáº§n kÃ©o thÃªm scikit-learn.
    Tráº£ vá» (centroid_thap, centroid_cao) - Ä‘Ã£ sáº¯p xáº¿p tÄƒng dáº§n.
    """
    import numpy as np

    arr = np.array(values, dtype=float)
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-6:
        # Táº¥t cáº£ cÃ¡c cÃ¢u gáº§n nhÆ° cÃ¹ng 1 cao Ä‘á»™ -> khÃ´ng tÃ¡ch Ä‘Æ°á»£c 2 cá»¥m tháº­t sá»±,
        # tráº£ vá» 2 centroid trÃ¹ng nhau Ä‘á»ƒ bÆ°á»›c phÃ¢n loáº¡i sau coi nhÆ° "1 giá»ng".
        return lo, hi

    c1, c2 = lo, hi  # khá»Ÿi táº¡o táº¡i 2 Ä‘iá»ƒm xa nhau nháº¥t, há»™i tá»¥ nhanh vÃ  á»•n Ä‘á»‹nh hÆ¡n random
    for _ in range(n_iter):
        d1 = np.abs(arr - c1)
        d2 = np.abs(arr - c2)
        group1 = arr[d1 <= d2]
        group2 = arr[d1 > d2]
        new_c1 = group1.mean() if len(group1) else c1
        new_c2 = group2.mean() if len(group2) else c2
        if abs(new_c1 - c1) < 1e-4 and abs(new_c2 - c2) < 1e-4:
            c1, c2 = new_c1, new_c2
            break
        c1, c2 = new_c1, new_c2

    return min(c1, c2), max(c1, c2)


def detect_speaker_gender(
    video_path: str,
    segments: List[SubtitleSegment],
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[SubtitleSegment]:
    """
    Tráº£ vá» list SubtitleSegment Má»šI (khÃ´ng sá»­a list gá»‘c), má»—i segment Ä‘Ã£ Ä‘Æ°á»£c
    gÃ¡n `gender` = "male" hoáº·c "female" dá»±a trÃªn cao Ä‘á»™ giá»ng thá»±c táº¿.

    Náº¿u KHÃ”NG Ä‘o Ä‘Æ°á»£c Ä‘á»§ dá»¯ liá»‡u tin cáº­y Ä‘á»ƒ tÃ¡ch 2 cá»¥m (vd video chá»‰ 1 ngÆ°á»i
    nÃ³i, hoáº·c audio quÃ¡ nhiá»…u), táº¥t cáº£ segment sáº½ Ä‘Æ°á»£c gÃ¡n "female" (máº·c Ä‘á»‹nh
    an toÃ n - váº«n dÃ¹ng Ä‘Æ°á»£c 1 giá»ng duy nháº¥t nhÆ° hÃ nh vi cÅ©, khÃ´ng há»ng gÃ¬).
    """
    try:
        import librosa
        import numpy as np
    except ImportError as e:
        raise ImportError(
            "Cáº§n cÃ i Ä‘áº·t: pip install librosa numpy Ä‘á»ƒ dÃ¹ng tÃ­nh nÄƒng tá»± nháº­n diá»‡n Nam/Ná»¯."
        ) from e

    if progress_cb:
        progress_cb(0.0, "Äang trÃ­ch audio gá»‘c Ä‘á»ƒ phÃ¢n tÃ­ch giá»ng nÃ³i...")

    tmp_dir = tempfile.mkdtemp(prefix="gender_detect_")
    sr = 16000
    try:
        wav_path = _extract_audio(video_path, os.path.join(tmp_dir, "full_audio.wav"), sr=sr)
        y_full, _ = librosa.load(wav_path, sr=sr, mono=True)

        total = max(1, len(segments))
        pitches: List[Optional[float]] = []
        for i, seg in enumerate(segments, start=1):
            start_sample = max(0, int(seg.start * sr))
            end_sample = min(len(y_full), int(seg.end * sr))
            clip = y_full[start_sample:end_sample]
            pitches.append(_median_pitch(clip, sr))
            if progress_cb:
                progress_cb(i / total * 0.7, f"Äang Ä‘o cao Ä‘á»™ giá»ng cÃ¢u {i}/{total}...")

        valid_pitches = [p for p in pitches if p is not None]

        if len(valid_pitches) < 2:
            if progress_cb:
                progress_cb(1.0, "âš  KhÃ´ng Ä‘á»§ dá»¯ liá»‡u Ä‘á»ƒ tÃ¡ch Nam/Ná»¯ - dÃ¹ng 1 giá»ng máº·c Ä‘á»‹nh cho cáº£ video")
            return [
                SubtitleSegment(index=s.index, start=s.start, end=s.end, text=s.text, gender="female")
                for s in segments
            ]

        if progress_cb:
            progress_cb(0.8, "Äang phÃ¢n nhÃ³m giá»ng Nam/Ná»¯...")

        c_low, c_high = _kmeans_1d_2clusters(valid_pitches)
        threshold = (c_low + c_high) / 2.0

        out: List[SubtitleSegment] = []
        last_gender = "female"
        n_male, n_female = 0, 0
        for seg, pitch in zip(segments, pitches):
            if pitch is None:
                gender = last_gender  # cÃ¢u khÃ´ng Ä‘o Ä‘Æ°á»£c -> giá»¯ theo giá»ng liá»n trÆ°á»›c (thÆ°á»ng cÃ¹ng ngÆ°á»i nÃ³i)
            else:
                gender = "female" if pitch >= threshold else "male"
            last_gender = gender
            if gender == "male":
                n_male += 1
            else:
                n_female += 1
            out.append(SubtitleSegment(index=seg.index, start=seg.start, end=seg.end, text=seg.text, gender=gender))

        if progress_cb:
            progress_cb(1.0, f"HoÃ n táº¥t nháº­n diá»‡n giá»ng nÃ³i: {n_male} cÃ¢u Nam, {n_female} cÃ¢u Ná»¯")

        return out
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

