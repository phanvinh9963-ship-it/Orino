"""Tìm và in ra mọi dòng chứa thương hiệu cũ trong dự án (in UTF-8).

Cách dùng:  python tools/scan_brand.py [thư_mục_gốc]
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Các mẫu cần loại bỏ khỏi bản phát hành công khai
PATTERN = re.compile(r"orino|rp[ _-]?studio", re.IGNORECASE)

SKIP_DIRS = {
    "venv_build", "build", "dist", "__pycache__", "node_modules", ".git",
    "model_cache", "backup", "site-packages", "DLLs", "Lib", "tcl",
    "ensurepip", "idlelib", "turtledemo", "distutils", "lib2to3",
    "python312_embed", "chrome_profile_data",
}


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else r"F:\Orino"

    hits = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith((".py", ".md", ".txt", ".json", ".spec", ".bat", ".yml", ".yaml", ".ini", ".cfg", ".ps1", ".html", ".js", ".ts")):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if PATTERN.search(line):
                            rel = os.path.relpath(path, root)
                            print(f"{rel}:{i}: {line.rstrip()[:220]}")
                            hits += 1
            except Exception:
                continue
    print(f"--- Tổng: {hits} dòng khớp ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
