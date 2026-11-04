"""
core/face_speaker_detect.py
Nháº­n diá»‡n AI ÄANG NÃ“I trong khung hÃ¬nh báº±ng CHUYá»‚N Äá»˜NG MÃ”I (kháº©u hÃ¬nh) qua
MediaPipe Face Mesh, thay vÃ¬ chá»‰ Ä‘oÃ¡n Nam/Ná»¯ theo cao Ä‘á»™ giá»ng nhÆ° core/
gender_detect.py - chÃ­nh xÃ¡c hÆ¡n nhiá»u khi video cÃ³ 2+ khuÃ´n máº·t xuáº¥t hiá»‡n
cÃ¹ng lÃºc, vÃ¬ tháº¥y Ä‘Æ°á»£c TRá»°C TIáº¾P ai Ä‘ang máº¥p mÃ¡y miá»‡ng, khÃ´ng suy Ä‘oÃ¡n giÃ¡n
tiáº¿p qua Ã¢m thanh (dá»… nháº§m khi giá»ng tráº§m/cao láº«n lá»™n, cÃ³ nháº¡c ná»n...).

CÃCH HOáº T Äá»˜NG (tá»•ng quan - Ä‘á»c chi tiáº¿t á»Ÿ docstring tá»«ng hÃ m bÃªn dÆ°á»›i):
  1. Vá»›i Má»–I cÃ¢u thoáº¡i: láº¥y máº«u vÃ i khung hÃ¬nh ráº£i Ä‘á»u trong [start, end].
  2. á»ž má»—i khung hÃ¬nh máº«u: MediaPipe Face Mesh tÃ¬m táº¥t cáº£ khuÃ´n máº·t, tÃ­nh
     "Ä‘á»™ má»Ÿ miá»‡ng" (khoáº£ng cÃ¡ch mÃ´i trÃªn-dÆ°á»›i, chuáº©n hoÃ¡ theo chiá»u cao máº·t)
     cho tá»«ng khuÃ´n máº·t.
  3. Khá»›p khuÃ´n máº·t giá»¯a cÃ¡c khung hÃ¬nh LIÃŠN TIáº¾P trong CÃ™NG 1 cÃ¢u (theo vá»‹
     trÃ­ gáº§n nhau) thÃ nh tá»«ng "track" - giáº£ Ä‘á»‹nh khÃ´ng cáº¯t cáº£nh giá»¯a 1 cÃ¢u
     (há»£p lÃ½ vÃ¬ má»—i cÃ¢u chá»‰ dÃ i 1-4 giÃ¢y).
  4. Track cÃ³ Äá»˜ Má»ž MIá»†NG BIáº¾N THIÃŠN (phÆ°Æ¡ng sai) CAO NHáº¤T trong sá»‘ cÃ¡c track
     á»Ÿ cÃ¢u Ä‘Ã³ -> Ä‘Ã¢y lÃ  khuÃ´n máº·t ÄANG NÃ“I (ngÆ°á»i khÃ´ng nÃ³i miá»‡ng khÃ¡ tÄ©nh).
  5. Láº¥y histogram mÃ u (Ä‘áº·c trÆ°ng ngoáº¡i hÃ¬nh Ä‘Æ¡n giáº£n) cá»§a khuÃ´n máº·t Ä‘ang nÃ³i
     á»Ÿ Má»–I cÃ¢u, gom toÃ n bá»™ Ä‘áº·c trÆ°ng nÃ y cá»§a Cáº¢ VIDEO láº¡i, cháº¡y k-means (k=2
     máº·c Ä‘á»‹nh) -> cÃ¡c cÃ¢u do CÃ™NG 1 ngÆ°á»i nÃ³i (dÃ¹ khÃ´ng liÃªn tiáº¿p, khÃ¡c cáº£nh)
     Ä‘Æ°á»£c gÃ¡n chung 1 `speaker_id`.
  6. Vá»›i má»—i speaker_id: gá»™p pitch (cao Ä‘á»™ giá»ng, Ä‘o báº±ng core/gender_detect.py)
     cá»§a Táº¤T Cáº¢ cÃ¢u thuá»™c nhÃ³m Ä‘Ã³, láº¥y median CHUNG -> quyáº¿t Ä‘á»‹nh Nam/Ná»¯ theo
     Cáº¢ NHÃ“M (á»•n Ä‘á»‹nh hÆ¡n háº³n quyáº¿t Ä‘á»‹nh láº» tá»«ng cÃ¢u cá»§a báº£n gender_detect.py
     gá»‘c - Ä‘Ã¢y chÃ­nh lÃ  nguyÃªn nhÃ¢n "nháº­n diá»‡n sai/lung tung" báº¡n gáº·p pháº£i).

GIá»šI Háº N Cáº¦N BIáº¾T (thÃ nh tháº­t Ä‘á»ƒ báº¡n lÆ°á»ng trÆ°á»›c, khÃ´ng pháº£i "AI nháº­n diá»‡n
khuÃ´n máº·t hoÃ n háº£o"):
  - Äáº·c trÆ°ng ngoáº¡i hÃ¬nh dÃ¹ng histogram mÃ u HSV Ä‘Æ¡n giáº£n (KHÃ”NG pháº£i model
    face recognition chuyÃªn sÃ¢u nhÆ° FaceNet/ArcFace) - Ä‘á»§ tá»‘t khi 2 nhÃ¢n váº­t
    cÃ³ tÃ´ng mÃ u/trang phá»¥c khÃ¡c biá»‡t rÃµ, sáº½ kÃ©m chÃ­nh xÃ¡c hÆ¡n náº¿u 2 nhÃ¢n váº­t
    Äƒn máº·c/tÃ´ng da tÆ°Æ¡ng Ä‘á»“ng hoáº·c Ã¡nh sÃ¡ng cáº£nh quay thay Ä‘á»•i nhiá»u.
  - Viá»‡c khá»›p track khuÃ´n máº·t CHá»ˆ hoáº¡t Ä‘á»™ng TRONG PHáº M VI 1 cÃ¢u thoáº¡i (khÃ´ng
    coi lÃ  cáº¯t cáº£nh giá»¯a cÃ¢u) - viá»‡c "cÃ¹ng 1 ngÆ°á»i dÃ¹ khÃ¡c cáº£nh" chá»‰ Ä‘Æ°á»£c ná»‘i
    láº¡i qua bÆ°á»›c phÃ¢n cá»¥m k-means á»Ÿ bÆ°á»›c 5, khÃ´ng pháº£i theo dÃµi (tracking)
    xuyÃªn suá»‘t cáº£ video.
  - Cáº§n khuÃ´n máº·t xuáº¥t hiá»‡n RÃ•, Äá»¦ Lá»šN, KHÃ”NG Bá»Š CHE trong khung hÃ¬nh - cáº£nh
    quay xa/má»/quay lÆ°ng sáº½ khÃ´ng detect Ä‘Æ°á»£c, cÃ¢u Ä‘Ã³ tá»± Ä‘á»™ng fallback dÃ¹ng
    káº¿t quáº£ pitch riÃªng láº» (giá»‘ng hÃ nh vi cÅ©) thay vÃ¬ crash.
  - CHáº¬M hÆ¡n core/gender_detect.py vÃ¬ pháº£i Ä‘á»c vÃ  xá»­ lÃ½ HÃŒNH áº¢NH (khÃ´ng chá»‰
    audio) - Ä‘Ã£ tá»‘i Æ°u báº±ng cÃ¡ch chá»‰ láº¥y máº«u vÃ i khung hÃ¬nh/cÃ¢u (máº·c Ä‘á»‹nh 6),
    khÃ´ng quÃ©t toÃ n bá»™ video theo tá»«ng frame.

CÃ€I Äáº¶T:
    pip install mediapipe opencv-python numpy librosa
"""
from __future__ import annotations
import os
from typing import Callable, Dict, List, Optional, Tuple

from core.transcribe import SubtitleSegment
from core.gender_detect import _extract_audio, _median_pitch, _kmeans_1d_2clusters

# Chá»‰ sá»‘ landmark mÃ´i (theo chuáº©n 468 Ä‘iá»ƒm cá»§a MediaPipe Face Mesh)
MOUTH_TOP = 13       # mÃ´i trÃªn (máº·t trong)
MOUTH_BOTTOM = 14    # mÃ´i dÆ°á»›i (máº·t trong)
FACE_TOP = 10        # trÃ¡n
FACE_BOTTOM = 152    # cáº±m - dÃ¹ng lÃ m chiá»u cao máº·t Ä‘á»ƒ chuáº©n hoÃ¡ Ä‘á»™ má»Ÿ miá»‡ng

N_SAMPLES_PER_SEGMENT = 6         # sá»‘ khung hÃ¬nh láº¥y máº«u má»—i cÃ¢u thoáº¡i
MATCH_DIST_THRESHOLD = 0.15       # ngÆ°á»¡ng khoáº£ng cÃ¡ch (tá»‰ lá»‡ theo chiá»u rá»™ng khung hÃ¬nh) Ä‘á»ƒ coi lÃ  CÃ™NG 1 khuÃ´n máº·t giá»¯a 2 khung hÃ¬nh liÃªn tiáº¿p
MIN_FACE_SIZE_RATIO = 0.03        # bá» qua khuÃ´n máº·t quÃ¡ nhá» (< 3% chiá»u rá»™ng khung hÃ¬nh) - thÆ°á»ng lÃ  ngÆ°á»i á»Ÿ xa/phÃ´ng ná»n


def _face_landmarks_to_bbox_and_points(landmarks, frame_w: int, frame_h: int):
    xs = [p.x for p in landmarks.landmark]
    ys = [p.y for p in landmarks.landmark]
    x0, x1 = min(xs) * frame_w, max(xs) * frame_w
    y0, y1 = min(ys) * frame_h, max(ys) * frame_h
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (x0, y0, x1, y1), (cx, cy)


def _mouth_openness(landmarks, frame_h: int) -> float:
    top = landmarks.landmark[MOUTH_TOP]
    bottom = landmarks.landmark[MOUTH_BOTTOM]
    face_top = landmarks.landmark[FACE_TOP]
    face_bottom = landmarks.landmark[FACE_BOTTOM]
    mouth_gap = abs(bottom.y - top.y) * frame_h
    face_height = abs(face_bottom.y - face_top.y) * frame_h
    if face_height < 1e-6:
        return 0.0
    return mouth_gap / face_height


def _face_hist(frame, bbox) -> Optional["object"]:
    import cv2
    import numpy as np

    x0, y0, x1, y1 = [int(max(0, v)) for v in bbox]
    x1 = min(x1, frame.shape[1])
    y1 = min(y1, frame.shape[0])
    if x1 <= x0 or y1 <= y0:
        return None
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist.flatten()


def _detect_faces_in_frame(face_mesh, frame):
    """Tráº£ vá» list cÃ¡c dict {bbox, center, mouth_open, hist} cho má»—i khuÃ´n máº·t detect Ä‘Æ°á»£c trong 1 khung hÃ¬nh."""
    h, w = frame.shape[:2]
    results = face_mesh.process(frame[:, :, ::-1])  # BGR -> RGB cho mediapipe
    faces = []
    if not results.multi_face_landmarks:
        return faces
    for landmarks in results.multi_face_landmarks:
        bbox, center = _face_landmarks_to_bbox_and_points(landmarks, w, h)
        face_w = bbox[2] - bbox[0]
        if face_w / w < MIN_FACE_SIZE_RATIO:
            continue
        mouth_open = _mouth_openness(landmarks, h)
        hist = _face_hist(frame, bbox)
        if hist is None:
            continue
        faces.append({"bbox": bbox, "center": center, "mouth_open": mouth_open, "hist": hist})
    return faces


def _active_speaker_for_segment(face_mesh, cap, fps: float, start: float, end: float, frame_w: int):
    """
    Láº¥y máº«u N khung hÃ¬nh trong [start, end], khá»›p khuÃ´n máº·t giá»¯a cÃ¡c khung hÃ¬nh
    thÃ nh track, tráº£ vá» (hist, n_samples) cá»§a track cÃ³ Ä‘á»™ má»Ÿ miá»‡ng biáº¿n thiÃªn
    nhiá»u nháº¥t - hoáº·c (None, 0) náº¿u khÃ´ng detect Ä‘Æ°á»£c khuÃ´n máº·t nÃ o Ä‘Ã¡ng tin cáº­y.
    """
    import numpy as np

    dur = max(0.05, end - start)
    n = min(N_SAMPLES_PER_SEGMENT, max(2, int(dur * 4)))  # Ã­t nháº¥t 2 máº«u, nhiá»u hÆ¡n vá»›i cÃ¢u dÃ i
    times = [start + dur * (k + 0.5) / n for k in range(n)]

    tracks: List[Dict] = []  # má»—i track: {"center": (cx,cy), "mouth_opens": [...], "hists": [...]}

    for t in times:
        cap.set(0, int(t * 1000))  # CAP_PROP_POS_MSEC = 0
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        faces = _detect_faces_in_frame(face_mesh, frame)
        for f in faces:
            matched = None
            for track in tracks:
                dx = abs(track["center"][0] - f["center"][0]) / frame_w
                if dx < MATCH_DIST_THRESHOLD:
                    matched = track
                    break
            if matched is None:
                matched = {"center": f["center"], "mouth_opens": [], "hists": []}
                tracks.append(matched)
            matched["center"] = f["center"]  # cáº­p nháº­t vá»‹ trÃ­ má»›i nháº¥t
            matched["mouth_opens"].append(f["mouth_open"])
            matched["hists"].append(f["hist"])

    if not tracks:
        return None, 0

    best_track, best_var = None, -1.0
    for track in tracks:
        if len(track["mouth_opens"]) < 2:
            continue
        var = float(np.var(track["mouth_opens"]))
        if var > best_var:
            best_var = var
            best_track = track

    if best_track is None:
        return None, 0

    mean_hist = np.mean(best_track["hists"], axis=0)
    return mean_hist, len(best_track["mouth_opens"])


def _kmeans_hist_clusters(hists: List, k: int = 2, n_iter: int = 30):
    """K-means Ä‘Æ¡n giáº£n trÃªn cÃ¡c vector histogram, tá»± viáº¿t báº±ng numpy (khÃ´ng cáº§n scikit-learn)."""
    import numpy as np

    arr = np.stack(hists)
    n = len(arr)
    k = min(k, n)
    rng = np.random.RandomState(42)
    idx = rng.choice(n, size=k, replace=False)
    centroids = arr[idx].copy()

    labels = np.zeros(n, dtype=int)
    for _ in range(n_iter):
        dists = np.stack([np.linalg.norm(arr - c, axis=1) for c in centroids], axis=1)
        new_labels = np.argmin(dists, axis=1)
        if np.array_equal(new_labels, labels) and _ > 0:
            break
        labels = new_labels
        for ci in range(k):
            pts = arr[labels == ci]
            if len(pts):
                centroids[ci] = pts.mean(axis=0)
    return labels


def detect_speakers_by_face(
    video_path: str,
    segments: List[SubtitleSegment],
    n_speakers: int = 2,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[SubtitleSegment]:
    """
    Tráº£ vá» list SubtitleSegment Má»šI, má»—i segment Ä‘Ã£ gÃ¡n `speaker_id`
    ("person_0", "person_1"...) vÃ  `gender` ("male"/"female") dá»±a trÃªn kháº©u
    hÃ¬nh + phÃ¢n cá»¥m ngoáº¡i hÃ¬nh + pitch gá»™p theo nhÃ³m.

    CÃ¢u nÃ o KHÃ”NG detect Ä‘Æ°á»£c khuÃ´n máº·t Ä‘Ã¡ng tin cáº­y (nÃ³i ngoÃ i hÃ¬nh, cáº£nh
    quay xa, bá»‹ che...) sáº½ cÃ³ speaker_id="" vÃ  gender Ä‘Æ°á»£c Ä‘iá»n táº¡m theo
    pitch riÃªng láº» cá»§a cÃ¢u Ä‘Ã³ (fallback, giá»‘ng hÃ nh vi core/gender_detect.py).
    """
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
        import librosa
    except ImportError as e:
        raise ImportError(
            "Cáº§n cÃ i Ä‘áº·t: pip install mediapipe opencv-python numpy librosa "
            "Ä‘á»ƒ dÃ¹ng tÃ­nh nÄƒng nháº­n diá»‡n ngÆ°á»i nÃ³i theo kháº©u hÃ¬nh."
        ) from e

    if progress_cb:
        progress_cb(0.0, "Äang má»Ÿ video Ä‘á»ƒ phÃ¢n tÃ­ch kháº©u hÃ¬nh...")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"KhÃ´ng má»Ÿ Ä‘Æ°á»£c video Ä‘á»ƒ phÃ¢n tÃ­ch kháº©u hÃ¬nh: {video_path}")
    fps = cap.get(5) or 25.0  # CAP_PROP_FPS = 5
    frame_w = int(cap.get(3)) or 1280  # CAP_PROP_FRAME_WIDTH = 3

    mp_face_mesh = mp.solutions.face_mesh
    total = max(1, len(segments))

    seg_hists: List[Optional["object"]] = []
    seg_face_ok: List[bool] = []

    with mp_face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=4,
        refine_landmarks=False, min_detection_confidence=0.5,
    ) as face_mesh:
        for i, seg in enumerate(segments, start=1):
            hist, n_ok = _active_speaker_for_segment(face_mesh, cap, fps, seg.start, seg.end, frame_w)
            seg_hists.append(hist)
            seg_face_ok.append(hist is not None and n_ok >= 2)
            if progress_cb:
                progress_cb(i / total * 0.6, f"Äang phÃ¢n tÃ­ch kháº©u hÃ¬nh cÃ¢u {i}/{total}...")

    cap.release()

    # --- Äo pitch riÃªng cho tá»«ng cÃ¢u (dÃ¹ng láº¡i Ä‘Ãºng logic cá»§a core/gender_detect.py) ---
    if progress_cb:
        progress_cb(0.6, "Äang Ä‘o cao Ä‘á»™ giá»ng Ä‘á»ƒ gá»™p theo nhÃ³m nhÃ¢n váº­t...")

    tmp_wav = os.path.join(os.path.dirname(video_path) or ".", "_tmp_pitch_probe.wav")
    try:
        _extract_audio(video_path, tmp_wav, sr=16000)
        y_full, sr = librosa.load(tmp_wav, sr=16000, mono=True)
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)

    pitches: List[Optional[float]] = []
    for seg in segments:
        s = max(0, int(seg.start * sr))
        e = min(len(y_full), int(seg.end * sr))
        pitches.append(_median_pitch(y_full[s:e], sr))

    # --- PhÃ¢n cá»¥m cÃ¡c cÃ¢u CÃ“ khuÃ´n máº·t Ä‘Ã¡ng tin cáº­y thÃ nh n_speakers nhÃ³m ---
    valid_indices = [i for i, ok in enumerate(seg_face_ok) if ok]
    speaker_ids = [""] * len(segments)

    if len(valid_indices) >= n_speakers:
        # Káº¿t há»£p Ä‘áº·c trÆ°ng NGOáº I HÃŒNH (hist) + CAO Äá»˜ GIá»ŒNG (pitch) khi phÃ¢n cá»¥m nhÃ¢n
        # váº­t - dÃ¹ng hist ÄÆ N THUáº¦N dá»… bá»‹ lá»‡ch khi 1 ngÆ°á»i xuáº¥t hiá»‡n á»Ÿ nhiá»u gÃ³c quay/
        # Ã¡nh sÃ¡ng khÃ¡c nhau (hist Ä‘á»•i nhiá»u dÃ¹ váº«n lÃ  1 ngÆ°á»i), khiáº¿n 1 nhÃ¢n váº­t bá»‹
        # TÃCH NHáº¦M thÃ nh 2 nhÃ³m -> 2 giá»ng Ä‘á»c khÃ¡c nhau cho CÃ™NG 1 ngÆ°á»i. ThÃªm pitch
        # lÃ m "neo" á»•n Ä‘á»‹nh hÆ¡n nhiá»u vÃ¬ cao Ä‘á»™ giá»ng cá»§a 1 ngÆ°á»i thá»±c táº¿ Ã­t Ä‘á»•i hÆ¡n háº³n
        # ngoáº¡i hÃ¬nh theo gÃ³c quay/Ã¡nh sÃ¡ng.
        valid_pitches_for_cluster = [pitches[i] for i in valid_indices]
        known_pitches = [p for p in valid_pitches_for_cluster if p is not None]
        mean_pitch = float(np.mean(known_pitches)) if known_pitches else 165.0
        std_pitch = float(np.std(known_pitches)) if len(known_pitches) > 1 else 1.0
        std_pitch = max(std_pitch, 1e-3)

        PITCH_WEIGHT = 3.0  # cao Ä‘á»™ giá»ng cÃ³ trá»ng sá»‘ Ä‘á»§ máº¡nh Ä‘á»ƒ khÃ´ng bá»‹ tÃ¡ch nháº§m 1 ngÆ°á»i,
                            # nhÆ°ng váº«n cÃ²n chá»— cho hist phÃ¢n biá»‡t 2 ngÆ°á»i CÃ™NG giá»›i tÃ­nh/tÃ´ng giá»ng

        combined_features = []
        for local_i, global_i in enumerate(valid_indices):
            hist = seg_hists[global_i]
            p = valid_pitches_for_cluster[local_i]
            p_z = (p - mean_pitch) / std_pitch if p is not None else 0.0
            combined_features.append(np.concatenate([hist, [p_z * PITCH_WEIGHT]]))

        labels = _kmeans_hist_clusters(combined_features, k=n_speakers)
        for local_i, global_i in enumerate(valid_indices):
            speaker_ids[global_i] = f"person_{labels[local_i]}"
    elif progress_cb:
        progress_cb(0.9, "âš  KhÃ´ng Ä‘á»§ cÃ¢u detect Ä‘Æ°á»£c khuÃ´n máº·t rÃµ Ä‘á»ƒ phÃ¢n nhÃ³m nhÃ¢n váº­t - fallback dÃ¹ng pitch riÃªng láº»")

    # --- Vá»›i má»—i speaker_id: gá»™p pitch cáº£ nhÃ³m Ä‘á»ƒ quyáº¿t Ä‘á»‹nh Nam/Ná»¯ á»•n Ä‘á»‹nh ---
    from collections import defaultdict
    group_pitches: Dict[str, List[float]] = defaultdict(list)
    for sid, p in zip(speaker_ids, pitches):
        if sid and p is not None:
            group_pitches[sid].append(p)

    # An toÃ n thÃªm: náº¿u 2 nhÃ³m hoÃ¡ ra cÃ³ pitch (median) Gáº¦N GIá»NG NHAU (< 25Hz, khoáº£ng
    # cÃ¡ch ráº¥t nhá» so vá»›i má»©c chÃªnh Nam/Ná»¯ thÆ°á»ng >40-50Hz) -> kháº£ nÄƒng cao Ä‘Ã¢y lÃ  1
    # ngÆ°á»i bá»‹ thuáº­t toÃ¡n tÃ¡ch nháº§m thÃ nh 2 nhÃ³m (dÃ¹ Ä‘Ã£ thÃªm pitch lÃ m neo á»Ÿ bÆ°á»›c phÃ¢n
    # cá»¥m, ngoáº¡i hÃ¬nh Ä‘Ã´i khi váº«n kÃ©o lá»‡ch) -> Gá»˜P Láº I thÃ nh 1 nhÃ³m duy nháº¥t, trÃ¡nh 1
    # nhÃ¢n váº­t bá»‹ 2 giá»ng khÃ¡c nhau.
    MERGE_PITCH_DIFF_HZ = 25.0
    group_medians = {sid: float(np.median(v)) for sid, v in group_pitches.items() if v}
    sids_sorted = sorted(group_medians.keys(), key=lambda s: group_medians[s])
    remap: Dict[str, str] = {}
    for idx in range(1, len(sids_sorted)):
        prev_sid, cur_sid = sids_sorted[idx - 1], sids_sorted[idx]
        prev_final = remap.get(prev_sid, prev_sid)
        if abs(group_medians[cur_sid] - group_medians[prev_final]) < MERGE_PITCH_DIFF_HZ:
            remap[cur_sid] = prev_final
    if remap:
        if progress_cb:
            progress_cb(0.95, f"ÄÃ£ gá»™p {len(remap)} nhÃ³m nhÃ¢n váº­t cÃ³ giá»ng quÃ¡ giá»‘ng nhau (kháº£ nÄƒng bá»‹ tÃ¡ch nháº§m)")
        speaker_ids = [remap.get(sid, sid) for sid in speaker_ids]
        merged_group_pitches: Dict[str, List[float]] = defaultdict(list)
        for sid, p in zip(speaker_ids, pitches):
            if sid and p is not None:
                merged_group_pitches[sid].append(p)
        group_pitches = merged_group_pitches

    group_gender: Dict[str, str] = {}
    if group_pitches:
        all_medians = [float(np.median(v)) for v in group_pitches.values()]
        if len(all_medians) >= 2 and max(all_medians) - min(all_medians) > 1e-3:
            c_low, c_high = _kmeans_1d_2clusters(all_medians)
            threshold = (c_low + c_high) / 2.0
        else:
            threshold = 165.0  # chá»‰ 1 nhÃ³m hoáº·c táº¥t cáº£ pitch gáº§n báº±ng nhau -> dÃ¹ng ngÆ°á»¡ng sinh lÃ½ há»c trung bÃ¬nh
        for sid, plist in group_pitches.items():
            group_gender[sid] = "female" if float(np.median(plist)) >= threshold else "male"

    # --- GÃ¡n káº¿t quáº£ cuá»‘i cÃ¹ng cho tá»«ng segment, fallback pitch riÃªng láº» náº¿u khÃ´ng cÃ³ speaker_id ---
    out: List[SubtitleSegment] = []
    last_gender = "female"
    n_male, n_female, n_no_face = 0, 0, 0
    for seg, sid, p in zip(segments, speaker_ids, pitches):
        if sid and sid in group_gender:
            gender = group_gender[sid]
        elif p is not None:
            gender = "female" if p >= 165.0 else "male"
            n_no_face += 1
        else:
            gender = last_gender
            n_no_face += 1
        last_gender = gender
        if gender == "male":
            n_male += 1
        else:
            n_female += 1
        out.append(SubtitleSegment(
            index=seg.index, start=seg.start, end=seg.end, text=seg.text,
            gender=gender, speaker_id=sid,
        ))

    if progress_cb:
        n_speakers_found = len(group_gender)
        progress_cb(
            1.0,
            f"HoÃ n táº¥t: {n_speakers_found} nhÃ¢n váº­t nháº­n diá»‡n qua kháº©u hÃ¬nh, "
            f"{n_male} cÃ¢u Nam / {n_female} cÃ¢u Ná»¯ ({n_no_face} cÃ¢u fallback pitch riÃªng láº»)",
        )

    return out

