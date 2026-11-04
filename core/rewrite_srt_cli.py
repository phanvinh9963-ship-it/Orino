"""
rewrite_srt_cli.py
Chạy công cụ viết lại SRT (core/rewrite_srt.py) trực tiếp từ dòng lệnh, không
cần mở app chính. Yêu cầu Gemini Web2API đang chạy sẵn (vd bằng
START_GEMINI_WEB2API.bat) trước khi chạy script này.

Cách dùng:
    py rewrite_srt_cli.py input.srt output.srt --lang Vietnamese --keep-ratio 0.4

Các tham số:
    input.srt           File SRT gốc cần viết lại.
    output.srt           Đường dẫn file SRT mới sẽ xuất ra.
    --lang               Ngôn ngữ của SRT (vd Vietnamese, English) - PHẢI khớp
                          ngôn ngữ THẬT của nội dung, dùng để tra tốc độ đọc
                          (core/text_fit.py:CHARS_PER_SEC) và ghi trong prompt.
    --keep-ratio          0.0 - 1.0, mặc định 0.4 (giữ ~40% cách diễn đạt gốc,
                          biến tấu ~60%). Càng THẤP thì viết lại càng KHÁC bản gốc.
    --base-url            Địa chỉ Gemini Web2API, mặc định http://127.0.0.1:8000.
    --model                Model Web2API, mặc định gemini-3.6-flash.
    --api-key              API key local (nếu server có bật xác thực).
    --speech-rate          Tốc độ đọc gốc dạng edge-tts, mặc định "+0%".
    --max-gap               Khoảng lặng tối đa cho phép giữa 2 câu (giây), mặc định 1.2.
    --min-gap               Khoảng cách tối thiểu giữa 2 câu (giây), mặc định 0.12.
    --from-zero             Nếu có cờ này: câu đầu tiên bắt đầu từ 0s thay vì giữ
                          nguyên timestamp start gốc.
"""
from __future__ import annotations

import argparse
import sys

from core.rewrite_srt import rewrite_srt_file


def main():
    p = argparse.ArgumentParser(description="Viết lại SRT (biến tấu, cùng ngôn ngữ) + cân chỉnh timing.")
    p.add_argument("input_srt")
    p.add_argument("output_srt")
    p.add_argument("--lang", default="Vietnamese")
    p.add_argument("--keep-ratio", type=float, default=0.4)
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--model", default="gemini-3.6-flash")
    p.add_argument("--api-key", default=None)
    p.add_argument("--speech-rate", default="+0%")
    p.add_argument("--max-gap", type=float, default=1.2)
    p.add_argument("--min-gap", type=float, default=0.12)
    p.add_argument("--from-zero", action="store_true")
    p.add_argument(
        "--total-duration", type=float, default=None,
        help="Trần cứng (giây) - timeline mới sẽ KHÔNG BAO GIỜ vượt quá mốc này (nén đều "
             "khoảng nghỉ rồi nén đều tốc độ đọc nếu cần). Bỏ trống = không giới hạn (hành vi cũ).",
    )
    p.add_argument(
        "--video", default=None,
        help="Đường dẫn video gốc - nếu có, TỰ ĐỘNG đo thời lượng bằng ffprobe làm trần "
             "cứng (ưu tiên hơn --total-duration nếu cả 2 cùng được truyền).",
    )
    args = p.parse_args()

    total_duration_sec = args.total_duration
    if args.video:
        from core.export import probe_duration
        total_duration_sec = probe_duration(args.video)
        print(f"Đã đo thời lượng video gốc: {total_duration_sec:.2f}s (dùng làm trần cứng)")

    def progress_cb(pct: float, msg: str):
        print(f"[{int(pct * 100):3d}%] {msg}")

    try:
        out = rewrite_srt_file(
            args.input_srt, args.output_srt, args.lang,
            base_url=args.base_url, model=args.model, api_key=args.api_key,
            keep_ratio=args.keep_ratio, speech_rate=args.speech_rate,
            min_gap_sec=args.min_gap, max_gap_sec=args.max_gap,
            keep_original_start=not args.from_zero,
            total_duration_sec=total_duration_sec,
            progress_cb=progress_cb,
        )
    except Exception as e:
        print(f"LỖI: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nXong: {out}")


if __name__ == "__main__":
    main()
