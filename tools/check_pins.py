# ============================================================
#  Kiểm tra các phiên bản trong requirements.txt có tồn tại trên PyPI
#  Cách dùng: python tools/check_pins.py
# ============================================================
from __future__ import annotations

import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REQ_FILES = ["requirements.txt", "requirements-optional.txt"]
PIN_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)==([^\s;#]+)")


def parse_pins(path: str) -> list[tuple[str, str]]:
    pins: list[tuple[str, str]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            match = PIN_RE.match(line)
            if match:
                pins.append((match.group(1), match.group(2)))
    return pins


def fetch_versions(name: str) -> tuple[str, str, set[str] | None]:
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            payload = json.load(response)
        return name, "", set(payload.get("releases", {}).keys())
    except Exception as exc:  # noqa: BLE001
        return name, str(exc), None


def latest_of(versions: set[str]) -> str:
    def key(value: str):
        return [int(part) if part.isdigit() else part for part in re.split(r"[.\-+]", value)]

    try:
        ordered = sorted(versions, key=key)
        return ordered[-1] if ordered else "?"
    except Exception:  # noqa: BLE001
        return "?"


def main() -> int:
    pins: list[tuple[str, str]] = []
    for path in REQ_FILES:
        try:
            pins.extend(parse_pins(path))
        except FileNotFoundError:
            print(f"[BỎ QUA] Không thấy {path}")

    problems: list[str] = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda item: fetch_versions(item[0]), pins))

    for (name, wanted), (_, error, versions) in zip(pins, results):
        if versions is None:
            print(f"[LỖI MẠNG] {name}: {error}")
            problems.append(f"{name} (không truy vấn được)")
            continue
        if wanted not in versions:
            print(f"[SAI] {name}=={wanted}  -> bản mới nhất: {latest_of(versions)}")
            problems.append(f"{name}=={wanted} (mới nhất {latest_of(versions)})")
        else:
            print(f"[OK ] {name}=={wanted}")

    print()
    if problems:
        print(f"CÓ {len(problems)} phiên bản không tồn tại:")
        for item in problems:
            print("  -", item)
        return 1
    print("Tất cả phiên bản đều tồn tại trên PyPI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
