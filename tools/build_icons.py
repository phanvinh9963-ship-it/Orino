"""Sinh bộ icon Reup Studio từ PNG 512x512 đã dựng sẵn.

Tạo:
  - assets/reup_logo_<kích thước>.png  (dùng trong giao diện)
  - assets/reup_logo.ico                (16/32/48/64/128/256 - dùng cho exe + installer)

Cách chạy:  python tools/build_icons.py
"""
from __future__ import annotations

import io
import os
import sys

from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
MASTER_PNG = os.path.join(ASSETS_DIR, "reup_logo_512.png")
MASTER_SVG = os.path.join(ASSETS_DIR, "reup_logo.svg")

# Kích thước ảnh PNG xuất ra (dùng trong giao diện + tài liệu)
PNG_SIZES = [16, 24, 32, 48, 64, 128, 256, 512]

# Kích thước gói trong file .ico (Windows + PyInstaller + Inno Setup)
ICO_SIZES = [16, 32, 48, 64, 128, 256]


def main() -> int:
    if not os.path.isfile(MASTER_PNG):
        print(f"Không tìm thấy {MASTER_PNG} - hãy dựng lại từ SVG trước.")
        return 1

    master = Image.open(MASTER_PNG).convert("RGBA")
    if master.size != (512, 512):
        master = master.resize((512, 512), Image.LANCZOS)

    # 1) Xuất từng kích thước PNG
    for size in PNG_SIZES:
        img = master.resize((size, size), Image.LANCZOS)
        out = os.path.join(ASSETS_DIR, f"reup_logo_{size}.png")
        img.save(out, format="PNG", optimize=True)
        print(f"  PNG  {out}  ({os.path.getsize(out)} bytes)")

    # 2) Tạo file .ico đa kích thước
    ico_path = os.path.join(ASSETS_DIR, "reup_logo.ico")
    master.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"  ICO  {ico_path}  ({os.path.getsize(ico_path)} bytes)")

    # 3) Kiểm tra lại nội dung file .ico
    with Image.open(ico_path) as ico:
        got = sorted(ico.info.get("sizes", []))
        print(f"  Kích thước trong .ico: {got}")
        missing = [s for s in ICO_SIZES if (s, s) not in got]
        if missing:
            print(f"  THIẾU kích thước: {missing}")
            return 2

    print("Hoàn tất.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
