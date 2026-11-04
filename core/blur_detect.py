"""Tự động dò vùng CHỮ CỐ ĐỊNH VỊ TRÍ trong video (phụ đề gốc hardsub, tên kênh/logo
nguồn ở góc màn hình...) để tự điền vào blur_regions - dùng cho nút "🔍 Tự động dò"
cạnh nút "🖼 Vẽ vùng cần che" trong main.py.

Ý TƯỞNG (heuristic đơn giản, KHÔNG phải OCR/AI thật, chỉ dựa vào thống kê ảnh):
  1. Trích ra nhiều khung hình (frame) rải đều trên toàn bộ video bằng ffmpeg.
  2. Với mỗi khung hình, tính bản đồ BIÊN (edge map - nơi màu sắc thay đổi đột
     ngột, đặc trưng của viền chữ/nét chữ).
  3. CỘNG DỒN bản đồ biên của tất cả khung hình lại. Chữ phụ đề/logo tuy đổi nội
     dung qua từng khung nhưng luôn nằm ở CÙNG MỘT VÙNG trên màn hình -> vùng đó
     sẽ có biên xuất hiện lặp đi lặp lại rất nhiều lần, cộng dồn lên sẽ "sáng" rõ
     rệt. Ngược lại nội dung video (người, cảnh vật...) chuyển động liên tục nên
     biên của nó rải rác khắp nơi, không lặp lại ở cùng 1 chỗ -> cộng dồn ra mờ,
     không nổi bật.
  4. Từ bản đồ cộng dồn đó, quét theo HÀNG NGANG để tìm các dải có điểm biên cao
     bất thường (nghi là 1 dòng chữ), rồi trong mỗi dải quét theo CỘT để giới hạn
     đúng chiều rộng có chữ (không lấy tràn hết chiều ngang khung hình).

Vì đây là suy đoán thống kê (không đọc hiểu nội dung) nên có thể sai/lệch với
video có chuyển động chậm, có logo trong suốt mờ, hoặc phụ đề đổi vị trí liên
tục - main.py LUÔN cho phép người dùng mở "Vẽ vùng cần che" để kiểm tra và kéo
chỉnh lại khung dò được, không bắt buộc phải đúng 100% ngay lần đầu.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Callable, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter

Region = Tuple[int, int, int, int]  # (x, y, w, h) theo pixel GỐC của video


def _ffprobe_size_duration(video_path: str) -> Tuple[int, int, float]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,duration",
         "-of", "csv=p=0", video_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    parts = probe.stdout.strip().split(",")
    if len(parts) < 2:
        raise RuntimeError(f"Không đọc được kích thước video (ffprobe trả về: {probe.stdout.strip()!r}).")
    w, h = int(parts[0]), int(parts[1])
    dur = float(parts[2]) if len(parts) > 2 and parts[2] not in ("", "N/A") else 5.0
    return w, h, dur


def _extract_frame(video_path: str, t: float, out_path: str) -> bool:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(t), "-i", video_path, "-frames:v", "1", out_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return proc.returncode == 0 and os.path.exists(out_path)


def _find_text_bands(heat: "np.ndarray") -> List[Tuple[int, int, int, int]]:
    """Từ bản đồ nhiệt (heat, giá trị 0..1, đã chuẩn hoá theo số khung hình mẫu),
    tìm các dải NGANG có biên lặp lại nhiều (nghi là 1 dòng chữ), rồi trong mỗi
    dải xác định khoảng CỘT chứa chữ -> trả về list (x0,y0,x1,y1) theo toạ độ
    của chính bản đồ heat (chưa quy đổi ra pixel video gốc)."""
    h, w = heat.shape
    row_score = heat.mean(axis=1)
    row_thresh = max(row_score.mean() + row_score.std() * 1.0, 0.05)
    is_band_row = row_score > row_thresh

    bands = []
    y = 0
    min_band_h = max(3, int(h * 0.015))
    while y < h:
        if is_band_row[y]:
            y0 = y
            while y < h and is_band_row[y]:
                y += 1
            y1 = y
            if y1 - y0 >= min_band_h:
                bands.append((y0, y1))
        else:
            y += 1

    regions = []
    min_band_w = max(6, int(w * 0.03))
    for (y0, y1) in bands:
        strip = heat[y0:y1, :]
        col_score = strip.mean(axis=0)
        col_thresh = max(col_score.mean() + col_score.std() * 0.5, 0.04)
        cols = np.where(col_score > col_thresh)[0]
        if cols.size == 0:
            continue
        x0, x1 = int(cols.min()), int(cols.max()) + 1
        if x1 - x0 < min_band_w:
            continue  # dải quá hẹp - nhiều khả năng chỉ là nhiễu, không phải chữ
        regions.append((x0, y0, x1, y1))

    return regions


def detect_subtitle_regions(
    video_path: str,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    num_samples: int = 12,
    work_w: int = 480,
) -> Tuple[List[Region], int, int]:
    """Lấy `num_samples` khung hình rải đều trên video, dò các vùng chữ cố định vị
    trí (phụ đề gốc hardsub / logo tên kênh...) bằng cách cộng dồn bản đồ biên qua
    nhiều khung hình khác nhau.

    Trả về (regions, video_w, video_h):
      - regions: list [(x, y, w, h), ...] theo PIXEL GỐC của video (không phải
        toạ độ hiển thị đã scale trên preview) - đúng định dạng self.blur_regions
        mà main.py đang dùng.
      - video_w, video_h: kích thước gốc của video, để bên gọi tự quy đổi thêm
        toạ độ hiển thị nếu cần (vd để vẽ sẵn lên khung xem trước).
    """

    def report(pct: float, msg: str = "") -> None:
        if progress_cb:
            progress_cb(pct, msg)

    report(0.0, "Đang đọc thông tin video...")
    vw, vh, dur = _ffprobe_size_duration(video_path)
    if vw <= 0 or vh <= 0:
        raise RuntimeError("Kích thước video không hợp lệ.")

    n = max(2, num_samples)
    # Bỏ 5% đầu/cuối video - thường là intro/outro/logo giới thiệu, không có phụ
    # đề, dễ làm nhiễu kết quả dò.
    margin = dur * 0.05
    start_t = margin
    end_t = max(start_t + 0.1, dur - margin)
    timestamps = [start_t + i * (end_t - start_t) / (n - 1) for i in range(n)]

    scale = work_w / vw
    work_h = max(1, int(round(vh * scale)))

    with tempfile.TemporaryDirectory(prefix="reup_autodetect_") as tmp_dir:
        accum = np.zeros((work_h, work_w), dtype=np.float64)
        ok_count = 0
        for i, t in enumerate(timestamps):
            frame_path = os.path.join(tmp_dir, f"f{i:03d}.jpg")
            if _extract_frame(video_path, t, frame_path):
                img = Image.open(frame_path).convert("L").resize((work_w, work_h))
                edges = img.filter(ImageFilter.FIND_EDGES)
                arr = np.asarray(edges, dtype=np.float64)
                # Nhị phân hoá biên (giữ biên MẠNH, bỏ nhiễu yếu) trước khi cộng dồn.
                frame_thresh = arr.mean() + arr.std() * 1.5
                accum += (arr > frame_thresh).astype(np.float64)
                ok_count += 1
            report(0.1 + 0.7 * (i + 1) / n, f"Đang phân tích khung hình {i + 1}/{n}...")

        if ok_count < 2:
            raise RuntimeError(
                "Không trích được đủ khung hình mẫu để phân tích "
                "(video quá ngắn hoặc ffmpeg lỗi khi trích khung hình)."
            )

        report(0.85, "Đang xác định vùng chữ...")
        heat = accum / ok_count  # chuẩn hoá 0..1: càng gần 1 = biên càng LẶP LẠI ở nhiều khung

        regions_work = _find_text_bands(heat)

        report(0.95, "Đang quy đổi toạ độ...")
        inv_scale = 1.0 / scale
        regions: List[Region] = []
        for (x0, y0, x1, y1) in regions_work:
            px_x = int(x0 * inv_scale)
            px_y = int(y0 * inv_scale)
            px_w = int((x1 - x0) * inv_scale)
            px_h = int((y1 - y0) * inv_scale)
            # Nới thêm biên đệm mỗi bên để chắc chắn che hết viền/bóng đổ của chữ
            # (dò theo biên thường hơi "ăn hụt" sát mép nét chữ).
            pad_x = max(4, int(px_w * 0.06))
            pad_y = max(4, int(px_h * 0.25))
            px_x = max(0, px_x - pad_x)
            px_y = max(0, px_y - pad_y)
            px_w = min(vw - px_x, px_w + pad_x * 2)
            px_h = min(vh - px_y, px_h + pad_y * 2)
            if px_w > 2 and px_h > 2:
                regions.append((px_x, px_y, px_w, px_h))

        report(1.0, f"Xong - tìm thấy {len(regions)} vùng.")
        return regions, vw, vh
