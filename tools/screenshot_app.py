"""Chụp ảnh cửa sổ Reup Studio để kiểm tra giao diện bằng mắt.

Cách dùng:
    python tools/screenshot_app.py [--wait 15] [--out duong_dan.png] [--title "Reup Studio"]

Script tự khởi chạy main.py, đợi app lên cửa sổ, chụp lại vùng cửa sổ rồi tắt app.
"""
from __future__ import annotations

import argparse
import ctypes
import io
import os
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def find_window(title_part: str):
    """Tìm cửa sổ đang mở có tiêu đề chứa `title_part` (trả về (hwnd, x, y, w, h))."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_part.lower() in buf.value.lower() and user32.IsWindowVisible(hwnd):
                rect = ctypes.wintypes.RECT() if hasattr(ctypes, "wintypes") else None
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(enum_proc, 0)

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    for hwnd, _title in found:
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left > 200 and r.bottom - r.top > 200:
            return hwnd, r.left, r.top, r.right - r.left, r.bottom - r.top
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=18, help="số giây chờ app mở xong")
    ap.add_argument("--out", default=os.path.join(BASE_DIR, "build", "ui_check.png"))
    ap.add_argument("--title", default="Reup Studio")
    ap.add_argument("--keep-open", action="store_true", help="giữ app mở sau khi chụp")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    win = None
    deadline = time.time() + args.wait
    while time.time() < deadline:
        if proc.poll() is not None:
            print("!! App đã thoát sớm. Output:")
            print(proc.stdout.read() if proc.stdout else "(không có)")
            return 1
        win = find_window(args.title)
        if win:
            break
        time.sleep(1)

    if not win:
        print("!! Không tìm thấy cửa sổ app trong thời gian chờ.")
        if not args.keep_open:
            proc.terminate()
        return 2

    _hwnd, x, y, w, h = win
    time.sleep(2.5)   # chờ giao diện vẽ xong
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        img.save(args.out)
        print(f"Đã chụp cửa sổ ({w}x{h}) -> {args.out}")
    except Exception as exc:
        print(f"Lỗi khi chụp ảnh: {exc}")
        return 3

    if not args.keep_open:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
