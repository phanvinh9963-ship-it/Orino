"""Sửa nhanh một đoạn code trong tệp (giữ nguyên encoding và kiểu xuống dòng).

Cách chạy:  python tools/patch_file.py <tệp> <tệp_mô_tả_thay_thế>
Trong tệp mô tả thay thế, dùng @@OLD@@ và @@NEW@@ làm dấu phân cách.
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main() -> int:
    if len(sys.argv) < 3:
        print("Thiếu tham số.")
        return 1
    target = sys.argv[1]
    spec_path = sys.argv[2]

    with open(spec_path, "r", encoding="utf-8") as fh:
        spec = fh.read()

    parts = spec.split("@@OLD@@")
    if len(parts) != 2:
        print("Tệp mô tả phải có đúng một cặp @@OLD@@ ... @@NEW@@ ... @@END@@")
        return 1
    old, rest = parts[0], parts[1]
    new, _ = rest.split("@@NEW@@", 1)
    new = new.split("@@END@@")[0]

    with open(target, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        content = fh.read()

    # Thử khớp với cả LF và CRLF
    if old in content:
        new_content = content.replace(old, new, 1)
    else:
        old_crlf = old.replace("\n", "\r\n")
        new_crlf = new.replace("\n", "\r\n")
        if old_crlf in content:
            new_content = content.replace(old_crlf, new_crlf, 1)
        else:
            print("!! Không tìm thấy đoạn cần sửa.")
            return 2

    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(new_content)
    print(f"Đã sửa {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
