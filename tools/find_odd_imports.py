"""Tìm nguồn gốc của các import có vẻ là thư viện ngoài nhưng thực ra là tên cũ
của Python 2 hoặc mã chỉ nằm trong khối try/except.

Cách chạy:  python tools/find_odd_imports.py
"""
from __future__ import annotations

import ast
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOTS = ["main.py", "core", "douyin_batch", "gemini_fastapi_server/app",
         "gemini_fastapi_server/scripts", "gemini_web2api_server", "workers"]

PY2_OR_OPTIONAL = {
    "ConfigParser", "Queue", "Tkinter", "StringIO", "cStringIO", "urlparse",
    "urllib2", "httplib", "xmlrpclib", "htmlentitydefs", "dummy_thread",
    "dummy_threading", "distutils", "imp", "HTMLParser", "Cryptodome",
    "Crypto", "PyQt6", "PySide6", "gemini_web2api", "simplejson",
    "pkg_resources", "tkFileDialog", "android", "jaraco", "jaraco.text",
    "backports", "zipp", "sphinx", "sphinx.util",
}


def main() -> int:
    for rel in ROOTS:
        path = os.path.join(BASE_DIR, rel)
        if os.path.isfile(path):
            files = [path]
        elif os.path.isdir(path):
            files = [
                os.path.join(dp, f)
                for dp, dn, fn in os.walk(path)
                for f in fn
                if f.endswith(".py") and "__pycache__" not in dp
            ]
        else:
            continue
        for fp in files:
            try:
                tree = ast.parse(open(fp, encoding="utf-8", errors="replace").read())
            except Exception:
                continue
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module.split(".")[0]]
                for m in mods:
                    if m in PY2_OR_OPTIONAL:
                        rel_p = os.path.relpath(fp, BASE_DIR)
                        print(f"{rel_p}:{node.lineno}: {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
