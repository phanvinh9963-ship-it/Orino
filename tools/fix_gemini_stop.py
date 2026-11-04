"""Sửa method stop() của GeminiFastAPIProcess để tắt đúng server do app khởi động."""
from __future__ import annotations

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "core", "gemini_fastapi_server.py")

OLD = '''    def stop(self, timeout: float = 8.0) -> None:
        """
        Không tắt Gemini-FastAPI.

        Vì server này dùng CHUNG cho nhiều ứng dụng.
        """

        del timeout

        # Cố tình không làm gì.
        #
        # Reup Studio không được phép shutdown server chung.
        return
'''

NEW = '''    def stop(self, timeout: float = 8.0) -> None:
        """
        Tắt server Gemini-FastAPI mà chính Reup Studio đã khởi động.

        Nếu server đã chạy sẵn từ trước (dùng chung với ứng dụng khác)
        thì KHÔNG tắt - đúng nguyên tắc "không shutdown server chung".
        """
        proc = self._process
        if proc is None or not self._started_by_us:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=timeout)
                except Exception:
                    proc.kill()
        except Exception:
            pass
        finally:
            self._process = None
            self._started_by_us = False
'''


def main() -> int:
    with open(TARGET, "r", encoding="utf-8-sig", errors="replace") as fh:
        content = fh.read()
    if NEW in content:
        print("Đã sửa rồi, không cần làm gì thêm.")
        return 0
    if OLD not in content:
        print("!! Không tìm thấy đoạn cần sửa.")
        return 1
    content = content.replace(OLD, NEW, 1)
    with open(TARGET, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    print("Đã sửa method stop().")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
