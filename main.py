"""
Reup Studio - Video Translate & Dubbing Tool
Pipeline: Transcript -> Translate -> Subtitles -> Voice -> Export

Chạy: python main.py
Yêu cầu: xem requirements.txt và README.md
"""
from __future__ import annotations
import os
import json
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk
import io


def get_app_base_dir() -> str:
    """Thu muc goc thuc su cua app - noi dat cac file di kem nhu TiktokAuto/,
    client_secret.json, cac file log/settings...

    Khi chay bang "python main.py": la thu muc chua main.py.
    Khi da dong goi thanh .exe (PyInstaller --onedir): __file__ tro vao ben
    trong thu muc "_internal" (noi PyInstaller giai nen code), KHONG phai noi
    dat file .exe - neu dung __file__ se tinh sai duong dan toi TiktokAuto/,
    client_secret.json... (nhung file nay duoc dat CANH file .exe, khong nam
    trong _internal). Phai dung os.path.dirname(sys.executable) trong truong
    hop nay de tro dung ve thu muc chua ReupStudio.exe.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_asset_path(name: str) -> str:
    """Duong dan toi 1 file tai nguyen (logo, icon...) cua app.

    Khi chay tu source: tai nguyen nam o <thu muc du an>/assets/<name>.
    Khi chay ban .exe (PyInstaller): tai nguyen duoc giai nen vao thu muc
    "_internal" - dung sys._MEIPASS de lay dung duong dan.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, "assets", name)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(get_app_base_dir(), "assets", name)


def get_user_data_dir() -> str:
    """Thu muc du lieu rieng cua nguoi dung - noi luu CAU HINH, KEY va LOG.

    Reup Studio la app cong khai, nen dung lieu nguoi dung KHONG duoc nam
    trong thu muc cai dat (thu muc do co the khong ghi duoc, va se bi ghi de
    moi lan cai lai). Mac dinh: %APPDATA%\\ReupStudio (Windows).
    """
    override = os.environ.get("REUP_STUDIO_DATA_DIR", "").strip()
    if override:
        base = override
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~")
        base = os.path.join(base, ".config")
    path = os.path.join(base, "ReupStudio")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = os.path.join(os.path.expanduser("~"), ".reup_studio")
        os.makedirs(path, exist_ok=True)
    return path


def get_douyin_cookie_path() -> str:
    """Đường dẫn CỐ ĐỊNH của file cookie Douyin.

    Theo yêu cầu đóng gói: <thư mục app>\\cookies\\douyin_cookies.txt
    Nếu thư mục cài đặt không ghi được (chẳng hạn đặt trong Program Files),
    app dùng đường dẫn dự phòng trong thư mục dữ liệu người dùng.
    """
    app_dir = os.path.join(get_app_base_dir(), "cookies")
    try:
        os.makedirs(app_dir, exist_ok=True)
        probe = os.path.join(app_dir, ".write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return os.path.join(app_dir, "douyin_cookies.txt")
    except Exception:
        fallback_dir = os.path.join(get_user_data_dir(), "cookies")
        os.makedirs(fallback_dir, exist_ok=True)
        return os.path.join(fallback_dir, "douyin_cookies.txt")


class _NullWriter:
    """Stream gia, bo qua moi lenh ghi - dung khi app dong goi --noconsole
    (khong co console that nen sys.stdout/sys.stderr la None). Neu de None,
    bat ky print() nao con sot trong code (ke ca trong core/*) se crash app."""
    def write(self, *args, **kwargs):
        pass

    def flush(self, *args, **kwargs):
        pass

    def isatty(self):
        return False


if sys.platform == "win32":
    if sys.stdout is None:
        sys.stdout = _NullWriter()
    elif hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if sys.stderr is None:
        sys.stderr = _NullWriter()
    elif hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from PIL import Image, ImageTk

from core.pipeline import Pipeline, PipelineConfig
from core import ui_helpers as UIH

# Kéo-thả video vào cửa sổ: cần `pip install tkinterdnd2` (tuỳ chọn - không có thì app vẫn chạy bình thường).
try:
    from tkinterdnd2 import TkinterDnD as _TkDnD, DND_FILES as _DND_FILES

    class _AppBase(ctk.CTk, _TkDnD.DnDWrapper):
        pass
    _DND_IMPORT_OK = True
except Exception:
    class _AppBase(ctk.CTk):
        pass
    _DND_IMPORT_OK = False
from core.omnivoice_tts import (
    GENDER_OPTIONS as OMNI_GENDER_OPTIONS,
    AGE_OPTIONS as OMNI_AGE_OPTIONS,
    PITCH_OPTIONS as OMNI_PITCH_OPTIONS,
    STYLE_OPTIONS as OMNI_STYLE_OPTIONS,
    ACCENT_OPTIONS as OMNI_ACCENT_OPTIONS,
    DIALECT_OPTIONS as OMNI_DIALECT_OPTIONS,
    PRESET_VOICES as OMNI_PRESET_VOICES,
    build_instruct as omnivoice_build_instruct,
)
from core.gemini_fastapi_server import (
    GeminiFastAPIProcess,
    check_server_health as _gfa_check_server_health_once,
    test_chat_completion as gfa_test_chat_completion,
    get_bundled_server_dir as gfa_get_bundled_server_dir,
    DEFAULT_BASE_URL as GFA_DEFAULT_BASE_URL,
)
from core.translate import (
    check_cliproxy_health as cliproxy_check_health,
    test_cliproxy_chat_completion as cliproxy_test_chat_completion,
    CLIPROXY_DEFAULT_BASE_URL,
    DEFAULT_CLIPROXY_MODEL,
)

# Render biến thể (chống trùng nội dung) - đặt tại core/render_variant.py.
# Bọc try/except vì đây là tính năng tuỳ chọn (cần ffmpeg riêng hỗ trợ QSV) -
# nếu thiếu module hoặc lỗi import, app vẫn chạy bình thường, chỉ tắt tính
# năng render biến thể (checkbox tương ứng sẽ bị vô hiệu hoá trên giao diện).
try:
    from core.render_variant import (
        render_video as variant_render_video,
        RENDER_TARGETS as VARIANT_RENDER_TARGETS,
        get_video_info as _variant_get_video_info,
    )
    VARIANT_RENDER_AVAILABLE = True
    VARIANT_RENDER_IMPORT_ERROR = ""
except Exception as _variant_import_exc:
    variant_render_video = None
    _variant_get_video_info = None
    VARIANT_RENDER_TARGETS = {"long": (1920, 1080), "short": (1080, 1920)}
    VARIANT_RENDER_AVAILABLE = False
    VARIANT_RENDER_IMPORT_ERROR = str(_variant_import_exc)


def gfa_check_server_health(base_url, attempts: int = 3, base_timeout: float = 5.0):
    """Wrapper quanh check_server_health gốc: thử lại vài lần với timeout tăng dần
    (5s -> 8s -> 11s) trước khi thật sự báo "chưa sẵn sàng". Mục đích: 1 nhịp giật
    thoáng qua (CPU máy bận, Windows Defender quét socket mới, v.v.) không nên chặn
    hẳn người dùng bắt đầu dịch, trong khi server thực chất vẫn đang chạy tốt (như
    thấy trong log Preview/Log ngay trước đó). Trả về kết quả của lần thử THÀNH CÔNG
    đầu tiên, hoặc kết quả của lần thử CUỐI nếu cả attempts lần đều thất bại."""
    import time as _time
    ok, msg = False, ""
    for i in range(max(1, attempts)):
        ok, msg = _gfa_check_server_health_once(base_url, timeout=base_timeout + i * 3.0)
        if ok:
            return ok, msg
        if i < attempts - 1:
            _time.sleep(1.5)
    return ok, msg


import subprocess as _subprocess_orig

_original_run = _subprocess_orig.run

def _patched_run(*args, **kwargs):
    if kwargs.get("text") or kwargs.get("universal_newlines"):
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "replace")
    return _original_run(*args, **kwargs)

_subprocess_orig.run = _patched_run
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _norm_name(s: str) -> str:
    """Chuẩn hoá tên để so khớp: bỏ khoảng trắng/ký tự đặc biệt, hạ chữ thường."""
    return "".join(ch for ch in s.lower() if ch.isalnum())


def resolve_job_video(rec, root_dir: str) -> Optional[str]:
    """Tìm video output THẬT của 1 job trong lịch sử.

    history.json lưu đường dẫn lúc pipeline chạy (thư mục tạm .processing_xxx), nhưng
    sau khi xong, pipeline chuyển video sang  <root_dir>/<tên gốc> => <tiêu đề>/final_vi.mp4
    và xoá thư mục tạm - nên đường dẫn đã lưu thường không còn tồn tại. Hàm này:
      1. dùng đường dẫn đã lưu nếu file còn đó;
      2. không thì quét các thư mục con của root_dir có tiền tố trùng tên video gốc,
         chọn thư mục có thời điểm sửa gần với thời điểm chạy job nhất.
    """
    saved = getattr(rec, "output_video", "") or ""
    if saved and os.path.isfile(saved):
        return saved
    if not root_dir or not os.path.isdir(root_dir):
        return None

    stem = _norm_name(os.path.splitext(os.path.basename(getattr(rec, "input_video", "") or ""))[0])
    if not stem:
        return None

    try:
        from datetime import datetime as _dt
        ts = _dt.strptime(rec.time_str(), "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        ts = None

    best, best_score = None, None
    for name in os.listdir(root_dir):
        folder = os.path.join(root_dir, name)
        if name.startswith(".") or not os.path.isdir(folder):
            continue
        prefix = _norm_name(name.split(" => ")[0])
        if not prefix or not (prefix.startswith(stem[:60]) or stem.startswith(prefix[:60])):
            continue
        video = os.path.join(folder, "final_vi.mp4")
        if not os.path.isfile(video):
            mp4s = [f for f in os.listdir(folder) if f.lower().endswith((".mp4", ".mov", ".mkv"))]
            if not mp4s:
                continue
            video = os.path.join(folder, mp4s[0])
        mtime = os.path.getmtime(video)
        score = abs(mtime - ts) if ts is not None else -mtime   # gần giờ chạy nhất / mới nhất
        if best_score is None or score < best_score:
            best, best_score = video, score
    return best


def _apply_auto_screen_scaling():
    """TỰ ĐỘNG cân bằng toàn bộ giao diện (font chữ, padding, kích thước nút/ô nhập...)
    theo ĐÚNG độ phân giải màn hình thật của máy đang chạy - giải quyết TẬN GỐC hiện
    tượng giao diện bị lệch/quá to/quá nhỏ trên các màn hình khác nhau (laptop 1366x768,
    màn hình FullHD 1920x1080, màn hình 2K/4K, hay máy có DPI scaling khác 100% của
    Windows), thay vì phải chỉnh tay từng widget một (không xuể, dễ sót).

    Dùng ĐÚNG cơ chế `ctk.set_widget_scaling()` có sẵn của CustomTkinter - hệ số này
    áp dụng ĐỒNG LOẠT cho MỌI widget được tạo SAU đó (font, padding, corner radius...),
    nên phải gọi hàm này TRƯỚC KHI tạo cửa sổ App() chính (xem main() bên dưới).

    Cách tính: lấy độ phân giải màn hình LÀM MỐC là 1920x1080 (thiết kế gốc của giao
    diện này) - máy có màn hình NHỎ hơn mốc thì tự giảm scale (chữ/nút nhỏ lại, tránh
    tràn/khuất), máy có màn hình LỚN hơn mốc thì tự tăng scale (chữ/nút to lên, tránh
    nhìn "bé tí" giữa màn hình rộng). Giới hạn trong khoảng [0.8, 1.35] để tránh 2 cực
    đoan: quá nhỏ (chữ khó đọc) hoặc quá to (tràn màn hình ngược lại) trên các màn hình
    quá khác biệt so với mốc.
    """
    try:
        probe = ctk.CTk()
        probe.withdraw()   # không hiện cửa sổ dò này ra màn hình, chỉ dùng để đọc thông số
        screen_w = probe.winfo_screenwidth()
        screen_h = probe.winfo_screenheight()
        # Đọc thêm hệ số DPI scaling của HỆ ĐIỀU HÀNH (vd Windows đặt "Scale" 125%/150%)
        # qua winfo_fpixels - 1 "point" (1/72 inch) quy đổi ra bao nhiêu pixel màn hình
        # thật, so với mốc chuẩn 96 DPI (tương đương 100% scale trên Windows).
        try:
            os_dpi_scale = probe.winfo_fpixels("1i") / 96.0
        except Exception:
            os_dpi_scale = 1.0
        probe.destroy()

        baseline_w, baseline_h = 1920, 1080
        resolution_scale = min(screen_w / baseline_w, screen_h / baseline_h)
        # Nhân thêm hệ số DPI của OS - máy đã tự phóng to UI ở cấp hệ điều hành (vd
        # laptop 4K thu nhỏ về 150%) thì không cần scale thêm gấp đôi nữa (2 lớp scale
        # chồng lên nhau), lấy CĂN BẬC HAI để làm dịu mức ảnh hưởng thay vì cộng dồn
        # tuyến tính - tránh giao diện phóng to quá đà trên máy đã có DPI scaling cao.
        combined_scale = resolution_scale * (os_dpi_scale ** 0.5)
        combined_scale = max(0.8, min(1.35, combined_scale))

        ctk.set_widget_scaling(combined_scale)
        ctk.set_window_scaling(combined_scale)
    except Exception:
        pass   # dò lỗi (vd môi trường không có display) -> giữ nguyên scale mặc định 1.0, không chặn app khởi động

BG = "#0e0f13"
PANEL = "#15161c"
PANEL2 = "#1b1c24"
ACCENT = "#6c5ce7"
ACCENT_HOVER = "#5a4bd6"   # hover đồng bộ cho MỌI control dùng ACCENT (nút, checkbox, radio) -
                            # trước đây phần lớn thiếu hover riêng, rơi về hover mặc định của
                            # theme "blue" (lệch tông so với ACCENT tím), tạo cảm giác thô/rời rạc.
GREEN = "#2ecc71"
TEXT_MUTED = "#8b8d98"
BORDER = "#26272f"
BORDER_SOFT = "#2f3038"    # viền mảnh cho các khối PANEL2 (card) - thêm viền tinh tế thay vì chỉ
                            # dựa vào chênh lệch màu nền (PANEL2 vốn khá gần PANEL, dễ nhìn "bẹt").

def _truncate_middle(name: str, max_chars: int = 45) -> str:
    """Rút gọn tên file quá dài để KHÔNG đẩy các nút bấm cố định (Mở thư mục, Dùng
    video này...) ra ngoài vùng nhìn thấy trong danh sách file - giữ lại phần ĐẦU
    (thường chứa tên kênh/tiêu đề) và phần ĐUÔI (đuôi mở rộng .mp4/.mp3...), cắt bớt
    đoạn GIỮA bằng dấu "..." - vừa gọn vừa vẫn nhận ra được đúng file nào khi nhìn
    lướt qua danh sách (khác với cắt cụt đuôi, dễ mất luôn phần đuôi file .mp4)."""
    if len(name) <= max_chars:
        return name
    keep = max_chars - 3   # trừ 3 ký tự cho "..."
    head_len = keep * 2 // 3
    tail_len = keep - head_len
    return f"{name[:head_len]}...{name[-tail_len:]}"


FONT_FAMILY = "Segoe UI"   # font hệ thống native trên Windows (đúng nền tảng app đang chạy) -
                            # sắc nét hơn, đồng bộ với các app Windows khác, thay cho Arial vốn
                            # nhìn hơi "web-y"/thô khi đặt trong app desktop.

RADIUS_PANEL = 16          # bo góc khối PANEL ngoài cùng (trang/section lớn)
RADIUS_CARD = 14           # bo góc từng "card" PANEL2 bên trong 1 trang
RADIUS_ROW = 10            # bo góc các hàng nhỏ hơn (item trong list, badge...)

STEPS = ["Transcript", "Translate", "Voice", "Subtitles", "Export"]
# Đuôi file được coi là video khi quét thư mục cho tính năng "Render cả thư mục".
BATCH_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v", ".wmv", ".ts", ".mpg", ".mpeg"}
LANGS = ["Chinese", "English", "Vietnamese", "Japanese", "Korean", "French", "Spanish"]
PRESETS = ["Neon", "Classic", "Minimal", "Bold", "Mint", "Rose"]
# Danh sách font phổ biến để hiển thị trong combobox chọn font phụ đề.
# LƯU Ý: font phải được CÀI SẴN trên máy chạy ffmpeg/libass thì mới hiện đúng,
# nếu máy không có font đó, libass sẽ tự thay bằng font mặc định của hệ thống.
SUBTITLE_FONTS = [
    FONT_FAMILY, "Arial Black", "Tahoma", "Segoe UI", "Times New Roman",
    "Verdana", "Calibri", "Roboto", "Montserrat", "Impact",
]

# Ánh xạ nhãn hiển thị (tiếng Việt, dễ hiểu cho người dùng) sang key persona nội bộ
# mà core/translate.py:TOPIC_PERSONAS dùng. "Tự động theo chủ đề" -> None (để
# PipelineConfig.content_persona=None, AI tự nhận diện category từ transcript).
CONTENT_PERSONA_LABELS = {
    "Tự động theo chủ đề": None,
    "Khoa học (Discovery/Veritasium)": "science",
    "Lịch sử (Documentary)": "history",
    "Tâm lý (Kể chuyện)": "psychology",
    "Tài chính (Phân tích)": "finance",
    "Công nghệ (Giải thích)": "technology",
}

# Ánh xạ nhãn hiển thị (tiếng Việt) -> giá trị thuộc tính (tiếng Anh) mà OmniVoice
# hiểu được cho tham số `instruct` (Voice Design) - xem docs/voice-design.md của
# OmniVoice. "-- Không chọn --" -> None (bỏ qua thuộc tính đó, model tự quyết định).
OMNI_NONE_LABEL = "-- Không chọn --"
OMNI_GENDER_LABELS = {OMNI_NONE_LABEL: None, "Nam": "male", "Nữ": "female"}
OMNI_AGE_LABELS = {
    OMNI_NONE_LABEL: None, "Trẻ em": "child", "Thiếu niên": "teenager",
    "Thanh niên": "young adult", "Trung niên": "middle-aged", "Cao tuổi": "elderly",
}
OMNI_PITCH_LABELS = {
    OMNI_NONE_LABEL: None, "Rất trầm": "very low pitch", "Trầm": "low pitch",
    "Vừa": "moderate pitch", "Cao": "high pitch", "Rất cao": "very high pitch",
}
OMNI_STYLE_LABELS = {OMNI_NONE_LABEL: None, "Giọng thì thầm (whisper)": "whisper"}
OMNI_ACCENT_LABELS = {
    OMNI_NONE_LABEL: None,
    "Mỹ (American)": "american accent", "Anh (British)": "british accent",
    "Úc (Australian)": "australian accent", "Canada": "canadian accent",
    "Ấn Độ (Indian)": "indian accent", "Trung Quốc (Chinese)": "chinese accent",
    "Hàn Quốc (Korean)": "korean accent", "Nhật Bản (Japanese)": "japanese accent",
    "Bồ Đào Nha (Portuguese)": "portuguese accent", "Nga (Russian)": "russian accent",
}
OMNI_DIALECT_LABELS = {OMNI_NONE_LABEL: None, **{d: d for d in OMNI_DIALECT_OPTIONS}}

# Nhãn ngắn gọn (tiếng Việt) cho từng accent, dùng để hiển thị trong tên preset
# (vd "Adam (Nam · Mỹ)") - map value tiếng Anh -> chữ ngắn hiển thị.
OMNI_ACCENT_SHORT = {
    "american accent": "Mỹ", "british accent": "Anh", "australian accent": "Úc",
    "canadian accent": "Canada", "indian accent": "Ấn", "chinese accent": "Trung",
    "korean accent": "Hàn", "japanese accent": "Nhật", "portuguese accent": "Bồ",
    "russian accent": "Nga",
}
OMNI_GENDER_SHORT = {"male": "Nam", "female": "Nữ"}

OMNI_PRESET_NONE = "-- Tuỳ chỉnh (tự chọn thuộc tính) --"
OMNI_PRESET_KEEP_DEFAULT = "-- Dùng giọng mặc định --"
# {tên hiển thị: (tên, gender, age, pitch, accent)} - giữ nguyên thứ tự khai báo
# trong core/omnivoice_tts.py để hiển thị Nam trước, Nữ sau trong dropdown.
OMNI_PRESET_LABELS = {
    f"{name} ({OMNI_GENDER_SHORT[gender]} · {OMNI_ACCENT_SHORT.get(accent, accent)})": (name, gender, age, pitch, accent)
    for name, gender, age, pitch, accent in OMNI_PRESET_VOICES
}
OMNI_PRESET_LABELS_MALE = {k: v for k, v in OMNI_PRESET_LABELS.items() if v[1] == "male"}
OMNI_PRESET_LABELS_FEMALE = {k: v for k, v in OMNI_PRESET_LABELS.items() if v[1] == "female"}

# Reverse-lookup: giá trị thuộc tính (tiếng Anh) -> nhãn hiển thị (tiếng Việt),
# dùng để tự điền các dropdown fine-tune khi người dùng chọn 1 preset.
def _omni_reverse(labels_dict):
    return {v: k for k, v in labels_dict.items() if v is not None}

_OMNI_GENDER_REV = _omni_reverse(OMNI_GENDER_LABELS)
_OMNI_AGE_REV = _omni_reverse(OMNI_AGE_LABELS)
_OMNI_PITCH_REV = _omni_reverse(OMNI_PITCH_LABELS)
_OMNI_ACCENT_REV = _omni_reverse(OMNI_ACCENT_LABELS)


class StepIndicator(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color=PANEL, corner_radius=RADIUS_PANEL, **kw)
        self.dots = {}
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=16)
        for i, name in enumerate(STEPS):
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.pack(side="left", expand=True, fill="x")
            dot = ctk.CTkLabel(
                col, text="○", font=(FONT_FAMILY, 22),
                text_color=TEXT_MUTED, width=30
            )
            dot.pack()
            label = ctk.CTkLabel(col, text=name, font=(FONT_FAMILY, 12), text_color=TEXT_MUTED)
            label.pack()
            self.dots[name] = (dot, label)

    def set_state(self, name: str, state: str):
        # state: pending | active | done
        if name not in self.dots:
            return
        dot, label = self.dots[name]
        if state == "done":
            dot.configure(text="✓", text_color=GREEN)
            label.configure(text_color=GREEN)
        elif state == "active":
            dot.configure(text="●", text_color=ACCENT)
            label.configure(text_color="white")
        else:
            dot.configure(text="○", text_color=TEXT_MUTED)
            label.configure(text_color=TEXT_MUTED)


class ReupStudioApp(_AppBase):
    def __init__(self):
        super().__init__()
        self._dnd_ok = False
        if _DND_IMPORT_OK:
            try:
                self.TkdndVersion = _TkDnD._require(self)
                self._dnd_ok = True
            except Exception:
                self._dnd_ok = False
        self.title("Reup Studio - Công cụ dịch & lồng tiếng video")
        # Kích thước cửa sổ tính theo % màn hình (thay vì số cố định 1300x820 - trên màn
        # hình nhỏ hơn FullHD sẽ bị tràn/khuất, trên màn hình lớn lại trông bé tí giữa
        # màn hình trống) + CĂN GIỮA màn hình khi mở app (trước đây mở ở góc trên-trái
        # theo mặc định window manager - cảm giác thiếu chuyên nghiệp cho app thương mại).
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = min(1500, int(screen_w * 0.82))
        win_h = min(940, int(screen_h * 0.85))
        pos_x = (screen_w - win_w) // 2
        pos_y = max(0, (screen_h - win_h) // 2 - 20)   # hơi lệch lên trên trung tâm 1 chút - vị trí mắt người nhìn quen thuộc hơn là chính giữa tuyệt đối
        self.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.minsize(1180, 720)   # MỚI: chặn không cho resize nhỏ hơn mức này - dưới ngưỡng này nhiều khối 2-3 cột sẽ đè/vỡ lên nhau
        self.configure(fg_color=BG)
        self._apply_window_icon()

        self.video_path: tk.StringVar = tk.StringVar(value="Chưa chọn video")
        # Nhớ giữa các lần mở app (tự lưu cùng cấu hình): trang đang dùng + thư mục video gần nhất.
        self.last_page = tk.StringVar(value="Translate")
        self.last_video_dir = tk.StringVar(value="")
        self.work_dir = os.path.join(get_user_data_dir(), "output")
        self._batch_running = False  # đang render hàng loạt cả thư mục hay không
        # set() = đang chạy bình thường, clear() = đang tạm dừng (thread nền sẽ
        # block ở wait() giữa 2 video để người dùng kịp chỉnh lại cấu hình).
        self._batch_resume_event = threading.Event()
        self._batch_resume_event.set()
        self._variant_manual_running = False  # legacy: không còn tạo output biến thể riêng

        self._gfa_process: Optional[GeminiFastAPIProcess] = None
        self.toast = UIH.Toast(
            self, dict(PANEL2=PANEL2, ACCENT=ACCENT, BORDER=BORDER, TEXT_MUTED=TEXT_MUTED), FONT_FAMILY)
        self._build_layout()
        self._reset_steps()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
        self._log_runtime_diagnostics()
        # Trỏ ffmpeg/ffprobe về bản đi kèm trong vendor\bin (nếu có) và kiểm tra
        # thư viện còn thiếu - chạy nền để không làm chậm lúc mở app.
        try:
            from core.external_tools import setup_env
            setup_env()
        except Exception:
            pass
        threading.Thread(target=self._run_startup_check, daemon=True).start()

    def _run_startup_check(self):
        """Kiểm tra (và tự cài nếu thiếu) thư viện + công cụ ngoài cần thiết."""
        try:
            from core.startup_check import ensure_dependencies

            def _cb(message: str) -> None:
                try:
                    self.after(0, self.log, f"[Kiểm tra] {message}")
                except Exception:
                    pass

            result = ensure_dependencies(progress_cb=_cb)
            if result.get("thiếu_thư_viện"):
                self.after(0, self.toast.show,
                           "Thiếu thư viện: " + ", ".join(result["thiếu_thư_viện"]), "error", 8000)
            elif result.get("thiếu_công_cụ"):
                self.after(0, self.toast.show,
                           "Thiếu công cụ: " + ", ".join(result["thiếu_công_cụ"]), "error", 8000)
        except Exception as exc:
            try:
                self.after(0, self.log, f"[Kiểm tra] Bỏ qua kiểm tra thành phần: {exc}")
            except Exception:
                pass

    def _apply_window_icon(self):
        """Gắn logo Reup Studio làm biểu tượng cửa sổ.

        Windows chỉ nhận biểu tượng kích thước 16/32/48 - dùng ảnh PNG 64px
        để nhìn rõ nhất. Nếu thiếu file ảnh (chạy từ source chưa build logo)
        thì bỏ qua, app vẫn chạy bình thường.
        """
        try:
            icon_path = get_asset_path("reup_logo_64.png")
            if not os.path.isfile(icon_path):
                return
            from PIL import ImageTk
            img = Image.open(icon_path).convert("RGBA")
            self._window_icon_img = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._window_icon_img)
        except Exception:
            pass

    def _log_runtime_diagnostics(self):
        """In ra Python đang chạy + nơi tìm thấy (hoặc không thấy) pydub/audioop,
        để xác định chính xác cần đặt file audioop.py vào đâu."""
        try:
            import sys
            self.log(f"[Chẩn đoán] sys.executable = {sys.executable}")
            try:
                import pydub
                self.log(f"[Chẩn đoán] pydub tìm thấy tại: {os.path.dirname(pydub.__file__)}")
            except Exception as e:
                self.log(f"[Chẩn đoán] KHÔNG import được pydub: {e}")
            try:
                import audioop
                aud_file = getattr(audioop, "__file__", None)
                self.log(f"[Chẩn đoán] audioop OK - nguồn: {aud_file or '(builtin, không có __file__)'}")
            except Exception as e:
                self.log(f"[Chẩn đoán] KHÔNG import được audioop: {e}")
        except Exception:
            pass

    def _on_app_close(self):
        """Tắt tiến trình Gemini Web2API đã tự khởi động cùng app (nếu có) trước khi
        đóng cửa sổ, tránh để lại tiến trình mồ côi chạy nền sau khi thoát app."""
        self._save_settings_silent()   # tự lưu cấu hình khi thoát - khỏi lo quên bấm "Lưu cấu hình"
        try:
            if self._gfa_process is not None and self._gfa_process.is_alive:
                self._gfa_process.stop()
        except Exception:
            pass
        try:
            if getattr(self, "editor_page", None) is not None:
                self.editor_page.shutdown()
        except Exception:
            pass
        self.destroy()

    # ---------- Layout ----------
    def _build_layout(self):
        # Sidebar - tăng width 210 -> 232 (thoáng hơn, đỡ chật khi có icon + chữ dài
        # như "Voice Studio"), thêm viền phải mảnh để tách bạch rõ với content thay vì
        # chỉ dựa vào chênh lệch màu nền (PANEL vs BG khá gần nhau).
        sidebar = ctk.CTkFrame(self, fg_color=PANEL, width=232, corner_radius=0,
                                border_width=0, border_color=BORDER)
        sidebar.pack(side="left", fill="y")
        sidebar_border = ctk.CTkFrame(self, fg_color=BORDER, width=1, corner_radius=0)
        sidebar_border.pack(side="left", fill="y")

        # Header sidebar: logo Reup Studio + tên + phiên bản.
        # Logo nạp từ assets/reup_logo_128.png (nếu thiếu file thì chỉ hiện chữ).
        brand_row = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand_row.pack(fill="x", padx=22, pady=(28, 0))
        logo_path = get_asset_path("reup_logo_128.png")
        if os.path.isfile(logo_path):
            try:
                from PIL import Image as _PILImage
                self._brand_logo = ctk.CTkImage(
                    light_image=_PILImage.open(logo_path),
                    dark_image=_PILImage.open(logo_path),
                    size=(34, 34),
                )
                ctk.CTkLabel(brand_row, text="", image=self._brand_logo).pack(side="left")
                ctk.CTkLabel(brand_row, text="Reup Studio", font=(FONT_FAMILY, 19, "bold")).pack(side="left", padx=(10, 0))
            except Exception:
                ctk.CTkLabel(brand_row, text="Reup Studio", font=(FONT_FAMILY, 19, "bold")).pack(side="left")
        else:
            ctk.CTkLabel(brand_row, text="Reup Studio", font=(FONT_FAMILY, 19, "bold")).pack(side="left")
        ctk.CTkLabel(sidebar, text="v1.0", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(padx=22, anchor="w", pady=(2, 28))

        # Icon riêng cho từng mục điều hướng - giúp quét mắt nhanh hơn, trông đầy đủ/
        # chuyên nghiệp hơn so với chỉ có chữ suông trước đây.
        NAV_ICONS = {
            "Download": "⬇",
            "Translate": "🌐",
            "Voice Studio": "🎙",
            "Job Center": "🗂",
            "TikTok": "🎵",
            "YouTube": "▶",
            "Editor": "✂",
        }

        self.sidebar_buttons: dict[str, ctk.CTkButton] = {}
        self.sidebar_indicators: dict[str, ctk.CTkFrame] = {}
        nav_container = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav_container.pack(fill="x", padx=12)
        for item in ["Download", "Translate", "Editor", "Voice Studio", "Job Center", "TikTok", "YouTube"]:
            row = ctk.CTkFrame(nav_container, fg_color="transparent", height=40)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            # Thanh chỉ báo "đang chọn" bên trái (rõ ràng hơn hẳn so với chỉ đổi màu
            # chữ/nền - đây là pattern chuẩn của các app thương mại: Slack, Notion, Linear...)
            indicator = ctk.CTkFrame(row, fg_color="transparent", width=3, corner_radius=2)
            indicator.pack(side="left", fill="y", padx=(0, 2))
            self.sidebar_indicators[item] = indicator

            btn = ctk.CTkButton(
                row, text=f"{NAV_ICONS.get(item, '•')}   {item}", anchor="w",
                fg_color="transparent",
                hover_color=PANEL2,
                text_color=TEXT_MUTED,
                font=(FONT_FAMILY, 13),
                height=38, corner_radius=8,
                command=lambda name=item: self.show_page(name),
            )
            btn.pack(side="left", fill="both", expand=True)
            self.sidebar_buttons[item] = btn

        # ----- Lưu / nạp lại toàn bộ tuỳ chỉnh (watermark, âm thanh, phụ đề...) -----
        # để không phải cấu hình lại từ đầu mỗi lần mở app mới.
        ctk.CTkFrame(sidebar, fg_color=BORDER, height=1).pack(fill="x", padx=22, pady=(20, 16))
        settings_row = ctk.CTkFrame(sidebar, fg_color="transparent")
        settings_row.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkButton(
            settings_row, text="💾 Lưu cấu hình", height=34, font=(FONT_FAMILY, 12),
            fg_color=PANEL2, hover_color=BORDER, corner_radius=8, command=self._save_settings_to_file,
        ).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(
            settings_row, text="📂 Nạp lại cấu hình", height=34, font=(FONT_FAMILY, 12),
            fg_color=PANEL2, hover_color=BORDER, corner_radius=8, command=lambda: self._load_settings_from_file(silent=False),
        ).pack(fill="x")

        ctk.CTkLabel(
            sidebar, justify="left", anchor="w", wraplength=196, font=(FONT_FAMILY, 10), text_color=TEXT_MUTED,
            text="Phím tắt\nCtrl+1…7  chuyển trang\nCtrl+O  chọn video\nCtrl+Enter  bắt đầu dịch\nCtrl+S  lưu cấu hình"
                 + ("\n\nKéo-thả video vào cửa sổ để mở nhanh" if self._dnd_ok else ""),
        ).pack(side="bottom", anchor="w", padx=22, pady=(0, 20))

        # Main content container - chứa nhiều "trang", chỉ 1 trang hiện tại được pack
        self.content_container = ctk.CTkFrame(self, fg_color=BG)
        self.content_container.pack(side="left", fill="both", expand=True, padx=24, pady=22)

        self.pages: dict[str, ctk.CTkFrame] = {}
        self.pages["Translate"] = self._wrap_page_scrollable(self._build_translate_page)
        self.pages["Job Center"] = self._wrap_page_scrollable(self._build_job_center_page)
        self.pages["Voice Studio"] = self._wrap_page_scrollable(self._build_voice_studio_page)
        self.pages["Download"] = self._wrap_page_scrollable(self._build_download_page)
        self.pages["TikTok"] = self._wrap_page_scrollable(self._build_tiktok_page)
        self.pages["YouTube"] = self._wrap_page_scrollable(self._build_youtube_page)
        # Editor chiếm trọn khung (có timeline riêng, không bọc scroll). Khung rỗng
        # này được dựng nội dung thật ở lần mở đầu tiên - xem _ensure_editor().
        self.pages["Editor"] = ctk.CTkFrame(self.content_container, fg_color=BG)
        self.editor_page = None

        self.show_page("Translate")

        nav_order = ["Download", "Translate", "Editor", "Voice Studio", "Job Center", "TikTok", "YouTube"]
        UIH.bind_shortcuts(
            self, nav_order, self.show_page,
            open_video=self._shortcut_open_video, start=self._shortcut_start,
            save=lambda: self._save_settings_silent(toast=True),
        )
        if self._dnd_ok:
            try:
                self.drop_target_register(_DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop_files)
            except Exception:
                self._dnd_ok = False

        # Tự động nạp lại cấu hình đã lưu từ lần trước (nếu có) - PHẢI gọi SAU KHI
        # toàn bộ trang/biến đã được tạo xong ở trên, nếu không sẽ không tìm thấy
        # thuộc tính để nạp giá trị vào.
        self.after(200, lambda: self._load_settings_from_file(silent=True))
        # Mở lại đúng trang đã dùng lần trước (bỏ qua Editor vì dựng nặng).
        def _restore_last_page():
            name = self.last_page.get()
            if name in self.pages and name != "Editor":
                self.show_page(name)
        self.after(320, _restore_last_page)
        # Tự khởi động Gemini Web2API (nếu bật) SAU KHI đã nạp cấu hình đã lưu, để
        # dùng đúng Base URL/API key người dùng từng lưu lần trước.
        self.after(600, self._maybe_autostart_gemini_fastapi)

    def _wrap_page_scrollable(self, builder_fn) -> ctk.CTkScrollableFrame:
        """Boc noi dung tung trang (Translate, TikTok, YouTube...) trong 1
        CTkScrollableFrame - de khi noi dung dai hon man hinh (nhieu tuy chon,
        panel cai dat nang cao mo ra...) nguoi dung con cuon xem het duoc, thay
        vi bi cat mat phia duoi khong co cach nao xem toi."""
        scroll = ctk.CTkScrollableFrame(
            self.content_container, fg_color=BG,
            scrollbar_button_color=ACCENT, scrollbar_button_hover_color=ACCENT_HOVER,
        )
        # Lam thanh cuon TO va NOI BAT hon mac dinh (mac dinh cua customtkinter
        # rat manh, gan nhu khong thay, gay cam giac "khong cuon duoc").
        try:
            scroll._scrollbar.configure(width=18)
        except Exception:
            pass

        inner_page = builder_fn(scroll)
        inner_page.pack(fill="both", expand=True)

        # customtkinter mac dinh CHI bind cuon chuot cho nhung widget da ton tai
        # NGAY LUC scrollable frame duoc tao - toan bo noi dung trang (duoc them
        # vao SAU, ben trong builder_fn) khong tu duoc bind, nen tro chuot dang o
        # tren 1 o nhap/dropdown/nut la khong cuon duoc, phai di chuot ra vung
        # trong mo hoac keo thanh cuon. Ham nay bind lai DE QUY cho toan bo cay
        # widget con, de cuon duoc bang chuot o BAT KY DAU tren trang.
        def _on_wheel(event):
            delta = event.delta if event.delta else (-120 if event.num == 4 else 120)
            scroll._parent_canvas.yview_scroll(int(-1 * (delta / 120)), "units")
            return "break"

        def _bind_wheel_recursive(widget, is_root=True):
            # Khong de len len cac CTkScrollableFrame con (vd danh sach video) -
            # de chung tu quan ly cuon rieng cua chinh no, tranh xung dot huong cuon.
            if not is_root and isinstance(widget, ctk.CTkScrollableFrame):
                return
            try:
                widget.bind("<MouseWheel>", _on_wheel, add="+")
                widget.bind("<Button-4>", _on_wheel, add="+")
                widget.bind("<Button-5>", _on_wheel, add="+")
            except Exception:
                pass
            for child in widget.winfo_children():
                _bind_wheel_recursive(child, is_root=False)

        self.after(80, lambda: _bind_wheel_recursive(inner_page))
        return scroll

    def show_page(self, name: str):
        try:
            self.last_page.set(name)
        except Exception:
            pass
        for pname, frame in self.pages.items():
            frame.pack_forget()
            btn = self.sidebar_buttons[pname]
            indicator = self.sidebar_indicators[pname]
            active = pname == name
            btn.configure(
                fg_color=PANEL2 if active else "transparent",
                text_color="white" if active else TEXT_MUTED,
                font=(FONT_FAMILY, 13, "bold" if active else "normal"),
            )
            indicator.configure(fg_color=ACCENT if active else "transparent")
        self.pages[name].pack(fill="both", expand=True)
        if name == "Job Center":
            self._refresh_job_center()
        elif name == "Editor":
            self._ensure_editor()

    # ---------- Trang Editor (dựng video kiểu CapCut - core/editor_*.py) ----------
    def _ensure_editor(self):
        """Dựng EditorPage ở lần mở đầu tiên. Lỗi import/thiếu thư viện chỉ hiện thông
        báo ngay trong trang Editor, KHÔNG làm hỏng phần còn lại của app."""
        if self.editor_page is not None:
            return self.editor_page
        host = self.pages["Editor"]
        try:
            from core.editor_ui import EditorPage
            self.editor_page = EditorPage(
                host, app=self, font=FONT_FAMILY,
                theme=dict(BG=BG, PANEL=PANEL, PANEL2=PANEL2, ACCENT=ACCENT,
                           ACCENT_HOVER=ACCENT_HOVER, TEXT_MUTED=TEXT_MUTED,
                           BORDER=BORDER, GREEN=GREEN),
            )
            self.editor_page.pack(fill="both", expand=True)
        except Exception as e:
            import traceback
            ctk.CTkLabel(
                host, text_color=TEXT_MUTED, justify="left", font=(FONT_FAMILY, 13),
                text=(
                    f"Không mở được Editor: {e}\n\n"
                    "• Báo 'No module named core.editor_...': chép 3 file editor_ui.py, editor_media.py, "
                    "editor_model.py vào thư mục core/ (cạnh pipeline.py).\n"
                    "• Báo thiếu thư viện: pip install av pillow numpy imageio-ffmpeg"
                ),
            ).pack(padx=24, pady=24, anchor="w")
            self.log(f"[Editor] Lỗi khởi tạo: {traceback.format_exc()}")
        return self.editor_page

    def open_in_editor(self, video_path: str, srt_path: Optional[str] = None) -> bool:
        """Chuyển sang trang Editor và mở video (+ file .srt tuỳ chọn) thành dự án mới."""
        self.show_page("Editor")
        page = self._ensure_editor()
        if page is None:
            return False
        return bool(page.open_media(video_path, srt_path))

    # ---------- Trang Translate (pipeline chính) ----------
    def _build_translate_page(self, parent) -> ctk.CTkFrame:
        main = ctk.CTkFrame(parent, fg_color=BG)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="Translate", font=(FONT_FAMILY, 22, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Pipeline tự động: tách thoại → dịch → giọng đọc → xuất video",
            font=(FONT_FAMILY, 12), text_color=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 12))

        # Input video row
        input_row = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=RADIUS_PANEL)
        input_row.pack(fill="x", pady=(0, 14))
        inner = ctk.CTkFrame(input_row, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)
        ctk.CTkLabel(inner, text="▶", font=(FONT_FAMILY, 20), text_color=ACCENT).pack(side="left", padx=(0, 12))
        # SỬA THỨ TỰ: pack 2 nút (kích thước CỐ ĐỊNH) TRƯỚC info/tên file (co giãn) -
        # cùng lý do đã sửa ở khu vực "Video đã tải" bên dưới: Tkinter ưu tiên chỗ cho
        # widget pack() TRƯỚC, tên video dài (không giới hạn qua textvariable) pack
        # trước như code cũ sẽ đẩy nút ra ngoài vùng nhìn thấy.
        self.run_btn = ctk.CTkButton(
            inner, text="▶ Bắt đầu dịch", width=150, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self.start_pipeline,
        )
        self.run_btn.pack(side="right", padx=6)
        # Render hàng loạt: chọn 1 thư mục (mặc định gợi ý Downloads), tự tìm hết
        # video trong đó và render LẦN LƯỢT theo đúng cấu hình đang thiết lập trên
        # giao diện hiện tại - không cần bấm "Chọn video" + "Bắt đầu dịch" cho từng file.
        self.batch_btn = ctk.CTkButton(
            inner, text="📁 Render cả thư mục", width=170,
            fg_color="transparent", border_width=1, border_color=ACCENT,
            command=self.start_batch_pipeline,
        )
        self.batch_btn.pack(side="right", padx=6)
        # Nút tạm dừng/tiếp tục hàng loạt: CHỈ hiện ra khi đang render cả thư mục
        # (pack/pack_forget động), để không chiếm chỗ lúc bình thường.
        self.batch_pause_btn = ctk.CTkButton(
            inner, text="⏸ Tạm dừng", width=110,
            fg_color="#8a6d1a", hover_color="#a5842a",
            command=self._toggle_batch_pause,
        )
        ctk.CTkButton(inner, text="Chọn video", width=120, command=self.choose_video).pack(side="right", padx=6)
        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkLabel(info, text="INPUT VIDEO" + ("   ·   kéo-thả file vào cửa sổ để chọn nhanh" if self._dnd_ok else ""),
                     font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkLabel(info, textvariable=self.video_path, font=(FONT_FAMILY, 13, "bold"), anchor="w", justify="left").pack(anchor="w", fill="x")

        # Step indicator
        self.steps_panel = StepIndicator(main)
        self.steps_panel.pack(fill="x", pady=(0, 14))

        # Config + preview split
        split = ctk.CTkFrame(main, fg_color="transparent")
        split.pack(fill="both", expand=True)

        cfg_panel = ctk.CTkScrollableFrame(split, fg_color=PANEL, corner_radius=RADIUS_PANEL, width=680)
        cfg_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self._build_config_panel(cfg_panel)
        # Hàng nút "Đi tới: ..." - panel cấu hình rất dài, bấm để nhảy thẳng tới mục cần chỉnh.
        try:
            section_nav = UIH.build_section_nav(
                main, cfg_panel, dict(PANEL2=PANEL2, ACCENT=ACCENT, BORDER=BORDER, TEXT_MUTED=TEXT_MUTED), FONT_FAMILY)
            section_nav.pack(fill="x", pady=(0, 8), before=split)
        except Exception:
            pass

        right_panel = ctk.CTkFrame(split, fg_color=PANEL, corner_radius=RADIUS_PANEL, width=340)
        right_panel.pack(side="left", fill="both")
        self._build_right_panel(right_panel)

        return main

    # ---------- Trang Job Center (lịch sử job - đọc thật từ file) ----------
    def _build_job_center_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color=BG)

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="Job Center", font=(FONT_FAMILY, 22, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Lịch sử các lần dịch video đã chạy (đọc từ reup_output/history.json)",
            font=(FONT_FAMILY, 12), text_color=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 12))

        top_row = ctk.CTkFrame(page, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(top_row, text="🔄 Làm mới", width=110, command=self._refresh_job_center).pack(side="left")

        self.job_list_frame = ctk.CTkScrollableFrame(page, fg_color=PANEL, corner_radius=RADIUS_PANEL)
        self.job_list_frame.pack(fill="both", expand=True)

        return page

    def _refresh_job_center(self):
        from core.history import load_history

        for w in self.job_list_frame.winfo_children():
            w.destroy()

        records = load_history(self.work_dir)
        if not records:
            ctk.CTkLabel(
                self.job_list_frame, text="Chưa có job nào chạy. Qua tab Translate để bắt đầu.",
                text_color=TEXT_MUTED
            ).pack(padx=16, pady=16, anchor="w")
            return

        for rec in reversed(records):
            row = ctk.CTkFrame(self.job_list_frame, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
            row.pack(fill="x", padx=10, pady=6)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=10)

            status_color = GREEN if rec.status == "done" else "#e74c3c"
            status_icon = "✓" if rec.status == "done" else "✕"
            ctk.CTkLabel(inner, text=status_icon, text_color=status_color, font=(FONT_FAMILY, 16, "bold"), width=24).pack(side="left")

            info = ctk.CTkFrame(inner, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=8)
            name = os.path.basename(rec.input_video)
            ctk.CTkLabel(info, text=f"{name}  ({rec.source_lang} → {rec.target_lang})", font=(FONT_FAMILY, 13, "bold")).pack(anchor="w")
            detail = f"{rec.time_str()} · sub={rec.subtitles} · dub={rec.dubbing} · watermark={rec.watermark}"
            ctk.CTkLabel(info, text=detail, font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
            if rec.status == "error":
                ctk.CTkLabel(info, text=f"Lỗi: {rec.error_msg[:120]}", font=(FONT_FAMILY, 11), text_color="#e74c3c").pack(anchor="w")

            if rec.status == "done":
                video = resolve_job_video(rec, self.work_dir)
                if video:
                    ctk.CTkButton(
                        inner, text="Mở thư mục", width=100,
                        command=lambda p=video: self._open_folder(os.path.dirname(p)),
                    ).pack(side="right")
                    ctk.CTkButton(
                        inner, text="✂ Mở trong Editor", width=140,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER,
                        command=lambda r=rec, p=video: self._open_job_in_editor(r, p),
                    ).pack(side="right", padx=(0, 8))
                else:
                    ctk.CTkButton(
                        inner, text="📂 Chọn video…", width=120,
                        fg_color=PANEL, hover_color=BORDER, border_width=1, border_color=BORDER_SOFT,
                        command=lambda r=rec: self._open_job_in_editor(r, None),
                    ).pack(side="right")
                    ctk.CTkLabel(
                        inner, text="Không thấy file output", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED,
                    ).pack(side="right", padx=(0, 10))

        return

    def _open_job_in_editor(self, rec, video: Optional[str] = None):
        """Mở video output của 1 job trong Editor để kiểm tra / chỉnh sửa lại.
        - Phụ đề ĐÃ đốt cứng vào hình (rec.subtitles) -> chỉ mở video, không nạp .srt
          (nếu nạp thêm sẽ bị chữ chồng đôi).
        - Phụ đề CHƯA đốt -> nạp kèm translated.srt (nếu còn) để sửa từng câu.
        Không dò ra video -> mở hộp thoại để người dùng tự chọn file."""
        if not video or not os.path.isfile(video):
            video = filedialog.askopenfilename(
                title="Chọn video output để mở trong Editor",
                initialdir=self.work_dir if os.path.isdir(self.work_dir) else None,
                filetypes=[("Video", "*.mp4 *.mov *.mkv *.avi *.webm"), ("Tất cả", "*.*")],
            )
            if not video:
                return
        srt = None
        if not getattr(rec, "subtitles", False):
            cand = os.path.join(os.path.dirname(video), "translated.srt")
            if os.path.isfile(cand):
                srt = cand
        self.open_in_editor(video, srt)

    # ---------- Trang Voice Studio (test giọng đọc TTS độc lập - chạy thật) ----------
    def _build_voice_studio_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color=BG)

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="Voice Studio", font=(FONT_FAMILY, 22, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Test nhanh giọng đọc AI (edge-tts) trước khi dùng cho dubbing",
            font=(FONT_FAMILY, 12), text_color=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 12))

        panel = ctk.CTkFrame(page, fg_color=PANEL, corner_radius=RADIUS_PANEL)
        panel.pack(fill="both", expand=True)
        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(inner, text="Ngôn ngữ / giọng", text_color=TEXT_MUTED).pack(anchor="w")
        self.vs_lang = ctk.StringVar(value="English")
        ctk.CTkComboBox(inner, values=LANGS, variable=self.vs_lang, fg_color=PANEL2, border_color=BORDER, width=280).pack(anchor="w", pady=(4, 14))

        ctk.CTkLabel(inner, text="Engine giọng đọc", text_color=TEXT_MUTED).pack(anchor="w")
        self.vs_engine = ctk.StringVar(value="online")
        ctk.CTkComboBox(
            inner, values=["online", "offline", "clone"], variable=self.vs_engine,
            fg_color=PANEL2, border_color=BORDER, width=280,
            command=lambda _v=None: self._on_vs_engine_change(),
        ).pack(anchor="w", pady=(4, 14))
        ctk.CTkLabel(
            inner, text="online = edge-tts (hay hơn, cần mạng, có thể lỗi tạm thời từ server Microsoft)\noffline = giọng máy tính (luôn chạy được, không cần mạng)\nclone = giọng riêng của bạn (XTTS-v2, cần voice profile đã tạo bằng setup_voice_clone.py)",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left"
        ).pack(anchor="w", pady=(0, 14))

        self.vs_voice_name = ctk.StringVar(value="")
        vs_voice_row = ctk.CTkFrame(inner, fg_color="transparent")
        vs_voice_row.pack(anchor="w", pady=(0, 14))
        ctk.CTkLabel(vs_voice_row, text="Voice profile (clone): ", text_color=TEXT_MUTED).pack(side="left")
        self.vs_voice_combo = ctk.CTkComboBox(
            vs_voice_row, values=[], variable=self.vs_voice_name,
            fg_color=PANEL2, border_color=BORDER, width=200,
        )
        self.vs_voice_combo.pack(side="left")
        ctk.CTkButton(vs_voice_row, text="🔄", width=36, command=self._refresh_vs_voice_profiles).pack(side="left", padx=6)
        self._refresh_vs_voice_profiles()
        self._on_vs_engine_change()

        ctk.CTkLabel(inner, text="Nhập câu thoại cần đọc thử", text_color=TEXT_MUTED).pack(anchor="w")
        self.vs_text = ctk.CTkTextbox(inner, height=120, fg_color=PANEL2)
        self.vs_text.pack(fill="x", pady=(4, 14))
        self.vs_text.insert("end", "Hello, this is a voice test from Reup Studio.")

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(anchor="w")
        self.vs_status = ctk.CTkLabel(inner, text="", text_color=TEXT_MUTED)
        self.vs_run_btn = ctk.CTkButton(btn_row, text="▶ Tạo & phát thử", fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._run_voice_test)
        self.vs_run_btn.pack(side="left")
        self.vs_status.pack(side="left", padx=12)

        return page

    def _refresh_vs_voice_profiles(self):
        names = self._list_voice_profiles()
        self.vs_voice_combo.configure(values=names)
        if names and self.vs_voice_name.get() not in names:
            self.vs_voice_name.set(names[0])
        elif not names:
            self.vs_voice_name.set("")

    def _on_vs_engine_change(self):
        state = "normal" if self.vs_engine.get() == "clone" else "disabled"
        try:
            self.vs_voice_combo.configure(state=state)
        except Exception:
            pass

    def _run_voice_test(self):
        text = self.vs_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Thiếu nội dung", "Nhập câu thoại cần đọc thử.")
            return
        if self.vs_engine.get() == "clone" and not self.vs_voice_name.get():
            messagebox.showwarning(
                "Thiếu voice profile",
                "Chưa có/chưa chọn voice profile để clone. Chạy setup_voice_clone.py trước.",
            )
            return
        self.vs_run_btn.configure(state="disabled", text="Đang tạo giọng...")
        self.vs_status.configure(text="")
        threading.Thread(
            target=self._voice_test_thread,
            args=(text, self.vs_lang.get(), self.vs_engine.get(), self.vs_voice_name.get()),
            daemon=True,
        ).start()

    def _voice_test_thread(self, text: str, lang: str, engine: str, voice_name: str = ""):
        try:
            from core.transcribe import SubtitleSegment
            from core.tts import synthesize_segments

            os.makedirs(self.work_dir, exist_ok=True)
            out_dir = os.path.join(self.work_dir, "voice_studio_test")

            engine_msg = {
                "online": " (online, tự retry nếu lỗi)",
                "offline": " (offline)",
                "clone": " (clone - giọng riêng của bạn, có thể mất vài phút nếu tải model lần đầu)",
            }.get(engine, "")
            self.after(0, lambda: self.vs_status.configure(
                text="Đang tạo giọng đọc..." + engine_msg,
                text_color=TEXT_MUTED))

            fake_seg = [SubtitleSegment(index=1, start=0, end=0, text=text)]
            paths = synthesize_segments(
                fake_seg, lang, out_dir, engine=engine,
                voice_name=voice_name or None,
                profiles_dir=self.voice_profiles_dir,
            )
            out_path = paths[0]

            if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                raise RuntimeError("File audio tạo ra rỗng")

            self.after(0, lambda: self.vs_status.configure(text="Đang phát...", text_color=TEXT_MUTED))

            import subprocess, shutil as _sh
            if _sh.which("ffplay") is None:
                self.after(0, lambda: self.vs_status.configure(
                    text=f"✓ Đã tạo file (chưa có ffplay để nghe thử): {out_path}", text_color=GREEN))
            else:
                subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", out_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self.after(0, lambda: self.vs_status.configure(text=f"✓ Đã tạo & đang phát: {out_path}", text_color=GREEN))

        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda: self.vs_status.configure(
                text=f"✕ Lỗi: {err_msg}\n(Gợi ý: đổi engine sang 'offline' để không phụ thuộc mạng)",
                text_color="#e74c3c"))
        finally:
            self.after(0, lambda: self.vs_run_btn.configure(state="normal", text="▶ Tạo & phát thử"))

    # ---------- Trang Download (tải video từ Douyin + danh sách file output) ----------
    def _build_download_page(self, parent) -> ctk.CTkFrame:
        # LƯU Ý: trang này đã được bọc trong 1 CTkScrollableFrame ở
        # _wrap_page_scrollable() rồi — dùng CTkFrame thường ở đây (không
        # phải CTkScrollableFrame) để tránh scrollable-frame LỒNG trong
        # scrollable-frame. Lồng 2 lớp như vậy làm customtkinter tính sai
        # chiều cao nội dung, sinh ra khoảng trống trống trơn rất to giữa
        # các khối (đúng lỗi trong ảnh chụp: khối "Tải video từ Douyin" bị
        # kéo giãn cao bất thường dù bên trong chỉ có vài dòng).
        page = ctk.CTkFrame(parent, fg_color=BG)

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="Download", font=(FONT_FAMILY, 22, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Tải video từ Douyin (1 video hoặc cả trang cá nhân) hoặc từ link bất kỳ (YouTube, TikTok, X, Facebook...) để dùng làm input cho Translate",
            font=(FONT_FAMILY, 12), text_color=TEXT_MUTED
        ).pack(anchor="w", pady=(0, 12))

        # ----- Khối MỚI: Tải hàng loạt từ Douyin (dùng mô-đun douyin_batch) -----
        # Khối này dùng bộ tải Douyin chuyên dụng: tải được CẢ trang cá nhân
        # (hàng trăm video), có chống tải trùng, tự thử lại và chống bot.
        try:
            from core.douyin_batch_card import DouyinBatchCard, default_video_dir

            self.douyin_batch_out_dir = tk.StringVar(value=default_video_dir())
            self.douyin_batch_card = DouyinBatchCard(
                page,
                theme=dict(PANEL=PANEL, PANEL2=PANEL2, ACCENT=ACCENT, ACCENT_HOVER=ACCENT_HOVER,
                           TEXT_MUTED=TEXT_MUTED, BORDER=BORDER, BORDER_SOFT=BORDER_SOFT, GREEN=GREEN,
                           RADIUS_PANEL=RADIUS_PANEL, RADIUS_CARD=RADIUS_CARD, RADIUS_ROW=RADIUS_ROW),
                font=FONT_FAMILY,
                out_dir_var=self.douyin_batch_out_dir,
                cookie_path=get_douyin_cookie_path(),
                log=self.log,
                open_folder=self._open_folder,
                on_use=self._use_downloaded_video,
            )
            self.douyin_batch_card.pack(fill="x", pady=(0, 14))
        except Exception as e:
            self.log(f"[Download] Không dựng được khối tải hàng loạt Douyin: {e}")

        # ----- Khối: Tải nhanh (yt-dlp) -----
        douyin_panel = ctk.CTkFrame(page, fg_color=PANEL, corner_radius=RADIUS_PANEL)
        douyin_panel.pack(fill="x", pady=(0, 14))
        dinner = ctk.CTkFrame(douyin_panel, fg_color="transparent")
        dinner.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(dinner, text="⬇ Tải nhanh (yt-dlp)", font=(FONT_FAMILY, 14, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            dinner,
            text="Dán link video/bài lẻ hoặc link trang cá nhân (mỗi dòng 1 link) - hỗ trợ CẢ Douyin lẫn Xiaohongshu, dán chung 1 ô cũng được, tự nhận diện theo domain. Link trang cá nhân sẽ tải NHIỀU video.",
            font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", pady=(2, 8))

        self.douyin_urls_box = ctk.CTkTextbox(dinner, height=80, fg_color=PANEL2)
        self.douyin_urls_box.pack(fill="x", pady=(0, 10))
        self.douyin_urls_box.insert(
            "end",
            "https://v.douyin.com/-YGh7Z21zaY/\nhttps://v.douyin.com/W9J5P4N27gU/ 复制此链接，打开Dou音搜索，直接观看视频！",
        )

        opt_row = ctk.CTkFrame(dinner, fg_color="transparent")
        opt_row.pack(fill="x", pady=(0, 4))

        max_wrap = ctk.CTkFrame(opt_row, fg_color="transparent")
        max_wrap.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(max_wrap, text="Giới hạn video / trang cá nhân", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        self.douyin_max_videos = tk.StringVar(value="20")
        ctk.CTkEntry(max_wrap, textvariable=self.douyin_max_videos, width=100, fg_color=PANEL2, border_color=BORDER).pack(anchor="w", pady=(4, 0))

        # Cookie Douyin: đường dẫn CỐ ĐỊNH trong app, người dùng không phải chọn.
        #   <thư mục app>\cookies\douyin_cookies.txt
        # Nếu thư mục cài đặt không ghi được (đặt ở Program Files), app tự chuyển
        # sang thư mục dữ liệu người dùng: %APPDATA%\ReupStudio\cookies\
        # Cookie đăng nhập Douyin/Xiaohongshu - dùng chung với khối tải hàng loạt,
        # nằm ở vị trí cố định <thư mục app>\cookies\douyin_cookies.txt
        self.douyin_cookies_file_var = tk.StringVar(value=get_douyin_cookie_path())
        self.douyin_cookies_browser = ctk.StringVar(value="(không dùng)")

        status_wrap = ctk.CTkFrame(opt_row, fg_color="transparent")
        status_wrap.pack(side="left")
        ctk.CTkLabel(status_wrap, text="Cookie đăng nhập Douyin/Xiaohongshu", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        status_row = ctk.CTkFrame(status_wrap, fg_color="transparent")
        status_row.pack(anchor="w", pady=(4, 0))
        self.douyin_cookie_status_label = ctk.CTkLabel(status_row, text="", font=(FONT_FAMILY, 12))
        self.douyin_cookie_status_label.pack(side="left")
        self.douyin_cookie_toggle_btn = ctk.CTkButton(
            status_row, text="⚙️", width=30, height=26, fg_color="transparent", hover_color=PANEL2,
            command=self._toggle_douyin_cookie_advanced,
        )
        self.douyin_cookie_toggle_btn.pack(side="left", padx=(6, 0))

        # ----- Panel cau hinh chi tiet cookie - an mac dinh NEU da lien ket san
        # (huong toi trai nghiem gon cho khach hang thuong mai), chi hien khi
        # chua co cookie nao hoac nguoi dung bam nut ⚙️ mo ra. -----
        self._douyin_cookie_advanced_visible = not os.path.isfile(self.douyin_cookies_file_var.get())
        self.douyin_cookie_advanced_panel = ctk.CTkFrame(dinner, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        adv_inner = ctk.CTkFrame(self.douyin_cookie_advanced_panel, fg_color="transparent")
        adv_inner.pack(fill="x", padx=14, pady=12)

        cookie_wrap = ctk.CTkFrame(adv_inner, fg_color="transparent")
        cookie_wrap.pack(side="left")
        ctk.CTkLabel(cookie_wrap, text="Lấy cookie từ trình duyệt (nếu cần)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkComboBox(
            cookie_wrap, values=["(không dùng)", "chrome", "edge", "firefox", "brave", "opera", "vivaldi", "safari"],
            variable=self.douyin_cookies_browser, fg_color=PANEL2, border_color=BORDER, width=180,
        ).pack(anchor="w", pady=(4, 0))

        cookiefile_wrap = ctk.CTkFrame(adv_inner, fg_color="transparent")
        cookiefile_wrap.pack(side="left", padx=(20, 0))
        ctk.CTkLabel(cookiefile_wrap, text="...hoặc dùng file cookies.txt có sẵn", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        cookiefile_row = ctk.CTkFrame(cookiefile_wrap, fg_color="transparent")
        cookiefile_row.pack(anchor="w", pady=(4, 0))
        initial_text = (
            os.path.basename(self.douyin_cookies_file_var.get())
            if os.path.isfile(self.douyin_cookies_file_var.get())
            else "Chưa chọn file"
        )
        self.douyin_cookies_file_label = ctk.CTkLabel(
            cookiefile_row, text=initial_text,
            text_color=("white" if os.path.isfile(self.douyin_cookies_file_var.get()) else TEXT_MUTED),
            font=(FONT_FAMILY, 11), width=140, anchor="w",
        )
        self.douyin_cookies_file_label.pack(side="left", padx=(0, 8))
        ctk.CTkButton(cookiefile_row, text="Chọn cookies.txt", width=130, command=self._choose_douyin_cookies_file).pack(side="left")
        ctk.CTkLabel(
            cookiefile_wrap,
            text="Chỉ cần chọn 1 lần — app tự lưu lại cố định, các lần mở app sau tự dùng luôn, "
                 "không cần chọn lại. Xuất file bằng extension 'Get cookies.txt LOCALLY' khi đang\n"
                 "đăng nhập douyin.com trên trình duyệt.",
            font=(FONT_FAMILY, 9), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        def _sync_cookies_label(*_args):
            p = self.douyin_cookies_file_var.get()
            if os.path.isfile(p):
                self.douyin_cookies_file_label.configure(text=os.path.basename(p), text_color="white")
            else:
                self.douyin_cookies_file_label.configure(text="Chưa chọn file", text_color=TEXT_MUTED)
            self._refresh_douyin_cookie_status()
        self.douyin_cookies_file_var.trace_add("write", _sync_cookies_label)
        self.douyin_cookies_browser.trace_add("write", lambda *_a: self._refresh_douyin_cookie_status())

        btn_row = ctk.CTkFrame(dinner, fg_color="transparent")
        self._douyin_cookie_panel_anchor = btn_row
        if self._douyin_cookie_advanced_visible:
            self.douyin_cookie_advanced_panel.pack(fill="x", pady=(8, 10))
        btn_row.pack(fill="x")
        self.douyin_download_btn = ctk.CTkButton(
            btn_row, text="⬇ Tải xuống", fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._start_douyin_download,
        )
        self.douyin_download_btn.pack(side="left")

        self.douyin_progress = ctk.CTkProgressBar(dinner, fg_color=BORDER, progress_color=ACCENT)
        self.douyin_progress.set(0)
        self.douyin_progress.pack(fill="x", pady=(12, 4))
        self.douyin_status_label = ctk.CTkLabel(dinner, text="Sẵn sàng", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, wraplength=600, justify="left")
        self.douyin_status_label.pack(anchor="w")

        self._refresh_douyin_cookie_status()

        # ----- Khối: Tải video từ LINK BẤT KỲ (YouTube, TikTok, X, Facebook... qua yt-dlp) -----
        # Dán link -> bấm Tải xuống. Lưu chung thư mục "downloads" với khối Douyin nên video tải về
        # tự hiện ở danh sách "Video đã tải" bên dưới (có nút "Dùng video này" đưa sang Translate).
        try:
            from core.download_card import DownloadAnyCard
            self.download_any_card = DownloadAnyCard(
                page,
                theme=dict(PANEL=PANEL, PANEL2=PANEL2, ACCENT=ACCENT, ACCENT_HOVER=ACCENT_HOVER, TEXT_MUTED=TEXT_MUTED,
                           BORDER=BORDER, BORDER_SOFT=BORDER_SOFT, GREEN=GREEN,
                           RADIUS_PANEL=RADIUS_PANEL, RADIUS_CARD=RADIUS_CARD),
                font=FONT_FAMILY,
                out_dir=lambda: os.path.join(self.work_dir, "downloads"),
                log=self.log,
                on_done=self._refresh_douyin_downloads,
                on_use=self._use_downloaded_video,
                open_folder=self._open_folder,
            )
            self.download_any_card.pack(fill="x", pady=(0, 14))
        except Exception as e:
            self.log(f"[Download] Không dựng được khối tải link bất kỳ: {e}")

        # ----- Khối: Video đã tải (chọn để dùng cho Translate) -----
        dl_header_row = ctk.CTkFrame(page, fg_color="transparent")
        dl_header_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(dl_header_row, text="Video đã tải", font=(FONT_FAMILY, 14, "bold")).pack(side="left")
        ctk.CTkButton(dl_header_row, text="🔄 Làm mới", width=100, command=self._refresh_douyin_downloads).pack(side="right")

        self.douyin_list_frame = ctk.CTkScrollableFrame(page, fg_color=PANEL, corner_radius=RADIUS_PANEL, height=180)
        self.douyin_list_frame.pack(fill="x", pady=(0, 18))
        self._refresh_douyin_downloads()

        # ----- Khối: File đã xuất (từ Translate) -----
        out_header_row = ctk.CTkFrame(page, fg_color="transparent")
        out_header_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(out_header_row, text="File đã xuất (Translate)", font=(FONT_FAMILY, 14, "bold")).pack(side="left")
        ctk.CTkButton(out_header_row, text="📂 Mở thư mục output", width=150, command=lambda: self._open_folder(self.work_dir)).pack(side="right", padx=(8, 0))
        ctk.CTkButton(out_header_row, text="🔄 Làm mới", width=100, command=self._refresh_download_page).pack(side="right")

        self.download_list_frame = ctk.CTkScrollableFrame(page, fg_color=PANEL, corner_radius=RADIUS_PANEL, height=200)
        self.download_list_frame.pack(fill="both", expand=True)
        self._refresh_download_page()

        return page

    # ----- Actions: Douyin downloader -----
    def _start_douyin_download(self):
        from core.douyin_download import parse_urls_textbox as _parse_douyin_urls
        from core.xiaohongshu_download import parse_urls_textbox as _parse_xhs_urls

        raw = self.douyin_urls_box.get("1.0", "end")
        douyin_urls = _parse_douyin_urls(raw)
        xhs_urls = _parse_xhs_urls(raw)
        # bỏ url placeholder mẫu nếu người dùng chưa xoá
        douyin_urls = [u for u in douyin_urls if "xxxxxxx" not in u and "MS4wLjABAAAA..." not in u]
        if not douyin_urls and not xhs_urls:
            messagebox.showwarning(
                "Thiếu link",
                "Dán ít nhất 1 link Douyin hoặc Xiaohongshu (video/bài lẻ hoặc trang cá nhân) trước khi tải.",
            )
            return

        try:
            max_videos_raw = self.douyin_max_videos.get().strip()
            max_videos = int(max_videos_raw) if max_videos_raw else None
        except ValueError:
            messagebox.showwarning("Sai định dạng", "Giới hạn video phải là số nguyên (hoặc để trống = không giới hạn).")
            return

        cookies_browser = self.douyin_cookies_browser.get().strip()
        if cookies_browser in ("", "(không dùng)"):
            cookies_browser = None

        cookies_file_candidate = self.douyin_cookies_file_var.get().strip()
        cookies_file = cookies_file_candidate if os.path.isfile(cookies_file_candidate) else None
        if cookies_file:
            # Có file cookies.txt -> ƯU TIÊN dùng file này, KHÔNG đọc cookie trình duyệt
            # nữa (tránh xung đột 2 nguồn cookie cùng lúc, và né hẳn lỗi mã hoá Chrome mới).
            cookies_browser = None

        out_dir = os.path.join(self.work_dir, "downloads")

        self.douyin_download_btn.configure(state="disabled", text="Đang tải...")
        self.douyin_progress.set(0)
        self.douyin_status_label.configure(text="Đang chuẩn bị tải...", text_color=TEXT_MUTED)
        self.log(
            f"[Download] Bắt đầu tải {len(douyin_urls)} link Douyin + {len(xhs_urls)} link Xiaohongshu -> {out_dir}"
            + (" (dùng cookies.txt)" if cookies_file else "")
        )

        thread = threading.Thread(
            target=self._douyin_download_thread,
            args=(douyin_urls, xhs_urls, out_dir, max_videos, cookies_browser, cookies_file),
            daemon=True,
        )
        thread.start()

    def _toggle_douyin_cookie_advanced(self):
        self._douyin_cookie_advanced_visible = not self._douyin_cookie_advanced_visible
        if self._douyin_cookie_advanced_visible:
            self.douyin_cookie_advanced_panel.pack(fill="x", pady=(8, 10), before=self._douyin_cookie_panel_anchor)
        else:
            self.douyin_cookie_advanced_panel.pack_forget()

    def _refresh_douyin_cookie_status(self):
        linked = os.path.isfile(self.douyin_cookies_file_var.get())
        if linked:
            self.douyin_cookie_status_label.configure(text="🍪 Đã liên kết cookie ✓", text_color=GREEN)
        else:
            browser = self.douyin_cookies_browser.get()
            if browser and browser != "(không dùng)":
                self.douyin_cookie_status_label.configure(text=f"🍪 Dùng cookie trình duyệt: {browser}", text_color=TEXT_MUTED)
            else:
                self.douyin_cookie_status_label.configure(text="⚠ Chưa cấu hình cookie", text_color="#e0a030")

    def _choose_douyin_cookies_file(self):
        path = filedialog.askopenfilename(
            title="Chọn file cookies.txt (định dạng Netscape)",
            filetypes=[("Cookie/Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            fixed_path = self.douyin_cookies_file_var.get()
            try:
                import shutil
                shutil.copyfile(path, fixed_path)
            except Exception as e:
                messagebox.showerror("Lỗi copy file", f"Không copy được file vào vị trí lưu cố định:\n{e}")
                return
            self.douyin_cookies_file_label.configure(text=os.path.basename(path), text_color="white")
            self._refresh_douyin_cookie_status()
            self.log(f"[Download] Đã lưu cố định file cookies.txt (từ {path}) -> {fixed_path}. Các lần mở app sau sẽ tự dùng, không cần chọn lại.")
            # Da lien ket xong -> thu gon panel cau hinh chi tiet cho gon giao dien.
            if self._douyin_cookie_advanced_visible:
                self._toggle_douyin_cookie_advanced()

    def _douyin_download_thread(self, douyin_urls, xhs_urls, out_dir, max_videos, cookies_browser, cookies_file=None):
        from core.douyin_download import download_from_douyin, DouyinDownloadResult
        from core.xiaohongshu_download import download_from_xiaohongshu

        def on_progress(pct, msg):
            self.after(0, self._on_douyin_progress, pct, msg)

        try:
            # Chạy LẦN LƯỢT 2 nguồn (không chạy song song để tránh dồn quá nhiều request
            # cùng lúc, dễ bị 2 nền tảng cùng nghi ngờ là bot) rồi GỘP kết quả lại thành
            # 1 báo cáo chung - vẫn giữ đúng cấu trúc DouyinDownloadResult (videos + failed)
            # để phần hiển thị kết quả (_on_douyin_done) không cần sửa gì thêm.
            combined = DouyinDownloadResult()

            if douyin_urls:
                on_progress(0.0, f"Đang tải {len(douyin_urls)} link Douyin...")
                r1 = download_from_douyin(
                    douyin_urls, out_dir,
                    max_videos=max_videos,
                    cookies_from_browser=cookies_browser,
                    cookies_file=cookies_file,
                    progress_cb=lambda p, m: on_progress(p * (0.5 if xhs_urls else 1.0), f"[Douyin] {m}"),
                )
                combined.videos.extend(r1.videos)
                combined.failed.extend(r1.failed)

            if xhs_urls:
                base = 0.5 if douyin_urls else 0.0
                on_progress(base, f"Đang tải {len(xhs_urls)} link Xiaohongshu...")
                r2 = download_from_xiaohongshu(
                    xhs_urls, out_dir,
                    max_videos=max_videos,
                    cookies_from_browser=cookies_browser,
                    cookies_file=cookies_file,
                    progress_cb=lambda p, m: on_progress(base + p * (0.5 if douyin_urls else 1.0), f"[Xiaohongshu] {m}"),
                )
                combined.videos.extend(r2.videos)
                combined.failed.extend(r2.failed)

            self.after(0, self._on_douyin_done, combined)
        except Exception as e:
            self.after(0, self._on_douyin_error, str(e))

    def _on_douyin_progress(self, pct, msg):
        self.douyin_progress.set(min(1.0, max(0.0, pct)))
        self.douyin_status_label.configure(text=msg, text_color=TEXT_MUTED)
        self.log(f"[Douyin] {msg}")

    def _on_douyin_done(self, result):
        self.douyin_download_btn.configure(state="normal", text="⬇ Tải xuống")
        ok, fail = len(result.videos), len(result.failed)
        color = GREEN if fail == 0 and ok > 0 else ("#e74c3c" if ok == 0 else "#e2b93b")
        self.douyin_status_label.configure(text=f"Hoàn tất: {ok} video thành công, {fail} link lỗi", text_color=color)
        self.log(f"[Douyin] Hoàn tất: {ok} video thành công, {fail} link lỗi")
        if result.failed:
            detail_lines = [f"  {url}\n    -> {reason}" for url, reason in result.failed]
            self.log("[Douyin] Chi tiết link lỗi:\n" + "\n".join(detail_lines))
        self._refresh_douyin_downloads()
        if ok:
            messagebox.showinfo(
                "Tải xong",
                f"Đã tải xong {ok} video (có {fail} link lỗi).\n"
                f"Chọn video ở danh sách 'Video đã tải' bên dưới để dùng cho Translate.",
            )
        else:
            # Hiện ĐÚNG lý do lỗi thật của từng link (thay vì gợi ý chung chung), lấy
            # từ đúng thông báo yt-dlp trả về - dễ biết chính xác cần sửa gì.
            reasons_text = "\n\n".join(f"• {url}\n   {reason}" for url, reason in result.failed[:5])
            if len(result.failed) > 5:
                reasons_text += f"\n\n... và {len(result.failed) - 5} link lỗi khác (xem đầy đủ trong log)."
            messagebox.showwarning(
                "Không tải được video nào",
                reasons_text or "Kiểm tra lại link, hoặc thử bật cookie từ trình duyệt (video riêng tư/giới hạn).",
            )

    def _on_douyin_error(self, err: str):
        self.douyin_download_btn.configure(state="normal", text="⬇ Tải xuống")
        self.douyin_status_label.configure(text=f"✕ Lỗi: {err}", text_color="#e74c3c")
        self.log(f"[Douyin] ✕ Lỗi: {err}")
        messagebox.showerror(
            "Lỗi tải video",
            f"{err}\n\n(Gợi ý: cần 'pip install -U yt-dlp'. Nếu link riêng tư/giới hạn, thử bật cookie từ trình duyệt.)",
        )

    def _refresh_douyin_downloads(self):
        for w in self.douyin_list_frame.winfo_children():
            w.destroy()

        out_dir = os.path.join(self.work_dir, "downloads")
        if not os.path.isdir(out_dir):
            ctk.CTkLabel(self.douyin_list_frame, text="Chưa tải video nào.", text_color=TEXT_MUTED).pack(padx=16, pady=16, anchor="w")
            return

        exts = (".mp4", ".mkv", ".mov", ".webm")
        files = [f for f in os.listdir(out_dir) if f.lower().endswith(exts)]
        if not files:
            ctk.CTkLabel(self.douyin_list_frame, text="Chưa tải video nào.", text_color=TEXT_MUTED).pack(padx=16, pady=16, anchor="w")
            return

        for f in sorted(files):
            full = os.path.join(out_dir, f)
            row = ctk.CTkFrame(self.douyin_list_frame, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
            row.pack(fill="x", padx=10, pady=5)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=8)
            size_mb = os.path.getsize(full) / (1024 * 1024)
            # SỬA THỨ TỰ: pack 2 nút (kích thước CỐ ĐỊNH) TRƯỚC, label tên file (co giãn)
            # SAU - Tkinter ưu tiên chỗ cho widget nào pack() TRƯỚC, nên nếu label tên
            # file (dài, không giới hạn) pack trước như code cũ, nó giành hết chỗ và đẩy
            # nút ra ngoài vùng nhìn thấy (bị cuộn/che khuất) - đổi thứ tự để nút LUÔN đủ
            # chỗ hiển thị, label tên file tự nhường/co lại theo phần còn dư.
            ctk.CTkButton(
                inner, text="▶ Dùng video này", width=130, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                command=lambda p=full: self._use_downloaded_video(p),
            ).pack(side="right", padx=(6, 0))
            ctk.CTkButton(inner, text="Mở thư mục", width=100, command=lambda d=out_dir: self._open_folder(d)).pack(side="right")
            display_name = _truncate_middle(f, 42)
            ctk.CTkLabel(
                inner, text=f"{display_name}   ({size_mb:.1f} MB)", font=(FONT_FAMILY, 12), anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=(0, 10))

    def _use_downloaded_video(self, path: str):
        self.video_path.set(os.path.basename(path))
        self._video_full_path = path
        self._refresh_video_preview()
        self.log(f"Đã chọn video (từ Download) để dịch: {path}")
        self.show_page("Translate")

    def _refresh_download_page(self):
        for w in self.download_list_frame.winfo_children():
            w.destroy()

        if not os.path.isdir(self.work_dir):
            ctk.CTkLabel(self.download_list_frame, text="Chưa có file nào. Chạy Translate trước.", text_color=TEXT_MUTED).pack(padx=16, pady=16, anchor="w")
            return

        exts = (".mp4", ".srt", ".mp3")
        files = [f for f in os.listdir(self.work_dir) if f.lower().endswith(exts)]
        if not files:
            ctk.CTkLabel(self.download_list_frame, text="Chưa có file nào. Chạy Translate trước.", text_color=TEXT_MUTED).pack(padx=16, pady=16, anchor="w")
            return

        for f in sorted(files):
            full = os.path.join(self.work_dir, f)
            row = ctk.CTkFrame(self.download_list_frame, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
            row.pack(fill="x", padx=10, pady=5)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=8)
            size_kb = os.path.getsize(full) / 1024
            # Đổi thứ tự pack (nút trước, label sau) - cùng lý do đã sửa ở _refresh_download_page_douyin
            ctk.CTkButton(inner, text="Mở thư mục", width=100, command=lambda p=full: self._open_folder(os.path.dirname(p))).pack(side="right")
            display_name = _truncate_middle(f, 48)
            ctk.CTkLabel(
                inner, text=f"{display_name}   ({size_kb:.0f} KB)", font=(FONT_FAMILY, 12), anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=(0, 10))

    def _open_folder(self, path: str):
        if not os.path.isdir(path):
            messagebox.showwarning("Không tìm thấy", f"Thư mục không tồn tại:\n{path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không mở được thư mục: {e}")

    # ---------- Trang TikTok (đăng video đã dựng lên TikTok, tránh đăng trùng) ----------
    def _build_tiktok_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color=BG)

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="TikTok", font=(FONT_FAMILY, 22, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Cài Chrome, đăng nhập tài khoản TikTok, rồi đăng video có sẵn trong thư mục output.",
            font=(FONT_FAMILY, 12), text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(0, 12))

        default_tool_dir = os.path.join(get_app_base_dir(), "TiktokAuto")
        embedded_python = os.path.join(default_tool_dir, "python312_embed", "python.exe")
        default_python_cmd = embedded_python if os.path.isfile(embedded_python) else "py -3.12"
        self.tiktok_tool_dir_var = tk.StringVar(value=default_tool_dir)
        self.tiktok_python_cmd_var = tk.StringVar(value=default_python_cmd)
        self.work_dir_var = tk.StringVar(value=self.work_dir)

        # ----- Quan ly tai khoan (phan chinh, khach hang chi can dung phan nay) -----
        acc_panel = ctk.CTkFrame(page, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        acc_panel.pack(fill="x", pady=(0, 12))
        acc_inner = ctk.CTkFrame(acc_panel, fg_color="transparent")
        acc_inner.pack(fill="x", padx=16, pady=14)

        self.tiktok_active_account_var = tk.StringVar(value="")

        acc_header_row = ctk.CTkFrame(acc_inner, fg_color="transparent")
        acc_header_row.pack(fill="x")
        ctk.CTkLabel(acc_header_row, text="Tài khoản TikTok đã lưu", font=(FONT_FAMILY, 13, "bold")).pack(side="left")
        ctk.CTkLabel(
            acc_header_row, text="  (bấm vào tên để chọn dùng)", text_color=TEXT_MUTED, font=(FONT_FAMILY, 11),
        ).pack(side="left")

        ctk.CTkLabel(
            acc_inner,
            text="Tài khoản đã thêm sẽ được ghi nhớ vĩnh viễn, không cần đăng nhập lại mỗi lần mở app. "
                 "Chỉ bấm 🔄 bên cạnh tài khoản nếu phiên đăng nhập bị TikTok tự huỷ (hiếm khi xảy ra).",
            text_color=TEXT_MUTED, font=(FONT_FAMILY, 10), justify="left", wraplength=560,
        ).pack(anchor="w", pady=(2, 10))

        self.tiktok_accounts_list_frame = ctk.CTkFrame(acc_inner, fg_color="transparent")
        self.tiktok_accounts_list_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(acc_inner, text="Thêm tài khoản mới", text_color=TEXT_MUTED).pack(anchor="w")

        # Email/SĐT TikTok sẽ đăng nhập trong Chrome. TikTok không hỗ trợ
        # "login_hint" như Google OAuth, nên ô này chỉ là ghi chú để bạn nhớ
        # đúng tài khoản cần đăng nhập trong cửa sổ Chrome vừa mở, và được lưu
        # lại kèm tên tài khoản để lần "🔄 Đăng nhập lại" sau nhắc đúng email.
        ctk.CTkLabel(
            acc_inner,
            text="Email/SĐT TikTok đang dùng để đăng nhập",
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(4, 0))
        self.tiktok_login_email_var = tk.StringVar(value="")
        ctk.CTkEntry(
            acc_inner,
            textvariable=self.tiktok_login_email_var,
            fg_color=PANEL,
            border_color=BORDER,
            placeholder_text="vd: tenkenh@gmail.com hoặc số điện thoại",
        ).pack(fill="x", pady=(4, 8))

        add_row = ctk.CTkFrame(acc_inner, fg_color="transparent")
        add_row.pack(fill="x", pady=(0, 4))
        self.tiktok_new_account_var = tk.StringVar(value="")
        ctk.CTkEntry(
            add_row, textvariable=self.tiktok_new_account_var, fg_color=PANEL, border_color=BORDER,
            placeholder_text="Đặt tên cho tài khoản mới, vd: kenh1",
        ).pack(side="left", fill="x", expand=True)
        self.tiktok_add_account_btn = ctk.CTkButton(
            add_row, text="🔑 Đăng nhập / Thêm tài khoản", width=210, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._tiktok_add_account,
        )
        self.tiktok_add_account_btn.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            acc_inner,
            text="Email/SĐT chỉ để bạn ghi nhớ và kiểm tra lại đúng tài khoản trước khi đăng nhập trong Chrome; "
                 "TikTok không hỗ trợ tự chọn sẵn tài khoản như Google.",
            text_color=TEXT_MUTED, font=(FONT_FAMILY, 9), justify="left", wraplength=560,
        ).pack(anchor="w", pady=(2, 0))

        self.tiktok_add_status_label = ctk.CTkLabel(acc_inner, text="", text_color=TEXT_MUTED, font=(FONT_FAMILY, 11), anchor="w", justify="left", wraplength=560)
        self.tiktok_add_status_label.pack(anchor="w", pady=(2, 8))

        self.tiktok_rotate_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            acc_inner, text="🔁 Luân phiên qua tất cả tài khoản khi đăng nhiều video (đỡ bị TikTok để ý spam)",
            variable=self.tiktok_rotate_var, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(4, 0))

        # ----- Đặt lịch đăng (giao diện y chang trang YouTube) -----
        pub_panel = ctk.CTkFrame(page, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        pub_panel.pack(fill="x", pady=(0, 12))
        pub_inner = ctk.CTkFrame(pub_panel, fg_color="transparent")
        pub_inner.pack(fill="x", padx=16, pady=14)

        self.tiktok_schedule_enabled_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            pub_inner, text="📅 Đặt lịch đăng (thay vì đăng ngay)",
            variable=self.tiktok_schedule_enabled_var, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w")

        tt_sched_inner = ctk.CTkFrame(pub_inner, fg_color="transparent")
        tt_sched_inner.pack(fill="x", pady=(6, 0))

        tt_date_col = ctk.CTkFrame(tt_sched_inner, fg_color="transparent")
        tt_date_col.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(tt_date_col, text="Ngày đăng đầu tiên (dd/mm/yyyy)", text_color=TEXT_MUTED).pack(anchor="w")
        tt_tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
        self.tiktok_schedule_date_var = tk.StringVar(value=tt_tomorrow)
        ctk.CTkEntry(tt_date_col, textvariable=self.tiktok_schedule_date_var, fg_color=PANEL, border_color=BORDER, width=140).pack(anchor="w", pady=(4, 0))

        tt_time_col = ctk.CTkFrame(tt_sched_inner, fg_color="transparent")
        tt_time_col.pack(side="left")
        ctk.CTkLabel(tt_time_col, text="Giờ đăng (HH:MM)", text_color=TEXT_MUTED).pack(anchor="w")
        self.tiktok_schedule_time_var = tk.StringVar(value="08:00")
        ctk.CTkEntry(tt_time_col, textvariable=self.tiktok_schedule_time_var, fg_color=PANEL, border_color=BORDER, width=100).pack(anchor="w", pady=(4, 0))

        self.tiktok_schedule_next_day_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            pub_inner,
            text="🔁 Tự động đăng mỗi video cách nhau 1 ngày, cùng giờ đã chọn",
            variable=self.tiktok_schedule_next_day_var, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(8, 0))
        ctk.CTkLabel(
            pub_inner,
            text="⚠ Khác với YouTube (đặt lịch ở server Google, tắt máy vẫn tự đăng đúng giờ), TikTok không có API "
                 "đặt lịch công khai để app dùng — nên app tự canh giờ rồi tự bấm đăng hộ bạn đúng lúc. Lịch được LƯU "
                 "XUỐNG FILE nên tắt/mở lại app hoặc khởi động lại máy KHÔNG làm mất lịch — nhưng máy tính + app vẫn "
                 "PHẢI ĐANG MỞ ngay tại đúng thời điểm hẹn của từng video thì mới tự đăng được lúc đó (đóng app suốt "
                 "từ giờ tới lúc đó thì bỏ lỡ, đợi lần mở app kế tiếp mới đăng bù). Nếu giờ đã chọn ở trong quá khứ, "
                 "video đó được đăng ngay lập tức.",
            text_color=TEXT_MUTED, font=(FONT_FAMILY, 10), justify="left", wraplength=520,
        ).pack(anchor="w", pady=(4, 0))

        # ----- Cai dat nang cao (an mac dinh, khach hang khong can dung toi) -----
        self._tiktok_advanced_visible = False
        adv_toggle_row = ctk.CTkFrame(page, fg_color="transparent")
        adv_toggle_row.pack(fill="x", pady=(0, 4))
        self.tiktok_adv_toggle_btn = ctk.CTkButton(
            adv_toggle_row, text="⚙️ Cài đặt nâng cao ▸", width=180, fg_color="transparent",
            hover_color=PANEL2, text_color=TEXT_MUTED, anchor="w",
            command=self._tiktok_toggle_advanced,
        )
        self.tiktok_adv_toggle_btn.pack(anchor="w")

        self.tiktok_advanced_panel = ctk.CTkFrame(page, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        adv_inner = ctk.CTkFrame(self.tiktok_advanced_panel, fg_color="transparent")
        adv_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(adv_inner, text="Lệnh Python chạy TiktokAuto (vd: py -3.12)", text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkEntry(adv_inner, textvariable=self.tiktok_python_cmd_var, fg_color=PANEL, border_color=BORDER).pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(adv_inner, text="Thư mục chứa cli.py (TiktokAutoUploader)", text_color=TEXT_MUTED).pack(anchor="w")
        tt_dir_row = ctk.CTkFrame(adv_inner, fg_color="transparent")
        tt_dir_row.pack(fill="x", pady=(4, 10))
        ctk.CTkEntry(tt_dir_row, textvariable=self.tiktok_tool_dir_var, fg_color=PANEL, border_color=BORDER).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(tt_dir_row, text="Chọn", width=80, command=self._choose_tiktok_tool_dir).pack(side="left", padx=8)

        ctk.CTkLabel(adv_inner, text="Thư mục output (nơi chứa video đã dựng)", text_color=TEXT_MUTED).pack(anchor="w")
        out_dir_row = ctk.CTkFrame(adv_inner, fg_color="transparent")
        out_dir_row.pack(fill="x", pady=(4, 0))
        ctk.CTkEntry(out_dir_row, textvariable=self.work_dir_var, fg_color=PANEL, border_color=BORDER).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(out_dir_row, text="Chọn", width=80, command=self._choose_work_dir).pack(side="left", padx=8)
        # Panel nang cao chua duoc .pack() - an mac dinh, bam nut o tren de mo.

        # ----- Danh sách video sẵn sàng đăng -----
        list_panel = ctk.CTkFrame(page, fg_color=PANEL, corner_radius=RADIUS_PANEL)
        self._tiktok_list_panel_ref = list_panel
        list_panel.pack(fill="both", expand=True)
        list_header = ctk.CTkFrame(list_panel, fg_color="transparent")
        list_header.pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkLabel(list_header, text="Video trong thư mục output", font=(FONT_FAMILY, 13, "bold")).pack(side="left")
        ctk.CTkButton(
            list_header, text="🔄 Quét lại", width=100, fg_color=PANEL2, hover_color=BORDER,
            command=self._tiktok_scan_videos,
        ).pack(side="right")
        ctk.CTkButton(
            list_header, text="🚀 Đăng video đã chọn", fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._tiktok_upload_selected,
        ).pack(side="right", padx=(0, 8))

        self.tiktok_list_scroll = ctk.CTkScrollableFrame(list_panel, fg_color="transparent")
        self.tiktok_list_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.tiktok_video_rows: dict[str, dict] = {}

        ctk.CTkLabel(list_panel, text="Nhật ký đăng bài", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(0, 2))
        self.tiktok_log_box = ctk.CTkTextbox(list_panel, fg_color=PANEL2, height=120, wrap="word")
        self.tiktok_log_box.pack(fill="x", padx=14, pady=(0, 14))
        self.tiktok_log_box.configure(state="disabled")

        self.after(300, self._tiktok_scan_videos)
        self.after(300, self._tiktok_refresh_accounts_ui)
        # ----- Nếu còn lịch đăng dang dở lưu từ lần chạy app TRƯỚC (chưa kịp đăng vì
        # ----- app/máy đã tắt) -> tự động khôi phục lại đúng vào lúc app mở lên, KHÔNG
        # ----- cần người dùng bấm gì thêm. Chỉ khởi động nếu thực sự còn việc phải làm. -----
        self.after(500, self._tiktok_schedule_start_checker)
        return page

    def _tiktok_toggle_advanced(self):
        self._tiktok_advanced_visible = not self._tiktok_advanced_visible
        if self._tiktok_advanced_visible:
            self.tiktok_advanced_panel.pack(fill="x", pady=(0, 12), before=self._tiktok_list_panel_ref)
            self.tiktok_adv_toggle_btn.configure(text="⚙️ Cài đặt nâng cao ▾")
        else:
            self.tiktok_advanced_panel.pack_forget()
            self.tiktok_adv_toggle_btn.configure(text="⚙️ Cài đặt nâng cao ▸")

    def _choose_work_dir(self):
        path = filedialog.askdirectory(title="Chọn thư mục lưu output")
        if path:
            self.work_dir = path
            self.work_dir_var.set(path)
            self.log(f"Đã đổi thư mục output: {path}")
            self._tiktok_scan_videos()

    def _choose_tiktok_tool_dir(self):
        path = filedialog.askdirectory(title="Chọn thư mục chứa cli.py (TiktokAutoUploader)")
        if path:
            self.tiktok_tool_dir_var.set(path)

    def _tiktok_log(self, msg: str):
        try:
            self.tiktok_log_box.configure(state="normal")
            self.tiktok_log_box.insert("end", f"{msg}\n")
            self.tiktok_log_box.see("end")
            self.tiktok_log_box.configure(state="disabled")
        except Exception:
            pass
        self.log(f"[TikTok] {msg}")

    # ----- Log/tránh đăng trùng: lưu id video đã đăng ra 1 file JSON riêng -----
    def _tiktok_log_path(self) -> str:
        return os.path.join(get_user_data_dir(), "tiktok_uploaded_log.json")

    def _tiktok_load_uploaded_log(self) -> dict:
        path = self._tiktok_log_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _tiktok_save_uploaded_log(self, data: dict):
        try:
            with open(self._tiktok_log_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._tiktok_log(f"⚠ Không lưu được log: {e}")

    # ----- Hàng đợi lịch đăng TikTok - LƯU RA FILE (không giữ trong RAM của 1 thread
    # ----- đang time.sleep()) để lịch đăng SỐNG SÓT qua việc tắt/mở lại app, sập app,
    # ----- restart máy Windows update... - miễn app được mở lại TRƯỚC giờ đăng thì nó
    # ----- tự động đăng tiếp, không mất lịch. -----
    def _tiktok_schedule_path(self) -> str:
        return os.path.join(get_user_data_dir(), "tiktok_schedule_queue.json")

    def _tiktok_load_schedule_queue(self) -> list:
        path = self._tiktok_schedule_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _tiktok_save_schedule_queue(self, items: list):
        try:
            with open(self._tiktok_schedule_path(), "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._tiktok_log(f"⚠ Không lưu được file hàng đợi lịch đăng: {e}")

    def _tiktok_schedule_start_checker(self):
        """Bật vòng lặp kiểm tra hàng đợi lịch đăng (chạy bằng self.after, KHÔNG
        chiếm 1 thread nền ngồi time.sleep() suốt nhiều ngày). Gọi an toàn nhiều
        lần - tự bỏ qua nếu đã đang chạy hoặc không còn video nào đang chờ.

        Video sẽ được UPLOAD NGAY (kèm lịch đăng gốc của TikTok - schedule_time)
        ngay khi rơi vào khoảng TikTok chấp nhận (≤10 ngày) - KHÔNG cần app/máy
        bật liên tục chờ tới đúng giờ hẹn (xem _tiktok_schedule_checker_tick)."""
        if getattr(self, "_tiktok_schedule_checker_running", False):
            return
        queue = self._tiktok_load_schedule_queue()
        pending = [it for it in queue if it.get("status") == "pending"]
        if not pending:
            return
        self._tiktok_schedule_checker_running = True
        self._tiktok_schedule_worker_busy = False
        self._tiktok_schedule_last_logged_min = None
        self._tiktok_log(f"📅 Khôi phục hàng đợi lịch đăng: còn {len(pending)} video chưa gửi lên TikTok.")
        self._tiktok_schedule_checker_tick()

    def _tiktok_schedule_checker_tick(self):
        """LƯU Ý QUAN TRỌNG: TikTok có sẵn tính năng hẹn giờ đăng CỦA CHÍNH NỀN TẢNG
        (schedule_time trong tiktok_uploader) - chấp nhận từ 15 phút đến 10 ngày kể
        từ lúc upload. Vì vậy hàm này KHÔNG còn "ngồi chờ" tới đúng giờ hẹn rồi mới
        upload nữa (cách cũ: máy/app phải bật liên tục hàng trăm giờ mới đăng) - mà
        NGAY KHI video rơi vào khoảng TikTok chấp nhận (≤10 ngày), upload NGAY LẬP
        TỨC kèm schedule_time = đúng số giây còn lại - TikTok tự giữ video riêng tư
        và tự động công khai đúng giờ đã hẹn, không cần app/máy phải bật chờ tới lúc
        đó nữa. App chỉ còn cần bật để: (1) video hẹn xa hơn 10 ngày (hiếm, phải chờ
        tới khi rơi vào khoảng ≤10 ngày mới handoff được), (2) video đã tới hẳn giờ
        hẹn (≤15 phút) thì đăng công khai ngay vì TikTok không nhận lịch quá sát giờ."""
        queue = self._tiktok_load_schedule_queue()
        pending = [it for it in queue if it.get("status") == "pending"]
        if not pending:
            # Hết việc - dừng hẳn vòng lặp thay vì self.after() vô thời hạn vô ích.
            self._tiktok_schedule_checker_running = False
            return

        now = datetime.now()
        TIKTOK_MIN_SCHEDULE_SEC = 900        # TikTok tối thiểu 15 phút
        TIKTOK_MAX_SCHEDULE_SEC = 864000     # TikTok tối đa 10 ngày

        due_now = []          # đã tới hẳn giờ (hoặc quá sát, TikTok không nhận lịch nữa) -> đăng công khai NGAY
        handoff_native = []   # đã rơi vào khoảng TikTok chấp nhận lịch -> upload NGAY kèm schedule_time, để TikTok tự giữ/tự đăng
        for it in pending:
            remaining = (datetime.fromisoformat(it["target_iso"]) - now).total_seconds()
            if remaining <= TIKTOK_MIN_SCHEDULE_SEC:
                due_now.append(it)
            elif remaining <= TIKTOK_MAX_SCHEDULE_SEC:
                handoff_native.append(it)
            # else: còn xa hơn 10 ngày -> chưa làm gì được, giữ nguyên "pending", tick sau kiểm tra lại.

        busy = getattr(self, "_tiktok_schedule_worker_busy", False)
        if (due_now or handoff_native) and not busy:
            self._tiktok_schedule_worker_busy = True
            threading.Thread(
                target=self._tiktok_schedule_process_batch,
                args=(due_now, handoff_native),
                daemon=True,
            ).start()
        elif not due_now and not handoff_native:
            # Chưa video nào rơi vào khoảng xử lý được (tất cả còn xa hơn 10 ngày) -
            # log 1 dòng tóm tắt, THƯA (mỗi ~30 phút, hoặc khi còn dưới 1 phút) thay
            # vì spam liên tục.
            nearest = min(pending, key=lambda it: it["target_iso"])
            remaining_min = int((datetime.fromisoformat(nearest["target_iso"]) - now).total_seconds() // 60)
            last = self._tiktok_schedule_last_logged_min
            if last is None or last - remaining_min >= 30 or remaining_min <= 1:
                self._tiktok_schedule_last_logged_min = remaining_min
                self._tiktok_log(
                    f"📅 Còn {len(pending)} video trong hàng đợi — gần nhất '{nearest['folder_name']}' còn "
                    f"khoảng {remaining_min} phút ({remaining_min // 60}h{remaining_min % 60}p) nữa mới rơi vào "
                    f"khoảng TikTok nhận lịch (≤10 ngày) để handoff, chưa cần app bật liên tục từ giờ tới đó."
                )

        # 20s/lần là đủ chính xác cho lịch đăng theo phút, không tốn tài nguyên đáng kể.
        self.after(20000, self._tiktok_schedule_checker_tick)

    def _tiktok_schedule_process_batch(self, due_now: list, handoff_native: list):
        """Chạy trong thread nền: xử lý cả 2 nhóm - đăng công khai ngay (due_now) và
        handoff cho TikTok tự giữ lịch (handoff_native) - TUẦN TỰ (không song song) vì
        Browser trong TiktokAuto là singleton."""
        if handoff_native:
            self._tiktok_schedule_process_native(handoff_native)
        if due_now:
            self._tiktok_schedule_process_due(due_now)
        self._tiktok_schedule_worker_busy = False

    def _tiktok_schedule_process_native(self, items: list):
        """Upload NGAY cho từng video trong `items`, kèm -nsc <số giây còn lại> để
        TikTok dùng ĐÚNG tính năng hẹn giờ đăng của chính nền tảng - TikTok tự giữ
        video ở chế độ riêng tư/chờ đăng và tự động công khai đúng giờ đã hẹn, không
        cần app/máy phải bật liên tục chờ tới lúc đó nữa. Sau khi handoff xong (upload
        thành công), đánh dấu "done" trong hàng đợi cục bộ - phần còn lại (tự động
        công khai đúng giờ) giờ là trách nhiệm của TikTok, không phải app này nữa."""
        for item in items:
            folder_name = item["folder_name"]
            target_dt = datetime.fromisoformat(item["target_iso"])
            remaining_sec = max(900, int((target_dt - datetime.now()).total_seconds()))
            self.after(0, self._tiktok_log, f"→ [Lịch đăng TikTok] Đang gửi lên TikTok để TikTok tự giữ lịch tới {target_dt.strftime('%H:%M %d/%m/%Y')}: {folder_name}")
            row = self.tiktok_video_rows.get(folder_name) if hasattr(self, "tiktok_video_rows") else None
            if row:
                self.after(0, lambda lbl=row["status_label"]: lbl.configure(text="Đang gửi lên TikTok...", text_color=ACCENT))

            cmd = self._tiktok_python_prefix() + [
                "cli.py", "upload", "-u", item["account"], "-v", item["video_path"],
                "-t", item["title"], "-nsc", str(remaining_sec),
            ]
            # Truyen ten tai khoan qua env de Browser.py dung DUNG profile Chrome
            # cua tai khoan nay, tranh bi lan sang session cua tai khoan khac.
            env = os.environ.copy()
            env["TIKTOK_PROFILE_NAME"] = item["account"]
            success = False
            try:
                result = subprocess.run(cmd, cwd=item["tool_dir"], capture_output=True, text=True, env=env)
                out = (result.stdout or "") + (result.stderr or "")
                for line in out.strip().splitlines()[-10:]:
                    self.after(0, self._tiktok_log, f"    {line}")
                success = result.returncode == 0 and "[-]" not in out
            except Exception as e:
                self.after(0, self._tiktok_log, f"    ⚠ Lỗi chạy lệnh: {e}")

            queue = self._tiktok_load_schedule_queue()
            for q in queue:
                if q.get("id") == item["id"]:
                    if success:
                        q["status"] = "done"
                        q["handoff"] = "native"   # đánh dấu: đã giao cho TikTok tự giữ lịch, KHÔNG phải đã đăng công khai
                        self.after(0, self._tiktok_log, f"  ✓ [Lịch đăng TikTok] Đã gửi xong - TikTok sẽ tự công khai đúng {target_dt.strftime('%H:%M %d/%m/%Y')}.")
                        if row:
                            self.after(0, lambda lbl=row["status_label"]: lbl.configure(text=f"📅 TikTok tự đăng lúc {target_dt.strftime('%H:%M %d/%m')}", text_color=GREEN))
                            self.after(0, lambda v=row["check_var"]: v.set(False))
                    else:
                        q["status"] = "error"
                        q["error"] = "Handoff lịch đăng cho TikTok thất bại - xem nhật ký"
                        self.after(0, self._tiktok_log, f"  ✗ [Lịch đăng TikTok] Gửi thất bại: {folder_name}")
                        if row:
                            self.after(0, lambda lbl=row["status_label"]: lbl.configure(text="✗ Lỗi", text_color="#e74c3c"))
                    break
            self._tiktok_save_schedule_queue(queue)

    def _tiktok_schedule_process_due(self, due_items: list):
        """Chạy trong thread nền: thực sự bấm đăng (mở Chrome, upload) cho các video
        đã tới giờ. Xử lý TUẦN TỰ từng video (không song song) vì Browser trong
        TiktokAuto là singleton - 2 phiên Chrome cùng lúc sẽ đụng nhau."""
        import shutil
        uploaded_log = self._tiktok_load_uploaded_log()
        for item in due_items:
            folder_name = item["folder_name"]
            self.after(0, self._tiktok_log, f"→ [Lịch đăng] Đang đăng (tài khoản '{item['account']}'): {folder_name}")
            row = self.tiktok_video_rows.get(folder_name) if hasattr(self, "tiktok_video_rows") else None
            if row:
                self.after(0, lambda lbl=row["status_label"]: lbl.configure(text="Đang đăng...", text_color=ACCENT))

            cmd = self._tiktok_python_prefix() + ["cli.py", "upload", "-u", item["account"], "-v", item["video_path"], "-t", item["title"]]
            env = os.environ.copy()
            env["TIKTOK_PROFILE_NAME"] = item["account"]
            success = False
            try:
                result = subprocess.run(cmd, cwd=item["tool_dir"], capture_output=True, text=True, env=env)
                out = (result.stdout or "") + (result.stderr or "")
                for line in out.strip().splitlines()[-10:]:
                    self.after(0, self._tiktok_log, f"    {line}")
                success = result.returncode == 0
            except Exception as e:
                self.after(0, self._tiktok_log, f"    ⚠ Lỗi chạy lệnh: {e}")

            # Cập nhật trạng thái ngay xuống file hàng đợi SAU MỖI VIDEO (không đợi
            # xong hết cả loạt) - để nếu app bị tắt giữa chừng, video đã xong không bị
            # đăng lại lần 2 khi mở app lên.
            queue = self._tiktok_load_schedule_queue()
            for q in queue:
                if q.get("id") == item["id"]:
                    if success:
                        q["status"] = "done"
                        done_dir = os.path.join(self.work_dir, "da_dang")
                        os.makedirs(done_dir, exist_ok=True)
                        try:
                            shutil.move(item["folder_path"], os.path.join(done_dir, folder_name))
                            self.after(0, self._tiktok_log, "  ✓ [Lịch đăng] Đăng xong, đã chuyển vào da_dang/")
                        except Exception as e:
                            self.after(0, self._tiktok_log, f"  ✓ [Lịch đăng] Đăng xong nhưng không chuyển được thư mục: {e}")
                        uploaded_log[item["video_id"]] = {"folder": folder_name, "title": item["title"], "account": item["account"]}
                        self._tiktok_save_uploaded_log(uploaded_log)
                        if row:
                            self.after(0, lambda lbl=row["status_label"]: lbl.configure(text="✓ Đã đăng", text_color=GREEN))
                            self.after(0, lambda v=row["check_var"]: v.set(False))
                    else:
                        q["status"] = "error"
                        q["error"] = "Đăng thất bại - xem nhật ký"
                        self.after(0, self._tiktok_log, f"  ✗ [Lịch đăng] Đăng thất bại: {folder_name}")
                        if row:
                            self.after(0, lambda lbl=row["status_label"]: lbl.configure(text="✗ Lỗi", text_color="#e74c3c"))
                    break
            self._tiktok_save_schedule_queue(queue)

        self._tiktok_schedule_worker_busy = False

    # ----- Quan ly nhieu tai khoan TikTok -----
    def _tiktok_accounts_path(self) -> str:
        return os.path.join(get_user_data_dir(), "tiktok_accounts.json")

    def _tiktok_account_emails_path(self) -> str:
        return os.path.join(get_user_data_dir(), "tiktok_account_emails.json")

    def _tiktok_load_account_emails(self) -> dict:
        path = self._tiktok_account_emails_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    def _tiktok_save_account_email(self, account: str, email: str):
        try:
            emails = self._tiktok_load_account_emails()
            emails[account] = email
            with open(self._tiktok_account_emails_path(), "w", encoding="utf-8") as f:
                json.dump(emails, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._tiktok_log(f"⚠ Không lưu được email tài khoản '{account}': {e}")

    def _tiktok_accounts_email(self, account: str) -> str:
        return self._tiktok_load_account_emails().get(account, "").strip()

    def _tiktok_load_accounts(self) -> list:
        path = self._tiktok_accounts_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("accounts", [])
            except Exception:
                return []
        return []

    def _tiktok_save_accounts(self, accounts: list):
        try:
            with open(self._tiktok_accounts_path(), "w", encoding="utf-8") as f:
                json.dump({"accounts": accounts}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._tiktok_log(f"⚠ Không lưu được danh sách tài khoản: {e}")

    def _tiktok_refresh_accounts_ui(self):
        accounts = self._tiktok_load_accounts()

        if accounts and self.tiktok_active_account_var.get() not in accounts:
            self.tiktok_active_account_var.set(accounts[0])
        elif not accounts:
            self.tiktok_active_account_var.set("")

        # Ve lai danh sach tai khoan da luu dang the card: bam vao ten de chon
        # lam tai khoan dang dung, nut 🔄 de dang nhap lai rieng tai khoan do,
        # nut 🗑 de xoa khoi danh sach.
        for child in list(self.tiktok_accounts_list_frame.winfo_children()):
            child.destroy()

        if not accounts:
            ctk.CTkLabel(
                self.tiktok_accounts_list_frame, text="Chưa có tài khoản nào — thêm tài khoản đầu tiên ở khung bên dưới.",
                text_color=TEXT_MUTED,
            ).pack(anchor="w", pady=6)
            return

        active = self.tiktok_active_account_var.get()
        for acc in accounts:
            is_active = acc == active
            row = ctk.CTkFrame(
                self.tiktok_accounts_list_frame,
                fg_color=(ACCENT if is_active else PANEL),
                corner_radius=RADIUS_ROW, border_width=1,
                border_color=(ACCENT if is_active else BORDER_SOFT),
            )
            row.pack(fill="x", pady=3)
            row_inner = ctk.CTkFrame(row, fg_color="transparent")
            row_inner.pack(fill="x", padx=10, pady=6)

            ctk.CTkButton(
                row_inner, text=("● Đang dùng — " if is_active else "○ ") + acc,
                anchor="w", fg_color="transparent",
                hover_color=(ACCENT_HOVER if is_active else PANEL2),
                text_color="white",
                font=(FONT_FAMILY, 12, "bold" if is_active else "normal"),
                command=lambda a=acc: self._tiktok_select_account(a),
            ).pack(side="left", fill="x", expand=True)

            ctk.CTkButton(
                row_inner, text="🔄", width=32, height=26,
                fg_color="transparent", hover_color=(ACCENT_HOVER if is_active else PANEL2),
                command=lambda a=acc: self._tiktok_relogin_account(a),
            ).pack(side="left", padx=(4, 0))
            ctk.CTkButton(
                row_inner, text="🗑", width=32, height=26,
                fg_color="transparent", hover_color=(ACCENT_HOVER if is_active else PANEL2),
                command=lambda a=acc: self._tiktok_delete_account(a),
            ).pack(side="left", padx=(4, 0))

    def _tiktok_select_account(self, account: str):
        self.tiktok_active_account_var.set(account)
        self._tiktok_refresh_accounts_ui()
        self._tiktok_log(f"Đã chọn tài khoản đang dùng: '{account}'.")

    def _tiktok_relogin_account(self, account: str):
        tool_dir = self.tiktok_tool_dir_var.get().strip()
        if not tool_dir or not os.path.isfile(os.path.join(tool_dir, "cli.py")):
            messagebox.showerror("Không tìm thấy cli.py", f"Không thấy cli.py trong:\n{tool_dir}\n\nMở '⚙️ Cài đặt nâng cao' để kiểm tra/sửa lại đường dẫn.")
            return
        # Đổ lại email/SĐT đã lưu cho tài khoản này (nếu có) lên ô nhập, để
        # nhắc đúng tài khoản cần đăng nhập trong Chrome — y như hành vi bên
        # trang YouTube.
        saved_email = self._tiktok_accounts_email(account)
        if saved_email:
            self.tiktok_login_email_var.set(saved_email)
        self._tiktok_set_add_status(f"🔄 Đang mở Chrome để đăng nhập lại '{account}'...", ACCENT)
        self._tiktok_log(f"Đang mở Chrome để đăng nhập lại '{account}'...")
        threading.Thread(target=self._tiktok_login_thread, args=(tool_dir, account, saved_email), daemon=True).start()

    def _tiktok_delete_account(self, account: str):
        accounts = self._tiktok_load_accounts()
        if account in accounts:
            accounts.remove(account)
            self._tiktok_save_accounts(accounts)
            try:
                emails = self._tiktok_load_account_emails()
                emails.pop(account, None)
                with open(self._tiktok_account_emails_path(), "w", encoding="utf-8") as f:
                    json.dump(emails, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            self._tiktok_refresh_accounts_ui()
            self._tiktok_log(f"Đã xoá tài khoản '{account}' khỏi danh sách (không xoá cookie đăng nhập trên máy).")

    def _tiktok_set_add_status(self, text: str, color=None):
        try:
            self.tiktok_add_status_label.configure(text=text, text_color=(color or TEXT_MUTED))
        except Exception:
            pass

    def _tiktok_add_account(self):
        account = self.tiktok_new_account_var.get().strip()
        login_email = self.tiktok_login_email_var.get().strip()
        if not account:
            messagebox.showwarning("Thiếu tên tài khoản", "Đặt tên cho tài khoản mới trước (tên tự đặt, dùng để phân biệt các tài khoản).")
            return
        tool_dir = self.tiktok_tool_dir_var.get().strip()
        if not tool_dir or not os.path.isfile(os.path.join(tool_dir, "cli.py")):
            messagebox.showerror("Không tìm thấy cli.py", f"Không thấy cli.py trong:\n{tool_dir}\n\nMở '⚙️ Cài đặt nâng cao' để kiểm tra/sửa lại đường dẫn.")
            return

        # Phan hoi ngay lap tuc (khong doi thread) de nguoi dung biet nut da an dung,
        # tranh cam giac "bam khong thay gi" trong luc cho Chrome mo len.
        self.tiktok_add_account_btn.configure(state="disabled", text="⏳ Đang xử lý...")
        self._tiktok_set_add_status("🔄 Đang khởi động Chrome... (có thể mất vài giây tới ~1 phút lần đầu)", ACCENT)
        if login_email:
            self._tiktok_log(f"Đang mở Chrome để đăng nhập '{account}' ({login_email})... hãy đăng nhập TikTok trong cửa sổ Chrome vừa mở.")
        else:
            self._tiktok_log(f"Đang mở Chrome để đăng nhập '{account}'... hãy đăng nhập TikTok trong cửa sổ Chrome vừa mở.")
        threading.Thread(target=self._tiktok_login_thread, args=(tool_dir, account, login_email), daemon=True).start()

    def _tiktok_python_prefix(self) -> list:
        """Tách chuỗi lệnh Python (vd 'py -3.12') thành list args để ghép vào subprocess.
        Dùng shlex để xử lý đúng trường hợp đường dẫn có khoảng trắng, đặt trong dấu ngoặc kép."""
        import shlex
        raw = self.tiktok_python_cmd_var.get().strip() or "py -3.12"
        try:
            return shlex.split(raw, posix=False)
        except Exception:
            return raw.split()

    def _tiktok_login_thread(self, tool_dir: str, account: str, login_email: str = ""):
        def finish():
            self.after(0, lambda: self.tiktok_add_account_btn.configure(state="normal", text="🔑 Đăng nhập / Thêm tài khoản"))

        try:
            cmd = self._tiktok_python_prefix() + ["cli.py", "login", "-n", account]
            login_email = (login_email or "").strip()
            if login_email:
                # -e/--email chỉ là gợi ý (nếu cli.py/tiktok.login hỗ trợ tự điền sẵn
                # ô đăng nhập); nếu không hỗ trợ, cli.py vẫn bỏ qua an toàn và bạn tự
                # gõ tài khoản như trước giờ.
                cmd += ["-e", login_email]
            # Truyen ten tai khoan qua bien moi truong de Browser.py tu tao PROFILE
            # CHROME RIENG BIET cho tai khoan nay - neu khong lam vay, moi tai
            # khoan dang nhap sau se bi "ke thua" nham session cua tai khoan truoc
            # (dung chung 1 profile Chrome) -> 2 tai khoan bi trung cookie nhau.
            env = os.environ.copy()
            env["TIKTOK_PROFILE_NAME"] = account
            try:
                result = subprocess.run(cmd, cwd=tool_dir, capture_output=True, text=True, env=env)
            except FileNotFoundError as e:
                # Loi thuong gap nhat: lenh Python cau hinh (vd "py -3.12") khong
                # ton tai tren may nay -> bao ro thay vi im lang.
                msg = f"⚠ Không chạy được lệnh Python '{' '.join(cmd[:2])}': {e}\nKiểm tra lại ô 'Lệnh Python chạy TiktokAuto' trong '⚙️ Cài đặt nâng cao'."
                self.after(0, self._tiktok_log, msg)
                self.after(0, self._tiktok_set_add_status, "✗ Không chạy được lệnh Python — xem log bên dưới", "#e74c3c")
                finish()
                return

            out = (result.stdout or "") + (result.stderr or "")
            for line in out.strip().splitlines()[-15:]:
                self.after(0, self._tiktok_log, line)
            if result.returncode == 0:
                self.after(0, self._tiktok_log, f"✓ Đăng nhập xong cho '{account}'.")
                self.after(0, self._tiktok_set_add_status, f"✓ Đăng nhập thành công cho '{account}'.", GREEN)
                accounts = self._tiktok_load_accounts()
                if account not in accounts:
                    accounts.append(account)
                    self._tiktok_save_accounts(accounts)
                if login_email:
                    self._tiktok_save_account_email(account, login_email)
                self.after(0, self.tiktok_new_account_var.set, "")
                self.after(0, self.tiktok_login_email_var.set, "")
                self.after(0, lambda: self.tiktok_active_account_var.set(account))
                self.after(0, self._tiktok_refresh_accounts_ui)
            else:
                self.after(0, self._tiktok_log, f"⚠ Lệnh login kết thúc với lỗi (mã {result.returncode}). Xem log ở trên.")
                self.after(0, self._tiktok_set_add_status, f"✗ Đăng nhập thất bại (mã lỗi {result.returncode}) — xem chi tiết trong Nhật ký bên dưới.", "#e74c3c")
        except Exception as e:
            self.after(0, self._tiktok_log, f"⚠ Lỗi khi chạy login: {e}")
            self.after(0, self._tiktok_set_add_status, f"✗ Lỗi: {e}", "#e74c3c")
        finally:
            finish()

    def _tiktok_extract_video_id(self, folder_name: str) -> str:
        import re
        m = re.search(r"\[([^\]]+)\]", folder_name)
        return m.group(1) if m else folder_name

    def _tiktok_find_video_file(self, folder_path: str) -> Optional[str]:
        if not os.path.isdir(folder_path):
            return None
        # Cấp 1: ngay trong thư mục video.
        for fname in sorted(os.listdir(folder_path)):
            full = os.path.join(folder_path, fname)
            if os.path.isfile(full) and fname.lower().startswith("final_vi"):
                return full
        # Cấp 2: phòng trường hợp final_vi.* nằm trong 1 thư mục con (vd "output/").
        for sub in sorted(os.listdir(folder_path)):
            sub_full = os.path.join(folder_path, sub)
            if os.path.isdir(sub_full):
                for fname in sorted(os.listdir(sub_full)):
                    full = os.path.join(sub_full, fname)
                    if os.path.isfile(full) and fname.lower().startswith("final_vi"):
                        return full
        return None

    def _tiktok_default_title(self, folder_path: str, folder_name: str) -> str:
        # Ưu tiên file title_vi.txt riêng (tiêu đề + hashtag tự soạn), rồi mới tới
        # phần chữ sau dấu "=" trong tên thư mục (bản dịch ngắn có sẵn), cuối cùng
        # fallback dùng nguyên tên thư mục.
        title_file = os.path.join(folder_path, "title_vi.txt")
        if os.path.exists(title_file):
            try:
                with open(title_file, "r", encoding="utf-8") as f:
                    t = f.read().strip()
                    if t:
                        return t
            except Exception:
                pass
        if "=" in folder_name:
            t = folder_name.split("=", 1)[1].strip()
            if t:
                return t
        return folder_name[:150]

    def _tiktok_scan_videos(self):
        for child in list(self.tiktok_list_scroll.winfo_children()):
            child.destroy()
        self.tiktok_video_rows = {}

        if not os.path.isdir(self.work_dir):
            ctk.CTkLabel(self.tiktok_list_scroll, text="Chưa có thư mục output.", text_color=TEXT_MUTED).pack(anchor="w", pady=10)
            return

        uploaded_log = self._tiktok_load_uploaded_log()
        folders = sorted(
            f for f in os.listdir(self.work_dir)
            if os.path.isdir(os.path.join(self.work_dir, f)) and f != "da_dang"
        )
        found = 0
        for folder_name in folders:
            folder_path = os.path.join(self.work_dir, folder_name)
            video_path = self._tiktok_find_video_file(folder_path)
            if not video_path:
                continue  # thư mục chưa có file final_vi.* -> chưa sẵn sàng đăng, bỏ qua
            found += 1
            video_id = self._tiktok_extract_video_id(folder_name)
            already = video_id in uploaded_log

            row = ctk.CTkFrame(self.tiktok_list_scroll, fg_color=PANEL2, corner_radius=RADIUS_ROW, border_width=1, border_color=BORDER_SOFT)
            row.pack(fill="x", pady=4)
            row_inner = ctk.CTkFrame(row, fg_color="transparent")
            row_inner.pack(fill="x", padx=12, pady=10)

            check_var = tk.BooleanVar(value=not already)
            ctk.CTkCheckBox(
                row_inner, text="", variable=check_var, width=20,
                fg_color=ACCENT, hover_color=ACCENT_HOVER,
                state=("disabled" if already else "normal"),
            ).pack(side="left", padx=(0, 10))

            mid = ctk.CTkFrame(row_inner, fg_color="transparent")
            mid.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(mid, text=_truncate_middle(folder_name, 70), font=(FONT_FAMILY, 12, "bold"), anchor="w").pack(fill="x")
            title_var = tk.StringVar(value=self._tiktok_default_title(folder_path, folder_name))
            ctk.CTkEntry(mid, textvariable=title_var, fg_color=PANEL, border_color=BORDER).pack(fill="x", pady=(4, 0))

            status_label = ctk.CTkLabel(
                row_inner, text=("✓ Đã đăng" if already else "Chưa đăng"),
                text_color=(GREEN if already else TEXT_MUTED), width=90,
            )
            status_label.pack(side="right", padx=(10, 0))

            self.tiktok_video_rows[folder_name] = {
                "folder_path": folder_path, "video_path": video_path, "video_id": video_id,
                "check_var": check_var, "title_var": title_var, "status_label": status_label,
                "already": already,
            }

        if found == 0:
            ctk.CTkLabel(
                self.tiktok_list_scroll,
                text="Chưa thấy video nào có file final_vi.* trong thư mục output.",
                text_color=TEXT_MUTED,
            ).pack(anchor="w", pady=10)
        self._tiktok_log(f"Đã quét thấy {found} video sẵn sàng.")

    def _tiktok_upload_selected(self):
        accounts = self._tiktok_load_accounts()
        if not accounts:
            messagebox.showwarning("Chưa có tài khoản", "Thêm và đăng nhập ít nhất 1 tài khoản TikTok trước khi đăng.")
            return
        tool_dir = self.tiktok_tool_dir_var.get().strip()
        if not tool_dir or not os.path.isfile(os.path.join(tool_dir, "cli.py")):
            messagebox.showerror("Không tìm thấy cli.py", f"Không thấy cli.py trong:\n{tool_dir}")
            return

        selected = [
            (name, info) for name, info in self.tiktok_video_rows.items()
            if info["check_var"].get() and not info["already"]
        ]
        if not selected:
            messagebox.showinfo("Chưa chọn video", "Không có video nào được chọn để đăng (hoặc tất cả đã đăng trước đó).")
            return

        rotate = self.tiktok_rotate_var.get() and len(accounts) > 1
        active_account = self.tiktok_active_account_var.get() or accounts[0]

        if self.tiktok_schedule_enabled_var.get():
            self._tiktok_enqueue_schedule(tool_dir, accounts, rotate, active_account, selected)
            return

        if rotate:
            self._tiktok_log(f"Bắt đầu đăng {len(selected)} video, luân phiên qua {len(accounts)} tài khoản...")
        else:
            self._tiktok_log(f"Bắt đầu đăng {len(selected)} video, tài khoản '{active_account}'...")
        threading.Thread(target=self._tiktok_upload_thread, args=(tool_dir, accounts, rotate, selected), daemon=True).start()

    def _tiktok_enqueue_schedule(self, tool_dir: str, accounts: list, rotate: bool, active_account: str, selected: list):
        """Nhánh 'đặt lịch đăng': KHÔNG chờ trong 1 thread (cách cũ, mất lịch nếu tắt
        app/máy) mà GHI THẲNG xuống file hàng đợi bền (_tiktok_schedule_path), rồi bật
        vòng kiểm tra định kỳ (_tiktok_schedule_start_checker) để tự đăng đúng giờ -
        kể cả khi người dùng tắt rồi mở lại app trước giờ đăng, lịch vẫn còn nguyên."""
        try:
            base_date = datetime.strptime(self.tiktok_schedule_date_var.get().strip(), "%d/%m/%Y")
            hh, mm = self.tiktok_schedule_time_var.get().strip().split(":")
            base_dt_local = base_date.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except Exception as e:
            messagebox.showerror("Ngày/giờ không hợp lệ", f"Không đọc được ngày/giờ đặt lịch:\n{e}")
            return
        auto_next_day = self.tiktok_schedule_next_day_var.get()

        queue = self._tiktok_load_schedule_queue()

        # Các ngày ĐÃ được dùng cho video đăng lịch trước đó (kể cả ở 1 lượt bấm "Đăng
        # video đã chọn" KHÁC, trước đó) - lấy từ chính hàng đợi đã lưu file, để "cách
        # nhau 1 ngày" đúng nghĩa dù bạn đăng từng video 1, mỗi lần bấm 1 video.
        reserved_dates = set()
        for item in queue:
            if item.get("status") in ("pending", "done"):
                try:
                    reserved_dates.add(datetime.fromisoformat(item["target_iso"]).date())
                except Exception:
                    pass

        cursor_date = base_dt_local.date()
        for idx, (folder_name, info) in enumerate(selected):
            account = accounts[idx % len(accounts)] if rotate else active_account
            title = info["title_var"].get().strip() or folder_name[:150]
            if auto_next_day:
                while cursor_date in reserved_dates:
                    cursor_date += timedelta(days=1)
                reserved_dates.add(cursor_date)
                target_dt = datetime.combine(cursor_date, base_dt_local.time())
                cursor_date += timedelta(days=1)
            else:
                target_dt = base_dt_local
            queue.append({
                "id": str(uuid.uuid4()),
                "folder_name": folder_name,
                "folder_path": info["folder_path"],
                "video_path": info["video_path"],
                "video_id": info["video_id"],
                "title": title,
                "account": account,
                "tool_dir": tool_dir,
                "target_iso": target_dt.isoformat(),
                "status": "pending",
                "error": None,
            })
            info["status_label"].configure(text=f"📅 {target_dt.strftime('%H:%M %d/%m/%Y')}", text_color=ACCENT)
            info["check_var"].set(False)

        self._tiktok_save_schedule_queue(queue)
        self._tiktok_log(
            f"📅 Đã thêm {len(selected)} video vào hàng đợi. Video nào đã trong khoảng ≤10 ngày sẽ được "
            f"upload NGAY kèm lịch đăng gốc của TikTok (TikTok tự giữ & tự công khai đúng giờ) - KHÔNG "
            f"cần app/máy bật liên tục chờ tới lúc đó. Video hẹn xa hơn 10 ngày sẽ chờ tới khi rơi vào "
            f"khoảng đó mới tự gửi lên."
        )
        self._tiktok_schedule_start_checker()

    def _tiktok_upload_thread(self, tool_dir: str, accounts: list, rotate: bool, selected: list):
        import shutil
        done_dir = os.path.join(self.work_dir, "da_dang")
        os.makedirs(done_dir, exist_ok=True)
        uploaded_log = self._tiktok_load_uploaded_log()
        active_account = self.tiktok_active_account_var.get() or accounts[0]

        for idx, (folder_name, info) in enumerate(selected):
            account = accounts[idx % len(accounts)] if rotate else active_account
            title = info["title_var"].get().strip() or folder_name[:150]
            self.after(0, self._tiktok_log, f"→ Đang đăng (tài khoản '{account}'): {folder_name}")
            self.after(0, lambda lbl=info["status_label"]: lbl.configure(text="Đang đăng...", text_color=ACCENT))

            cmd = self._tiktok_python_prefix() + ["cli.py", "upload", "-u", account, "-v", info["video_path"], "-t", title]
            env = os.environ.copy()
            env["TIKTOK_PROFILE_NAME"] = account
            success = False
            try:
                result = subprocess.run(cmd, cwd=tool_dir, capture_output=True, text=True, env=env)
                out = (result.stdout or "") + (result.stderr or "")
                for line in out.strip().splitlines()[-10:]:
                    self.after(0, self._tiktok_log, f"    {line}")
                success = result.returncode == 0
            except Exception as e:
                self.after(0, self._tiktok_log, f"    ⚠ Lỗi chạy lệnh: {e}")

            if success:
                uploaded_log[info["video_id"]] = {"folder": folder_name, "title": title, "account": account}
                self._tiktok_save_uploaded_log(uploaded_log)
                dest = os.path.join(done_dir, folder_name)
                try:
                    shutil.move(info["folder_path"], dest)
                    self.after(0, self._tiktok_log, "  ✓ Đăng xong, đã chuyển vào da_dang/")
                except Exception as e:
                    self.after(0, self._tiktok_log, f"  ✓ Đăng xong nhưng không chuyển được thư mục: {e}")
                self.after(0, lambda lbl=info["status_label"]: lbl.configure(text="✓ Đã đăng", text_color=GREEN))
                self.after(0, lambda v=info["check_var"]: v.set(False))
            else:
                self.after(0, self._tiktok_log, f"  ✗ Đăng thất bại: {folder_name}")
                self.after(0, lambda lbl=info["status_label"]: lbl.configure(text="✗ Lỗi", text_color="#e74c3c"))

        self.after(0, self._tiktok_log, "Hoàn tất.")

    # ---------- Trang YouTube (đăng video lên YouTube qua YouTube Data API v3) ----------
    def _build_youtube_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color=BG)

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text="YouTube", font=(FONT_FAMILY, 22, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Đăng nhập tài khoản Google, rồi đăng video có sẵn trong thư mục output lên YouTube.",
            font=(FONT_FAMILY, 12), text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(0, 12))

        script_dir = get_app_base_dir()
        # client_secret.json KHÔNG được đóng gói kèm bản phát hành (mỗi người dùng
        # cần OAuth Client riêng của Google Cloud). Nếu không có sẵn ở thư mục app,
        # mặc định trỏ tới thư mục dữ liệu người dùng - người dùng tự tải về rồi
        # bấm "Chọn file".
        _default_client_secret = os.path.join(script_dir, "client_secret.json")
        if not os.path.isfile(_default_client_secret):
            _default_client_secret = os.path.join(get_user_data_dir(), "client_secret.json")
        self.youtube_client_secret_var = tk.StringVar(value=_default_client_secret)

        # ----- Quan ly tai khoan Google (phan chinh) -----
        acc_panel = ctk.CTkFrame(page, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        acc_panel.pack(fill="x", pady=(0, 12))
        acc_inner = ctk.CTkFrame(acc_panel, fg_color="transparent")
        acc_inner.pack(fill="x", padx=16, pady=14)

        self.youtube_active_account_var = tk.StringVar(value="")

        acc_header_row = ctk.CTkFrame(acc_inner, fg_color="transparent")
        acc_header_row.pack(fill="x")
        ctk.CTkLabel(acc_header_row, text="Tài khoản Google đã lưu", font=(FONT_FAMILY, 13, "bold")).pack(side="left")
        ctk.CTkLabel(
            acc_header_row, text="  (bấm vào tên để chọn dùng)", text_color=TEXT_MUTED, font=(FONT_FAMILY, 11),
        ).pack(side="left")
        ctk.CTkLabel(
            acc_inner,
            text="Tài khoản đã thêm sẽ được ghi nhớ vĩnh viễn, không cần đăng nhập lại mỗi lần mở app.",
            text_color=TEXT_MUTED, font=(FONT_FAMILY, 10), justify="left", wraplength=560,
        ).pack(anchor="w", pady=(2, 10))

        self.youtube_accounts_list_frame = ctk.CTkFrame(acc_inner, fg_color="transparent")
        self.youtube_accounts_list_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(acc_inner, text="Thêm tài khoản mới", text_color=TEXT_MUTED).pack(anchor="w")

        # Email Google đang đăng nhập trong Chrome.
        # Dùng làm OAuth login_hint để Google ưu tiên đúng tài khoản.
        ctk.CTkLabel(
            acc_inner,
            text="Email Google đang mở trên Chrome",
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(4, 0))
        self.youtube_login_email_var = tk.StringVar(value="")
        ctk.CTkEntry(
            acc_inner,
            textvariable=self.youtube_login_email_var,
            fg_color=PANEL,
            border_color=BORDER,
            placeholder_text="vd: tenkenh@gmail.com",
        ).pack(fill="x", pady=(4, 8))

        add_row = ctk.CTkFrame(acc_inner, fg_color="transparent")
        add_row.pack(fill="x", pady=(0, 4))
        self.youtube_new_account_var = tk.StringVar(value="")
        ctk.CTkEntry(
            add_row, textvariable=self.youtube_new_account_var, fg_color=PANEL, border_color=BORDER,
            placeholder_text="Đặt tên cho tài khoản mới, vd: kenh1",
        ).pack(side="left", fill="x", expand=True)
        self.youtube_add_account_btn = ctk.CTkButton(
            add_row, text="🔑 Đăng nhập / Thêm tài khoản", width=210, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._youtube_add_account,
        )
        self.youtube_add_account_btn.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            acc_inner,
            text="Email chỉ dùng để định hướng Google OAuth tới đúng tài khoản; hãy kiểm tra lại email trên trang Google trước khi bấm Cho phép.",
            text_color=TEXT_MUTED, font=(FONT_FAMILY, 9), justify="left", wraplength=560,
        ).pack(anchor="w", pady=(2, 0))

        self.youtube_add_status_label = ctk.CTkLabel(acc_inner, text="", text_color=TEXT_MUTED, font=(FONT_FAMILY, 11), anchor="w", justify="left", wraplength=560)
        self.youtube_add_status_label.pack(anchor="w", pady=(2, 8))

        self.youtube_rotate_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            acc_inner, text="🔁 Luân phiên qua tất cả tài khoản khi đăng nhiều video",
            variable=self.youtube_rotate_var, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(4, 0))

        # ----- Tuy chon dang bai -----
        pub_panel = ctk.CTkFrame(page, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        pub_panel.pack(fill="x", pady=(0, 12))
        pub_inner = ctk.CTkFrame(pub_panel, fg_color="transparent")
        pub_inner.pack(fill="x", padx=16, pady=14)

        row2 = ctk.CTkFrame(pub_inner, fg_color="transparent")
        row2.pack(fill="x")
        left2 = ctk.CTkFrame(row2, fg_color="transparent")
        left2.pack(side="left", fill="x", expand=True, padx=(0, 16))
        ctk.CTkLabel(left2, text="Chế độ hiển thị (khi KHÔNG đặt lịch)", text_color=TEXT_MUTED).pack(anchor="w")
        self.youtube_privacy_var = tk.StringVar(value="public")
        ctk.CTkOptionMenu(left2, values=["public", "unlisted", "private"], variable=self.youtube_privacy_var, fg_color=PANEL, button_color=PANEL, button_hover_color=BORDER).pack(anchor="w", pady=(4, 0))

        right2 = ctk.CTkFrame(row2, fg_color="transparent")
        right2.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(right2, text="Video có dùng AI (giọng đọc/dịch AI)?", text_color=TEXT_MUTED).pack(anchor="w")
        self.youtube_ai_disclosure_var = tk.StringVar(value="Có")
        ctk.CTkOptionMenu(right2, values=["Có", "Không"], variable=self.youtube_ai_disclosure_var, fg_color=PANEL, button_color=PANEL, button_hover_color=BORDER).pack(anchor="w", pady=(4, 0))

        # ----- Giới hạn đăng tối đa/ngày (chống bị YouTube đánh dấu spam khi đăng
        # ----- dồn dập nhiều video liên tục). Đếm dựa trên số video ĐÃ THỰC SỰ upload
        # ----- (gọi API thành công) trong ngày hôm nay, tính trên TOÀN BỘ log
        # ----- (kể cả các lượt bấm "Đăng video đã chọn" trước đó trong cùng ngày),
        # ----- không phải chỉ đếm trong lượt đăng hiện tại.
        row3 = ctk.CTkFrame(pub_inner, fg_color="transparent")
        row3.pack(fill="x", pady=(12, 0))
        limit_col = ctk.CTkFrame(row3, fg_color="transparent")
        limit_col.pack(side="left")
        ctk.CTkLabel(limit_col, text="Giới hạn đăng tối đa mỗi ngày (chống bị YouTube đánh spam)", text_color=TEXT_MUTED).pack(anchor="w")
        self.youtube_daily_limit_var = tk.StringVar(value="5")
        ctk.CTkEntry(limit_col, textvariable=self.youtube_daily_limit_var, fg_color=PANEL, border_color=BORDER, width=60).pack(anchor="w", pady=(4, 0))
        self.youtube_daily_count_label = ctk.CTkLabel(row3, text="", text_color=TEXT_MUTED, font=(FONT_FAMILY, 11))
        self.youtube_daily_count_label.pack(side="left", padx=(20, 0), anchor="s", pady=(0, 4))

        # ----- Đặt lịch đăng -----
        self.youtube_schedule_enabled_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            pub_inner, text="📅 Đặt lịch đăng (thay vì đăng công khai ngay)",
            variable=self.youtube_schedule_enabled_var, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(12, 0))

        sched_inner = ctk.CTkFrame(pub_inner, fg_color="transparent")
        sched_inner.pack(fill="x", pady=(6, 0))

        date_col = ctk.CTkFrame(sched_inner, fg_color="transparent")
        date_col.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(date_col, text="Ngày đăng đầu tiên (dd/mm/yyyy)", text_color=TEXT_MUTED).pack(anchor="w")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
        self.youtube_schedule_date_var = tk.StringVar(value=tomorrow)
        ctk.CTkEntry(date_col, textvariable=self.youtube_schedule_date_var, fg_color=PANEL, border_color=BORDER, width=140).pack(anchor="w", pady=(4, 0))

        time_col = ctk.CTkFrame(sched_inner, fg_color="transparent")
        time_col.pack(side="left")
        ctk.CTkLabel(time_col, text="Giờ đăng (HH:MM)", text_color=TEXT_MUTED).pack(anchor="w")
        self.youtube_schedule_time_var = tk.StringVar(value="08:00")
        ctk.CTkEntry(time_col, textvariable=self.youtube_schedule_time_var, fg_color=PANEL, border_color=BORDER, width=100).pack(anchor="w", pady=(4, 0))

        self.youtube_schedule_next_day_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            pub_inner,
            text="🔁 Tự động đăng mỗi video cách nhau 1 ngày, cùng giờ đã chọn",
            variable=self.youtube_schedule_next_day_var, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(8, 0))
        ctk.CTkLabel(
            pub_inner,
            text="Khi đặt lịch, YouTube yêu cầu video ở chế độ riêng tư rồi tự chuyển công khai đúng giờ hẹn "
                 "— mục 'Chế độ hiển thị' phía trên sẽ không áp dụng khi đặt lịch. Video YouTube sau khi đăng "
                 "KHÔNG bị chuyển thư mục (để bạn còn dùng lại cho TikTok nếu chưa đăng).",
            text_color=TEXT_MUTED, font=(FONT_FAMILY, 10), justify="left", wraplength=520,
        ).pack(anchor="w", pady=(4, 0))

        # ----- Cai dat nang cao (an mac dinh) -----
        self._youtube_advanced_visible = False
        adv_toggle_row = ctk.CTkFrame(page, fg_color="transparent")
        adv_toggle_row.pack(fill="x", pady=(0, 4))
        self.youtube_adv_toggle_btn = ctk.CTkButton(
            adv_toggle_row, text="⚙️ Cài đặt nâng cao ▸", width=180, fg_color="transparent",
            hover_color=PANEL2, text_color=TEXT_MUTED, anchor="w",
            command=self._youtube_toggle_advanced,
        )
        self.youtube_adv_toggle_btn.pack(anchor="w")

        self.youtube_advanced_panel = ctk.CTkFrame(page, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        yadv_inner = ctk.CTkFrame(self.youtube_advanced_panel, fg_color="transparent")
        yadv_inner.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(yadv_inner, text="File client_secret.json (tải từ Google Cloud Console)", text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkLabel(
            yadv_inner,
            text="App KHÔNG tự tạo file này — cần tự tải từ Google Cloud Console rồi trỏ vào đây. "
                 "1 file client_secret.json này dùng chung được cho mọi tài khoản Google đăng nhập.",
            text_color=TEXT_MUTED, font=(FONT_FAMILY, 10), justify="left", wraplength=520,
        ).pack(anchor="w", pady=(2, 4))
        cs_row = ctk.CTkFrame(yadv_inner, fg_color="transparent")
        cs_row.pack(fill="x", pady=(4, 0))
        ctk.CTkEntry(cs_row, textvariable=self.youtube_client_secret_var, fg_color=PANEL, border_color=BORDER).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(cs_row, text="Chọn file", width=100, command=self._choose_youtube_client_secret).pack(side="left", padx=(8, 0))
        # Panel nang cao chua duoc .pack() - an mac dinh, bam nut o tren de mo.

        # ----- Danh sách video -----
        list_panel = ctk.CTkFrame(page, fg_color=PANEL, corner_radius=RADIUS_PANEL)
        self._youtube_list_panel_ref = list_panel
        list_panel.pack(fill="both", expand=True)
        list_header = ctk.CTkFrame(list_panel, fg_color="transparent")
        list_header.pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkLabel(list_header, text="Video trong thư mục output", font=(FONT_FAMILY, 13, "bold")).pack(side="left")
        ctk.CTkButton(
            list_header, text="🔄 Quét lại", width=100, fg_color=PANEL2, hover_color=BORDER,
            command=self._youtube_scan_videos,
        ).pack(side="right")
        ctk.CTkButton(
            list_header, text="🚀 Đăng video đã chọn", fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._youtube_upload_selected,
        ).pack(side="right", padx=(0, 8))

        self.youtube_list_scroll = ctk.CTkScrollableFrame(list_panel, fg_color="transparent")
        self.youtube_list_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.youtube_video_rows: dict[str, dict] = {}

        ctk.CTkLabel(list_panel, text="Nhật ký đăng bài", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(0, 2))
        self.youtube_log_box = ctk.CTkTextbox(list_panel, fg_color=PANEL2, height=120, wrap="word")
        self.youtube_log_box.pack(fill="x", padx=14, pady=(0, 14))
        self.youtube_log_box.configure(state="disabled")

        self.after(300, self._youtube_scan_videos)
        self.after(300, self._youtube_refresh_accounts_ui)
        self.after(300, self._youtube_update_daily_count_label)
        return page

    def _youtube_toggle_advanced(self):
        self._youtube_advanced_visible = not self._youtube_advanced_visible
        if self._youtube_advanced_visible:
            self.youtube_advanced_panel.pack(fill="x", pady=(0, 12), before=self._youtube_list_panel_ref)
            self.youtube_adv_toggle_btn.configure(text="⚙️ Cài đặt nâng cao ▾")
        else:
            self.youtube_advanced_panel.pack_forget()
            self.youtube_adv_toggle_btn.configure(text="⚙️ Cài đặt nâng cao ▸")

    def _choose_youtube_client_secret(self):
        path = filedialog.askopenfilename(title="Chọn file client_secret.json", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self.youtube_client_secret_var.set(path)

    # ----- Quan ly nhieu tai khoan Google -----
    def _youtube_accounts_path(self) -> str:
        return os.path.join(get_user_data_dir(), "youtube_accounts.json")

    def _youtube_account_emails_path(self) -> str:
        return os.path.join(get_user_data_dir(), "youtube_account_emails.json")

    def _youtube_load_account_emails(self) -> dict:
        path = self._youtube_account_emails_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    def _youtube_save_account_email(self, label: str, email: str):
        try:
            emails = self._youtube_load_account_emails()
            emails[label] = email
            with open(self._youtube_account_emails_path(), "w", encoding="utf-8") as f:
                json.dump(emails, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._youtube_log(f"⚠ Không lưu được email tài khoản '{label}': {e}")

    def _youtube_accounts_email(self, label: str) -> str:
        return self._youtube_load_account_emails().get(label, "").strip()

    def _youtube_load_accounts(self) -> list:
        path = self._youtube_accounts_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f).get("accounts", [])
            except Exception:
                return []
        return []

    def _youtube_save_accounts(self, accounts: list):
        try:
            with open(self._youtube_accounts_path(), "w", encoding="utf-8") as f:
                json.dump({"accounts": accounts}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._youtube_log(f"⚠ Không lưu được danh sách tài khoản: {e}")

    def _youtube_token_path(self, label: str) -> str:
        # Moi tai khoan (label) co 1 file token rieng, luu canh client_secret.
        cs = self.youtube_client_secret_var.get().strip()
        base_dir = os.path.dirname(cs) if cs else get_user_data_dir()
        safe_label = "".join(c for c in label if c.isalnum() or c in ("-", "_")) or "default"
        return os.path.join(base_dir, f"youtube_token_{safe_label}.json")

    def _youtube_refresh_accounts_ui(self):
        accounts = self._youtube_load_accounts()

        if accounts and self.youtube_active_account_var.get() not in accounts:
            self.youtube_active_account_var.set(accounts[0])
        elif not accounts:
            self.youtube_active_account_var.set("")

        for child in list(self.youtube_accounts_list_frame.winfo_children()):
            child.destroy()

        if not accounts:
            ctk.CTkLabel(
                self.youtube_accounts_list_frame, text="Chưa có tài khoản nào — thêm tài khoản đầu tiên ở khung bên dưới.",
                text_color=TEXT_MUTED,
            ).pack(anchor="w", pady=6)
            return

        active = self.youtube_active_account_var.get()
        for acc in accounts:
            is_active = acc == active
            row = ctk.CTkFrame(
                self.youtube_accounts_list_frame,
                fg_color=(ACCENT if is_active else PANEL),
                corner_radius=RADIUS_ROW, border_width=1,
                border_color=(ACCENT if is_active else BORDER_SOFT),
            )
            row.pack(fill="x", pady=3)
            row_inner = ctk.CTkFrame(row, fg_color="transparent")
            row_inner.pack(fill="x", padx=10, pady=6)

            ctk.CTkButton(
                row_inner, text=("● Đang dùng — " if is_active else "○ ") + acc,
                anchor="w", fg_color="transparent",
                hover_color=(ACCENT_HOVER if is_active else PANEL2),
                text_color="white",
                font=(FONT_FAMILY, 12, "bold" if is_active else "normal"),
                command=lambda a=acc: self._youtube_select_account(a),
            ).pack(side="left", fill="x", expand=True)

            ctk.CTkButton(
                row_inner, text="🔄", width=32, height=26,
                fg_color="transparent", hover_color=(ACCENT_HOVER if is_active else PANEL2),
                command=lambda a=acc: self._youtube_relogin_account(a),
            ).pack(side="left", padx=(4, 0))
            ctk.CTkButton(
                row_inner, text="🗑", width=32, height=26,
                fg_color="transparent", hover_color=(ACCENT_HOVER if is_active else PANEL2),
                command=lambda a=acc: self._youtube_delete_account(a),
            ).pack(side="left", padx=(4, 0))

    def _youtube_select_account(self, label: str):
        self.youtube_active_account_var.set(label)
        self._youtube_refresh_accounts_ui()
        self._youtube_log(f"Đã chọn tài khoản đang dùng: '{label}'.")

    def _youtube_relogin_account(self, label: str):
        cs = self.youtube_client_secret_var.get().strip()
        if not os.path.isfile(cs):
            messagebox.showerror("Không tìm thấy file", f"Không thấy client_secret.json tại:\n{cs}\n(mở '⚙️ Cài đặt nâng cao' để trỏ đúng file).")
            return
        # Xoa token cu de bat buoc xac thuc lai tu dau (phong khi token loi ma
        # khong refresh duoc tu dong).
        token_path = self._youtube_token_path(label)
        if os.path.exists(token_path):
            try:
                os.remove(token_path)
            except Exception:
                pass
        login_email = self._youtube_accounts_email(label)
        if not login_email:
            messagebox.showwarning(
                "Thiếu email Google",
                f"Chưa lưu email Google cho '{label}'. Hãy nhập email ở dòng "
                f"'Email Google đang mở trên Chrome' rồi đăng nhập lại.",
            )
            try:
                self.youtube_login_email_var.set("")
                self.youtube_login_email_var.focus_set()
            except Exception:
                pass
            return
        try:
            self.youtube_login_email_var.set(login_email)
        except Exception:
            pass
        self._youtube_set_add_status(
            f"🔄 Đang mở trình duyệt để đăng nhập lại '{label}' ({login_email})...",
            ACCENT,
        )
        self._youtube_log(f"Đang mở trình duyệt để đăng nhập lại '{label}' bằng email '{login_email}'...")
        threading.Thread(
            target=self._youtube_add_account_thread,
            args=(label, login_email),
            daemon=True,
        ).start()

    def _youtube_delete_account(self, label: str):
        accounts = self._youtube_load_accounts()
        if label in accounts:
            accounts.remove(label)
            self._youtube_save_accounts(accounts)
            try:
                emails = self._youtube_load_account_emails()
                emails.pop(label, None)
                with open(self._youtube_account_emails_path(), "w", encoding="utf-8") as f:
                    json.dump(emails, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            self._youtube_refresh_accounts_ui()
            self._youtube_log(f"Đã xoá tài khoản '{label}' khỏi danh sách (không thu hồi quyền trên Google).")

    def _youtube_get_credentials(self, label: str, login_email: str = ""):
        """Trả về Credentials hợp lệ cho 1 tài khoản (label) cụ thể, tự refresh
        hoặc mở trình duyệt xin quyền nếu cần. Import google-* cục bộ để phần còn
        lại của app vẫn chạy được nếu máy chưa cài các gói này."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        client_secret_path = self.youtube_client_secret_var.get().strip()
        token_path = self._youtube_token_path(label)

        if not os.path.isfile(client_secret_path):
            raise FileNotFoundError(f"Không tìm thấy file client_secret.json tại: {client_secret_path}")

        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, scopes)
                # login_hint giúp Google ưu tiên đúng email đang mở trong Chrome,
                # tránh trường hợp Chrome đang có nhiều tài khoản Google.
                login_email = (login_email or "").strip()
                if login_email:
                    creds = flow.run_local_server(port=0, login_hint=login_email)
                else:
                    creds = flow.run_local_server(port=0)
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        return creds

    def _youtube_set_add_status(self, text: str, color=None):
        try:
            self.youtube_add_status_label.configure(text=text, text_color=(color or TEXT_MUTED))
        except Exception:
            pass

    def _youtube_add_account(self):
        label = self.youtube_new_account_var.get().strip()
        login_email = self.youtube_login_email_var.get().strip()
        if not label:
            messagebox.showwarning("Thiếu tên tài khoản", "Đặt tên cho tài khoản mới trước (tên tự đặt để phân biệt các kênh).")
            return
        if not login_email or "@" not in login_email:
            messagebox.showwarning(
                "Thiếu email Google",
                "Nhập đúng email Google đang đăng nhập trong Chrome trước khi bấm đăng nhập.",
            )
            return
        cs = self.youtube_client_secret_var.get().strip()
        if not os.path.isfile(cs):
            messagebox.showerror("Không tìm thấy file", f"Không thấy client_secret.json tại:\n{cs}\n(mở '⚙️ Cài đặt nâng cao' để trỏ đúng file).")
            return

        self.youtube_add_account_btn.configure(state="disabled", text="⏳ Đang xử lý...")
        self._youtube_set_add_status(
            f"🔄 Đang mở Google OAuth cho {login_email}... (hãy kiểm tra đúng email trước khi Cho phép)",
            ACCENT,
        )
        self._youtube_log(
            f"Đang mở trình duyệt để đăng nhập '{label}' bằng email '{login_email}'..."
        )
        threading.Thread(
            target=self._youtube_add_account_thread,
            args=(label, login_email),
            daemon=True,
        ).start()

    def _youtube_add_account_thread(self, label: str, login_email: str = ""):
        try:
            self._youtube_get_credentials(label, login_email)
            self.after(0, self._youtube_log, f"✓ Đăng nhập xong cho '{label}'.")
            self.after(0, self._youtube_set_add_status, f"✓ Đăng nhập thành công cho '{label}'.", GREEN)
            accounts = self._youtube_load_accounts()
            if label not in accounts:
                accounts.append(label)
                self._youtube_save_accounts(accounts)
            if login_email:
                self._youtube_save_account_email(label, login_email)
            self.after(0, self.youtube_new_account_var.set, "")
            self.after(0, self.youtube_login_email_var.set, "")
            self.after(0, lambda: self.youtube_active_account_var.set(label))
            self.after(0, self._youtube_refresh_accounts_ui)
        except Exception as e:
            self.after(0, self._youtube_log, f"⚠ Đăng nhập thất bại: {e}")
            self.after(0, self._youtube_set_add_status, f"✗ Lỗi: {e}", "#e74c3c")
        finally:
            self.after(0, lambda: self.youtube_add_account_btn.configure(state="normal", text="🔑 Đăng nhập / Thêm tài khoản"))

    def _youtube_log(self, msg: str):
        try:
            self.youtube_log_box.configure(state="normal")
            self.youtube_log_box.insert("end", f"{msg}\n")
            self.youtube_log_box.see("end")
            self.youtube_log_box.configure(state="disabled")
        except Exception:
            pass
        self.log(f"[YouTube] {msg}")

    def _youtube_log_path(self) -> str:
        return os.path.join(get_user_data_dir(), "youtube_uploaded_log.json")

    def _youtube_load_uploaded_log(self) -> dict:
        path = self._youtube_log_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _youtube_save_uploaded_log(self, data: dict):
        try:
            with open(self._youtube_log_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._youtube_log(f"⚠ Không lưu được log: {e}")

    def _youtube_get_daily_limit(self) -> int:
        """Đọc giới hạn đăng tối đa/ngày từ ô nhập trên giao diện. Nhập sai/để trống
        thì mặc định 5; tối thiểu luôn là 1 (không cho phép tắt hẳn giới hạn bằng
        cách nhập 0 hoặc số âm, tránh nhập nhầm)."""
        try:
            val = int(str(self.youtube_daily_limit_var.get()).strip())
            return max(1, val)
        except Exception:
            return 5

    def _youtube_count_uploaded_today(self, uploaded_log: dict) -> int:
        """Đếm số video đã ĐĂNG THẬT (gọi API upload thành công) trong ngày hôm nay
        theo giờ máy local. Dựa vào field 'uploaded_at' (thời điểm upload THẬT SỰ
        diễn ra) - khác với 'publish_at' (thời điểm YouTube sẽ tự chuyển công khai
        nếu có đặt lịch, có thể là một ngày trong tương lai). Các entry log cũ chưa
        có 'uploaded_at' (tạo trước khi có tính năng này) sẽ không được tính, coi
        như không ảnh hưởng tới giới hạn của hôm nay."""
        today_local = datetime.now().astimezone().date()
        count = 0
        for entry in uploaded_log.values():
            ts = entry.get("uploaded_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts)
                if dt.astimezone().date() == today_local:
                    count += 1
            except Exception:
                pass
        return count

    def _youtube_update_daily_count_label(self):
        """Cập nhật nhãn 'Hôm nay đã đăng: x/y' cạnh ô giới hạn/ngày."""
        try:
            uploaded_log = self._youtube_load_uploaded_log()
            done_today = self._youtube_count_uploaded_today(uploaded_log)
            limit = self._youtube_get_daily_limit()
            self.youtube_daily_count_label.configure(
                text=f"Hôm nay đã đăng: {done_today}/{limit}",
                text_color=(TEXT_MUTED if done_today < limit else "#e74c3c"),
            )
        except Exception:
            pass

    def _youtube_parse_note_file(self, folder_path: str):
        """Đọc NOTE.txt (nếu có) trong thư mục video, trả về (title, description).

        Định dạng NOTE.txt do bước dịch tạo ra (core/pipeline.py:_package_final_output):
            <tên file gốc> [id]

            Tiêu đề YouTube (Tiếng Việt)
            <tiêu đề>

            Mô tả video YouTube
            <mô tả nhiều dòng>
            <toàn bộ hashtag, LUÔN nằm ở cuối - KHÔNG còn header "HASHTAGS (n)"
            riêng nữa kể từ khi bỏ giới hạn 5 hashtag>

        Việc nhận diện section bên dưới CHỈ so khớp TIỀN TỐ "TIÊU ĐỀ"/"MÔ TẢ"/"HASHTAG"
        (không phân biệt hoa-thường) nên vẫn hoạt động đúng dù header đã đổi thành
        "Tiêu đề YouTube (Tiếng Việt)"/"Mô tả video YouTube" cho dễ đọc hơn. Vì NOTE.txt
        giờ không còn ghi header "HASHTAGS" riêng, _extract_section("HASHTAG") ở dưới sẽ
        luôn trả về rỗng - hashtag tự động nằm gọn trong phần "MÔ TẢ" (đúng ý, vì
        YouTube/TikTok cũng thường đặt hashtag ở cuối mô tả). Logic hashtags riêng vẫn
        được giữ lại để tương thích ngược với NOTE.txt cũ (bản có header "HASHTAGS (n)").

        Trả về (None, None) nếu không có file hoặc không đọc được.
        """
        note_path = os.path.join(folder_path, "NOTE.txt")
        if not os.path.exists(note_path):
            return None, None
        try:
            with open(note_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return None, None

        section_headers = ("TIÊU ĐỀ", "MÔ TẢ", "HASHTAG")

        def _extract_section(label_prefix: str) -> str:
            lines = content.splitlines()
            capture = False
            collected = []
            for line in lines:
                stripped = line.strip()
                if not capture and stripped.upper().startswith(label_prefix):
                    capture = True
                    continue
                if capture:
                    # Dừng khi gặp header của section kế tiếp.
                    if stripped and any(stripped.upper().startswith(p) for p in section_headers):
                        break
                    collected.append(line)
            return "\n".join(collected).strip()

        title = _extract_section("TIÊU ĐỀ")
        desc_body = _extract_section("MÔ TẢ")
        hashtags = _extract_section("HASHTAG")

        description = desc_body
        if hashtags:
            description = f"{desc_body}\n\n{hashtags}".strip() if desc_body else hashtags

        return (title or None), (description or None)

    def _youtube_candidate_folders(self) -> list:
        """Quét thư mục output + thêm 1 cấp trong da_dang/ (video TikTok đã đăng
        nhưng có thể vẫn chưa đăng YouTube)."""
        candidates = []
        if not os.path.isdir(self.work_dir):
            return candidates
        for f in sorted(os.listdir(self.work_dir)):
            full = os.path.join(self.work_dir, f)
            if not os.path.isdir(full):
                continue
            if f == "da_dang":
                for f2 in sorted(os.listdir(full)):
                    full2 = os.path.join(full, f2)
                    if os.path.isdir(full2):
                        candidates.append((f2, full2))
                continue
            candidates.append((f, full))
        return candidates

    def _youtube_scan_videos(self):
        for child in list(self.youtube_list_scroll.winfo_children()):
            child.destroy()
        self.youtube_video_rows = {}

        uploaded_log = self._youtube_load_uploaded_log()
        found = 0
        for folder_name, folder_path in self._youtube_candidate_folders():
            video_path = self._tiktok_find_video_file(folder_path)
            if not video_path:
                continue
            found += 1
            video_id = self._tiktok_extract_video_id(folder_name)
            already = video_id in uploaded_log

            row = ctk.CTkFrame(self.youtube_list_scroll, fg_color=PANEL2, corner_radius=RADIUS_ROW, border_width=1, border_color=BORDER_SOFT)
            row.pack(fill="x", pady=4)
            row_inner = ctk.CTkFrame(row, fg_color="transparent")
            row_inner.pack(fill="x", padx=12, pady=10)

            check_var = tk.BooleanVar(value=not already)
            ctk.CTkCheckBox(
                row_inner, text="", variable=check_var, width=20,
                fg_color=ACCENT, hover_color=ACCENT_HOVER,
                state=("disabled" if already else "normal"),
            ).pack(side="left", padx=(0, 10))

            mid = ctk.CTkFrame(row_inner, fg_color="transparent")
            mid.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(mid, text=_truncate_middle(folder_name, 70), font=(FONT_FAMILY, 12, "bold"), anchor="w").pack(fill="x")
            note_title, note_desc = self._youtube_parse_note_file(folder_path)
            default_title = note_title or self._tiktok_default_title(folder_path, folder_name)
            default_desc = note_desc or default_title
            title_var = tk.StringVar(value=default_title)
            ctk.CTkEntry(mid, textvariable=title_var, fg_color=PANEL, border_color=BORDER, placeholder_text="Tiêu đề video").pack(fill="x", pady=(4, 0))
            desc_var = tk.StringVar(value=default_desc)
            ctk.CTkEntry(mid, textvariable=desc_var, fg_color=PANEL, border_color=BORDER, placeholder_text="Mô tả video").pack(fill="x", pady=(4, 0))

            status_label = ctk.CTkLabel(
                row_inner, text=("✓ Đã đăng" if already else "Chưa đăng"),
                text_color=(GREEN if already else TEXT_MUTED), width=90,
            )
            status_label.pack(side="right", padx=(10, 0))

            self.youtube_video_rows[folder_name] = {
                "folder_path": folder_path, "video_path": video_path, "video_id": video_id,
                "check_var": check_var, "title_var": title_var, "desc_var": desc_var,
                "status_label": status_label, "already": already,
            }

        if found == 0:
            ctk.CTkLabel(
                self.youtube_list_scroll, text="Chưa thấy video nào có file final_vi.* trong thư mục output.",
                text_color=TEXT_MUTED,
            ).pack(anchor="w", pady=10)
        self._youtube_log(f"Đã quét thấy {found} video sẵn sàng.")

    def _youtube_upload_selected(self):
        accounts = self._youtube_load_accounts()
        if not accounts:
            messagebox.showwarning("Chưa có tài khoản", "Thêm và đăng nhập ít nhất 1 tài khoản Google trước khi đăng.")
            return
        selected = [
            (name, info) for name, info in self.youtube_video_rows.items()
            if info["check_var"].get() and not info["already"]
        ]
        if not selected:
            messagebox.showinfo("Chưa chọn video", "Không có video nào được chọn để đăng (hoặc tất cả đã đăng trước đó).")
            return

        # ----- Giới hạn tối đa N video/ngày (chống bị YouTube đánh dấu spam khi
        # ----- đăng dồn dập nhiều video liên tục trong 1 ngày). Đếm dựa trên số
        # ----- video đã đăng THẬT trong hôm nay, tính TRÊN TOÀN BỘ log - kể cả từ
        # ----- các lượt bấm "Đăng video đã chọn" KHÁC trước đó trong cùng ngày,
        # ----- không phải chỉ đếm riêng lượt bấm lần này.
        daily_limit = self._youtube_get_daily_limit()
        uploaded_log = self._youtube_load_uploaded_log()
        done_today = self._youtube_count_uploaded_today(uploaded_log)
        remaining_today = max(0, daily_limit - done_today)

        if remaining_today <= 0:
            messagebox.showwarning(
                "Đã đạt giới hạn hôm nay",
                f"Hôm nay đã đăng {done_today}/{daily_limit} video — đã đạt giới hạn tối đa/ngày.\n"
                "Hãy quay lại vào ngày mai, hoặc tăng số ở ô 'Giới hạn đăng tối đa mỗi ngày'.",
            )
            self._youtube_log(f"⛔ Đã đạt giới hạn {daily_limit} video/ngày hôm nay, không đăng thêm.")
            return

        skipped_count = 0
        if len(selected) > remaining_today:
            skipped_count = len(selected) - remaining_today
            selected = selected[:remaining_today]

        rotate = self.youtube_rotate_var.get() and len(accounts) > 1
        if rotate:
            self._youtube_log(f"Bắt đầu đăng {len(selected)} video, luân phiên qua {len(accounts)} tài khoản...")
        else:
            active = self.youtube_active_account_var.get() or accounts[0]
            self._youtube_log(f"Bắt đầu đăng {len(selected)} video, tài khoản '{active}'...")
        if skipped_count > 0:
            self._youtube_log(
                f"⏳ Còn {skipped_count} video đã chọn bị hoãn lại (chưa đăng) do đã đạt giới hạn "
                f"{daily_limit} video/ngày (đã đăng {done_today} trước đó + {len(selected)} video lượt này). "
                "Quay lại quét/đăng tiếp vào ngày mai."
            )
        threading.Thread(target=self._youtube_upload_thread, args=(accounts, rotate, selected), daemon=True).start()

    def _youtube_upload_thread(self, accounts: list, rotate: bool, selected: list):
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        active_account = self.youtube_active_account_var.get() or accounts[0]
        privacy = self.youtube_privacy_var.get()
        contains_synthetic = self.youtube_ai_disclosure_var.get() == "Có"
        uploaded_log = self._youtube_load_uploaded_log()

        # ----- Tính lịch đăng (nếu bật) - CÙNG NGÀY đã dùng cho video đăng lịch TRƯỚC ĐÓ
        # ----- (kể cả ở 1 lượt bấm "Đăng video đã chọn" KHÁC, trước đó) sẽ bị bỏ qua, tự
        # ----- tìm ngày TRỐNG tiếp theo - để "cách nhau 1 ngày" đúng nghĩa dù bạn đăng
        # ----- từng video 1, mỗi lần bấm 1 video, thay vì phải tick chọn hết rồi bấm 1 lần.
        schedule_enabled = self.youtube_schedule_enabled_var.get()
        publish_times = [None] * len(selected)
        if schedule_enabled:
            try:
                base_date = datetime.strptime(self.youtube_schedule_date_var.get().strip(), "%d/%m/%Y")
                hh, mm = self.youtube_schedule_time_var.get().strip().split(":")
                base_dt_local = base_date.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                auto_next_day = self.youtube_schedule_next_day_var.get()

                # Các ngày ĐÃ được dùng cho video đăng lịch trước đó (đọc lại từ log đã lưu
                # - nếu chưa có field publish_at, tức log cũ/video đăng ngay, bỏ qua không tính).
                reserved_dates = set()
                for entry in uploaded_log.values():
                    pa = entry.get("publish_at")
                    if pa:
                        try:
                            reserved_dates.add(datetime.fromisoformat(pa).astimezone().date())
                        except Exception:
                            pass

                cursor_date = base_dt_local.date()
                for idx in range(len(selected)):
                    if auto_next_day:
                        while cursor_date in reserved_dates:
                            cursor_date += timedelta(days=1)
                        reserved_dates.add(cursor_date)
                        dt_local = datetime.combine(cursor_date, base_dt_local.time())
                        cursor_date += timedelta(days=1)
                    else:
                        dt_local = base_dt_local
                    dt_aware_local = dt_local.astimezone()  # gan tzinfo theo may local
                    publish_times[idx] = dt_aware_local.astimezone(timezone.utc).isoformat()
            except Exception as e:
                self.after(0, self._youtube_log, f"⚠ Ngày/giờ đặt lịch không hợp lệ ({e}) — sẽ đăng công khai ngay thay vì đặt lịch.")
                schedule_enabled = False

        # Cache credentials/service theo tung tai khoan de khong phai xac thuc lai lien tuc.
        service_cache: dict[str, object] = {}

        def get_service_for(label: str):
            if label not in service_cache:
                creds = self._youtube_get_credentials(label)
                service_cache[label] = build("youtube", "v3", credentials=creds)
            return service_cache[label]

        for idx, (folder_name, info) in enumerate(selected):
            account = accounts[idx % len(accounts)] if rotate else active_account
            title = (info["title_var"].get().strip() or folder_name[:90])[:100]  # YouTube gioi han 100 ky tu tieu de
            description = info["desc_var"].get().strip()
            self.after(0, self._youtube_log, f"→ Đang đăng (tài khoản '{account}'): {folder_name}")
            self.after(0, lambda lbl=info["status_label"]: lbl.configure(text="Đang đăng...", text_color=ACCENT))

            try:
                youtube = get_service_for(account)
                status_body = {"containsSyntheticMedia": contains_synthetic}
                if schedule_enabled and publish_times[idx]:
                    # YouTube yeu cau privacyStatus="private" khi dat publishAt trong tuong lai,
                    # video se tu dong chuyen cong khai dung gio hen.
                    status_body["privacyStatus"] = "private"
                    status_body["publishAt"] = publish_times[idx]
                    self.after(0, self._youtube_log, f"    Đặt lịch đăng lúc: {publish_times[idx]}")
                else:
                    status_body["privacyStatus"] = privacy

                body = {
                    "snippet": {"title": title, "description": description, "categoryId": "24"},
                    "status": status_body,
                }
                media = MediaFileUpload(info["video_path"], chunksize=-1, resumable=True)
                request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        pct = int(status.progress() * 100)
                        self.after(0, self._youtube_log, f"    ...{pct}%")
                video_url = f"https://youtu.be/{response['id']}"
                self.after(0, self._youtube_log, f"  ✓ Đăng xong: {video_url}")

                uploaded_log[info["video_id"]] = {
                    "folder": folder_name, "title": title, "url": video_url, "account": account,
                    "publish_at": (publish_times[idx] if schedule_enabled else None),
                    # Thời điểm upload THẬT SỰ diễn ra (khác publish_at) - dùng để
                    # tính giới hạn N video/ngày, kể cả khi video được đặt lịch
                    # công khai vào một ngày khác trong tương lai.
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                }
                self._youtube_save_uploaded_log(uploaded_log)
                self.after(0, lambda lbl=info["status_label"]: lbl.configure(text="✓ Đã đăng", text_color=GREEN))
                self.after(0, lambda v=info["check_var"]: v.set(False))
                self.after(0, self._youtube_update_daily_count_label)
            except Exception as e:
                self.after(0, self._youtube_log, f"  ✗ Đăng thất bại: {folder_name} — {e}")
                self.after(0, lambda lbl=info["status_label"]: lbl.configure(text="✗ Lỗi", text_color="#e74c3c"))

        self.after(0, self._youtube_log, "Hoàn tất.")
        self.after(0, self._youtube_update_daily_count_label)

    def _build_srt_loader_section(self, parent):
        """

        Cho phép nạp 1 file .srt CÓ SẴN (đã dịch/soạn sẵn) để dùng THẲNG, thay vì
        chạy Whisper tách thoại + dịch từ đầu. Khi bật, pipeline sẽ BỎ QUA hoàn
        toàn 2 bước Transcript và Translate (xem core/pipeline.py - input_srt_path),
        coi nội dung text trong .srt đã là ngôn ngữ đích, dùng thẳng cho các bước
        sau (ghép nhịp lời dẫn, lồng tiếng, burn phụ đề...).
        """
        # ---- Video KHÔNG có lời thoại - AI (xem video) tự viết kịch bản ----
        silent_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        silent_box.pack(fill="x", padx=18, pady=(0, 10))
        silent_inner = ctk.CTkFrame(silent_box, fg_color="transparent")
        silent_inner.pack(fill="x", padx=14, pady=12)

        ctk.CTkLabel(
            silent_inner, text="🎬 Video KHÔNG có lời thoại (chỉ có hành động) — AI tự viết kịch bản",
            font=(FONT_FAMILY, 12, "bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            silent_inner,
            text="Dành cho video CÂM/không lời thoại (có thể có nhạc nền). AI (Gemini) XEM TRỰC TIẾP video, "
                 "hiểu hành động đang diễn ra, rồi TỰ VIẾT 1 kịch bản thuyết minh khớp với hình - dùng thẳng cho "
                 "bước lồng tiếng/phụ đề như bình thường. Bỏ qua hẳn Tách thoại (Whisper) và bước Dịch. Cần ít "
                 "nhất 1 Gemini API key.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=560,
        ).pack(anchor="w", pady=(4, 8))

        self.silent_video_ai_script = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            silent_inner, text="Video này không có lời thoại - để AI tự viết kịch bản",
            variable=self.silent_video_ai_script, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._on_toggle_silent_video_script,
        ).pack(anchor="w")

        style_row = ctk.CTkFrame(silent_inner, fg_color="transparent")
        style_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(style_row, text="Giọng văn kịch bản", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.silent_video_narration_style = ctk.StringVar(value="neutral")
        self.silent_video_style_combo = ctk.CTkComboBox(
            style_row, values=["neutral", "dramatic"], variable=self.silent_video_narration_style,
            fg_color=PANEL, border_color=BORDER, button_color=ACCENT, state="disabled",
        )
        self.silent_video_style_combo.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            silent_inner,
            text="neutral = tường thuật khách quan, bám sát đúng hành động (kiểu tài liệu/thời sự). "
                 "dramatic = dẫn chuyện kịch tính/giật tít, tạo tò mò (kiểu video viral) nhưng vẫn không bịa "
                 "tình tiết không có thật.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=560,
        ).pack(anchor="w", pady=(4, 0))

        box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        box.pack(fill="x", padx=18, pady=(0, 4))
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)

        ctk.CTkLabel(inner, text="Nạp phụ đề (.srt) có sẵn — thay cho Tách thoại + Dịch", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            inner,
            text="Bật mục này nếu bạn ĐÃ CÓ file .srt đúng ngôn ngữ đích (tự soạn, hoặc lấy từ nguồn khác).\n"
                 "Pipeline sẽ bỏ qua hẳn Whisper (tách thoại) và bước Dịch, dùng THẲNG nội dung trong file này.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", pady=(4, 8))

        self.use_input_srt = ctk.BooleanVar(value=False)
        self.input_srt_path = ""

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkCheckBox(
            row, text="Dùng file .srt có sẵn", variable=self.use_input_srt,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._on_toggle_input_srt,
        ).pack(side="left", padx=(0, 16))
        self.input_srt_label = ctk.CTkLabel(row, text="Chưa chọn file", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED)
        self.input_srt_label.pack(side="left", fill="x", expand=True)
        self.input_srt_button = ctk.CTkButton(row, text="Chọn file .srt", width=120, command=self._choose_input_srt, state="disabled")
        self.input_srt_button.pack(side="right")

        # ---- Dịch nhanh & xuất .srt để tự chỉnh sửa tay trước khi lồng tiếng/burn phụ đề ----
        # Chỉ chạy Tách thoại (Whisper) + Dịch, KHÔNG chạy voice/export video. Xuất ra 1 file
        # .srt để người dùng tải về máy, tự sửa lại nội dung, rồi nạp lại bằng mục
        # "Dùng file .srt có sẵn" ở trên (bật checkbox + chọn đúng file vừa sửa).
        export_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        export_box.pack(fill="x", padx=18, pady=(10, 4))
        export_inner = ctk.CTkFrame(export_box, fg_color="transparent")
        export_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(export_inner, text="Dịch nhanh & xuất .srt để tự chỉnh sửa", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            export_inner,
            text="Chỉ chạy Tách thoại + Dịch (KHÔNG lồng tiếng/xuất video), rồi cho tải file .srt về máy.\n"
                 "Sửa xong, nạp lại bằng mục 'Dùng file .srt có sẵn' phía trên.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", pady=(4, 8))

        self.export_srt_btn = ctk.CTkButton(
            export_inner, text="📝 Dịch & Tải file SRT", width=180,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.export_srt_only,
        )
        self.export_srt_btn.pack(anchor="w")

        # ---- Viết lại/biến tấu nội dung SAU KHI dịch (né trùng lặp) ----
        # Chạy thêm 1 lượt qua core/rewrite_srt.py NGAY TRONG NGÔN NGỮ ĐÍCH sau khi
        # dịch xong - khác với việc dịch (translate.py) vốn đã "viết lại" so với bản
        # gốc, bước này biến tấu THÊM 1 lần nữa trên chính bản dịch, rồi tính lại
        # timing THEO ĐỘ DÀI VĂN BẢN MỚI (khớp hơn bản dịch gốc, vốn giữ nguyên
        # timestamp của bản gốc bất kể văn bản dịch dài/ngắn thế nào).
        rewrite_row = ctk.CTkFrame(export_inner, fg_color="transparent")
        rewrite_row.pack(fill="x", pady=(10, 0))
        self.rewrite_after_translate = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            rewrite_row,
            text="Viết lại/biến tấu thêm nội dung SAU KHI dịch (Gemini API, hoặc Web2API nếu không có key) + tự canh lại timing theo văn bản mới",
            variable=self.rewrite_after_translate, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w")
        keepratio_row = ctk.CTkFrame(export_inner, fg_color="transparent")
        keepratio_row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(keepratio_row, text="Mức giữ ý gốc", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.rewrite_keep_ratio = ctk.DoubleVar(value=0.4)
        self._slider_with_value(keepratio_row, self.rewrite_keep_ratio, 0.1, 0.9, fmt="{:.1f}")
        ctk.CTkLabel(
            export_inner,
            text="0.1 = biến tấu RẤT MẠNH (câu chữ khác xa bản dịch) — 0.9 = biến tấu NHẸ (gần sát bản dịch). "
                 "Sự kiện/số liệu/tên riêng luôn được giữ nguyên 100% dù chỉnh mức nào.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(2, 0))

        # Câu CTA (kêu gọi hành động) TỰ ĐỘNG chèn vào cuối video - đi qua đúng luồng lồng
        # tiếng + tự kéo dài đuôi video như mọi câu khác (core/pipeline.py, xem outro_cta_text).
        cta_row = ctk.CTkFrame(export_inner, fg_color="transparent")
        cta_row.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(cta_row, text="Câu CTA cuối video", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.outro_cta_text = ctk.StringVar(value="Hãy Like và Theo dõi kênh. Để Đón Xem Những Video Hữu Ích Khác.")
        ctk.CTkEntry(cta_row, textvariable=self.outro_cta_text, fg_color=PANEL, border_color=BORDER).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            export_inner,
            text="Tự động thêm làm câu CUỐI CÙNG sau khi dịch, trước khi lồng tiếng - để trống để KHÔNG chèn gì. "
                 "Nếu audio dài hơn video gốc (thường do câu này), đuôi video sẽ tự kéo dài (giữ khung hình cuối) "
                 "thay vì bị cắt mất - xem 'Kéo dài đuôi video' bên dưới.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(2, 0))

        # Intro Hook: AI tu chon 1 doan gay can/twist nhat trong video, cat ra dat len
        # DAU video lam intro mo man - video CHINH van phat DAY DU tu dau nhu binh
        # thuong (khong cat bo doan da dung lam intro). Dung chung Gemini API key da
        # dan o phan tren, khong can cau hinh them.
        self.add_hook_intro = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            export_inner, text="🎬 Tự động thêm Intro Hook (AI cắt đoạn gây cấn nhất đặt lên đầu video)",
            variable=self.add_hook_intro, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(14, 0))
        ctk.CTkLabel(
            export_inner,
            text="AI tự đọc toàn bộ phụ đề đã dịch, chọn đoạn kịch tính/bất ngờ nhất, cắt đặt lên đầu video kèm "
                 "1 câu hook giật tít riêng (kiểu phim mở đầu bằng cảnh cao trào). Video chính vẫn phát ĐẦY ĐỦ từ "
                 "đầu như bình thường (không cắt bỏ đoạn đã dùng làm intro). Cần Gemini API key.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(2, 0))

    def _on_toggle_input_srt(self):
        enabled = self.use_input_srt.get()
        self.input_srt_button.configure(state="normal" if enabled else "disabled")
        # Khi dùng srt có sẵn, các ô Source language / Translation method / Gemini key
        # không còn tác dụng (không tách thoại, không dịch) - làm mờ đi để tránh hiểu nhầm.
        state = "disabled" if enabled else "normal"
        for attr in ("_source_lang_combo", "_method_combo"):
            widget = getattr(self, attr, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except Exception:
                    pass
        # "Dùng file .srt có sẵn" và "Video không có lời thoại - AI viết kịch bản" là
        # 2 cách khác nhau để BỎ QUA transcribe+translate - không dùng cùng lúc được,
        # tự tắt cái kia nếu người dùng bật nhầm cả 2 (ưu tiên cái vừa bấm).
        if enabled and getattr(self, "silent_video_ai_script", None) is not None and self.silent_video_ai_script.get():
            self.silent_video_ai_script.set(False)
            self._on_toggle_silent_video_script()

    def _on_toggle_silent_video_script(self):
        enabled = self.silent_video_ai_script.get()
        self.silent_video_style_combo.configure(state="normal" if enabled else "disabled")
        # Bật chế độ này thì Tách thoại/Dịch không còn ý nghĩa (bỏ qua hẳn) - làm mờ
        # các ô liên quan để tránh hiểu nhầm, giống hệt cách "Dùng file .srt có sẵn" đang làm.
        state = "disabled" if enabled else "normal"
        for attr in ("_source_lang_combo", "_method_combo"):
            widget = getattr(self, attr, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except Exception:
                    pass
        if enabled and getattr(self, "use_input_srt", None) is not None and self.use_input_srt.get():
            self.use_input_srt.set(False)
            self._on_toggle_input_srt()

    def _choose_input_srt(self):
        path = filedialog.askopenfilename(
            title="Chọn file phụ đề .srt có sẵn",
            filetypes=[("SubRip subtitle", "*.srt"), ("All files", "*.*")],
        )
        if path:
            self.input_srt_path = path
            self.input_srt_label.configure(text=os.path.basename(path), text_color="white")
            self.log(f"Đã chọn file .srt có sẵn: {path}")

    def _choose_gemini_web2api_cookie_file(self):
        path = filedialog.askopenfilename(
            title="Chọn cookie.txt của Gemini Web2API (không bắt buộc với Flash)",
            filetypes=[("Cookie text/JSON", "*.txt *.json"), ("All files", "*.*")],
        )
        if path:
            self.gemini_web2api_cookie_file.set(path)

    # ---------- Gemini Web2API: kiểm tra kết nối / tự khởi động cùng app ----------
    def _test_gemini_fastapi(self):
        """Nút '🔎 Test Gemini': kiểm tra /health rồi thử gọi thật 1 lượt
        /v1/chat/completions, chạy trong thread riêng để không đứng UI."""
        base_url = (self.gemini_fastapi_base_url.get() or "").strip()
        if not base_url:
            messagebox.showwarning("Thiếu Base URL", "Điền Base URL của Gemini Web2API trước, vd http://127.0.0.1:8000")
            return
        api_key = self.gemini_fastapi_api_key.get().strip() or None
        model = self.gemini_fastapi_model.get().strip() or "gemini-3.6-flash"
        self.gemini_fastapi_status_label.configure(text="Đang kiểm tra...", text_color=TEXT_MUTED)
        threading.Thread(target=self._test_gemini_fastapi_thread, args=(base_url, api_key, model), daemon=True).start()

    def _test_gemini_fastapi_thread(self, base_url: str, api_key: Optional[str], model: str):
        ok_health, msg_health = gfa_check_server_health(base_url)
        if not ok_health:
            # "timeout" (khác với "CHƯA CHẠY") nghĩa là có thứ gì đó đang lắng nghe ở
            # base_url nhưng KHÔNG PHẢN HỒI KỊP - tức tiến trình server rất có thể đang
            # bị TREO HOÀN TOÀN (đứng hình), không phải chỉ chưa mở. Nếu server này là do
            # chính app tự khởi động (self._gfa_process còn sống theo góc nhìn OS), thử
            # buộc khởi động lại cứng 1 lần thay vì bắt người dùng tự tắt task/mở lại app.
            if "timeout" in msg_health.lower() and self._gfa_process is not None and self._gfa_process.is_alive:
                self.after(0, self.log, f"[Gemini Web2API] ⚠ {msg_health}")
                restarted = self._gfa_process.restart(
                    log_cb=lambda m: self.after(0, self.log, f"[Gemini Web2API] {m}")
                )
                if restarted:
                    self._gfa_process.wait_until_ready(
                        base_url, log_cb=lambda m: self.after(0, self.log, f"[Gemini Web2API] {m}")
                    )
                    ok_health, msg_health = gfa_check_server_health(base_url)
            if not ok_health:
                self.after(0, self._on_gemini_fastapi_test_result, False, msg_health)
                return
        ok_chat, msg_chat = gfa_test_chat_completion(base_url, api_key=api_key, model=model)
        final_msg = msg_health + "\n" + msg_chat
        self.after(0, self._on_gemini_fastapi_test_result, ok_chat, final_msg)

    def _on_gemini_fastapi_test_result(self, ok: bool, msg: str):
        self.gemini_fastapi_status_label.configure(text=msg, text_color=(GREEN if ok else "#e74c3c"))
        self.log(f"[Gemini Web2API] {msg}")

    # ---------- CLIProxyAPI: kiểm tra kết nối (TÁCH BIỆT hoàn toàn với Gemini
    # Web2API ở trên - app này KHÔNG tự khởi động CLIProxyAPI, bạn tự chạy server
    # riêng rồi bấm nút test). ----------
    def _test_cliproxy(self):
        """Nút '🔎 Test CLIProxyAPI': GET /v1/models rồi thử gọi thật 1 lượt
        /v1/chat/completions với model đã chọn, chạy trong thread riêng để không
        đứng UI."""
        base_url = (self.cliproxy_base_url.get() or "").strip()
        if not base_url:
            messagebox.showwarning("Thiếu Base URL", "Điền Base URL của CLIProxyAPI trước, vd http://127.0.0.1:8317")
            return
        api_key = self.cliproxy_api_key.get().strip() or None
        model = self.cliproxy_model.get().strip() or DEFAULT_CLIPROXY_MODEL
        self.cliproxy_status_label.configure(text="Đang kiểm tra...", text_color=TEXT_MUTED)
        threading.Thread(target=self._test_cliproxy_thread, args=(base_url, api_key, model), daemon=True).start()

    def _test_cliproxy_thread(self, base_url: str, api_key: Optional[str], model: str):
        ok_health, msg_health = cliproxy_check_health(base_url, api_key=api_key)
        if not ok_health:
            self.after(0, self._on_cliproxy_test_result, False, msg_health)
            return
        ok_chat, msg_chat = cliproxy_test_chat_completion(base_url, api_key=api_key, model=model)
        final_msg = msg_health + "\n" + msg_chat
        self.after(0, self._on_cliproxy_test_result, ok_chat, final_msg)

    def _on_cliproxy_test_result(self, ok: bool, msg: str):
        self.cliproxy_status_label.configure(text=msg, text_color=(GREEN if ok else "#e74c3c"))
        self.log(f"[CLIProxyAPI] {msg}")

    def _get_gemini_api_keys(self) -> list:
        """Đọc ô dán nhiều key (mỗi dòng 1 key, dòng trống/khoảng trắng bị bỏ qua)."""
        raw = self.gemini_api_keys_box.get("1.0", "end")
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _test_gemini_api(self):
        """Nút '🔎 Test Gemini API': gọi thật 1 lượt bằng KEY ĐẦU TIÊN dán vào, chạy
        trong thread riêng để không đứng UI. Chỉ test 1 key (không xoay vòng cả danh
        sách) - đủ để biết định dạng/model đúng, mỗi key còn lại tự biết lỗi lúc dịch
        thật qua log '⚠ Gemini key #N ...' nếu key đó có vấn đề."""
        keys = self._get_gemini_api_keys()
        if not keys:
            messagebox.showwarning("Thiếu API key", "Dán ít nhất 1 Gemini API key (mỗi dòng 1 key, lấy tại https://aistudio.google.com/apikey).")
            return
        model = self.gemini_api_model.get().strip() or "gemini-3.6-flash"
        self.gemini_api_status_label.configure(text=f"Đang kiểm tra (tổng {len(keys)} key đã dán)...", text_color=TEXT_MUTED)
        threading.Thread(target=self._test_gemini_api_thread, args=(keys, model), daemon=True).start()

    def _test_gemini_api_thread(self, keys: list, model: str):
        try:
            from google import genai
        except ImportError:
            self.after(
                0, self._on_gemini_api_test_result, False,
                "✗ Chưa cài 'google-genai'. Chạy: pip install google-genai",
            )
            return
        try:
            client = genai.Client(api_key=keys[0])
            resp = client.models.generate_content(model=model, contents="Trả lời đúng 2 chữ: OK")
            text = (resp.text or "").strip()
            self.after(
                0, self._on_gemini_api_test_result, True,
                f"✓ Gọi Gemini API thành công bằng key #1/{len(keys)} (model {model}): {text}",
            )
        except Exception as e:
            self.after(
                0, self._on_gemini_api_test_result, False,
                f"✗ Key #1 lỗi: {e}\n(Còn {len(keys) - 1} key khác chưa test - lúc dịch thật app sẽ tự xoay qua key đó nếu key #1 hỏng.)"
                if len(keys) > 1 else f"✗ Gọi Gemini API thất bại: {e}",
            )

    def _on_gemini_api_test_result(self, ok: bool, msg: str):
        self.gemini_api_status_label.configure(text=msg, text_color=(GREEN if ok else "#e74c3c"))
        self.log(f"[Gemini API] {msg}")

    def _maybe_autostart_gemini_fastapi(self):
        """Gọi khi app vừa mở (self.after) - nếu checkbox 'Tự khởi động' đang bật VÀ có
        bundle sẵn thư mục gemini_web2api_server/, tự chạy server nền trong ứng dụng, rồi
        cập nhật label trạng thái khi biết kết quả. Không chặn UI, không báo lỗi ồn ào
        nếu thất bại (chỉ log) - vì đây là tiện ích tự động, người dùng vẫn có thể tự
        chạy server tay + bấm 'Test Gemini' bất kỳ lúc nào."""
        if not getattr(self, "gemini_fastapi_auto_start", None) or not self.gemini_fastapi_auto_start.get():
            return
        if gfa_get_bundled_server_dir() is None:
            return
        base_url = (self.gemini_fastapi_base_url.get() or GFA_DEFAULT_BASE_URL).strip()
        self._gfa_process = GeminiFastAPIProcess()
        threading.Thread(target=self._autostart_gemini_fastapi_thread, args=(base_url,), daemon=True).start()

    def _autostart_gemini_fastapi_thread(self, base_url: str):
        ok_already, _ = _gfa_check_server_health_once(base_url, timeout=2.0)
        if ok_already:
            self.after(0, self._on_gemini_fastapi_test_result, True, "✓ Gemini Web2API đã đang chạy sẵn, dùng luôn.")
            return
        started = self._gfa_process.start(
            api_key=(self.gemini_fastapi_api_key.get().strip() or None),
            cookie_file=(self.gemini_web2api_cookie_file.get().strip() or None),
            proxy=(self.gemini_web2api_proxy.get().strip() or None),
            base_url=base_url,
            log_cb=lambda m: self.after(0, self.log, f"[Gemini Web2API] {m}"),
        )
        if not started:
            self.after(
                0, self._on_gemini_fastapi_test_result, False,
                "✗ Không khởi động được Gemini Web2API. Xem nhật ký; có thể cổng đang bị server cũ chiếm.",
            )
            return
        ready = self._gfa_process.wait_until_ready(
            base_url, log_cb=lambda m: self.after(0, self.log, f"[Gemini Web2API] {m}"),
        )
        if ready:
            ok, msg = gfa_check_server_health(base_url)
            self.after(0, self._on_gemini_fastapi_test_result, ok, msg)

    def _collect_style_dial(self) -> dict:
        """Đọc 5 ô Narrative Style/Audience/Speaking Speed/Creativity/Hook Level trên
        GUI (đang lưu label tiếng Việt) -> map sang giá trị code (vd "documentary"),
        "Tự động" -> None (không ép hướng nào). Dùng chung cho cả start_pipeline() và
        export_srt_only()."""
        maps = getattr(self, "_style_dial_maps", {})
        out = {}
        for field, var_name in (
            ("narrative_style", "narrative_style_display"),
            ("audience", "audience_display"),
            ("speaking_speed", "speaking_speed_display"),
            ("creativity", "creativity_display"),
            ("hook_level", "hook_level_display"),
        ):
            var = getattr(self, var_name, None)
            table = maps.get(field, {})
            label = var.get() if var else "Tự động"
            value = table.get(label, "auto")
            out[field] = None if value == "auto" else value
        return out

    def export_srt_only(self):
        """Chỉ chạy Tách thoại (Whisper) + Dịch (BỎ QUA voice/export video), rồi cho tải
        file .srt kết quả về máy để người dùng tự chỉnh sửa tay trước khi nạp lại."""
        if not getattr(self, "_video_full_path", None):
            messagebox.showwarning("Thiếu video", "Vui lòng chọn video đầu vào trước.")
            return
        if self.method.get() == "gemini_fastapi":
            gfa_base_url = (self.gemini_fastapi_base_url.get() or "").strip()
            if not gfa_base_url:
                messagebox.showwarning(
                    "Thiếu Base URL",
                    "Translation method = gemini_fastapi cần điền Base URL (vd http://127.0.0.1:8000).",
                )
                return
            ok, msg = gfa_check_server_health(gfa_base_url)
            if not ok:
                messagebox.showerror(
                    "Gemini Web2API chưa sẵn sàng",
                    f"{msg}\n\nBấm '🔎 Test Gemini' để kiểm tra lại, hoặc bật 'Tự khởi động Gemini Web2API cùng app'.",
                )
                return

        if self.method.get() == "gemini" and not self._get_gemini_api_keys():
            messagebox.showwarning(
                "Thiếu API key",
                "Translation method = gemini cần dán ít nhất 1 Gemini API key (lấy tại https://aistudio.google.com/apikey).",
            )
            return

        if self.method.get() == "cliproxy":
            cp_base_url = (self.cliproxy_base_url.get() or "").strip()
            if not cp_base_url:
                messagebox.showwarning(
                    "Thiếu Base URL",
                    "Translation method = cliproxy cần điền Base URL (vd http://127.0.0.1:8317).",
                )
                return
            ok, msg = cliproxy_check_health(cp_base_url, api_key=self.cliproxy_api_key.get().strip() or None)
            if not ok:
                messagebox.showerror(
                    "CLIProxyAPI chưa sẵn sàng",
                    f"{msg}\n\nBấm '🔎 Test CLIProxyAPI' để kiểm tra lại - nhớ tự khởi động server CLIProxyAPI trước.",
                )
                return

        self.export_srt_btn.configure(state="disabled", text="Đang dịch...")
        self.log("Bắt đầu Tách thoại + Dịch (chỉ xuất .srt, chưa lồng tiếng/xuất video)...")

        thread = threading.Thread(
            target=self._export_srt_thread,
            args=(
                self._video_full_path, self.source_lang.get(), self.target_lang.get(),
                self.method.get(), self.whisper_model.get(), None,
                [],
            ),
            kwargs=dict(
                gemini_api_keys=self._get_gemini_api_keys(),
                gemini_model=self.gemini_api_model.get().strip() or "gemini-3.6-flash",
                gemini_fastapi_base_url=self.gemini_fastapi_base_url.get().strip() or None,
                gemini_fastapi_api_key=self.gemini_fastapi_api_key.get().strip() or None,
                gemini_fastapi_model=self.gemini_fastapi_model.get().strip() or "gemini-3.6-flash",
                cliproxy_base_url=self.cliproxy_base_url.get().strip() or None,
                cliproxy_api_key=self.cliproxy_api_key.get().strip() or None,
                cliproxy_model=self.cliproxy_model.get().strip() or DEFAULT_CLIPROXY_MODEL,
                rewrite_after_translate=self.rewrite_after_translate.get(),
                rewrite_keep_ratio=self.rewrite_keep_ratio.get(),
                **self._collect_style_dial(),
            ),
            daemon=True,
        )
        thread.start()

    def _export_srt_thread(
        self, video_path, source_lang, target_lang, method, whisper_model, gemini_api_key, grok_api_keys=None,
        gemini_api_keys=None, gemini_model=None,
        gemini_fastapi_base_url=None, gemini_fastapi_api_key=None, gemini_fastapi_model=None,
        cliproxy_base_url=None, cliproxy_api_key=None, cliproxy_model=None,
        rewrite_after_translate=False, rewrite_keep_ratio=0.4,
        narrative_style=None, audience=None, speaking_speed=None, creativity=None, hook_level=None,
    ):
        try:
            from core.transcribe import transcribe_video, save_srt
            from core.translate import translate_segments
            from core.narration_merge import merge_segments_for_narration
            from core.text_fit import fit_segments_to_timing, split_segments_for_display

            def progress_cb(pct, msg):
                self.after(0, self.log, f"[SRT] {int(pct * 100)}% - {msg}")

            segments = transcribe_video(
                video_path, model_size=whisper_model, device="auto", progress_cb=progress_cb,
            )

            # Ghép nhịp lời dẫn TRƯỚC KHI DỊCH (cùng fix áp dụng cho pipeline lồng tiếng):
            # cue gốc là điểm cắt theo VAD (quãng lặng micro), KHÔNG phải ranh giới câu -
            # ghép các cue liên tục thành khối đọc trọn ý TRƯỚC khi đưa cho Gemini dịch,
            # để model nhận đúng khung giờ THẬT thay vì khung giờ vụn theo từng cue.
            progress_cb(0.0, "Đang ghép nhịp lời dẫn (trước khi dịch)...")
            segments = merge_segments_for_narration(segments, progress_cb=progress_cb)

            speech_rate = f"{self.speech_rate_pct.get():+d}%"

            translated = translate_segments(
                segments, source_lang, target_lang, method=method,
                progress_cb=progress_cb, gemini_api_key=gemini_api_key,
                gemini_api_keys=gemini_api_keys or [], gemini_model=gemini_model or "gemini-3.6-flash",
                grok_api_keys=grok_api_keys or [],
                gemini_fastapi_base_url=gemini_fastapi_base_url,
                gemini_fastapi_api_key=gemini_fastapi_api_key,
                gemini_fastapi_model=gemini_fastapi_model or "gemini-3.6-flash",
                cliproxy_base_url=cliproxy_base_url,
                cliproxy_api_key=cliproxy_api_key,
                cliproxy_model=cliproxy_model or DEFAULT_CLIPROXY_MODEL,
                narrative_style=narrative_style, audience=audience, speaking_speed=speaking_speed,
                creativity=creativity, hook_level=hook_level,
            )

            # ---- Viết lại/biến tấu THÊM 1 lượt trên chính bản dịch (né trùng lặp nội
            # dung), rồi canh lại timing THEO ĐỘ DÀI VĂN BẢN MỚI - xem core/rewrite_srt.py.
            # Chỉ chạy khi người dùng bật checkbox tương ứng trên UI, và CHỈ hợp lý khi
            # method dịch có dùng Gemini Web2API (base_url) - vì bước này gọi thẳng cùng
            # server đó để viết lại, không hỗ trợ các method dịch khác (online/offline/grok).
            if rewrite_after_translate:
                from core.rewrite_srt import retime_segments
                if gemini_api_keys:
                    # Ưu tiên gọi THẲNG Gemini API bằng API key thật (không cần chạy
                    # Gemini Web2API) - dùng lại đúng key/model đã cấu hình cho bước dịch.
                    from core.rewrite_srt import rewrite_segments_gemini_api
                    progress_cb(0.0, "Đang viết lại/biến tấu thêm nội dung sau khi dịch (Gemini API)...")
                    translated = rewrite_segments_gemini_api(
                        translated, target_lang, api_keys=gemini_api_keys,
                        model=gemini_model or "gemini-3.6-flash",
                        keep_ratio=rewrite_keep_ratio, progress_cb=progress_cb,
                    )
                    progress_cb(0.0, "Đang canh lại timing theo văn bản mới...")
                    translated = retime_segments(
                        translated, target_lang, speech_rate=speech_rate,
                        min_gap_sec=0.12, max_gap_sec=1.2, keep_original_start=True,
                    )
                elif gemini_fastapi_base_url:
                    from core.rewrite_srt import rewrite_segments_gemini_fastapi
                    progress_cb(0.0, "Đang viết lại/biến tấu thêm nội dung sau khi dịch (Gemini Web2API)...")
                    translated = rewrite_segments_gemini_fastapi(
                        translated, target_lang, base_url=gemini_fastapi_base_url,
                        api_key=gemini_fastapi_api_key, model=gemini_fastapi_model or "gemini-3.6-flash",
                        keep_ratio=rewrite_keep_ratio, progress_cb=progress_cb,
                    )
                    progress_cb(0.0, "Đang canh lại timing theo văn bản mới...")
                    translated = retime_segments(
                        translated, target_lang, speech_rate=speech_rate,
                        min_gap_sec=0.12, max_gap_sec=1.2, keep_original_start=True,
                    )
                else:
                    progress_cb(0.0, "⚠ Bỏ qua bước viết lại/biến tấu: cần ít nhất 1 Gemini API key (hoặc Translation method = gemini_fastapi) để dùng bước này.")

            # Rút gọn/viết lại câu nào VẪN còn dài hơn khung giờ gốc sau khi dịch - ưu
            # tiên dùng ĐÚNG phương thức Gemini Web2API đang cấu hình cho bước dịch ở
            # trên để viết lại có nghĩa (không cắt cụt cơ học), tự rơi về rule-based
            # cho từng câu lỗi nếu không gọi được.
            llm_shorten_fn = None
            if gemini_api_keys:
                try:
                    from core.llm_shorten import make_gemini_api_shorten_fn
                    llm_shorten_fn = make_gemini_api_shorten_fn(
                        api_keys=gemini_api_keys, model=gemini_model or "gemini-3.6-flash",
                    )
                except Exception as e:
                    progress_cb(0.0, f"⚠ Không dùng được Gemini API để viết lại câu ({e}) - dùng rule-based")
            elif gemini_fastapi_base_url:
                try:
                    from core.llm_shorten import make_gemini_fastapi_shorten_fn
                    llm_shorten_fn = make_gemini_fastapi_shorten_fn(
                        base_url=gemini_fastapi_base_url, api_key=gemini_fastapi_api_key,
                        model=gemini_fastapi_model or "gemini-3.6-flash",
                    )
                except Exception as e:
                    progress_cb(0.0, f"⚠ Không dùng được Gemini Web2API để viết lại câu ({e}) - dùng rule-based")

            progress_cb(0.0, "Đang khớp thời lượng câu dịch...")
            translated = fit_segments_to_timing(
                translated, target_lang,
                tolerance=self.fit_text_tolerance.get(),
                speech_rate=speech_rate,
                llm_shorten_fn=llm_shorten_fn,
                progress_cb=progress_cb,
            )

            # Tách hiển thị: câu dài chia thành nhiều dòng hiện lần lượt đúng khung giờ,
            # 1 dòng = 1 câu, không cắt cụt giữa câu (core/text_fit.py:split_segments_for_display).
            if self.split_long_subtitles.get():
                translated = split_segments_for_display(
                    translated, target_lang,
                    max_chars=int(self.max_subtitle_chars.get()),
                    speech_rate=speech_rate,
                )

            os.makedirs(self.work_dir, exist_ok=True)
            srt_path = save_srt(translated, os.path.join(self.work_dir, "translated_export.srt"))
            self.after(0, self._on_srt_export_done, srt_path)
        except Exception as e:
            self.after(0, self._on_srt_export_error, str(e))

    def _on_srt_export_done(self, srt_path: str):
        self.export_srt_btn.configure(state="normal", text="📝 Dịch & Tải file SRT")
        self.log(f"✅ Đã dịch xong, phụ đề tạm: {srt_path}")

        default_name = os.path.splitext(os.path.basename(self._video_full_path))[0] + "_translated.srt"
        save_path = filedialog.asksaveasfilename(
            title="Lưu file .srt về máy",
            defaultextension=".srt",
            initialfile=default_name,
            filetypes=[("SubRip subtitle", "*.srt"), ("All files", "*.*")],
        )
        if not save_path:
            self.log("Đã huỷ lưu file .srt (file tạm vẫn còn ở work_dir nếu cần).")
            return

        import shutil
        try:
            shutil.copyfile(srt_path, save_path)
            self.log(f"✅ Đã lưu file .srt về máy: {save_path}")
            messagebox.showinfo(
                "Hoàn tất",
                f"Đã lưu file .srt về:\n{save_path}\n\n"
                "Chỉnh sửa xong, quay lại bật 'Dùng file .srt có sẵn' và chọn đúng file này để nạp lại.",
            )
        except OSError as e:
            messagebox.showerror("Lỗi lưu file", f"Không lưu được file .srt: {e}")

    def _on_srt_export_error(self, err: str):
        self.export_srt_btn.configure(state="normal", text="📝 Dịch & Tải file SRT")
        self.log(f"❌ LỖI khi dịch xuất .srt: {err}")
        messagebox.showerror("Lỗi", err)

    def _build_config_panel(self, parent):
        self._build_srt_loader_section(parent)

        ctk.CTkLabel(parent, text="TRANSLATION CONFIG", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(16, 8))

        self.translation_grid_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.translation_grid_frame.pack(fill="x", padx=18)
        grid = self.translation_grid_frame

        self.source_lang = ctk.StringVar(value="Chinese")
        self.target_lang = ctk.StringVar(value="Vietnamese")
        self.method = ctk.StringVar(value="gemini")  # ĐỔI mặc định: dùng thẳng Gemini API key, không cần Gemini Web2API nữa

        self._labeled_combo(grid, "Source language", self.source_lang, LANGS, 0, 0)
        self._labeled_combo(grid, "Target language", self.target_lang, LANGS, 0, 1)
        self._labeled_combo(grid, "Translation method", self.method, ["online", "offline", "gemini_fastapi", "gemini", "cliproxy"], 1, 0)

        self.whisper_model = ctk.StringVar(value="small")
        self._labeled_combo(grid, "Whisper model", self.whisper_model,
                             ["tiny", "base", "small", "medium", "large-v3"], 1, 1)

        # ---- Gemini Web2API: server local bọc Gemini web (không cần API key trả phí
        # của Google), chỉ cần khi Translation method = gemini_fastapi. Bundle sẵn tại
        # thư mục gemini_web2api_server/ đi kèm app - có thể tự khởi động cùng lúc mở
        # app (xem _maybe_autostart_gemini_fastapi) hoặc bạn tự chạy server riêng rồi
        # điền đúng Base URL vào đây. ----
        gfa_row = ctk.CTkFrame(grid, fg_color="transparent")
        gfa_row.grid(row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(
            gfa_row, text="Gemini Web2API (server local OpenAI-compatible; Flash chạy không cần cookie) — Translation method = gemini_fastapi",
            font=(FONT_FAMILY, 11), text_color=TEXT_MUTED,
        ).pack(anchor="w")

        gfa_fields_row = ctk.CTkFrame(gfa_row, fg_color="transparent")
        gfa_fields_row.pack(fill="x", pady=(4, 0))
        gfa_fields_row.grid_columnconfigure(0, weight=2)
        gfa_fields_row.grid_columnconfigure(1, weight=1)
        gfa_fields_row.grid_columnconfigure(2, weight=1)

        base_url_col = ctk.CTkFrame(gfa_fields_row, fg_color="transparent")
        base_url_col.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(base_url_col, text="Base URL", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        self.gemini_fastapi_base_url = ctk.StringVar(value=GFA_DEFAULT_BASE_URL)
        ctk.CTkEntry(base_url_col, textvariable=self.gemini_fastapi_base_url, fg_color=PANEL2, border_color=BORDER).pack(fill="x")

        api_key_col = ctk.CTkFrame(gfa_fields_row, fg_color="transparent")
        api_key_col.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(api_key_col, text="API Key local (tuỳ chọn)", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        self.gemini_fastapi_api_key = ctk.StringVar(value="")
        ctk.CTkEntry(api_key_col, textvariable=self.gemini_fastapi_api_key, fg_color=PANEL2, border_color=BORDER, show="•").pack(fill="x")

        model_col = ctk.CTkFrame(gfa_fields_row, fg_color="transparent")
        model_col.grid(row=0, column=2, sticky="ew")
        ctk.CTkLabel(model_col, text="Model Web2API", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        self.gemini_fastapi_model = ctk.StringVar(value="gemini-3.6-flash")
        ctk.CTkComboBox(
            model_col, variable=self.gemini_fastapi_model,
            values=["gemini-3.6-flash", "gemini-3.5-flash-thinking", "gemini-3.1-pro", "gemini-auto", "gemini-flash-lite"],
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
        ).pack(fill="x")

        web2api_auth_row = ctk.CTkFrame(gfa_row, fg_color="transparent")
        web2api_auth_row.pack(fill="x", pady=(6, 0))
        web2api_auth_row.grid_columnconfigure(0, weight=3)
        web2api_auth_row.grid_columnconfigure(1, weight=2)

        cookie_col = ctk.CTkFrame(web2api_auth_row, fg_color="transparent")
        cookie_col.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(cookie_col, text="Cookie file (tuỳ chọn)", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        cookie_entry_row = ctk.CTkFrame(cookie_col, fg_color="transparent")
        cookie_entry_row.pack(fill="x")
        # Mặc định ĐỂ TRỐNG - người dùng mới cài app không có cookie nào.
        # Flash ẩn danh vẫn chạy được, không cần cookie.
        self.gemini_web2api_cookie_file = ctk.StringVar(value="")
        ctk.CTkEntry(
            cookie_entry_row, textvariable=self.gemini_web2api_cookie_file,
            placeholder_text="Để trống = dùng Flash ẩn danh",
            fg_color=PANEL2, border_color=BORDER,
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(cookie_entry_row, text="Chọn", width=62, fg_color=PANEL2, hover_color=BORDER, command=self._choose_gemini_web2api_cookie_file).pack(side="left", padx=(6, 0))

        proxy_col = ctk.CTkFrame(web2api_auth_row, fg_color="transparent")
        proxy_col.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(proxy_col, text="Proxy Web2API (tuỳ chọn)", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        self.gemini_web2api_proxy = ctk.StringVar(value="")
        ctk.CTkEntry(proxy_col, textvariable=self.gemini_web2api_proxy, fg_color=PANEL2, border_color=BORDER).pack(fill="x")

        gfa_action_row = ctk.CTkFrame(gfa_row, fg_color="transparent")
        gfa_action_row.pack(fill="x", pady=(6, 0))
        self.gemini_fastapi_auto_start = ctk.BooleanVar(value=gfa_get_bundled_server_dir() is not None)
        ctk.CTkCheckBox(
            gfa_action_row, text="Tự khởi động Gemini Web2API cùng app", variable=self.gemini_fastapi_auto_start,
            font=(FONT_FAMILY, 11), text_color=TEXT_MUTED,
        ).pack(side="left")
        ctk.CTkButton(
            gfa_action_row, text="🔎 Test Gemini", width=130, fg_color=PANEL2, hover_color=BORDER,
            command=self._test_gemini_fastapi,
        ).pack(side="left", padx=(12, 0))

        self.gemini_fastapi_status_label = ctk.CTkLabel(
            gfa_row, text="Chưa kiểm tra kết nối.", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=560,
        )
        self.gemini_fastapi_status_label.pack(anchor="w", pady=(4, 0))

        # ---- Gemini API CHÍNH THỨC (Google, trả phí/có hạn mức miễn phí riêng) - chỉ
        # dùng khi Translation method = gemini. KHÔNG phụ thuộc cookie/Web2API - gọi
        # thẳng https://aistudio.google.com bằng API key thật. Dán NHIỀU key (mỗi dòng
        # 1 key) để app tự XOAY VÒNG khi 1 key hết quota miễn phí trong ngày - xem
        # core/translate.py:translate_segments_gemini. ----
        gapi_row = ctk.CTkFrame(grid, fg_color="transparent")
        gapi_row.grid(row=6, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(
            gapi_row, text="Gemini API chính thức (aistudio.google.com) — Translation method = gemini — dán NHIỀU key (mỗi dòng 1 key) để xoay vòng khi hết quota",
            font=(FONT_FAMILY, 11), text_color=TEXT_MUTED,
        ).pack(anchor="w")
        self.gemini_api_keys_box = ctk.CTkTextbox(gapi_row, height=70, font=(FONT_FAMILY, 11))
        self.gemini_api_keys_box.pack(fill="x", pady=(4, 0))
        gapi_model_row = ctk.CTkFrame(gapi_row, fg_color="transparent")
        gapi_model_row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(gapi_model_row, text="Model", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(side="left")
        self.gemini_api_model = ctk.CTkOptionMenu(
            gapi_model_row, values=["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-pro"],
            fg_color=PANEL2, button_color=BORDER, width=200,
        )
        self.gemini_api_model.set("gemini-3.6-flash")
        self.gemini_api_model.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            gapi_model_row, text="🔎 Test Gemini API", width=140, fg_color=PANEL2, hover_color=BORDER,
            command=self._test_gemini_api,
        ).pack(side="left", padx=(12, 0))
        self.gemini_api_status_label = ctk.CTkLabel(
            gapi_row, text="Chưa kiểm tra kết nối.", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=560,
        )
        self.gemini_api_status_label.pack(anchor="w", pady=(4, 0))

        # ---- CLIProxyAPI (https://github.com/router-for-me/CLIProxyAPI) - server local
        # (Go) bọc CLI OAuth (mặc định ở đây: Codex/ChatGPT) thành API tương thích
        # OpenAI, chỉ dùng khi Translation method = cliproxy. TÁCH BIỆT hoàn toàn với
        # Gemini Web2API ở trên - xem core/translate.py: translate_segments_cliproxy /
        # check_cliproxy_health. Cần tự khởi động server CLIProxyAPI riêng (app này
        # KHÔNG tự động chạy kèm CLIProxyAPI). ----
        cliproxy_row = ctk.CTkFrame(grid, fg_color="transparent")
        cliproxy_row.grid(row=8, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(
            cliproxy_row,
            text="CLIProxyAPI (server local OpenAI-compatible, đăng nhập OAuth Codex/ChatGPT) — Translation method = cliproxy",
            font=(FONT_FAMILY, 11), text_color=TEXT_MUTED,
        ).pack(anchor="w")

        cliproxy_fields_row = ctk.CTkFrame(cliproxy_row, fg_color="transparent")
        cliproxy_fields_row.pack(fill="x", pady=(4, 0))
        cliproxy_fields_row.grid_columnconfigure(0, weight=2)
        cliproxy_fields_row.grid_columnconfigure(1, weight=1)
        cliproxy_fields_row.grid_columnconfigure(2, weight=1)

        cliproxy_base_url_col = ctk.CTkFrame(cliproxy_fields_row, fg_color="transparent")
        cliproxy_base_url_col.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(cliproxy_base_url_col, text="Base URL", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        self.cliproxy_base_url = ctk.StringVar(value=CLIPROXY_DEFAULT_BASE_URL)
        ctk.CTkEntry(cliproxy_base_url_col, textvariable=self.cliproxy_base_url, fg_color=PANEL2, border_color=BORDER).pack(fill="x")

        cliproxy_api_key_col = ctk.CTkFrame(cliproxy_fields_row, fg_color="transparent")
        cliproxy_api_key_col.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(cliproxy_api_key_col, text="API Key (tuỳ chọn)", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        self.cliproxy_api_key = ctk.StringVar(value="")
        ctk.CTkEntry(cliproxy_api_key_col, textvariable=self.cliproxy_api_key, fg_color=PANEL2, border_color=BORDER, show="•").pack(fill="x")

        cliproxy_model_col = ctk.CTkFrame(cliproxy_fields_row, fg_color="transparent")
        cliproxy_model_col.grid(row=0, column=2, sticky="ew")
        ctk.CTkLabel(cliproxy_model_col, text="Model", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
        self.cliproxy_model = ctk.StringVar(value=DEFAULT_CLIPROXY_MODEL)
        ctk.CTkComboBox(
            cliproxy_model_col, variable=self.cliproxy_model,
            values=["gpt-5-codex", "gpt-5.6", "gpt-5.5"],
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
        ).pack(fill="x")

        cliproxy_action_row = ctk.CTkFrame(cliproxy_row, fg_color="transparent")
        cliproxy_action_row.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(
            cliproxy_action_row, text="🔎 Test CLIProxyAPI", width=140, fg_color=PANEL2, hover_color=BORDER,
            command=self._test_cliproxy,
        ).pack(side="left")

        self.cliproxy_status_label = ctk.CTkLabel(
            cliproxy_row, text="Chưa kiểm tra kết nối.", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=560,
        )
        self.cliproxy_status_label.pack(anchor="w", pady=(4, 0))

        # ---- AI Script Rewriter: 5 "núm vặn" style (chỉ áp dụng khi Translation
        # method = gemini_fastapi - xem core/translate.py:_style_dial_block).
        # Mặc định "Tự động" = không ép hướng nào, giữ nguyên văn phong mặc định. ----
        style_row = ctk.CTkFrame(grid, fg_color="transparent")
        style_row.grid(row=7, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(
            style_row, text="AI Script Rewriter — style dịch (chỉ áp dụng khi dịch = gemini_fastapi)",
            font=(FONT_FAMILY, 11), text_color=TEXT_MUTED,
        ).pack(anchor="w")

        style_grid = ctk.CTkFrame(style_row, fg_color="transparent")
        style_grid.pack(fill="x", pady=(4, 0))
        for c in range(5):
            style_grid.grid_columnconfigure(c, weight=1)

        NARRATIVE_STYLE_LABELS = {
            "Tự động": "auto", "Phim tài liệu": "documentary", "Kể chuyện": "storytelling",
            "Giảng giải": "educational", "Vlog đời thường": "casual_vlog", "Bản tin tóm tắt": "news_recap",
        }
        AUDIENCE_LABELS = {
            "Tự động": "auto", "Người mới": "beginner", "Đại chúng": "general",
            "Người am hiểu": "expert", "Giới trẻ (Gen Z)": "gen_z",
        }
        SPEAKING_SPEED_LABELS = {"Tự động": "auto", "Chậm": "slow", "Vừa": "normal", "Nhanh": "fast"}
        CREATIVITY_LABELS = {"Tự động": "auto", "Thấp": "low", "Vừa": "medium", "Cao": "high"}
        HOOK_LEVEL_LABELS = {"Tự động": "auto", "Nhẹ": "low", "Vừa": "medium", "Mạnh": "high"}
        # Lưu lại để _collect_pipeline_style_dial() tra ngược label hiển thị -> giá trị code
        self._style_dial_maps = {
            "narrative_style": NARRATIVE_STYLE_LABELS, "audience": AUDIENCE_LABELS,
            "speaking_speed": SPEAKING_SPEED_LABELS, "creativity": CREATIVITY_LABELS,
            "hook_level": HOOK_LEVEL_LABELS,
        }

        def _style_combo(col: int, label: str, values: dict, default_key: str = "Tự động"):
            wrap = ctk.CTkFrame(style_grid, fg_color="transparent")
            wrap.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            ctk.CTkLabel(wrap, text=label, font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
            var = ctk.StringVar(value=default_key)
            ctk.CTkComboBox(
                wrap, values=list(values.keys()), variable=var,
                fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
            ).pack(fill="x")
            return var

        self.narrative_style_display = _style_combo(0, "Narrative Style", NARRATIVE_STYLE_LABELS)
        self.audience_display = _style_combo(1, "Audience", AUDIENCE_LABELS)
        self.speaking_speed_display = _style_combo(2, "Speaking Speed", SPEAKING_SPEED_LABELS)
        self.creativity_display = _style_combo(3, "Creativity", CREATIVITY_LABELS)
        self.hook_level_display = _style_combo(4, "Hook Level", HOOK_LEVEL_LABELS)

        # ---- Content Rewriter: phong cách/persona theo chủ đề (chỉ áp dụng khi
        # Translation method = gemini_fastapi - online/offline là dịch máy thuần
        # túy, không hỗ trợ viết lại theo văn phong) ----
        self.content_persona_display = ctk.StringVar(value="Tự động theo chủ đề")
        persona_row = ctk.CTkFrame(grid, fg_color="transparent")
        persona_row.grid(row=2, column=1, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(persona_row, text="Phong cách viết lại (chỉ áp dụng khi dịch = gemini_fastapi)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkComboBox(
            persona_row, values=list(CONTENT_PERSONA_LABELS.keys()), variable=self.content_persona_display,
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT, width=280,
        ).pack(fill="x", pady=(4, 0))

        self.tts_engine = ctk.StringVar(value="online")
        tts_combo_wrap = ctk.CTkFrame(grid, fg_color="transparent")
        tts_combo_wrap.grid(row=3, column=0, sticky="ew", padx=8, pady=8)
        grid.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tts_combo_wrap, text="Giọng đọc (TTS)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkComboBox(
            tts_combo_wrap, values=["online", "offline", "clone", "vieneu", "omnivoice"], variable=self.tts_engine,
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT, width=280,
            command=lambda _v=None: self._on_tts_engine_change(),
        ).pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(
            grid, text="online = edge-tts (hay hơn, cần mạng)\noffline = giọng máy (luôn chạy, không cần mạng)\n"
                       "clone = giọng riêng của bạn (XTTS-v2, xem tab Voice Studio)\n"
                       "vieneu = VieNeu-TTS (chạy local trên CPU, không cần mạng, chỉ tiếng Việt;\n"
                       "         'pip install vieneu'. Ô 'Giọng của bạn' bên dưới có thể để trống\n"
                       "         (giọng mặc định), điền tên voice profile (Voice Studio) để clone,\n"
                       "         hoặc điền ID giọng dựng sẵn của VieNeu-TTS)\n"
                       "omnivoice = OmniVoice (chạy local, 600+ ngôn ngữ, nên có GPU CUDA;\n"
                       "         'pip install torch torchaudio omnivoice'. Ô 'Giọng của bạn' bên\n"
                       "         dưới để CLONE giọng từ voice profile (Voice Studio); để trống thì\n"
                       "         dùng mô tả giọng ở khung 'OmniVoice · Voice Design' bên dưới)",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left"
        ).grid(row=3, column=1, sticky="w", padx=8, pady=8)

        # Chọn voice profile riêng (áp dụng khi tts_engine = clone / vieneu / omnivoice)
        # đặt NGAY DƯỚI ô chọn engine để nhóm các lựa chọn liên quan tới GIỌNG ĐỌC gần
        # nhau, dễ so sánh/chỉnh sửa cùng lúc thay vì rải rác như trước.
        clone_row = ctk.CTkFrame(parent, fg_color="transparent")
        clone_row.pack(fill="x", padx=18, pady=(0, 4))
        ctk.CTkLabel(clone_row, text="Giọng của bạn (voice profile)", text_color=TEXT_MUTED).pack(anchor="w")
        picker_row = ctk.CTkFrame(clone_row, fg_color="transparent")
        picker_row.pack(fill="x", pady=(4, 0))
        self.voice_profiles_dir = os.path.join(os.getcwd(), "voice_profiles")
        self.voice_name = ctk.StringVar(value="")
        self.voice_name_combo = ctk.CTkComboBox(
            picker_row, values=[], variable=self.voice_name,
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT, width=200,
        )
        self.voice_name_combo.pack(side="left")
        ctk.CTkButton(
            picker_row, text="🔄", width=36, command=self._refresh_voice_profiles,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            picker_row, text="📥 Giọng VieNeu-TTS", width=150,
            fg_color=PANEL2, hover_color=BORDER,
            command=self._reload_vieneu_voice_options,
        ).pack(side="left")
        self.clone_hint_label = ctk.CTkLabel(
            clone_row,
            text="Chưa có voice profile nào. Chạy 'python setup_voice_clone.py --source ... --name ...' trên máy bạn trước.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=620,
        )
        self.clone_hint_label.pack(anchor="w", pady=(4, 0))
        self._refresh_voice_profiles()

        # Chọn tay Nam/Nữ cho giọng đọc online (edge-tts) - dùng đúng 1 giọng cố định
        # cho cả video, hữu ích khi bạn tự xem trước và biết rõ nên chọn giọng nào hơn
        # để AI tự đoán (nhất là video review/thuyết minh nhiều nhân vật, cắt cảnh
        # nhanh, AI dễ nhận nhầm giọng). CHỈ áp dụng khi Giọng đọc (TTS) = online.
        self.voice_gender = ctk.StringVar(value="Nữ")
        gender_wrap = ctk.CTkFrame(parent, fg_color="transparent")
        gender_wrap.pack(fill="x", padx=18, pady=(0, 12))
        ctk.CTkLabel(gender_wrap, text="Giới tính giọng đọc NỀN (chỉ áp dụng khi Giọng đọc (TTS) = online, và cho câu KHÔNG nhận diện được nhân vật riêng)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkComboBox(
            gender_wrap, values=["Nữ", "Nam"], variable=self.voice_gender,
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT, width=280,
        ).pack(anchor="w", pady=(4, 0))

        # ---- Nhận diện nhân vật (DÙNG CHUNG cho mọi engine: online/vieneu/omnivoice) ----
        # Trước đây 2 checkbox này bị giấu bên trong khối "vieneu_gender_section" (chỉ
        # hiện khi Giọng đọc = vieneu), khiến người dùng KHÔNG BẬT ĐƯỢC khi đang dùng
        # Edge (online) - đây chính là lý do "chọn giọng riêng Nam/Nữ" tưởng như chỉ
        # VieNeu mới có. Đưa ra ngoài dùng chung cho tất cả engine.
        speaker_detect_wrap = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        speaker_detect_wrap.pack(fill="x", padx=18, pady=(0, 12))
        sd_inner = ctk.CTkFrame(speaker_detect_wrap, fg_color="transparent")
        sd_inner.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(
            sd_inner, text="Nhận diện nhân vật (video có 2 người thoại — vd 1 nhân vật chính + 1 người cầm máy)",
            font=(FONT_FAMILY, 12, "bold"), text_color="white",
        ).pack(anchor="w")
        ctk.CTkLabel(
            sd_inner,
            text="Bật 1 trong 2 cách bên dưới để tự động tách giọng đọc riêng theo từng nhân vật "
                 "(dùng ở phần 'Giọng lồng' bên dưới, theo đúng engine bạn chọn).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=560,
        ).pack(anchor="w", pady=(2, 8))

        self.detect_speaker_gender = ctk.BooleanVar(value=False)
        self.detect_speaker_by_face = ctk.BooleanVar(value=False)

        def _on_toggle_detect_pitch():
            # 2 co nay LOAI TRU NHAU o backend (bat ca 2 thi face duoc uu tien, pitch
            # bi bo qua hoan toan) - tick 1 cai thi tu bo tick cai kia cho ro rang,
            # tranh nguoi dung tuong ca 2 cung chay.
            if self.detect_speaker_gender.get():
                self.detect_speaker_by_face.set(False)

        def _on_toggle_detect_face():
            if self.detect_speaker_by_face.get():
                self.detect_speaker_gender.set(False)

        ctk.CTkCheckBox(
            sd_inner, text="🎙️ Theo cao độ giọng nói (nhẹ, nhanh, không cần xử lý hình ảnh)",
            variable=self.detect_speaker_gender, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=_on_toggle_detect_pitch,
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkCheckBox(
            sd_inner, text="🎥 Theo khuôn mặt/khẩu hình trong khung hình (chính xác hơn, phân biệt được từng "
                           "nhân vật cụ thể — cần pip install mediapipe opencv-python)",
            variable=self.detect_speaker_by_face, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=_on_toggle_detect_face,
        ).pack(anchor="w")

        # ---- Lồng tiếng · Giọng lồng · Edge (online) (chỉ hiện khi tts_engine="online") ----
        # Y HET pattern cua VieNeu ben duoi nhung cho Edge-tts: gan RIENG 1 giong Edge cu
        # the cho moi gioi tinh nhan vat, thay vi luon dung dung 1 cap co dinh cua
        # VOICE_MAP_BY_GENDER.
        self.edge_gender_section = ctk.CTkFrame(parent, fg_color="transparent")
        self.edge_gender_section.pack(fill="x", padx=0, pady=(4, 0))

        ctk.CTkLabel(
            self.edge_gender_section, text="LỒNG TIẾNG", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=18, pady=(16, 0))
        ctk.CTkLabel(
            self.edge_gender_section, text="Giọng lồng · Edge (online)",
            font=(FONT_FAMILY, 13, "bold"), text_color="white",
        ).pack(anchor="w", padx=18, pady=(0, 4))
        ctk.CTkLabel(
            self.edge_gender_section,
            text="Gán RIÊNG 1 giọng Edge cho mỗi giới tính nhân vật (thay vì cả video chỉ 1 giọng).\n"
                 "Cần bật 1 trong 2 ô nhận diện nhân vật ở trên, nếu không toàn bộ video vẫn đọc\n"
                 "bằng 1 giọng nền duy nhất theo 'Giới tính giọng đọc NỀN' ở trên.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 8))

        edge_voice_grid = ctk.CTkFrame(self.edge_gender_section, fg_color="transparent")
        edge_voice_grid.pack(fill="x", padx=18)
        edge_voice_grid.grid_columnconfigure(0, weight=1)
        edge_voice_grid.grid_columnconfigure(1, weight=1)

        self.edge_voice_male = ctk.StringVar(value="")
        edge_male_wrap = ctk.CTkFrame(edge_voice_grid, fg_color="transparent")
        edge_male_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(edge_male_wrap, text="Giọng Nam", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        self.edge_male_combo = ctk.CTkComboBox(
            edge_male_wrap, values=[], variable=self.edge_voice_male,
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
        )
        self.edge_male_combo.pack(fill="x", pady=(4, 0))

        self.edge_voice_female = ctk.StringVar(value="")
        edge_female_wrap = ctk.CTkFrame(edge_voice_grid, fg_color="transparent")
        edge_female_wrap.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ctk.CTkLabel(edge_female_wrap, text="Giọng Nữ", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        self.edge_female_combo = ctk.CTkComboBox(
            edge_female_wrap, values=[], variable=self.edge_voice_female,
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
        )
        self.edge_female_combo.pack(fill="x", pady=(4, 0))

        edge_reload_row = ctk.CTkFrame(self.edge_gender_section, fg_color="transparent")
        edge_reload_row.pack(fill="x", padx=18, pady=(8, 4))
        self.edge_voice_hint = ctk.CTkLabel(
            edge_reload_row,
            text="Để trống ô nào = giới tính đó dùng giọng mặc định của ngôn ngữ đang chọn.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=380,
        )
        self.edge_voice_hint.pack(side="left")
        ctk.CTkButton(
            edge_reload_row, text="🔄 Tải toàn bộ giọng Edge", width=210,
            command=self._reload_edge_voice_options_full,
        ).pack(side="right")

        self._reload_edge_voice_options()
        self.target_lang.trace_add("write", lambda *_a: self._reload_edge_voice_options())

        # ---- Lồng tiếng · Giọng lồng · Tiếng Việt (chỉ hiện khi tts_engine="vieneu") ----
        # Cho phép gán RIÊNG 1 giọng VieNeu-TTS cho từng giới tính nhân vật, thay vì cả
        # video chỉ đọc bằng 1 giọng (voice_name) duy nhất - hữu ích với video có 2 nhân
        # vật đối thoại (1 nam + 1 nữ).
        self.vieneu_gender_section = ctk.CTkFrame(parent, fg_color="transparent")
        self.vieneu_gender_section.pack(fill="x", padx=0, pady=(4, 0))

        ctk.CTkLabel(
            self.vieneu_gender_section, text="LỒNG TIẾNG", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=18, pady=(16, 0))
        ctk.CTkLabel(
            self.vieneu_gender_section, text="Giọng lồng · Tiếng Việt",
            font=(FONT_FAMILY, 13, "bold"), text_color="white",
        ).pack(anchor="w", padx=18, pady=(0, 4))
        ctk.CTkLabel(
            self.vieneu_gender_section,
            text="Gán RIÊNG 1 giọng VieNeu-TTS cho mỗi giới tính nhân vật (thay vì cả video\n"
                 "chỉ 1 giọng). Cần bật 1 trong 2 ô nhận diện nhân vật ở trên, nếu không toàn bộ\n"
                 "video vẫn đọc bằng 1 giọng nền duy nhất (ô 'Giọng của bạn' ở trên).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 8))

        gender_voice_grid = ctk.CTkFrame(self.vieneu_gender_section, fg_color="transparent")
        gender_voice_grid.pack(fill="x", padx=18)
        gender_voice_grid.grid_columnconfigure(0, weight=1)
        gender_voice_grid.grid_columnconfigure(1, weight=1)

        self.vieneu_voice_male = ctk.StringVar(value="")
        male_wrap = ctk.CTkFrame(gender_voice_grid, fg_color="transparent")
        male_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(male_wrap, text="Giọng Nam", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        self.vieneu_male_combo = ctk.CTkComboBox(
            male_wrap, values=[], variable=self.vieneu_voice_male,
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
        )
        self.vieneu_male_combo.pack(fill="x", pady=(4, 0))

        self.vieneu_voice_female = ctk.StringVar(value="")
        female_wrap = ctk.CTkFrame(gender_voice_grid, fg_color="transparent")
        female_wrap.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ctk.CTkLabel(female_wrap, text="Giọng Nữ", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        self.vieneu_female_combo = ctk.CTkComboBox(
            female_wrap, values=[], variable=self.vieneu_voice_female,
            fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
        )
        self.vieneu_female_combo.pack(fill="x", pady=(4, 0))

        reload_row = ctk.CTkFrame(self.vieneu_gender_section, fg_color="transparent")
        reload_row.pack(fill="x", padx=18, pady=(8, 4))
        self.vieneu_voice_hint = ctk.CTkLabel(
            reload_row, text="Để trống ô nào = giới tính đó dùng giọng nền ('Giọng của bạn' ở trên).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=500,
        )
        self.vieneu_voice_hint.pack(side="left")
        ctk.CTkButton(
            reload_row, text="🔄 Tải giọng dựng sẵn VieNeu-TTS", width=220,
            command=self._reload_vieneu_voice_options,
        ).pack(side="right")

        # ---- OmniVoice · Voice Design (chỉ hiện khi tts_engine="omnivoice") ----
        # OmniVoice không có ~600 giọng dựng sẵn như edge-tts (con số 600+ là số NGÔN
        # NGỮ hỗ trợ) - nó TẠO giọng theo thuộc tính. Để dễ chọn, bên dưới có sẵn 1 bộ
        # preset đặt tên (Adam, Emma...) tự điền thuộc tính giúp bạn, gom cùng 1 chỗ với
        # phần chọn riêng Nam/Nữ thay vì tách rời như trước. Chỉ dùng khi ô "Giọng của
        # bạn" ở trên ĐỂ TRỐNG (có giá trị = ưu tiên clone giọng đó).
        self.omnivoice_section = ctk.CTkFrame(parent, fg_color="transparent")
        self.omnivoice_section.pack(fill="x", padx=0, pady=(4, 0))

        ctk.CTkLabel(
            self.omnivoice_section, text="OMNIVOICE · VOICE DESIGN", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=18, pady=(16, 0))
        ctk.CTkLabel(
            self.omnivoice_section,
            text="Không cần audio mẫu - chọn preset đặt tên sẵn hoặc tự phối thuộc tính. Chỉ\n"
                 "dùng khi ô 'Giọng của bạn' ở trên ĐỂ TRỐNG.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", padx=18, pady=(2, 10))

        def _omni_combo(grid_parent, label, labels_dict, row, col, colspan=1, command=None):
            wrap = ctk.CTkFrame(grid_parent, fg_color="transparent")
            wrap.grid(row=row, column=col, columnspan=colspan, sticky="ew", padx=(0 if col == 0 else 6, 0), pady=(0, 8))
            ctk.CTkLabel(wrap, text=label, font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w")
            var = ctk.StringVar(value=OMNI_NONE_LABEL)
            ctk.CTkComboBox(
                wrap, values=list(labels_dict.keys()), variable=var,
                fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
                command=command if command else (lambda _v=None: self._update_omnivoice_preview()),
            ).pack(fill="x")
            return var

        # ---- Preset gợi ý (Adam/Emma...) + giọng riêng Nam/Nữ - GOM CHUNG 1 hàng để
        # dễ so sánh/chỉnh cùng lúc, thay vì phần Nam/Nữ nằm tách biệt phía dưới cùng. ----
        preset_row = ctk.CTkFrame(self.omnivoice_section, fg_color="transparent")
        preset_row.pack(fill="x", padx=18)
        preset_row.grid_columnconfigure(0, weight=1)
        preset_row.grid_columnconfigure(1, weight=1)
        preset_row.grid_columnconfigure(2, weight=1)

        def _preset_wrap(col, title, labels_dict, none_label, on_pick):
            wrap = ctk.CTkFrame(preset_row, fg_color="transparent")
            wrap.grid(row=0, column=col, sticky="new", padx=(0 if col == 0 else 8, 0))
            ctk.CTkLabel(wrap, text=title, font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w", pady=(0, 4))
            var = ctk.StringVar(value=none_label)
            ctk.CTkComboBox(
                wrap, values=[none_label] + list(labels_dict.keys()), variable=var,
                fg_color=PANEL2, border_color=BORDER, button_color=ACCENT,
                command=on_pick,
            ).pack(fill="x")
            return var

        self.omni_preset = _preset_wrap(
            0, "Giọng mặc định (cả video)", OMNI_PRESET_LABELS, OMNI_PRESET_NONE,
            lambda _v=None: self._apply_omni_preset(self.omni_preset.get(), OMNI_PRESET_LABELS,
                                                     self.omni_gender, self.omni_age, self.omni_pitch, self.omni_accent, self.omni_dialect),
        )
        self.omni_male_preset = _preset_wrap(
            1, "Giọng Nam riêng", OMNI_PRESET_LABELS_MALE, OMNI_PRESET_KEEP_DEFAULT,
            lambda _v=None: self._apply_omni_preset(self.omni_male_preset.get(), OMNI_PRESET_LABELS_MALE,
                                                     None, self.omni_male_age, self.omni_male_pitch, self.omni_male_accent, self.omni_male_dialect),
        )
        self.omni_female_preset = _preset_wrap(
            2, "Giọng Nữ riêng", OMNI_PRESET_LABELS_FEMALE, OMNI_PRESET_KEEP_DEFAULT,
            lambda _v=None: self._apply_omni_preset(self.omni_female_preset.get(), OMNI_PRESET_LABELS_FEMALE,
                                                     None, self.omni_female_age, self.omni_female_pitch, self.omni_female_accent, self.omni_female_dialect),
        )

        ctk.CTkLabel(
            self.omnivoice_section,
            text="Giọng Nam/Nữ riêng chỉ áp dụng cho câu ĐÃ nhận diện giới tính (bật ở mục 'Lồng\n"
                 "tiếng' phía trên) - để '-- Dùng giọng mặc định --' thì dùng chung preset bên trái.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", padx=18, pady=(8, 12))

        self.omnivoice_preview = ctk.CTkLabel(
            self.omnivoice_section, text="Chuỗi mô tả sẽ dùng: (model tự chọn giọng)",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=620,
        )
        self.omnivoice_preview.pack(anchor="w", padx=18, pady=(0, 10))

        # ---- Tuỳ chỉnh nâng cao: phối trực tiếp từng thuộc tính thay vì dùng preset
        # (preset ở trên sẽ tự điền vào đây - vẫn có thể chỉnh tay lại sau khi chọn preset) ----
        ctk.CTkLabel(
            self.omnivoice_section, text="Tuỳ chỉnh nâng cao (preset ở trên tự điền vào đây, có thể sửa lại)",
            font=(FONT_FAMILY, 11, "bold"), text_color="white",
        ).pack(anchor="w", padx=18, pady=(4, 6))
        base_grid = ctk.CTkFrame(self.omnivoice_section, fg_color="transparent")
        base_grid.pack(fill="x", padx=18)
        for c in range(3):
            base_grid.grid_columnconfigure(c, weight=1)
        self.omni_gender = _omni_combo(base_grid, "Giới tính", OMNI_GENDER_LABELS, 0, 0)
        self.omni_age = _omni_combo(base_grid, "Độ tuổi", OMNI_AGE_LABELS, 0, 1)
        self.omni_pitch = _omni_combo(base_grid, "Cao độ", OMNI_PITCH_LABELS, 0, 2)
        self.omni_style = _omni_combo(base_grid, "Phong cách", OMNI_STYLE_LABELS, 1, 0)
        self.omni_accent = _omni_combo(base_grid, "Accent (chỉ áp dụng tiếng Anh)", OMNI_ACCENT_LABELS, 1, 1)
        self.omni_dialect = _omni_combo(base_grid, "Phương ngữ (chỉ áp dụng tiếng Trung)", OMNI_DIALECT_LABELS, 1, 2)

        gender_split_grid = ctk.CTkFrame(self.omnivoice_section, fg_color="transparent")
        gender_split_grid.pack(fill="x", padx=18, pady=(4, 0))
        gender_split_grid.grid_columnconfigure(0, weight=1)
        gender_split_grid.grid_columnconfigure(1, weight=1)

        male_col = ctk.CTkFrame(gender_split_grid, fg_color="transparent")
        male_col.grid(row=0, column=0, sticky="new", padx=(0, 8))
        ctk.CTkLabel(male_col, text="Nam (chi tiết)", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w", pady=(0, 4))
        male_grid = ctk.CTkFrame(male_col, fg_color="transparent")
        male_grid.pack(fill="x")
        for c in range(2):
            male_grid.grid_columnconfigure(c, weight=1)
        self.omni_male_age = _omni_combo(male_grid, "Độ tuổi", OMNI_AGE_LABELS, 0, 0)
        self.omni_male_pitch = _omni_combo(male_grid, "Cao độ", OMNI_PITCH_LABELS, 0, 1)
        self.omni_male_accent = _omni_combo(male_grid, "Accent (Anh)", OMNI_ACCENT_LABELS, 1, 0)
        self.omni_male_dialect = _omni_combo(male_grid, "Phương ngữ (Trung)", OMNI_DIALECT_LABELS, 1, 1)

        female_col = ctk.CTkFrame(gender_split_grid, fg_color="transparent")
        female_col.grid(row=0, column=1, sticky="new", padx=(8, 0))
        ctk.CTkLabel(female_col, text="Nữ (chi tiết)", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED).pack(anchor="w", pady=(0, 4))
        female_grid = ctk.CTkFrame(female_col, fg_color="transparent")
        female_grid.pack(fill="x")
        for c in range(2):
            female_grid.grid_columnconfigure(c, weight=1)
        self.omni_female_age = _omni_combo(female_grid, "Độ tuổi", OMNI_AGE_LABELS, 0, 0)
        self.omni_female_pitch = _omni_combo(female_grid, "Cao độ", OMNI_PITCH_LABELS, 0, 1)
        self.omni_female_accent = _omni_combo(female_grid, "Accent (Anh)", OMNI_ACCENT_LABELS, 1, 0)
        self.omni_female_dialect = _omni_combo(female_grid, "Phương ngữ (Trung)", OMNI_DIALECT_LABELS, 1, 1)

        self._update_omnivoice_preview()
        self._refresh_voice_profiles()  # nạp lại lần nữa để đổ giá trị ban đầu vào 2 combo Nam/Nữ vừa tạo
        self._on_tts_engine_change()


        # ===== CẮT VIDEO: bỏ bớt đầu/đuôi theo số giây tuỳ chỉnh =====
        # Chạy NGAY BƯỚC ĐẦU TIÊN của pipeline (trước cả transcribe/dịch) - core/
        # pipeline.py + core/export.py:trim_video đã có sẵn từ trước, chỉ thêm UI.
        ctk.CTkLabel(parent, text="CẮT VIDEO", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(20, 8))
        trim_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        trim_box.pack(fill="x", padx=18, pady=(0, 16))
        trim_inner = ctk.CTkFrame(trim_box, fg_color="transparent")
        trim_inner.pack(fill="x", padx=16, pady=14)

        trim_start_row = ctk.CTkFrame(trim_inner, fg_color="transparent")
        trim_start_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(trim_start_row, text="Cắt đầu (giây)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.trim_start_sec = tk.StringVar(value="0")
        ctk.CTkEntry(trim_start_row, textvariable=self.trim_start_sec, width=100, fg_color=PANEL, border_color=BORDER).pack(side="left")

        trim_end_row = ctk.CTkFrame(trim_inner, fg_color="transparent")
        trim_end_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(trim_end_row, text="Cắt đuôi (giây)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.trim_end_sec = tk.StringVar(value="0")
        ctk.CTkEntry(trim_end_row, textvariable=self.trim_end_sec, width=100, fg_color=PANEL, border_color=BORDER).pack(side="left")

        ctk.CTkLabel(
            trim_inner,
            text="Cắt bỏ bấy nhiêu giây ở đầu/cuối video TRƯỚC KHI xử lý (0 = không cắt). Vd video 60s, cắt đầu 3s + cắt đuôi 5s -> video xử lý còn 52s (giây 3 -> giây 55 của bản gốc).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(4, 0))

        # ===== ÂM THANH: tốc độ đọc + biến đổi giọng đọc tuỳ chỉnh =====
        # Các field này (speech_rate, voice_pitch_semitones, voice_speed, dub_max_speedup...)
        # ĐÃ CÓ SẴN trong core/pipeline.py và core/tts.py từ trước, nhưng CHƯA TỪNG được
        # đưa lên UI - giờ thêm hẳn 1 mục riêng để chỉnh trực tiếp.
        ctk.CTkLabel(parent, text="ÂM THANH", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(20, 8))
        audio_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        audio_box.pack(fill="x", padx=18, pady=(0, 16))
        audio_inner = ctk.CTkFrame(audio_box, fg_color="transparent")
        audio_inner.pack(fill="x", padx=16, pady=14)

        # --- Tốc độ đọc GỐC (native prosody của chính giọng TTS, không phải tăng tốc
        # hậu kỳ) - chỉ áp dụng khi tts_engine="online" (edge-tts hỗ trợ SSML rate).
        rate_row = ctk.CTkFrame(audio_inner, fg_color="transparent")
        rate_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(rate_row, text="Tốc độ đọc gốc (%)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.speech_rate_pct = ctk.IntVar(value=0)  # % - map sang chuỗi "+0%" khi build config - mặc định TRUNG
                                                      # TÍNH (giữ nguyên tốc độ gốc của giọng TTS), không tự ý
                                                      # tăng tốc sẵn - tăng/giảm tuỳ ý theo gợi ý bên dưới.
        self._slider_with_value(rate_row, self.speech_rate_pct, -30, 40, fmt="{:+.0f}", step=70)
        ctk.CTkLabel(
            audio_inner,
            text="Mặc định 0% = giữ nguyên tốc độ gốc của giọng TTS (tự nhiên nhất). Gợi ý: nếu câu dịch hay bị "
                 "cảnh báo \"đã tăng tốc\" ở bước ghép giọng, tăng nhẹ +3% đến +8% giúp đọc kịp câu dài hơn mà vẫn "
                 "tự nhiên hơn tăng tốc hậu kỳ (chỉ áp dụng khi Giọng đọc (TTS) = online).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(0, 10))

        # --- Biến đổi giọng đọc TUỲ CHỈNH: cao độ + tốc độ đọc hậu kỳ (rubberband -
        # đổi độc lập pitch/tempo, không kéo cao độ lên khi tăng tốc như atempo thường).
        ctk.CTkLabel(audio_inner, text="Biến đổi giọng đọc tuỳ chỉnh", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w", pady=(4, 6))

        pitch_row = ctk.CTkFrame(audio_inner, fg_color="transparent")
        pitch_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(pitch_row, text="Cao độ (semitone)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.voice_pitch_semitones = ctk.DoubleVar(value=0.0)   # 0 = trung tính, giữ nguyên cao độ gốc
        self._slider_with_value(pitch_row, self.voice_pitch_semitones, -12, 12, fmt="{:+.1f}")

        vspeed_row = ctk.CTkFrame(audio_inner, fg_color="transparent")
        vspeed_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(vspeed_row, text="Tốc độ đọc (x)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.voice_speed = ctk.DoubleVar(value=1.0)   # 1.0 = trung tính, giữ nguyên tốc độ gốc (không nén/giãn thêm)
        self._slider_with_value(vspeed_row, self.voice_speed, 0.5, 2.0, fmt="{:.2f}")
        ctk.CTkLabel(
            audio_inner,
            text="Mặc định: Cao độ = 0, Tốc độ = 1.00 (giữ nguyên giọng gốc, KHÔNG biến đổi gì thêm - an toàn và "
                 "tự nhiên nhất). Gợi ý nếu muốn chỉnh: Cao độ ±1 đến ±2 semitone là mức trầm/cao nhẹ, khó nhận ra "
                 "là bị chỉnh; quá ±4 dễ nghe giả. Tốc độ 0.95-1.05 là mức nhanh/chậm nhẹ, hầu như không ảnh hưởng "
                 "độ khớp timeline; dưới 0.9 hoặc trên 1.15 bắt đầu nghe rõ bị đổi tốc độ. Áp dụng SAU khi ghép "
                 "giọng đọc, trước khi ghép vào video - chỉ có tác dụng khi bật Lồng tiếng.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(0, 10))

        # --- Nhịp điệu đọc ĐỀU: giới hạn atempo tối đa còn sót lại sau khi đã rút
        # ngắn văn bản khớp thời lượng, tránh câu nào cũng bị đổi tốc độ lung tung
        # nghe "dồn dập"/không lọt tai (đúng yêu cầu "tốc độ đọc chữ nhịp điều").
        ctk.CTkLabel(audio_inner, text="Nhịp điệu đọc đều (chống đọc quá nhanh/quá chậm)", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w", pady=(4, 6))

        self.fit_text_to_timing = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            audio_inner, text="Tự rút ngắn câu dịch nếu đọc không kịp (thay vì tăng tốc audio mạnh)",
            variable=self.fit_text_to_timing, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(0, 6))

        self.calibrate_speech_rate_cps = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            audio_inner, text="Tự đo tốc độ đọc thực tế của giọng đang dùng (chính xác hơn ước lượng tĩnh)",
            variable=self.calibrate_speech_rate_cps, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(0, 6))

        maxspeed_row = ctk.CTkFrame(audio_inner, fg_color="transparent")
        maxspeed_row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(maxspeed_row, text="Giới hạn tăng tốc (x)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.dub_max_speedup = ctk.DoubleVar(value=1.15)
        self._slider_with_value(maxspeed_row, self.dub_max_speedup, 1.0, 1.5, fmt="{:.2f}")
        ctk.CTkLabel(
            audio_inner,
            text="Mức tăng tốc TỐI ĐA cho phần lệch nhỏ còn sót lại sau khi đã rút ngắn văn bản - để thấp (1.10-1.20x) sẽ nghe đều tai hơn, gần như không nhận ra khác biệt giữa các câu.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(4, 0))

        # --- NẤC KHẨN CẤP ẩn: pipeline có 1 nấc tăng tốc thứ 2 (mặc định 1.6x, xem
        # PipelineConfig.dub_emergency_max_speedup) chỉ kích hoạt khi 1 câu VẪN còn dài
        # hơn khung giờ gốc sau khi đã rút gọn văn bản + tăng tốc tới mức "Giới hạn tăng
        # tốc" ở trên - đây chính là nguồn gốc của các log kiểu "đã tăng tốc 1.22x" dù
        # slider phía trên để 1.15x. Checkbox này tắt hẳn nấc khẩn cấp: ép trần tăng tốc
        # THẬT SỰ = đúng giá trị slider "Giới hạn tăng tốc", không có ngoại lệ nào cao
        # hơn - đổi lại, câu nào vẫn còn dư sau đó sẽ bị CẮT bớt chữ (nhìn thấy cảnh báo
        # "đã cắt bớt" trong log) thay vì được tăng tốc thêm.
        self.never_exceed_max_speedup = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            audio_inner,
            text="KHÔNG BAO GIỜ tăng tốc vượt quá 'Giới hạn tăng tốc' ở trên (câu quá dài sẽ bị cắt bớt chữ thay vì tăng tốc thêm)",
            variable=self.never_exceed_max_speedup, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(6, 6))

        # --- Ngưỡng rút gọn văn bản: PHẢI thấp hơn rõ rệt "Giới hạn tăng tốc" ở trên,
        # để bước rút gọn văn bản (viết lại/cắt câu) gánh phần lớn việc khớp thời
        # lượng, atempo chỉ còn xử lý phần lệch rất nhỏ còn sót (đọc core/pipeline.py
        # PipelineConfig.fit_text_tolerance để biết thêm).
        tolerance_row = ctk.CTkFrame(audio_inner, fg_color="transparent")
        tolerance_row.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(tolerance_row, text="Ngưỡng rút gọn câu (x)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.fit_text_tolerance = ctk.DoubleVar(value=1.08)
        self._slider_with_value(tolerance_row, self.fit_text_tolerance, 1.0, 1.3, fmt="{:.2f}")
        ctk.CTkLabel(
            audio_inner,
            text="Để THẤP (vd 1.00-1.03) ép rút gọn câu dịch sớm/mạnh hơn, giảm số câu phải nhờ tới 'Giới hạn tăng tốc' ở trên. Để CAO (vd 1.15-1.30) giữ câu dịch đầy đủ hơn, chấp nhận atempo xử lý nhiều hơn.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(4, 10))

        # --- Giãn/tăng tốc CẢ VIDEO (thủ thuật CapCut): làm chậm video gốc TRƯỚC khi
        # tách thoại/dịch/TTS để có thêm khoảng trống thời gian thật cho giọng đọc,
        # rồi tăng tốc lại VIDEO OUTPUT CUỐI CÙNG (đã có phụ đề/watermark) sau khi
        # xuất xong - bù lại nhịp phim. Đây là cách tạo thêm "chỗ trống" HIỆU QUẢ
        # NHẤT (không cần rút gọn câu/tăng tốc audio nhiều), nhưng tốn thêm 2 lần
        # re-encode toàn bộ video (chậm hơn) - chỉ áp dụng khi bật Lồng tiếng.
        ctk.CTkLabel(audio_inner, text="Giãn/tăng tốc video (thủ thuật CapCut, tuỳ chọn)", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w", pady=(4, 6))

        self.enable_speed_trick = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            audio_inner, text="Bật giãn video gốc trước / tăng tốc lại video output sau",
            variable=self.enable_speed_trick, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(0, 6))

        preslow_row = ctk.CTkFrame(audio_inner, fg_color="transparent")
        preslow_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(preslow_row, text="Giãn video gốc (x)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.pre_slowdown_speed = ctk.DoubleVar(value=0.85)
        self._slider_with_value(preslow_row, self.pre_slowdown_speed, 0.5, 1.0, fmt="{:.2f}")

        postspeed_row = ctk.CTkFrame(audio_inner, fg_color="transparent")
        postspeed_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(postspeed_row, text="Tăng tốc lại output (x)", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.post_speedup_speed = ctk.DoubleVar(value=round(1 / 0.85, 4))  # SỬA: đúng nghịch đảo của pre_slowdown_speed mặc định (0.85) - trước là 1.15 (lệch ~2.6%), giờ video output khớp ĐÚNG thời lượng gốc khi bật enable_speed_trick
        self._slider_with_value(postspeed_row, self.post_speedup_speed, 1.0, 2.0, fmt="{:.2f}")

        # TỰ ĐỘNG đồng bộ post_speedup_speed = 1/pre_slowdown_speed mỗi khi kéo slider "Giãn
        # video gốc" - tránh trường hợp 2 giá trị bị lệch tay (như file cấu hình từng gặp:
        # pre=0.6966 nhưng post=1.2977 thay vì phải là 1.4356 - khiến video output dài hơn
        # gốc ~10.6%, dễ gây cảm giác giọng đọc/nội dung không khớp với video khi xem).
        def _sync_post_speedup(*_args):
            try:
                pre = self.pre_slowdown_speed.get()
                if pre and pre > 0:
                    self.post_speedup_speed.set(round(1.0 / pre, 4))
            except Exception:
                pass
        self.pre_slowdown_speed.trace_add("write", _sync_post_speedup)
        ctk.CTkLabel(
            audio_inner,
            text="Vd 0.85 / 1.15: video gốc giãn ra ~1.18x trước khi xử lý (nhiều chỗ trống hơn cho giọng đọc), rồi tăng tốc lại 1.15x sau khi xuất - nhịp phim cuối chỉ chậm hơn gốc ~2% (0.85×1.15≈0.98), gần như không nhận ra bằng mắt. Chỉ có tác dụng khi bật Lồng tiếng.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(4, 0))

        # Output toggles
        ctk.CTkLabel(parent, text="OUTPUT", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(20, 8))
        toggles = ctk.CTkFrame(parent, fg_color="transparent")
        toggles.pack(fill="x", padx=18)

        self.do_subtitles = ctk.BooleanVar(value=True)
        self.do_dubbing = ctk.BooleanVar(value=False)
        # Watermark KHÔNG còn 1 checkbox "master" chung ở đây nữa - trước đây checkbox
        # này nằm tách biệt xa phần cấu hình logo/chữ chạy bên dưới (mục ADVANCED
        # EXPORT), khiến người dùng cấu hình logo xong nhưng QUÊN tick checkbox này
        # -> chạy xong không thấy watermark đâu cả, tưởng "advanced export không chạy".
        # Giờ mỗi loại watermark (chữ / logo) có checkbox BẬT-TẮT riêng, nằm NGAY
        # trong mục ADVANCED EXPORT - xem _build_advanced_export_section bên dưới.

        ctk.CTkCheckBox(toggles, text="Phụ đề (burn-in)", variable=self.do_subtitles, fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="left", padx=(0, 16))
        ctk.CTkCheckBox(toggles, text="Lồng tiếng (dubbing)", variable=self.do_dubbing, fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="left", padx=(0, 16))

        # Khi lồng tiếng: mặc định TẮT audio gốc, chỉ giữ giọng đọc mới tạo.
        self.keep_original_audio = ctk.BooleanVar(value=False)
        keep_row = ctk.CTkFrame(parent, fg_color="transparent")
        keep_row.pack(fill="x", padx=18, pady=(8, 0))
        ctk.CTkCheckBox(
            keep_row, text="Giữ lại audio gốc (trộn cùng giọng đọc mới)",
            variable=self.keep_original_audio, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(side="left")
        ctk.CTkLabel(
            keep_row, text="  (mặc định: TẮT — video xuất ra chỉ có giọng đọc mới, không còn audio gốc)",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED,
        ).pack(side="left")

        # Subtitle style
        ctk.CTkLabel(parent, text="SUBTITLE STYLE", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(20, 8))
        preset_row = ctk.CTkFrame(parent, fg_color="transparent")
        preset_row.pack(fill="x", padx=18)
        self.preset = ctk.StringVar(value="Classic")
        for p in PRESETS:
            ctk.CTkRadioButton(preset_row, text=p, variable=self.preset, value=p, fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="left", padx=6, pady=4)

        size_row = ctk.CTkFrame(parent, fg_color="transparent")
        size_row.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkLabel(size_row, text="Cỡ chữ", text_color=TEXT_MUTED).pack(side="left")
        self.font_size = ctk.IntVar(value=20)
        self._slider_with_value(size_row, self.font_size, 12, 40, fmt="{:.0f}", step=28)

        # --- Chế độ hiển thị: cả câu (như cũ) hoặc từng chữ nhảy liên tục (TikTok/Capcut) ---
        display_mode_row = ctk.CTkFrame(parent, fg_color="transparent")
        display_mode_row.pack(fill="x", padx=18, pady=(14, 0))
        ctk.CTkLabel(display_mode_row, text="Kiểu hiển thị", text_color=TEXT_MUTED).pack(side="left")
        self.subtitle_display_mode = ctk.StringVar(value="sentence")
        ctk.CTkRadioButton(
            display_mode_row, text="Cả câu", variable=self.subtitle_display_mode, value="sentence", fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(side="left", padx=(10, 6))
        ctk.CTkRadioButton(
            display_mode_row, text="Từng chữ (nhanh, kiểu TikTok)", variable=self.subtitle_display_mode, value="word", fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(side="left", padx=6)

        # --- Font chữ ---
        font_row = ctk.CTkFrame(parent, fg_color="transparent")
        font_row.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkLabel(font_row, text="Font chữ", text_color=TEXT_MUTED, width=180, anchor="w").pack(side="left")
        self.subtitle_font = ctk.StringVar(value=FONT_FAMILY)
        ctk.CTkComboBox(
            font_row, values=SUBTITLE_FONTS, variable=self.subtitle_font,
            fg_color=PANEL2, border_color=BORDER, width=220,
        ).pack(side="left")
        ctk.CTkLabel(
            font_row, text="  (font phải cài sẵn trên máy chạy, nếu không sẽ tự thay bằng font mặc định)",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED,
        ).pack(side="left")

        # --- Vị trí hiển thị: bỏ 3 vị trí cố định Trên/Giữa/Dưới - thay bằng 2 chế
        # độ linh hoạt để người dùng toàn quyền đặt phụ đề đúng chỗ:
        #   1) Đè lên vùng che mờ đã vẽ (dùng khung vẽ ở phần Xoá phụ đề/logo gốc)
        #   2) Tự kéo-thả tới vị trí mong muốn trên khung hình mẫu.
        position_wrap = ctk.CTkFrame(parent, fg_color="transparent")
        position_wrap.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkLabel(position_wrap, text="Vị trí phụ đề", text_color=TEXT_MUTED).pack(anchor="w")

        self.subtitle_position_mode = ctk.StringVar(value="blur_region")  # "blur_region" | "custom" - CHỈ dùng cho UI
        self.subtitle_position = ctk.StringVar(value="custom")  # giá trị THỰC gửi xuống pipeline - luôn là "custom"
        self.subtitle_pos_x_frac = tk.DoubleVar(value=0.5)
        self.subtitle_pos_y_frac = tk.DoubleVar(value=0.85)

        mode_row = ctk.CTkFrame(position_wrap, fg_color="transparent")
        mode_row.pack(fill="x", pady=(4, 0))
        ctk.CTkRadioButton(
            mode_row, text="🎯 Đè lên vùng che mờ đã vẽ", variable=self.subtitle_position_mode, value="blur_region",
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._resolve_subtitle_position_fracs,
        ).pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(
            mode_row, text="✋ Tự chọn vị trí (kéo-thả)", variable=self.subtitle_position_mode, value="custom",
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(side="left")

        pos_action_row = ctk.CTkFrame(position_wrap, fg_color="transparent")
        pos_action_row.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(
            pos_action_row, text="🖱 Chọn vị trí trên khung hình", width=220,
            command=self._open_subtitle_position_picker,
        ).pack(side="left")
        self.subtitle_pos_label = ctk.CTkLabel(
            pos_action_row, text="Vị trí: giữa-dưới màn hình (mặc định)", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED,
        )
        self.subtitle_pos_label.pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            position_wrap,
            text="'Đè lên vùng che mờ': dùng đúng khung bạn đã vẽ ở phần 'Xoá phụ đề/logo gốc' bên dưới (nếu vẽ\n"
                 "nhiều khung, lấy khung vẽ SAU CÙNG). 'Tự chọn vị trí': bấm nút trên để kéo phụ đề tới bất kỳ đâu.",
            font=(FONT_FAMILY, 9), text_color=TEXT_MUTED, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # --- Nền/box phía sau chữ ---
        self.subtitle_box_enabled = ctk.BooleanVar(value=False)
        box_row = ctk.CTkFrame(parent, fg_color="transparent")
        box_row.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkCheckBox(
            box_row, text="Nền phía sau chữ", variable=self.subtitle_box_enabled, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(side="left")
        self.subtitle_box_color = ctk.StringVar(value="&H000000&")
        ctk.CTkComboBox(
            box_row, values=["&H000000&", "&HFFFFFF&", "&H2D2D2D&", "&H0000FF&"], variable=self.subtitle_box_color,
            fg_color=PANEL2, border_color=BORDER, width=140,
        ).pack(side="left", padx=(10, 0))
        self.subtitle_box_opacity = ctk.DoubleVar(value=0.6)
        self._slider_with_value(box_row, self.subtitle_box_opacity, 0.1, 1.0, fmt="{:.2f}")

        # --- Hiệu ứng xuất hiện mỗi cue (phóng to / nảy / mờ dần) ---
        effect_row = ctk.CTkFrame(parent, fg_color="transparent")
        effect_row.pack(fill="x", padx=18, pady=(10, 0))
        ctk.CTkLabel(effect_row, text="Hiệu ứng xuất hiện", text_color=TEXT_MUTED).pack(side="left")
        self.subtitle_effect = ctk.StringVar(value="none")
        for val, label in (("none", "Không"), ("fade", "Mờ dần"), ("zoom", "Phóng to"), ("bounce", "Nảy nhẹ")):
            ctk.CTkRadioButton(
                effect_row, text=label, variable=self.subtitle_effect, value=val, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            ).pack(side="left", padx=(10, 6))

        # --- Ép phụ đề HIỂN THỊ ngắn lại: câu dịch dài sẽ tự tách thành nhiều dòng
        # ngắn hiện LẦN LƯỢT đúng nhịp giọng đọc (giữ nguyên 100% nội dung, chỉ chia
        # nhỏ khung hiển thị) - vd "Bạn có dám tin rằng, chỉ cần đổ thêm nước vào bể"
        # sẽ hiện "Bạn có dám tin rằng" trước, rồi "chỉ cần đổ thêm nước vào bể" sau,
        # thay vì hiện nguyên câu dài suốt cả đoạn. Field này đã có sẵn trong
        # core/pipeline.py + core/text_fit.py từ trước, giờ mới đưa lên UI.
        self.split_long_subtitles = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            parent, text="Ép phụ đề hiện ngắn (tự tách câu dài thành nhiều dòng, hiện lần lượt theo giọng đọc)",
            variable=self.split_long_subtitles, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", padx=18, pady=(14, 0))

        maxchars_row = ctk.CTkFrame(parent, fg_color="transparent")
        maxchars_row.pack(fill="x", padx=18, pady=(6, 0))
        ctk.CTkLabel(maxchars_row, text="Độ dài tối đa 1 dòng (ký tự)", text_color=TEXT_MUTED, width=180, anchor="w").pack(side="left")
        self.max_subtitle_chars = ctk.IntVar(value=42)
        self._slider_with_value(maxchars_row, self.max_subtitle_chars, 20, 80, fmt="{:.0f}", step=60)

        self._build_advanced_export_section(parent)

    def _build_advanced_export_section(self, parent):
        ctk.CTkLabel(parent, text="ADVANCED EXPORT", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(20, 8))

        # Biến DÙNG CHUNG giữa 2 panel bên dưới (chữ / logo) - vị trí/toạ độ dùng
        # chung là hợp lý (cùng 1 khung hình mẫu để đặt cả logo lẫn chữ cố định),
        # nhưng ĐỘ MỜ được tách RIÊNG hẳn cho mỗi loại (xem 2 panel bên dưới) - kéo
        # thanh mờ của chữ không còn làm đổi luôn độ mờ của logo và ngược lại.
        self.watermark_position = ctk.StringVar(value="top-right")
        self.watermark_x_frac = ctk.DoubleVar(value=0.85)
        self.watermark_y_frac = ctk.DoubleVar(value=0.1)

        # ===== Panel 1: Watermark CHỮ (cố định hoặc chạy quanh video) =====
        # ĐỘC LẬP hoàn toàn với panel Logo bên dưới - có thể bật CẢ HAI cùng lúc,
        # chỉ 1 trong 2, hoặc tắt hết. (Trước đây dùng chung 1 checkbox "Watermark"
        # nằm ở mục OUTUT phía trên + 1 radio 3 lựa chọn ở đây -> chỉ chọn được 1
        # kiểu, và rất dễ quên tick checkbox master khiến watermark không hiện ra.)
        text_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        text_box.pack(fill="x", padx=18, pady=(0, 16))
        text_inner = ctk.CTkFrame(text_box, fg_color="transparent")
        text_inner.pack(fill="x", padx=16, pady=14)

        self.do_watermark_text = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            text_inner, text="Watermark CHỮ", variable=self.do_watermark_text,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, font=(FONT_FAMILY, 12, "bold"),
        ).pack(anchor="w")

        wt_text_row = ctk.CTkFrame(text_inner, fg_color="transparent")
        wt_text_row.pack(fill="x", pady=(8, 6))
        ctk.CTkLabel(wt_text_row, text="Nội dung", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=90, anchor="w").pack(side="left")
        self.watermark_text = ctk.StringVar(value="Reup Studio")
        ctk.CTkEntry(wt_text_row, textvariable=self.watermark_text, fg_color=PANEL, border_color=BORDER).pack(side="left", fill="x", expand=True)

        self.watermark_text_style = ctk.StringVar(value="text")
        style_row = ctk.CTkFrame(text_inner, fg_color="transparent")
        style_row.pack(fill="x", pady=(0, 6))
        ctk.CTkRadioButton(style_row, text="Cố định", variable=self.watermark_text_style, value="text", fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(style_row, text="Chạy quanh video", variable=self.watermark_text_style, value="moving_text", fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="left")
        ctk.CTkLabel(
            text_inner, text="'Chạy quanh video' = chữ tự di chuyển ngẫu nhiên khắp khung hình (kiểu logo DVD nảy) - khó bị crop/che mất hơn watermark đứng yên 1 chỗ.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(0, 8))

        pattern_row = ctk.CTkFrame(text_inner, fg_color="transparent")
        pattern_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(pattern_row, text="Kiểu chạy", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=90, anchor="w").pack(side="left")
        self.watermark_pattern = ctk.StringVar(value="drift")
        ctk.CTkComboBox(
            pattern_row,
            values=["drift", "bounce", "zigzag", "random_jump", "four_corners"],
            variable=self.watermark_pattern,
            fg_color=PANEL, border_color=BORDER, button_color=ACCENT, width=180,
        ).pack(side="left")
        ctk.CTkLabel(
            pattern_row,
            text="  (chỉ áp dụng khi chọn 'Chạy quanh video')",
            font=(FONT_FAMILY, 9), text_color=TEXT_MUTED,
        ).pack(side="left")
        ctk.CTkLabel(
            text_inner,
            text="'drift' = chữ TRÔI CHẬM, MƯỢT từ 1 điểm ngẫu nhiên sang điểm ngẫu nhiên kế tiếp trong khung hình (đúng kiểu 'di chuyển chậm từ A sang B'), KHÁC 'random_jump'/'four_corners' (dạy tức thời, trông như 'hiện ngẫu nhiên' chứ không di chuyển).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(0, 8))

        wm_size_row = ctk.CTkFrame(text_inner, fg_color="transparent")
        wm_size_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(wm_size_row, text="Cỡ chữ", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=90, anchor="w").pack(side="left")
        self.watermark_font_size = ctk.IntVar(value=28)
        self._slider_with_value(wm_size_row, self.watermark_font_size, 12, 60, fmt="{:.0f}", step=48)

        speed_row = ctk.CTkFrame(text_inner, fg_color="transparent")
        speed_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(speed_row, text="Tốc độ chạy", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=90, anchor="w").pack(side="left")
        # Với "drift": speed THẤP = mỗi chặng trôi CHẬM/DÀI hơn (dễ chịu hơn). Gợi ý: 0.2-0.4.
        self.watermark_speed = ctk.DoubleVar(value=0.3)
        self._slider_with_value(speed_row, self.watermark_speed, 0.1, 2.0, fmt="{:.2f}")

        opac_row1 = ctk.CTkFrame(text_inner, fg_color="transparent")
        opac_row1.pack(fill="x")
        ctk.CTkLabel(opac_row1, text="Độ mờ", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=90, anchor="w").pack(side="left")
        self.watermark_text_opacity = ctk.DoubleVar(value=0.5)
        self._slider_with_value(opac_row1, self.watermark_text_opacity, 0.1, 1.0, fmt="{:.2f}")
        ctk.CTkLabel(
            text_inner, text="Gợi ý: 0.35–0.55 = thấy rõ chữ nhưng không chói/che nội dung video.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        # ===== Panel 2: Watermark LOGO (ảnh) =====
        # ĐỘC LẬP hoàn toàn với panel Chữ ở trên.
        logo_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        logo_box.pack(fill="x", padx=18, pady=(0, 16))
        logo_inner = ctk.CTkFrame(logo_box, fg_color="transparent")
        logo_inner.pack(fill="x", padx=16, pady=14)

        self.do_watermark_logo = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            logo_inner, text="Watermark LOGO (ảnh)", variable=self.do_watermark_logo,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, font=(FONT_FAMILY, 12, "bold"),
        ).pack(anchor="w")

        logo_row = ctk.CTkFrame(logo_inner, fg_color="transparent")
        logo_row.pack(fill="x", pady=(8, 8))
        self.watermark_logo_path = ""
        self.watermark_logo_label = ctk.CTkLabel(logo_row, text="Chưa chọn logo", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED)
        self.watermark_logo_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(logo_row, text="Chọn ảnh logo", width=120, command=self._choose_watermark_logo).pack(side="right")

        pos_row = ctk.CTkFrame(logo_inner, fg_color="transparent")
        pos_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(pos_row, text="Vị trí", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(side="left", padx=(0, 8))
        ctk.CTkComboBox(
            pos_row, values=["top-left", "top-right", "bottom-left", "bottom-right", "custom"],
            variable=self.watermark_position, fg_color=PANEL, border_color=BORDER, button_color=ACCENT, width=160,
        ).pack(side="left")
        ctk.CTkLabel(
            pos_row, text="  'custom' = tự chọn vị trí bằng cách kéo-thả trên khung hình mẫu bên dưới.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED,
        ).pack(side="left")

        custom_pos_row = ctk.CTkFrame(logo_inner, fg_color="transparent")
        custom_pos_row.pack(fill="x", pady=(0, 8))
        self.watermark_pos_label = ctk.CTkLabel(custom_pos_row, text="Vị trí tuỳ chỉnh: x=85%, y=10%", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED)
        self.watermark_pos_label.pack(side="left")
        ctk.CTkButton(
            custom_pos_row, text="📍 Kéo-thả chọn vị trí trên khung hình mẫu", width=260,
            command=self._open_watermark_position_picker,
        ).pack(side="right")

        opac_row2 = ctk.CTkFrame(logo_inner, fg_color="transparent")
        opac_row2.pack(fill="x")
        ctk.CTkLabel(opac_row2, text="Độ mờ", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=90, anchor="w").pack(side="left")
        self.watermark_logo_opacity = ctk.DoubleVar(value=0.8)
        self._slider_with_value(opac_row2, self.watermark_logo_opacity, 0.1, 1.0, fmt="{:.2f}")
        ctk.CTkLabel(
            logo_inner, text="Gợi ý: 0.6–0.9 - logo cần rõ nét hơn chữ để dễ nhận diện thương hiệu; 1.0 = đậm nét hoàn toàn (dễ gây khó chịu nếu logo lớn).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, wraplength=520, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        size_row2 = ctk.CTkFrame(logo_inner, fg_color="transparent")
        size_row2.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(size_row2, text="Kích thước", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=90, anchor="w").pack(side="left")
        # Tính bằng % CHIỀU RỘNG video (vd 0.18 = logo rộng bằng 18% chiều rộng khung
        # hình, cao theo đúng tỉ lệ ảnh gốc - xem core/export.py:add_watermark_image).
        self.watermark_scale_frac = ctk.DoubleVar(value=0.18)
        self._slider_with_value(size_row2, self.watermark_scale_frac, 0.05, 0.5, fmt="{:.2f}")
        ctk.CTkLabel(
            logo_inner, text="Tỉ lệ so với chiều rộng video (0.05 = rất nhỏ ~5%, 0.18 = mặc định, 0.5 = rất lớn ~nửa khung hình).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, wraplength=520, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # ----- MỚI: Tự động dò + XOÁ logo/phụ đề gốc (không cần tự vẽ vùng) -----
        auto_remove_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        auto_remove_box.pack(fill="x", padx=18, pady=(0, 16))
        auto_remove_inner = ctk.CTkFrame(auto_remove_box, fg_color="transparent")
        auto_remove_inner.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(auto_remove_inner, text="🧹 Tự động xoá logo + phụ đề gốc", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            auto_remove_inner,
            text="Tự dò vị trí (không cần vẽ tay) rồi XOÁ THẬT bằng nội suy từ pixel xung quanh (delogo) - tự "
                 "nhiên hơn hẳn so với chỉ làm mờ. Chỉ nhận diện được logo TĨNH ở góc khung hình và phụ đề "
                 "hardsub đủ tương phản - nếu không dò được, dùng 'Làm mờ phụ đề gốc' (vẽ tay) bên dưới thay thế.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, wraplength=560, justify="left",
        ).pack(anchor="w", pady=(4, 8))
        self.auto_remove_original_logo = ctk.BooleanVar(value=False)
        self.auto_remove_original_subtitle = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            auto_remove_inner, text="Tự động xoá logo/watermark kênh gốc (góc khung hình)",
            variable=self.auto_remove_original_logo, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(0, 6))
        ctk.CTkCheckBox(
            auto_remove_inner, text="Tự động xoá phụ đề (hardsub) gốc",
            variable=self.auto_remove_original_subtitle, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w")

        engine_row = ctk.CTkFrame(auto_remove_inner, fg_color="transparent")
        engine_row.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(engine_row, text="Công cụ xoá", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=120, anchor="w").pack(side="left")
        self.watermark_removal_engine = ctk.StringVar(value="delogo")
        ctk.CTkOptionMenu(
            engine_row, variable=self.watermark_removal_engine,
            values=["delogo", "ai"], fg_color=PANEL, button_color=BORDER, button_hover_color=ACCENT,
        ).pack(side="left")
        ctk.CTkLabel(
            auto_remove_inner,
            text="'delogo': ffmpeg, NHANH, chỉ xoá được logo TĨNH ở góc khung hình + hardsub đủ tương phản.  "
                 "'ai': Florence-2 + LaMA (core/ai_watermark_remove.py), dò được ở BẤT KỲ ĐÂU kể cả logo động/nền "
                 "phức tạp, chất lượng cao hơn hẳn nhưng CHẬM HƠN NHIỀU và cần GPU (CUDA) + cài thêm torch/"
                 "transformers/iopaint (xem hướng dẫn cài trong file đó).",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, wraplength=560, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # ----- Làm mờ phụ đề gốc (vẽ tay - phương án dự phòng) -----
        blur_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        blur_box.pack(fill="x", padx=18, pady=(0, 16))
        blur_inner = ctk.CTkFrame(blur_box, fg_color="transparent")
        blur_inner.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(blur_inner, text="Làm mờ phụ đề gốc (vẽ tay - dự phòng khi tự động không dò được)", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w")

        self.blur_original_subtitle = ctk.BooleanVar(value=False)
        self.blur_regions: list = []   # danh sách [(x,y,w,h), ...] - CÓ THỂ chọn NHIỀU vùng cùng lúc
        blur_row = ctk.CTkFrame(blur_inner, fg_color="transparent")
        blur_row.pack(fill="x", pady=(8, 0))
        ctk.CTkCheckBox(blur_row, text="Bật làm mờ", variable=self.blur_original_subtitle, fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="left", padx=(0, 16))
        self.blur_region_label = ctk.CTkLabel(blur_row, text="Chưa chọn vùng nào", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED)
        self.blur_region_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(blur_row, text="🖼 Vẽ vùng cần che", width=140, command=self._open_blur_region_picker).pack(side="right")

        strength_row = ctk.CTkFrame(blur_inner, fg_color="transparent")
        strength_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(strength_row, text="Độ mờ", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(side="left")
        self.blur_strength = ctk.IntVar(value=20)
        self._slider_with_value(strength_row, self.blur_strength, 5, 50, fmt="{:.0f}", step=45)

        # ----- Audio: tắt audio gốc + nhạc nền + âm lượng -----
        audio_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        audio_box.pack(fill="x", padx=18, pady=(0, 16))
        audio_inner = ctk.CTkFrame(audio_box, fg_color="transparent")
        audio_inner.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(audio_inner, text="Âm thanh", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w")

        self.remove_original_audio = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            audio_inner, text="Tắt audio gốc (khi KHÔNG lồng tiếng - nếu có lồng tiếng dùng ô 'Giữ lại audio gốc' ở trên)",
            variable=self.remove_original_audio, fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).pack(anchor="w", pady=(8, 8))

        bg_row = ctk.CTkFrame(audio_inner, fg_color="transparent")
        bg_row.pack(fill="x", pady=(0, 8))
        self.background_music_path = ""
        self.bg_music_label = ctk.CTkLabel(bg_row, text="Chưa chọn nhạc nền", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED)
        self.bg_music_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(bg_row, text="Chọn nhạc nền", width=120, command=self._choose_background_music).pack(side="right")

        vol_grid = ctk.CTkFrame(audio_inner, fg_color="transparent")
        vol_grid.pack(fill="x")
        vol_grid.grid_columnconfigure(0, weight=1)
        vol_grid.grid_columnconfigure(1, weight=1)

        dub_vol_wrap = ctk.CTkFrame(vol_grid, fg_color="transparent")
        dub_vol_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)
        ctk.CTkLabel(dub_vol_wrap, text="Âm lượng giọng đọc", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        self.dub_volume = ctk.DoubleVar(value=1.0)
        self._slider_with_value(dub_vol_wrap, self.dub_volume, 0.0, 2.0, fmt="{:.2f}")

        bg_vol_wrap = ctk.CTkFrame(vol_grid, fg_color="transparent")
        bg_vol_wrap.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)
        ctk.CTkLabel(bg_vol_wrap, text="Âm lượng nhạc nền", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        self.bg_music_volume = ctk.DoubleVar(value=0.18)
        self._slider_with_value(bg_vol_wrap, self.bg_music_volume, 0.0, 1.0, fmt="{:.2f}")

        ctk.CTkLabel(
            audio_inner,
            text="Gợi ý: Âm lượng giọng đọc = 1.00 (nguyên bản, rõ lời nhất). Âm lượng nhạc nền = 0.10-0.20 để nhạc "
                 "chỉ tạo không khí mà không lấn giọng đọc - dưới 0.10 gần như không nghe thấy nhạc, trên 0.30 dễ "
                 "át lời hoặc gây mệt tai khi nghe lâu.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(6, 0))

        # ----- Lật video -----
        flip_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        flip_box.pack(fill="x", padx=18, pady=(0, 16))
        flip_inner = ctk.CTkFrame(flip_box, fg_color="transparent")
        flip_inner.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(flip_inner, text="Lật video", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w")
        flip_row = ctk.CTkFrame(flip_inner, fg_color="transparent")
        flip_row.pack(fill="x", pady=(8, 0))
        self.flip_horizontal = ctk.BooleanVar(value=False)
        self.flip_vertical = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(flip_row, text="Lật ngang (trái-phải)", variable=self.flip_horizontal, fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="left", padx=(0, 16))
        ctk.CTkCheckBox(flip_row, text="Lật dọc (trên-dưới)", variable=self.flip_vertical, fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side="left")

        # ----- Filter hình ảnh -----
        filter_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        filter_box.pack(fill="x", padx=18, pady=(0, 16))
        filter_inner = ctk.CTkFrame(filter_box, fg_color="transparent")
        filter_inner.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(filter_inner, text="Filter hình ảnh", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w")

        self.filter_blur = ctk.DoubleVar(value=0.0)
        self.filter_sharpen = ctk.DoubleVar(value=0.0)
        self.filter_brightness = ctk.DoubleVar(value=0.0)
        self.filter_contrast = ctk.DoubleVar(value=1.0)
        self.filter_saturation = ctk.DoubleVar(value=1.0)
        # Khoảng giá trị đã thu hẹp lại cho SÁT với mức dùng thực tế (khoảng cũ 0-20 cho
        # Blur chẳng hạn hầu như chỉ dùng được tới ~10 là đã mờ nhoè hết chi tiết).
        for label, var, lo, hi, fmt, hint in [
            ("Blur", self.filter_blur, 0.0, 10.0, "{:.1f}", "0 = tắt · 2-4 mờ nhẹ · 6+ mờ mạnh"),
            ("Sharpen", self.filter_sharpen, 0.0, 2.0, "{:.2f}", "0 = tắt · 0.3-0.6 nét nhẹ vừa mắt"),
            ("Brightness", self.filter_brightness, -0.5, 0.5, "{:.2f}", "0 = giữ nguyên · ±0.05-0.15 chỉnh nhẹ"),
            ("Contrast", self.filter_contrast, 0.5, 1.5, "{:.2f}", "1.0 = giữ nguyên · 1.1-1.2 tương phản rõ hơn"),
            ("Saturation", self.filter_saturation, 0.0, 2.0, "{:.2f}", "1.0 = giữ nguyên · 1.1-1.3 màu rực hơn nhẹ · 0 = đen trắng"),
        ]:
            row = ctk.CTkFrame(filter_inner, fg_color="transparent")
            row.pack(fill="x", pady=(8, 0))
            ctk.CTkLabel(row, text=label, font=(FONT_FAMILY, 11), text_color=TEXT_MUTED, width=80, anchor="w").pack(side="left")
            self._slider_with_value(row, var, lo, hi, fmt=fmt)
            hint_row = ctk.CTkFrame(filter_inner, fg_color="transparent")
            hint_row.pack(fill="x")
            ctk.CTkLabel(hint_row, text="", width=80).pack(side="left")
            ctk.CTkLabel(hint_row, text=hint, font=(FONT_FAMILY, 9), text_color=TEXT_MUTED).pack(side="left", pady=(0, 4))

        # ----- Tỉ lệ khung hình & độ phân giải -----
        ratio_box = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        ratio_box.pack(fill="x", padx=18, pady=(0, 20))
        ratio_inner = ctk.CTkFrame(ratio_box, fg_color="transparent")
        ratio_inner.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(ratio_inner, text="Tỉ lệ khung hình & độ phân giải", font=(FONT_FAMILY, 12, "bold")).pack(anchor="w")

        ratio_grid = ctk.CTkFrame(ratio_inner, fg_color="transparent")
        ratio_grid.pack(fill="x", pady=(8, 0))
        ratio_grid.grid_columnconfigure(0, weight=1)
        ratio_grid.grid_columnconfigure(1, weight=1)

        self.aspect_ratio = ctk.StringVar(value="original")
        ar_wrap = ctk.CTkFrame(ratio_grid, fg_color="transparent")
        ar_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(ar_wrap, text="Tỉ lệ khung hình", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkComboBox(
            ar_wrap, values=["original", "16:9", "9:16", "4:3", "1:1"], variable=self.aspect_ratio,
            fg_color=PANEL, border_color=BORDER, button_color=ACCENT,
        ).pack(fill="x", pady=(4, 0))

        self.aspect_mode = ctk.StringVar(value="blur_pad_zoom")
        am_wrap = ctk.CTkFrame(ratio_grid, fg_color="transparent")
        am_wrap.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ctk.CTkLabel(am_wrap, text="Cách xử lý", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkComboBox(
            am_wrap, values=["crop", "pad", "blur_pad", "blur_pad_zoom"], variable=self.aspect_mode,
            fg_color=PANEL, border_color=BORDER, button_color=ACCENT,
        ).pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(
            ratio_inner,
            text="crop = lấp đầy khung mới, cắt mất 2 mép (hợp khi chủ thể luôn ở giữa). pad = giữ trọn nội dung, "
                 "thêm viền ĐEN 2 bên (không mất gì nhưng nhìn hơi cũ). blur_pad = giữ trọn nội dung, nền 2 bên là "
                 "CHÍNH video đó phóng to + làm mờ thay viền đen - cách phổ biến nhất trên TikTok/Reels/Shorts, "
                 "CapCut gọi là \"Background blur\". blur_pad_zoom = giống blur_pad nhưng phóng to nội dung chính "
                 "thêm ~8% cho đầy khung hơn (mất rất ít 2 mép) - đây cũng là mặc định của CapCut, khuyên dùng nếu "
                 "muốn video 16:9 -> 9:16 KHÔNG mất góc mà vẫn nhìn mượt, chuyên nghiệp.",
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=520,
        ).pack(anchor="w", pady=(6, 0))

        self.resolution = ctk.StringVar(value="original")
        res_wrap = ctk.CTkFrame(ratio_inner, fg_color="transparent")
        res_wrap.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(res_wrap, text="Độ phân giải", font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkComboBox(
            res_wrap, values=["original", "480p", "720p", "1080p", "1440p", "4k"], variable=self.resolution,
            fg_color=PANEL, border_color=BORDER, button_color=ACCENT,
        ).pack(fill="x", pady=(4, 0))

        self._build_render_variant_section(parent)

    def _build_render_variant_section(self, parent):
        """Tuỳ chọn chỉnh sửa nhẹ video cuối cùng nhưng LUÔN chỉ giữ 1 video đầu ra.

        Khi tắt: pipeline xuất đúng 1 video bình thường.
        Khi bật: tạo 1 bản chỉnh sửa tạm, thay thế video cuối cùng rồi xoá toàn bộ
        file/thư mục trung gian. Không tạo thư mục ``bien_the`` và không tạo thêm
        video thứ hai.
        """
        variant_box = ctk.CTkFrame(
            parent, fg_color=PANEL2, corner_radius=RADIUS_CARD,
            border_width=1, border_color=BORDER_SOFT,
        )
        variant_box.pack(fill="x", padx=18, pady=(0, 20))
        variant_inner = ctk.CTkFrame(variant_box, fg_color="transparent")
        variant_inner.pack(fill="x", padx=16, pady=14)

        self.variant_enabled = ctk.BooleanVar(value=False)
        variant_check = ctk.CTkCheckBox(
            variant_inner,
            text="🎲 Chỉnh sửa nhẹ video cuối cùng (vẫn chỉ xuất 1 video)",
            variable=self.variant_enabled, font=(FONT_FAMILY, 12, "bold"),
        )
        variant_check.pack(anchor="w")

        ctk.CTkLabel(
            variant_inner,
            text=(
                "Tắt = xuất 1 video bình thường. Bật = áp dụng 1 lần chỉnh sửa nhẹ lên chính video cuối cùng "
                "(màu sắc/tương phản/zoom/hạt film/bitrate...), sau đó thay thế video gốc. Không tạo thêm video, "
                "không tạo thư mục bien_the. Kết quả cuối cùng luôn chỉ gồm: 1 video.mp4 + NOTE.txt + translated.srt."
            ),
            font=(FONT_FAMILY, 10), text_color=TEXT_MUTED, justify="left", wraplength=560,
        ).pack(anchor="w", pady=(4, 10))

        if not VARIANT_RENDER_AVAILABLE:
            variant_check.configure(state="disabled")
            self.variant_enabled.set(False)
            ctk.CTkLabel(
                variant_inner,
                text=(
                    f"⚠ Không tải được module render biến thể (core/render_variant.py): "
                    f"{VARIANT_RENDER_IMPORT_ERROR or 'không tìm thấy file'}."
                ),
                font=(FONT_FAMILY, 10), text_color="#e07a5f",
                justify="left", wraplength=560,
            ).pack(anchor="w", pady=(8, 0))

    def _list_voice_profiles(self) -> list[str]:
        """Quét thư mục voice_profiles để tìm các profile (*.json) đã lưu bằng setup_voice_clone.py."""
        if not os.path.isdir(self.voice_profiles_dir):
            return []
        names = []
        for f in sorted(os.listdir(self.voice_profiles_dir)):
            if f.lower().endswith(".json"):
                names.append(os.path.splitext(f)[0])
        return names

    def _refresh_voice_profiles(self):
        names = self._list_voice_profiles()
        self.voice_name_combo.configure(values=names)
        if names:
            if self.voice_name.get() not in names:
                self.voice_name.set(names[0])
            self.clone_hint_label.configure(
                text=f"Tìm thấy {len(names)} voice profile: {', '.join(names)}",
                text_color=TEXT_MUTED,
            )
        else:
            self.voice_name.set("")
            self.clone_hint_label.configure(
                text="Chưa có voice profile nào. Chạy 'python setup_voice_clone.py --source ... --name ...' "
                     "trên máy bạn trước, sau đó bấm 🔄 để tải lại danh sách.",
                text_color=TEXT_MUTED,
            )
        # Ô Giọng Nam/Nữ (Lồng tiếng) cũng dùng chung danh sách voice profile này làm gợi ý
        # ban đầu (rẻ, không cần load model VieNeu-TTS) - bấm "🔄 Tải giọng dựng sẵn" để bổ
        # sung thêm các giọng dựng sẵn của VieNeu-TTS vào 2 ô này.
        if hasattr(self, "vieneu_male_combo"):
            self.vieneu_male_combo.configure(values=[""] + names)
            self.vieneu_female_combo.configure(values=[""] + names)

    def _reload_edge_voice_options(self):
        """Nạp danh sách giọng Edge (Nam/Nữ) theo đúng ngôn ngữ đích đang chọn vào 2
        combo 'Giọng Nam'/'Giọng Nữ' trong mục Lồng tiếng · Edge. Không cần tải model
        gì (khác VieNeu) - chỉ là danh sách tên giọng có sẵn (core/tts.py:list_edge_voice_options),
        nên chạy được ngay trên main thread, không cần thread nền."""
        if not hasattr(self, "edge_male_combo"):
            return
        try:
            from core.tts import list_edge_voice_options
            options = list_edge_voice_options(self.target_lang.get())
        except Exception as e:
            self.edge_voice_hint.configure(text=f"⚠ Không tải được danh sách giọng Edge: {e}")
            return

        male_ids = options.get("male", [])
        female_ids = options.get("female", [])
        self.edge_male_combo.configure(values=[""] + male_ids)
        self.edge_female_combo.configure(values=[""] + female_ids)
        # Neu gia tri dang chon khong con hop le voi ngon ngu moi (vd doi tu Chinese
        # sang Vietnamese) thi tu dong xoa de tranh dung nham ten giong sai ngon ngu.
        if self.edge_voice_male.get() not in ([""] + male_ids):
            self.edge_voice_male.set("")
        if self.edge_voice_female.get() not in ([""] + female_ids):
            self.edge_voice_female.set("")
        total = len(male_ids) + len(female_ids)
        self.edge_voice_hint.configure(
            text=f"Đã tải {total} lựa chọn giọng Edge cho ngôn ngữ '{self.target_lang.get()}'. "
                 f"Để trống ô nào = giới tính đó dùng giọng mặc định của ngôn ngữ đang chọn.",
        )

    def _reload_edge_voice_options_full(self):
        """Tải TOÀN BỘ danh sách giọng Edge thật từ server Microsoft (không giới hạn
        theo ngôn ngữ đích đang chọn) - vài trăm giọng, đủ mọi ngôn ngữ/vùng miền.
        Cần mạng, chạy trong thread nền để không đứng hình GUI."""
        if not hasattr(self, "edge_male_combo"):
            return
        self.edge_voice_hint.configure(text="Đang tải toàn bộ giọng Edge từ Microsoft (cần mạng, vài giây)...")

        def worker():
            try:
                from core.tts import fetch_all_edge_voices
                options = fetch_all_edge_voices()
            except Exception as e:
                err_msg = f"⚠ Không tải được danh sách đầy đủ giọng Edge: {e}"
                self.after(0, lambda: self.edge_voice_hint.configure(text=err_msg))
                return
            self.after(0, lambda: self._apply_edge_voice_options_full(options))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_edge_voice_options_full(self, options: dict):
        male_ids = options.get("male", [])
        female_ids = options.get("female", [])
        self.edge_male_combo.configure(values=[""] + male_ids)
        self.edge_female_combo.configure(values=[""] + female_ids)
        total = len(male_ids) + len(female_ids)
        self.edge_voice_hint.configure(
            text=f"Đã tải TOÀN BỘ {total} giọng Edge (mọi ngôn ngữ/vùng miền). "
                 f"Để trống ô nào = giới tính đó dùng giọng mặc định của ngôn ngữ đang chọn.",
        )


    def _reload_vieneu_voice_options(self):
        """Tải danh sách giọng dựng sẵn của VieNeu-TTS (phải load full model - có thể
        mất vài giây đến vài phút ở lần đầu) để bổ sung vào ô "Giọng của bạn" VÀ 2 ô
        Giọng Nam/Nữ (Lồng tiếng). Chạy trong thread nền để không đứng hình GUI."""
        loading_msg = "Đang tải giọng dựng sẵn VieNeu-TTS (lần đầu có thể chậm)..."
        self.clone_hint_label.configure(text=loading_msg)
        if hasattr(self, "vieneu_voice_hint"):
            self.vieneu_voice_hint.configure(text=loading_msg)

        def worker():
            try:
                from core.vieneu_tts import list_all_vieneu_voice_options
                options = list_all_vieneu_voice_options(self.voice_profiles_dir)
            except Exception as e:
                err_msg = f"⚠ Không tải được danh sách giọng VieNeu-TTS: {e}"
                self.after(0, lambda: self.clone_hint_label.configure(text=err_msg))
                if hasattr(self, "vieneu_voice_hint"):
                    self.after(0, lambda: self.vieneu_voice_hint.configure(text=err_msg))
                return
            self.after(0, lambda: self._apply_vieneu_voice_options(options))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_vieneu_voice_options(self, options: list[tuple[str, str]]):
        ids = [vid for _label, vid in options]

        # Ô "Giọng của bạn" - giữ nguyên lựa chọn đang chọn nếu vẫn còn trong danh sách mới
        current = self.voice_name.get()
        self.voice_name_combo.configure(values=ids)
        if current and current in ids:
            self.voice_name.set(current)
        self.clone_hint_label.configure(
            text=f"Đã tải {len(ids)} lựa chọn cho VieNeu-TTS (voice profile của bạn + giọng dựng "
                 f"sẵn có trong model). Chọn 1 giọng ở ô trên, hoặc để trống để dùng giọng mặc định.",
            text_color=TEXT_MUTED,
        )

        # 2 ô Giọng Nam/Nữ (Lồng tiếng)
        if hasattr(self, "vieneu_male_combo"):
            self.vieneu_male_combo.configure(values=[""] + ids)
            self.vieneu_female_combo.configure(values=[""] + ids)
            self.vieneu_voice_hint.configure(
                text=f"Đã tải {len(ids)} lựa chọn (voice profile + giọng dựng sẵn VieNeu-TTS). "
                     f"Để trống ô nào = giới tính đó dùng giọng nền ('Giọng của bạn' ở trên)."
            )

    def _on_tts_engine_change(self):
        # "clone" (XTTS-v2), "vieneu" (VieNeu-TTS) và "omnivoice" (OmniVoice) đều
        # dùng chung ô "Giọng của bạn": với "vieneu", voice_name có thể là tên voice
        # profile (clone) hoặc để trống (dùng giọng mặc định) hoặc gõ tay 1 ID giọng
        # dựng sẵn của VieNeu-TTS; với "omnivoice", để trống thì dùng khung "OmniVoice
        # · Voice Design" bên dưới thay vì clone.
        engine = self.tts_engine.get()
        needs_voice_field = engine in ("clone", "vieneu", "omnivoice")
        state = "normal" if needs_voice_field else "disabled"
        try:
            self.voice_name_combo.configure(state=state)
        except Exception:
            pass

        # "Lồng tiếng · Giọng lồng · Edge (online)" chỉ áp dụng cho engine="online".
        if hasattr(self, "edge_gender_section"):
            if engine == "online":
                self.edge_gender_section.pack(fill="x", padx=0, pady=(4, 0))
            else:
                self.edge_gender_section.pack_forget()

        # "Lồng tiếng · Giọng lồng · Tiếng Việt" chỉ áp dụng cho engine="vieneu"
        # (gán giọng riêng Nam/Nữ) - ẩn hẳn khi dùng engine khác để đỡ rối UI.
        if hasattr(self, "vieneu_gender_section"):
            if engine == "vieneu":
                self.vieneu_gender_section.pack(fill="x", padx=0, pady=(4, 0))
            else:
                self.vieneu_gender_section.pack_forget()

        # "OmniVoice · Voice Design" chỉ áp dụng cho engine="omnivoice" - ẩn hẳn khi
        # dùng engine khác để đỡ rối UI.
        if hasattr(self, "omnivoice_section"):
            if engine == "omnivoice":
                self.omnivoice_section.pack(fill="x", padx=0, pady=(4, 0))
            else:
                self.omnivoice_section.pack_forget()

    def _apply_omni_preset(self, picked_label, labels_dict, gender_var, age_var, pitch_var, accent_var, dialect_var):
        """Khi chọn 1 preset đặt tên (Adam, Emma...) trong dropdown, tự điền các
        dropdown thuộc tính (Tuỳ chỉnh nâng cao) tương ứng. Chọn '-- Tuỳ chỉnh --'
        hoặc '-- Dùng giọng mặc định --' thì không đổi gì (giữ nguyên lựa chọn tay
        hiện có, cho phép tinh chỉnh tiếp sau khi áp preset)."""
        info = labels_dict.get(picked_label)
        if info is not None:
            _name, gender, age, pitch, accent = info
            if gender_var is not None:
                gender_var.set(_OMNI_GENDER_REV.get(gender, OMNI_NONE_LABEL))
            age_var.set(_OMNI_AGE_REV.get(age, OMNI_NONE_LABEL))
            pitch_var.set(_OMNI_PITCH_REV.get(pitch, OMNI_NONE_LABEL))
            accent_var.set(_OMNI_ACCENT_REV.get(accent, OMNI_NONE_LABEL))
            dialect_var.set(OMNI_NONE_LABEL)  # preset không dùng phương ngữ Trung
        self._update_omnivoice_preview()

    def _omni_instruct_from(self, gender_var=None, age_var=None, pitch_var=None, style_var=None, accent_var=None, dialect_var=None):
        """Đổi các lựa chọn dropdown (nhãn tiếng Việt) sang 1 chuỗi `instruct` hợp
        lệ cho OmniVoice bằng core/omnivoice_tts.py:build_instruct. Trả về None nếu
        TẤT CẢ đều để '-- Không chọn --' (không dùng voice design cho phần đó)."""
        def _val(var, labels_dict):
            return labels_dict.get(var.get()) if var is not None else None

        return omnivoice_build_instruct(
            gender=_val(gender_var, OMNI_GENDER_LABELS),
            age=_val(age_var, OMNI_AGE_LABELS),
            pitch=_val(pitch_var, OMNI_PITCH_LABELS),
            style=_val(style_var, OMNI_STYLE_LABELS),
            accent=_val(accent_var, OMNI_ACCENT_LABELS),
            dialect=_val(dialect_var, OMNI_DIALECT_LABELS),
        )

    def _build_omnivoice_instructs(self):
        """Trả về (instruct_mặc_định, instruct_nam, instruct_nữ) - dùng khi build
        PipelineConfig. instruct_nam/nữ chỉ khác None nếu người dùng có chọn ít
        nhất 1 thuộc tính riêng cho giới tính đó."""
        default = self._omni_instruct_from(
            self.omni_gender, self.omni_age, self.omni_pitch,
            self.omni_style, self.omni_accent, self.omni_dialect,
        )
        male = self._omni_instruct_from(
            gender_var=None, age_var=self.omni_male_age, pitch_var=self.omni_male_pitch,
            accent_var=self.omni_male_accent, dialect_var=self.omni_male_dialect,
        )
        female = self._omni_instruct_from(
            gender_var=None, age_var=self.omni_female_age, pitch_var=self.omni_female_pitch,
            accent_var=self.omni_female_accent, dialect_var=self.omni_female_dialect,
        )
        # Giọng riêng theo giới tính không tự chọn "male"/"female" trong instruct
        # (đã ngầm hiểu qua đúng cột Nam/Nữ đang điền) - nhưng OmniVoice generate()
        # vẫn cần biết rõ giới tính nếu người dùng có chọn ít nhất 1 thuộc tính khác,
        # nên tự thêm vào để tránh model tự đoán sai giới tính.
        if male:
            male = f"male, {male}"
        if female:
            female = f"female, {female}"
        return default, male, female

    def _update_omnivoice_preview(self):
        if not hasattr(self, "omnivoice_preview"):
            return
        default, _male, _female = self._build_omnivoice_instructs()
        text = f"Chuỗi mô tả sẽ dùng: \"{default}\"" if default else "Chuỗi mô tả sẽ dùng: (model tự chọn giọng - auto voice)"
        self.omnivoice_preview.configure(text=text)

    def _labeled_combo(self, parent, label, var, values, row, col):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=col, sticky="ew", padx=8, pady=8)
        parent.grid_columnconfigure(col, weight=1)
        ctk.CTkLabel(wrap, text=label, font=(FONT_FAMILY, 11), text_color=TEXT_MUTED).pack(anchor="w")
        ctk.CTkComboBox(wrap, values=values, variable=var, fg_color=PANEL2, border_color=BORDER, button_color=ACCENT, width=280).pack(fill="x", pady=(4, 0))

    @staticmethod
    def _safe_float(text: str, default: float = 0.0) -> float:
        """Parse chuỗi từ 1 ô nhập StringVar thành float an toàn - trả về `default`
        nếu ô đang trống hoặc gõ dở (vd '', '-', '1.') thay vì crash."""
        try:
            return float(str(text).strip().replace(",", "."))
        except (ValueError, TypeError):
            return default

    def _slider_with_value(self, parent, var, from_, to, fmt="{:.2f}", step=None, value_width=52):
        """
        Tạo 1 CTkSlider đi kèm Ô SỐ NHẬP TRỰC TIẾP ngay cạnh nó (2 chiều: kéo
        slider thì số tự cập nhật, gõ số vào ô thì slider tự nhảy tới đúng vị
        trí) - để chỉnh số chính xác thay vì phải kéo chuột ướm chừng.
        Trả về (slider, value_entry) nếu cần tuỳ biến thêm.
        """
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", expand=True, side="left")

        value_var = ctk.StringVar(value=fmt.format(var.get()))

        def _on_slider_move(v):
            value_var.set(fmt.format(float(v)))

        slider = ctk.CTkSlider(
            row, from_=from_, to=to, variable=var, number_of_steps=step,
            fg_color=BORDER, progress_color=ACCENT, command=_on_slider_move,
        )
        slider.pack(side="left", fill="x", expand=True, padx=(0, 10))

        def _on_entry_commit(event=None):
            try:
                v = float(value_var.get())
            except ValueError:
                value_var.set(fmt.format(var.get()))
                return
            v = max(from_, min(to, v))
            var.set(v)
            value_var.set(fmt.format(v))

        value_entry = ctk.CTkEntry(row, textvariable=value_var, width=value_width, fg_color=PANEL, border_color=BORDER, justify="center")
        value_entry.pack(side="left")
        value_entry.bind("<Return>", _on_entry_commit)
        value_entry.bind("<FocusOut>", _on_entry_commit)

        return slider, value_entry

    def _build_right_panel(self, parent):
        ctk.CTkLabel(parent, text="PREVIEW / LOG", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=16, pady=(16, 8))

        # --- Khung xem trước video (trích 1 khung hình bằng ffmpeg, có thể tua) ---
        preview_frame = ctk.CTkFrame(parent, fg_color=PANEL2, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER_SOFT)
        preview_frame.pack(fill="x", padx=16, pady=(0, 10))

        self.preview_canvas = ctk.CTkLabel(
            preview_frame, text="Chưa có video\nđể xem trước",
            fg_color="#000000", text_color=TEXT_MUTED,
            width=300, height=170, corner_radius=6,
        )
        self.preview_canvas.pack(padx=8, pady=(8, 4))
        self._preview_photo = None       # giữ tham chiếu ImageTk, tránh bị garbage-collected
        self._preview_video_dur = 0.0     # thời lượng (giây) của video đang xem trước
        self._preview_after_id = None     # id job debounce khi kéo thanh tua

        self.preview_time_label = ctk.CTkLabel(preview_frame, text="00:00 / 00:00", font=(FONT_FAMILY, 10), text_color=TEXT_MUTED)
        self.preview_time_label.pack(padx=8, anchor="w")

        self.preview_slider = ctk.CTkSlider(
            preview_frame, from_=0, to=100, number_of_steps=200,
            command=self._on_preview_scrub, fg_color=BORDER, progress_color=ACCENT,
        )
        self.preview_slider.set(0)
        self.preview_slider.pack(fill="x", padx=8, pady=(0, 8))

        btn_row = ctk.CTkFrame(preview_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(
            btn_row, text="⟳ Làm mới", width=90, height=26, fg_color=PANEL, hover_color=BORDER,
            command=self._refresh_video_preview,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="▶ Mở bằng trình phát mặc định", height=26, fg_color=PANEL, hover_color=BORDER,
            command=self._open_video_in_player,
        ).pack(side="left", padx=(6, 0), fill="x", expand=True)

        self.progress = ctk.CTkProgressBar(parent, fg_color=BORDER, progress_color=ACCENT)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=16, pady=(0, 8))

        self.status_label = ctk.CTkLabel(parent, text="Sẵn sàng", font=(FONT_FAMILY, 12), text_color=TEXT_MUTED, wraplength=300, justify="left")
        self.status_label.pack(anchor="w", padx=16)

        self.log_box = ctk.CTkTextbox(parent, fg_color=PANEL2, height=340, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=16, pady=16)
        self.log_box.insert("end", "> Reup Studio đã sẵn sàng.\n")
        self.log_box.configure(state="disabled")

    # ---------- Xem trước video ----------
    @staticmethod
    def _fmt_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _refresh_video_preview(self):
        """Đọc lại thời lượng video hiện tại + hiển thị khung hình ở vị trí thanh tua đang đứng."""
        path = getattr(self, "_video_full_path", None)
        if not path or not os.path.isfile(path):
            self.preview_canvas.configure(image=None, text="Chưa có video\nđể xem trước")
            self._preview_photo = None
            self._preview_video_dur = 0.0
            self.preview_time_label.configure(text="00:00 / 00:00")
            return
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            self._preview_video_dur = max(0.1, float(probe.stdout.strip() or 0.1))
        except Exception:
            self._preview_video_dur = 0.1
        self.preview_slider.set(0)
        self._show_preview_at_fraction(0.0)

    def _on_preview_scrub(self, _value=None):
        """Người dùng kéo thanh tua -> debounce 150ms rồi mới trích frame (đỡ gọi ffmpeg liên tục)."""
        if not getattr(self, "_video_full_path", None):
            return
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        frac = self.preview_slider.get() / 100.0
        self._preview_after_id = self.after(150, lambda: self._show_preview_at_fraction(frac))

    def _show_preview_at_fraction(self, frac: float):
        path = getattr(self, "_video_full_path", None)
        if not path or not os.path.isfile(path) or self._preview_video_dur <= 0:
            return
        t = max(0.0, min(self._preview_video_dur - 0.05, frac * self._preview_video_dur))
        self.preview_time_label.configure(text=f"{self._fmt_time(t)} / {self._fmt_time(self._preview_video_dur)}")

        os.makedirs(self.work_dir, exist_ok=True)
        thumb_path = os.path.join(self.work_dir, "_preview_thumb.jpg")
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale=300:-1", thumb_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if proc.returncode != 0 or not os.path.exists(thumb_path):
                return
            img = Image.open(thumb_path)
            img.thumbnail((300, 170))
            photo = ImageTk.PhotoImage(img)
            self._preview_photo = photo  # giữ tham chiếu
            self.preview_canvas.configure(image=photo, text="")
        except Exception as e:
            self.log(f"⚠ Không xem trước được frame: {e}")

    def _open_video_in_player(self):
        """Mở video ĐẦU VÀO bằng trình phát mặc định của hệ điều hành - dùng để xem toàn bộ
        chuyển động thật (kéo/tua mượt), vì khung xem trước bên trong app chỉ hiện được từng
        khung hình tĩnh, không phát được video trực tiếp."""
        path = getattr(self, "_video_full_path", None)
        if not path or not os.path.isfile(path):
            messagebox.showwarning("Chưa chọn video", "Chọn video đầu vào trước.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không mở được video: {e}")


    # ---------- Actions ----------
    def _reset_steps(self):
        for s in STEPS:
            self.steps_panel.set_state(s, "pending")

    def choose_video(self):
        exts = " ".join(f"*{e}" for e in sorted(UIH.VIDEO_EXTS))
        initial = self.last_video_dir.get()
        path = filedialog.askopenfilename(
            title="Chọn video",
            initialdir=initial if initial and os.path.isdir(initial) else None,
            filetypes=[("Video files", exts), ("All files", "*.*")],
        )
        if path:
            self._set_video_path(path)

    def _set_video_path(self, path: str):
        """Đặt video đầu vào (dùng chung cho nút Chọn video, kéo-thả và phím tắt)."""
        self.video_path.set(os.path.basename(path))
        self._video_full_path = path
        try:
            self.last_video_dir.set(os.path.dirname(path))
        except Exception:
            pass
        self._refresh_video_preview()
        self.log(f"Đã chọn video: {path}")

    def _on_drop_files(self, event):
        """Kéo-thả file/thư mục video vào cửa sổ -> chuyển sang Translate và chọn video đầu tiên."""
        if getattr(self, "_batch_running", False):
            self.toast.show("Đang render hàng loạt - chưa đổi video lúc này.", "warn")
            return
        vids = UIH.pick_videos(UIH.parse_dropped_files(self, event.data))
        if not vids:
            self.toast.show("Không thấy file video hợp lệ trong thứ vừa thả.", "warn")
            return
        self.show_page("Translate")
        self._set_video_path(vids[0])
        if len(vids) > 1:
            self.toast.show(f"Đã chọn {os.path.basename(vids[0])}. Có {len(vids)} video - dùng 'Render cả thư mục' để chạy hàng loạt.", "info", 4500)
        else:
            self.toast.show(f"Đã chọn: {os.path.basename(vids[0])}", "ok")

    def _shortcut_open_video(self):
        self.show_page("Translate")
        self.choose_video()

    def _shortcut_start(self):
        if self.run_btn.cget("state") == "normal" and not self._batch_running:
            self.start_pipeline()
        else:
            self.toast.show("Đang xử lý - chờ xong rồi bấm lại.", "warn")

    def _choose_watermark_logo(self):
        path = filedialog.askopenfilename(
            title="Chọn ảnh logo",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if path:
            self.watermark_logo_path = path
            self.watermark_logo_label.configure(text=os.path.basename(path), text_color="white")
            self.do_watermark_logo.set(True)  # tự bật checkbox Logo khi đã chọn xong ảnh - đỡ phải tick tay

    def _choose_background_music(self):
        path = filedialog.askopenfilename(
            title="Chọn nhạc nền",
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.aac"), ("All files", "*.*")],
        )
        if path:
            self.background_music_path = path
            self.bg_music_label.configure(text=os.path.basename(path), text_color="white")
            # Mặc định TẮT audio gốc khi đã chọn nhạc nền - tránh tiếng ồn/nhạc gốc của
            # video đè lên nhạc nền vừa thêm, nghe rối. Áp dụng cho CẢ 2 trường hợp: có
            # lồng tiếng (bỏ tick "Giữ lại audio gốc") lẫn không lồng tiếng (tick "Tắt
            # audio gốc"). Người dùng vẫn có thể tự tick lại nếu thật sự muốn giữ.
            self.remove_original_audio.set(True)
            self.keep_original_audio.set(False)

    def _get_sample_frame(self, time_sec: float | None = None):
        """Trích 1 frame TẠI THỜI ĐIỂM time_sec của video input hiện tại (dùng ffmpeg)
        + kích thước gốc + tổng thời lượng (dùng ffprobe). time_sec=None (mặc định) =
        lấy khung hình ở GIỮA video như hành vi cũ.
        Trả về (đường dẫn ảnh jpg tạm, video_w, video_h, duration_giây) hoặc
        (None, 0, 0, 0) nếu lỗi/chưa chọn video."""
        path = getattr(self, "_video_full_path", None)
        if not path:
            messagebox.showwarning("Chưa chọn video", "Chọn video đầu vào trước khi chọn vùng/vị trí trên khung hình mẫu.")
            return None, 0, 0, 0
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,duration",
                 "-of", "csv=p=0", path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            parts = probe.stdout.strip().split(",")
            w, h = int(parts[0]), int(parts[1])
            dur = float(parts[2]) if len(parts) > 2 and parts[2] not in ("", "N/A") else 5.0
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không đọc được thông tin video: {e}")
            return None, 0, 0, 0

        seek_at = time_sec if time_sec is not None else max(0.1, dur / 2)
        seek_at = max(0.0, min(dur - 0.05 if dur > 0.1 else 0.0, seek_at))

        frame_path = os.path.join(self.work_dir, "_preview_frame.jpg")
        os.makedirs(self.work_dir, exist_ok=True)
        proc = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(seek_at), "-i", path, "-frames:v", "1", frame_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if proc.returncode != 0 or not os.path.exists(frame_path):
            messagebox.showerror("Lỗi", f"Không trích được khung hình mẫu:\n{proc.stdout[-800:]}")
            return None, 0, 0, 0
        return frame_path, w, h, dur

    def _resolve_subtitle_position_fracs(self, silent: bool = False):
        """Tính lại x_frac/y_frac cho vị trí phụ đề THEO ĐÚNG chế độ đang chọn ở
        'Vị trí phụ đề' - gọi cả khi người dùng bấm radio 'Đè lên vùng che mờ' LẪN
        ngay trước khi submit dịch (đảm bảo luôn dùng đúng vùng che mờ MỚI NHẤT,
        phòng trường hợp người dùng sửa lại vùng che mờ SAU KHI đã chọn radio này).
        Trả về (x_frac, y_frac) - cũng tự cập nhật self.subtitle_pos_x_frac/y_frac
        và nhãn hiển thị nếu đang ở chế độ 'blur_region'."""
        if self.subtitle_position_mode.get() != "blur_region":
            return self.subtitle_pos_x_frac.get(), self.subtitle_pos_y_frac.get()

        if not self.blur_regions:
            if not silent:
                messagebox.showwarning(
                    "Chưa có vùng che mờ",
                    "Vẽ ít nhất 1 vùng che mờ trước (phần 'Xoá phụ đề/logo gốc' ở Export), "
                    "rồi quay lại chọn chế độ này.",
                )
            return self.subtitle_pos_x_frac.get(), self.subtitle_pos_y_frac.get()

        path = getattr(self, "_video_full_path", None)
        if not path:
            return self.subtitle_pos_x_frac.get(), self.subtitle_pos_y_frac.get()
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            vw_str, vh_str = probe.stdout.strip().split(",")[:2]
            vw, vh = int(vw_str), int(vh_str)
        except Exception:
            return self.subtitle_pos_x_frac.get(), self.subtitle_pos_y_frac.get()

        x, y, w, h = self.blur_regions[-1]   # dùng khung vẽ SAU CÙNG nếu có nhiều khung
        cx_frac = (x + w / 2) / vw
        cy_frac = (y + h / 2) / vh
        self.subtitle_pos_x_frac.set(cx_frac)
        self.subtitle_pos_y_frac.set(cy_frac)
        self.subtitle_pos_label.configure(
            text=f"Vị trí: theo vùng che mờ (x={cx_frac*100:.0f}%, y={cy_frac*100:.0f}%)", text_color="white",
        )
        return cx_frac, cy_frac

    def _open_subtitle_position_picker(self):
        """Mở cửa sổ hiển thị khung hình mẫu, cho phép KÉO 1 khung chữ nhật minh
        hoạ tới vị trí mong muốn để đặt phụ đề - dùng khi chế độ 'Tự chọn vị trí'
        (không phụ thuộc vùng che mờ)."""
        frame_path, vw, vh, _dur = self._get_sample_frame()
        if not frame_path:
            return

        top = ctk.CTkToplevel(self)
        top.title("Chọn vị trí phụ đề - kéo khung tới vị trí mong muốn")
        top.grab_set()

        img = Image.open(frame_path)
        max_disp_w, max_disp_h = 720, 560
        scale = min(max_disp_w / img.width, max_disp_h / img.height)
        disp_w = max(1, int(img.width * scale))
        disp_h = max(1, int(img.height * scale))
        img_resized = img.resize((disp_w, disp_h))
        photo = ImageTk.PhotoImage(img_resized)

        canvas = tk.Canvas(top, width=disp_w, height=disp_h, highlightthickness=0)
        canvas.pack(padx=10, pady=10)
        canvas.image = photo  # giữ tham chiếu, tránh bị garbage-collected
        canvas.create_image(0, 0, anchor="nw", image=photo)

        hint = ctk.CTkLabel(top, text="Kéo khung chữ nhật tới vị trí muốn đặt phụ đề.", text_color=TEXT_MUTED)
        hint.pack(pady=(0, 6))

        state = {
            "x_frac": self.subtitle_pos_x_frac.get(),
            "y_frac": self.subtitle_pos_y_frac.get(),
            "dragging": False,
            "drag_start": (0, 0),
        }
        box_id = {"id": None}
        # Kích thước khung minh hoạ - chỉ để hình dung, KHÔNG ảnh hưởng cỡ chữ thật
        # (cỡ chữ do ô 'Cỡ chữ' ở trên quyết định) - phụ đề thật sẽ tự co theo nội
        # dung, canh giữa đúng tại điểm x_frac/y_frac này.
        BOX_W_FRAC, BOX_H_FRAC = 0.6, 0.12

        def _box_disp():
            half_w = BOX_W_FRAC * disp_w / 2
            half_h = BOX_H_FRAC * disp_h / 2
            cx = state["x_frac"] * disp_w
            cy = state["y_frac"] * disp_h
            return cx, cy, half_w, half_h

        def _redraw():
            if box_id["id"] is not None:
                canvas.delete(box_id["id"])
            cx, cy, half_w, half_h = _box_disp()
            box_id["id"] = canvas.create_rectangle(
                cx - half_w, cy - half_h, cx + half_w, cy + half_h,
                outline=ACCENT, width=2, dash=(4, 2),
            )
            hint.configure(text=f"Vị trí: x={state['x_frac']*100:.0f}%, y={state['y_frac']*100:.0f}%")

        _redraw()

        def on_press(event):
            cx, cy, half_w, half_h = _box_disp()
            if abs(event.x - cx) <= half_w and abs(event.y - cy) <= half_h:
                state["dragging"] = True
                state["drag_start"] = (event.x - cx, event.y - cy)

        def on_drag(event):
            if state["dragging"]:
                offx, offy = state["drag_start"]
                new_cx = event.x - offx
                new_cy = event.y - offy
                state["x_frac"] = max(0.0, min(1.0, new_cx / disp_w))
                state["y_frac"] = max(0.0, min(1.0, new_cy / disp_h))
                _redraw()

        def on_release(event):
            state["dragging"] = False

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

        def confirm():
            self.subtitle_pos_x_frac.set(state["x_frac"])
            self.subtitle_pos_y_frac.set(state["y_frac"])
            self.subtitle_position_mode.set("custom")
            self.subtitle_pos_label.configure(
                text=f"Vị trí: tự chọn (x={state['x_frac']*100:.0f}%, y={state['y_frac']*100:.0f}%)", text_color="white",
            )
            top.destroy()

        btn_row = ctk.CTkFrame(top, fg_color="transparent")
        btn_row.pack(pady=(0, 10))
        ctk.CTkButton(btn_row, text="Xác nhận", fg_color=ACCENT, hover_color=ACCENT_HOVER, command=confirm).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Huỷ", fg_color=PANEL2, command=top.destroy).pack(side="left", padx=6)
        top.resizable(False, False)
        self._center_toplevel(top)

    def _open_watermark_position_picker(self):
        """Mở cửa sổ hiển thị khung hình mẫu, hiện SẴN ảnh logo thật (nếu đã chọn) đè
        lên đúng vị trí/kích thước hiện tại - cho phép:
          - KÉO vào giữa logo để DI CHUYỂN (đổi vị trí x/y).
          - KÉO ô vuông nhỏ ở GÓC DƯỚI-PHẢI logo để PHÓNG TO/THU NHỎ (đổi kích thước).
        Giúp ước lượng trực quan ngay trên khung hình, không cần đoán qua slider."""
        frame_path, vw, vh, _dur = self._get_sample_frame()
        if not frame_path:
            return

        top = ctk.CTkToplevel(self)
        top.title("Chọn vị trí + kích thước watermark - kéo để di chuyển, kéo góc để phóng to/nhỏ")
        top.grab_set()

        img = Image.open(frame_path)
        max_disp_w, max_disp_h = 720, 560
        scale = min(max_disp_w / img.width, max_disp_h / img.height)
        disp_w = max(1, int(img.width * scale))
        disp_h = max(1, int(img.height * scale))
        img_resized = img.resize((disp_w, disp_h))
        photo = ImageTk.PhotoImage(img_resized)

        canvas = tk.Canvas(top, width=disp_w, height=disp_h, highlightthickness=0)
        canvas.pack(padx=10, pady=10)
        canvas.image = photo  # giữ tham chiếu, tránh bị garbage-collected
        canvas.create_image(0, 0, anchor="nw", image=photo)

        hint = ctk.CTkLabel(top, text="Kéo logo để di chuyển, kéo ô vuông ở góc để đổi kích thước.", text_color=TEXT_MUTED)
        hint.pack(pady=(0, 6))

        logo_path = self.watermark_logo_path or None
        logo_img_original = Image.open(logo_path).convert("RGBA") if logo_path and os.path.isfile(logo_path) else None

        state = {
            "x_frac": self.watermark_x_frac.get(),
            "y_frac": self.watermark_y_frac.get(),
            "scale_frac": self.watermark_scale_frac.get(),
            "dragging": None,   # None | "move" | "resize"
            "drag_start": (0, 0),
        }
        logo_canvas = {"img_id": None, "handle_id": None, "photo": None}
        HANDLE_R = 7   # bán kính ô vuông kéo-resize ở góc dưới-phải

        def _logo_disp_box():
            """Trả về (cx, cy, half_w, half_h) - toạ độ TÂM và nửa-kích-thước của logo
            trên canvas HIỂN THỊ (disp), quy đổi từ scale_frac (tỉ lệ % chiều rộng
            VIDEO GỐC) xuống đúng tỉ lệ preview đang hiển thị."""
            logo_disp_w = max(8, vw * state["scale_frac"] * scale)
            if logo_img_original is not None:
                logo_disp_h = logo_disp_w * logo_img_original.height / logo_img_original.width
            else:
                logo_disp_h = logo_disp_w
            cx = state["x_frac"] * disp_w
            cy = state["y_frac"] * disp_h
            return cx, cy, logo_disp_w / 2, logo_disp_h / 2

        def _redraw():
            cx, cy, half_w, half_h = _logo_disp_box()
            if logo_canvas["img_id"] is not None:
                canvas.delete(logo_canvas["img_id"])
            if logo_canvas["handle_id"] is not None:
                canvas.delete(logo_canvas["handle_id"])

            disp_w_px = max(1, int(half_w * 2))
            disp_h_px = max(1, int(half_h * 2))
            if logo_img_original is not None:
                resized_logo = logo_img_original.resize((disp_w_px, disp_h_px))
                logo_photo = ImageTk.PhotoImage(resized_logo)
                logo_canvas["photo"] = logo_photo   # giữ tham chiếu
                logo_canvas["img_id"] = canvas.create_image(cx, cy, anchor="center", image=logo_photo)
            else:
                # Chưa chọn logo - vẫn cho xem/kéo khung placeholder để ước lượng vị trí/kích thước.
                logo_canvas["img_id"] = canvas.create_rectangle(
                    cx - half_w, cy - half_h, cx + half_w, cy + half_h,
                    outline=ACCENT, width=2, dash=(4, 2),
                )

            hx, hy = cx + half_w, cy + half_h
            logo_canvas["handle_id"] = canvas.create_rectangle(
                hx - HANDLE_R, hy - HANDLE_R, hx + HANDLE_R, hy + HANDLE_R,
                fill=ACCENT, outline="white", width=1,
            )
            hint.configure(
                text=f"Vị trí: x={state['x_frac']*100:.0f}%, y={state['y_frac']*100:.0f}%  ·  "
                     f"Kích thước: {state['scale_frac']*100:.0f}% chiều rộng video"
            )

        _redraw()

        def on_press(event):
            cx, cy, half_w, half_h = _logo_disp_box()
            hx, hy = cx + half_w, cy + half_h
            # Bấm gần ô vuông góc dưới-phải -> chế độ RESIZE, ngược lại nếu bấm trong
            # vùng logo -> chế độ MOVE. Bấm ra ngoài logo thì bỏ qua (không làm gì).
            if abs(event.x - hx) <= HANDLE_R + 4 and abs(event.y - hy) <= HANDLE_R + 4:
                state["dragging"] = "resize"
            elif abs(event.x - cx) <= half_w and abs(event.y - cy) <= half_h:
                state["dragging"] = "move"
                state["drag_start"] = (event.x - cx, event.y - cy)
            else:
                state["dragging"] = None

        def on_drag(event):
            if state["dragging"] == "move":
                offx, offy = state["drag_start"]
                new_cx = event.x - offx
                new_cy = event.y - offy
                state["x_frac"] = max(0.0, min(1.0, new_cx / disp_w))
                state["y_frac"] = max(0.0, min(1.0, new_cy / disp_h))
                _redraw()
            elif state["dragging"] == "resize":
                cx = state["x_frac"] * disp_w
                # Khoảng cách từ tâm logo tới vị trí chuột hiện tại (theo chiều ngang)
                # quyết định độ rộng logo mới - kéo ra xa = to hơn, kéo vào gần = nhỏ lại.
                new_half_w = max(4, event.x - cx)
                new_disp_w = new_half_w * 2
                new_scale_frac = new_disp_w / (vw * scale)
                state["scale_frac"] = max(0.02, min(0.8, new_scale_frac))
                _redraw()

        def on_release(event):
            state["dragging"] = None

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

        def confirm():
            self.watermark_x_frac.set(state["x_frac"])
            self.watermark_y_frac.set(state["y_frac"])
            self.watermark_scale_frac.set(round(state["scale_frac"], 3))
            self.watermark_position.set("custom")
            self.watermark_pos_label.configure(
                text=f"Vị trí tuỳ chỉnh: x={state['x_frac']*100:.0f}%, y={state['y_frac']*100:.0f}%"
            )
            top.destroy()

        btn_row = ctk.CTkFrame(top, fg_color="transparent")
        btn_row.pack(pady=(0, 10))
        ctk.CTkButton(btn_row, text="Xác nhận", fg_color=ACCENT, hover_color=ACCENT_HOVER, command=confirm).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Huỷ", fg_color=PANEL2, command=top.destroy).pack(side="left", padx=6)
        top.resizable(False, False)
        self._center_toplevel(top)

    def _center_toplevel(self, top):
        """Canh giữa cửa sổ Toplevel trên màn hình, tránh trường hợp cửa sổ mở lệch
        ra ngoài vùng nhìn thấy (khiến nút Xác nhận có vẻ như 'biến mất')."""
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        top.geometry(f"{w}x{h}+{x}+{y}")

    def _open_blur_region_picker(self):
        """Mở cửa sổ hiển thị khung hình mẫu, cho phép KÉO-THẢ vẽ NHIỀU khung chữ
        nhật để chọn các vùng cần làm mờ (vd 1 khung che tên kênh nguồn ở góc trên
        + 1 khung khác che phụ đề gốc ở đáy màn hình - xem ảnh ví dụ người dùng).
        Cửa sổ này CÓ THỂ PHÓNG TO/THU NHỎ (kéo viền hoặc bấm nút phóng to trên thanh
        tiêu đề) - khung hình sẽ tự co giãn theo, giúp vẽ nhiều vùng làm mờ chính xác
        hơn trên video lớn."""
        frame_path, vw, vh, video_dur = self._get_sample_frame()
        if not frame_path:
            return

        top = ctk.CTkToplevel(self)
        top.title("Vẽ vùng cần làm mờ - kéo-thả chuột để vẽ, có thể vẽ NHIỀU khung")
        top.grab_set()

        img = Image.open(frame_path)

        # Mở cửa sổ Ở TRẠNG THÁI PHÓNG TO (full màn hình làm việc) NGAY KHI MỞ, khỏi
        # cần người dùng tự kéo viền hay tự bấm nút phóng to. Khung hình sẽ tự co giãn
        # theo (xem _on_canvas_resize bên dưới). Người dùng vẫn có thể bấm nút "khôi
        # phục"/thu nhỏ trên thanh tiêu đề nếu muốn cửa sổ nhỏ lại.
        top.update_idletasks()
        top.resizable(True, True)
        top.minsize(420, 340)
        try:
            top.state("zoomed")   # Windows: mở full màn hình làm việc (chừa taskbar)
        except Exception:
            # Fallback cho hệ điều hành không hỗ trợ "zoomed" (vd Linux/Mac) - đặt
            # geometry gần kín màn hình thay thế.
            screen_w = top.winfo_screenwidth()
            screen_h = top.winfo_screenheight()
            top.geometry(f"{screen_w - 60}x{screen_h - 80}+30+20")

        hint = ctk.CTkLabel(
            top, text="Kéo chuột để vẽ 1 khung - lặp lại để vẽ THÊM khung khác (không giới hạn số khung).",
            text_color=TEXT_MUTED,
        )

        # ----- Thanh tua video - de luot tim dung khung hinh CO SUB de ve vung
        # che (khung hinh giua video mac dinh nhieu luc khong co sub dang hien
        # ra, gay kho chon dung vi tri). Chi trich lai frame khi THA slider (
        # command mac dinh cua CTkSlider goi lien tuc trong luc keo se rat giat/
        # cham vi phai goi ffmpeg moi lan) - dung <ButtonRelease-1> tren slider
        # de chi trich 1 lan sau khi nguoi dung tha chuot.
        seek_wrap = ctk.CTkFrame(top, fg_color="transparent")
        seek_row = ctk.CTkFrame(seek_wrap, fg_color="transparent")
        seek_row.pack(fill="x", padx=10)
        ctk.CTkLabel(seek_row, text="🎞 Tua tìm khung hình có phụ đề:", text_color=TEXT_MUTED, font=(FONT_FAMILY, 11)).pack(side="left")
        seek_time_label = ctk.CTkLabel(seek_row, text="00:00 / 00:00", text_color=TEXT_MUTED, font=(FONT_FAMILY, 11))
        seek_time_label.pack(side="right")

        def _fmt_mmss(sec: float) -> str:
            sec = max(0, int(sec))
            return f"{sec // 60:02d}:{sec % 60:02d}"

        safe_dur = video_dur if video_dur and video_dur > 0.2 else 5.0
        seek_slider = ctk.CTkSlider(seek_wrap, from_=0, to=safe_dur, number_of_steps=max(10, int(safe_dur * 4)))
        seek_slider.set(safe_dur / 2)
        seek_slider.pack(fill="x", padx=10, pady=(4, 8))
        seek_time_label.configure(text=f"{_fmt_mmss(safe_dur / 2)} / {_fmt_mmss(safe_dur)}")

        def _do_seek(_event=None):
            nonlocal img
            t = seek_slider.get()
            seek_time_label.configure(text=f"{_fmt_mmss(t)} / {_fmt_mmss(safe_dur)}")
            new_frame_path, _w, _h, _d = self._get_sample_frame(time_sec=t)
            if not new_frame_path:
                return
            try:
                img = Image.open(new_frame_path)
            except Exception:
                return
            geom["disp_w"] = 0  # ép _on_canvas_resize vẽ lại ảnh (đang cache theo kích thước cũ)
            _on_canvas_resize()

        seek_slider.bind("<ButtonRelease-1>", _do_seek)

        seek_wrap.pack(side="top", fill="x", pady=(6, 0))

        # box_fracs: danh sách các khung ĐÃ VẼ XONG, lưu theo TỈ LỆ (0..1) so với khung
        # hình GỐC (KHÔNG phụ thuộc kích thước cửa sổ/hiển thị hiện tại) - nhờ vậy khi
        # người dùng PHÓNG TO/THU NHỎ cửa sổ, các khung đã vẽ vẫn bám đúng vị trí.
        box_fracs: list = []
        if self.blur_regions and vw and vh:
            for (px_x, px_y, px_w, px_h) in self.blur_regions:
                box_fracs.append((px_x / vw, px_y / vh, (px_x + px_w) / vw, (px_y + px_h) / vh))

        canvas_wrap = ctk.CTkFrame(top, fg_color="transparent")
        canvas = tk.Canvas(canvas_wrap, highlightthickness=0, bg="#202020")
        canvas.pack(fill="both", expand=True)

        geom = {"disp_w": 0, "disp_h": 0, "offset_x": 0, "offset_y": 0, "photo": None}
        state = {"x0": 0, "y0": 0, "rect": None}

        def _frac_to_canvas(fx, fy):
            return geom["offset_x"] + fx * geom["disp_w"], geom["offset_y"] + fy * geom["disp_h"]

        def _canvas_to_frac(x, y):
            fx = (x - geom["offset_x"]) / geom["disp_w"] if geom["disp_w"] else 0
            fy = (y - geom["offset_y"]) / geom["disp_h"] if geom["disp_h"] else 0
            return max(0.0, min(1.0, fx)), max(0.0, min(1.0, fy))

        def _redraw_boxes():
            canvas.delete("box")
            for (fx0, fy0, fx1, fy1) in box_fracs:
                x0, y0 = _frac_to_canvas(fx0, fy0)
                x1, y1 = _frac_to_canvas(fx1, fy1)
                canvas.create_rectangle(x0, y0, x1, y1, outline=ACCENT, width=2, tags="box")

        def _on_canvas_resize(event=None):
            # Được gọi mỗi khi khung canvas đổi kích thước (do cửa sổ bị kéo/phóng to) -
            # tự tính lại tỉ lệ hiển thị để LUÔN vừa khít trong canvas, giữ NGUYÊN tỉ lệ
            # khung hình gốc (không méo hình), rồi vẽ lại ảnh + các khung đã có.
            cw, ch = canvas.winfo_width(), canvas.winfo_height()
            if cw < 10 or ch < 10:
                return
            scale = min(cw / img.width, ch / img.height)
            disp_w = max(1, int(img.width * scale))
            disp_h = max(1, int(img.height * scale))
            if geom["disp_w"] == disp_w and geom["disp_h"] == disp_h:
                return
            img_resized = img.resize((disp_w, disp_h))
            geom["photo"] = ImageTk.PhotoImage(img_resized)
            geom["disp_w"], geom["disp_h"] = disp_w, disp_h
            geom["offset_x"] = (cw - disp_w) // 2
            geom["offset_y"] = (ch - disp_h) // 2
            canvas.delete("all")
            canvas.create_image(geom["offset_x"], geom["offset_y"], anchor="nw", image=geom["photo"], tags="bgimg")
            _redraw_boxes()

        canvas.bind("<Configure>", _on_canvas_resize)

        def _update_hint():
            hint.configure(text=f"Đã vẽ {len(box_fracs)} vùng. Kéo chuột để vẽ thêm, hoặc bấm Xác nhận.")

        if box_fracs:
            _update_hint()

        def on_press(event):
            state["x0"], state["y0"] = event.x, event.y
            if state["rect"] is not None:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline=ACCENT, width=2)

        def on_drag(event):
            if state["rect"] is not None:
                canvas.coords(state["rect"], state["x0"], state["y0"], event.x, event.y)

        def on_release(event):
            if state["rect"] is not None:
                canvas.delete(state["rect"])
                state["rect"] = None
            x0, y0 = state["x0"], state["y0"]
            x1, y1 = event.x, event.y
            ox, oy = geom["offset_x"], geom["offset_y"]
            dw, dh = geom["disp_w"], geom["disp_h"]
            x0, x1 = sorted((max(ox, min(ox + dw, x0)), max(ox, min(ox + dw, x1))))
            y0, y1 = sorted((max(oy, min(oy + dh, y0)), max(oy, min(oy + dh, y1))))
            if x1 - x0 < 4 or y1 - y0 < 4:
                # Vẽ nhầm 1 chấm/khung quá nhỏ - bỏ qua, không tính là 1 vùng.
                return
            fx0, fy0 = _canvas_to_frac(x0, y0)
            fx1, fy1 = _canvas_to_frac(x1, y1)
            box_fracs.append((fx0, fy0, fx1, fy1))
            _redraw_boxes()
            _update_hint()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

        def undo_last():
            if not box_fracs:
                return
            box_fracs.pop()
            _redraw_boxes()
            _update_hint()

        def clear_all():
            box_fracs.clear()
            _redraw_boxes()
            hint.configure(text="Đã xoá hết. Kéo chuột để vẽ khung vùng cần làm mờ.")

        def confirm():
            if not box_fracs:
                messagebox.showwarning("Chưa vẽ vùng nào", "Kéo chuột để vẽ ít nhất 1 khung chữ nhật trước khi xác nhận.")
                return
            regions = []
            for (fx0, fy0, fx1, fy1) in box_fracs:
                px_x = int(fx0 * vw)
                px_y = int(fy0 * vh)
                px_w = int((fx1 - fx0) * vw)
                px_h = int((fy1 - fy0) * vh)
                regions.append((px_x, px_y, px_w, px_h))
            self.blur_regions = regions
            self.blur_region_label.configure(
                text=f"Đã chọn {len(regions)} vùng (px, theo video gốc)",
                text_color="white",
            )
            self.blur_original_subtitle.set(True)
            top.destroy()

        btn_row = ctk.CTkFrame(top, fg_color="transparent")
        ctk.CTkButton(btn_row, text="↩ Xoá vùng cuối", width=120, fg_color=PANEL2, command=undo_last).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="🗑 Xoá hết", width=100, fg_color=PANEL2, command=clear_all).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Xác nhận", fg_color=ACCENT, hover_color=ACCENT_HOVER, command=confirm).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Huỷ", fg_color=PANEL2, command=top.destroy).pack(side="left", padx=6)

        # Đóng gói theo thứ tự: hàng nút + hint GHIM Ở DƯỚI trước, rồi mới đến khung
        # hình (canvas_wrap, expand=True) - để canvas chiếm hết phần còn lại và tự co
        # giãn mượt khi người dùng resize cửa sổ, thay vì bị hàng nút chèn ép.
        btn_row.pack(side="bottom", pady=(0, 10))
        hint.pack(side="bottom", pady=(0, 6))
        canvas_wrap.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))

    # ---------- Lưu / nạp lại cấu hình (watermark, âm thanh, phụ đề, xuất video...) ----------
    _SETTINGS_FILE = os.path.join(get_user_data_dir(), "reup_studio_settings.json")
    # Các thuộc tính KHÔNG lưu vì mang tính TỪNG PHIÊN/từng file cụ thể (không phải
    # "cấu hình" nên giữ lại giữa các lần chạy) - vd tên video vừa chọn.
    _SETTINGS_EXCLUDE = {"video_path"}

    def _collect_settings(self) -> dict:
        """Quét TOÀN BỘ biến tkinter (StringVar/BooleanVar/DoubleVar/IntVar) đang gắn
        trên self - đây chính là tất cả các ô nhập/checkbox/slider/combobox trong cả
        app (watermark, âm thanh, phụ đề, độ phân giải, cookie...) - không cần liệt
        kê tay từng cái, nên tự động bắt được cả tuỳ chỉnh thêm mới sau này."""
        data = {}
        for key, val in vars(self).items():
            if key in self._SETTINGS_EXCLUDE:
                continue
            if isinstance(val, (tk.StringVar, tk.BooleanVar, tk.DoubleVar, tk.IntVar)):
                try:
                    data[key] = val.get()
                except Exception:
                    pass
        return data

    def _apply_settings(self, data: dict) -> int:
        applied = 0
        for key, val in data.items():
            attr = getattr(self, key, None)
            if isinstance(attr, (tk.StringVar, tk.BooleanVar, tk.DoubleVar, tk.IntVar)):
                try:
                    attr.set(val)
                    applied += 1
                except Exception:
                    pass  # bỏ qua giá trị cũ không còn hợp lệ (vd combobox đổi values)
        return applied

    def _save_settings_silent(self, toast: bool = False) -> bool:
        """Lưu cấu hình không hiện hộp thoại (dùng cho tự lưu khi thoát và Ctrl+S)."""
        try:
            data = self._collect_settings()
            with open(self._SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if toast:
                self.log(f"💾 Đã lưu cấu hình ({len(data)} mục) -> {self._SETTINGS_FILE}")
                self.toast.show(f"💾 Đã lưu {len(data)} tuỳ chỉnh", "ok")
            return True
        except Exception as e:
            if toast:
                self.toast.show(f"Lỗi lưu cấu hình: {e}", "error", 5000)
            return False

    def _save_settings_to_file(self):
        self._save_settings_silent(toast=True)

    def _load_settings_from_file(self, silent: bool = False):
        if not os.path.isfile(self._SETTINGS_FILE):
            if not silent:
                messagebox.showinfo("Chưa có cấu hình", "Chưa từng lưu cấu hình nào (bấm '💾 Lưu cấu hình' trước).")
            return
        try:
            with open(self._SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            applied = self._apply_settings(data)
            self.log(f"📂 Đã nạp cấu hình đã lưu ({applied}/{len(data)} mục áp dụng được)")
            if not silent:
                self.toast.show(f"📂 Đã nạp lại {applied} tuỳ chỉnh đã lưu", "ok")
        except Exception as e:
            if not silent:
                messagebox.showerror("Lỗi nạp cấu hình", str(e))
            else:
                self.log(f"⚠ Không nạp được cấu hình đã lưu: {e}")

    def log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _validate_pipeline_settings(self) -> bool:
        """Kiểm tra các điều kiện cấu hình chung, KHÔNG bao gồm việc đã chọn video
        hay chưa (video được kiểm tra riêng ở nơi gọi, vì chạy đơn cần _video_full_path
        còn chạy hàng loạt cần danh sách video trong thư mục). Dùng chung cho cả
        start_pipeline() (1 video) và start_batch_pipeline() (cả thư mục) để tránh
        lặp lại nguyên khối kiểm tra này ở 2 nơi. Trả về True nếu hợp lệ, False nếu
        không (đã tự hiển thị messagebox báo lỗi)."""
        if self.use_input_srt.get() and not self.input_srt_path:
            messagebox.showwarning(
                "Thiếu file .srt",
                "Bạn đã bật 'Dùng file .srt có sẵn' nhưng chưa chọn file. "
                "Chọn file .srt hoặc tắt tuỳ chọn này để tự tách thoại + dịch.",
            )
            return False

        if self.silent_video_ai_script.get() and not self._get_gemini_api_keys():
            messagebox.showwarning(
                "Thiếu API key",
                "Chế độ 'Video không có lời thoại - AI viết kịch bản' cần ít nhất 1 Gemini API key "
                "(lấy tại https://aistudio.google.com/apikey).",
            )
            return False

        if self.do_dubbing.get() and self.tts_engine.get() == "clone" and not self.voice_name.get():
            messagebox.showwarning(
                "Thiếu voice profile",
                "Bạn đã chọn giọng đọc 'clone' nhưng chưa có/chưa chọn voice profile.\n"
                "Chạy setup_voice_clone.py để tạo profile trước, hoặc bấm 🔄 để tải lại danh sách.",
            )
            return False

        if self.method.get() == "gemini_fastapi" and not self.use_input_srt.get():
            gfa_base_url = (self.gemini_fastapi_base_url.get() or "").strip()
            if not gfa_base_url:
                messagebox.showwarning(
                    "Thiếu Base URL",
                    "Translation method = gemini_fastapi cần điền Base URL (vd http://127.0.0.1:8000).",
                )
                return False
            ok, msg = gfa_check_server_health(gfa_base_url)
            if not ok:
                messagebox.showerror(
                    "Gemini Web2API chưa sẵn sàng",
                    f"{msg}\n\nBấm '🔎 Test Gemini' để kiểm tra lại, hoặc bật 'Tự khởi động Gemini Web2API cùng app'.",
                )
                return False

        if self.method.get() == "gemini" and not self.use_input_srt.get():
            if not self._get_gemini_api_keys():
                messagebox.showwarning(
                    "Thiếu API key",
                    "Translation method = gemini cần dán ít nhất 1 Gemini API key (lấy tại https://aistudio.google.com/apikey).",
                )
                return False

        if self.method.get() == "cliproxy" and not self.use_input_srt.get():
            cp_base_url = (self.cliproxy_base_url.get() or "").strip()
            if not cp_base_url:
                messagebox.showwarning(
                    "Thiếu Base URL",
                    "Translation method = cliproxy cần điền Base URL (vd http://127.0.0.1:8317).",
                )
                return False
            ok, msg = cliproxy_check_health(cp_base_url, api_key=self.cliproxy_api_key.get().strip() or None)
            if not ok:
                messagebox.showerror(
                    "CLIProxyAPI chưa sẵn sàng",
                    f"{msg}\n\nBấm '🔎 Test CLIProxyAPI' để kiểm tra lại - nhớ tự khởi động server CLIProxyAPI trước.",
                )
                return False

        return True

    def _build_pipeline_config(
        self,
        video_path: str,
        job_work_dir: str,
        root_output_dir: str,
        sub_x_frac,
        sub_y_frac,
        omni_instructs,
        use_input_srt_override: Optional[bool] = None,
    ) -> "PipelineConfig":
        """Dựng PipelineConfig từ TOÀN BỘ tuỳ chọn đang thiết lập trên giao diện,
        áp dụng cho MỘT video cụ thể (video_path). Tách riêng hàm này để dùng lại
        được cho cả chạy đơn (start_pipeline) lẫn chạy hàng loạt cả thư mục
        (start_batch_pipeline) mà không phải lặp lại hơn 100 dòng khởi tạo config.

        use_input_srt_override: khi chạy hàng loạt, mỗi video cần phụ đề riêng của
        nó nên file .srt có sẵn (chỉ khớp với 1 video cụ thể) sẽ bị BỎ QUA - truyền
        False ở batch mode bất kể checkbox "Dùng file .srt có sẵn" đang bật hay không.
        None = dùng đúng theo checkbox trên giao diện (trường hợp chạy đơn)."""
        use_input_srt = (
            self.use_input_srt.get() if use_input_srt_override is None else use_input_srt_override
        )
        _omni_default_instruct, _omni_male_instruct, _omni_female_instruct = omni_instructs

        return PipelineConfig(
            video_path=video_path,
            work_dir=job_work_dir,
            history_dir=root_output_dir,
            input_srt_path=(self.input_srt_path or None) if use_input_srt else None,
            source_lang=self.source_lang.get(),
            target_lang=self.target_lang.get(),
            translation_method=self.method.get(),
            content_persona=CONTENT_PERSONA_LABELS.get(self.content_persona_display.get()),
            gemini_api_key=None,
            gemini_api_keys=self._get_gemini_api_keys(),
            gemini_model=self.gemini_api_model.get().strip() or "gemini-3.6-flash",
            grok_api_keys=[],
            gemini_fastapi_base_url=self.gemini_fastapi_base_url.get().strip() or "http://127.0.0.1:8000",
            gemini_fastapi_api_key=self.gemini_fastapi_api_key.get().strip() or None,
            gemini_fastapi_model=self.gemini_fastapi_model.get().strip() or "gemini-3.6-flash",
            gemini_fastapi_auto_start=bool(getattr(self, "gemini_fastapi_auto_start", None) and self.gemini_fastapi_auto_start.get()),
            gemini_web2api_cookie_file=self.gemini_web2api_cookie_file.get().strip() or None,
            gemini_web2api_proxy=self.gemini_web2api_proxy.get().strip() or None,
            outro_cta_text=self.outro_cta_text.get().strip() or None,
            cliproxy_base_url=self.cliproxy_base_url.get().strip() or CLIPROXY_DEFAULT_BASE_URL,
            cliproxy_api_key=self.cliproxy_api_key.get().strip() or None,
            cliproxy_model=self.cliproxy_model.get().strip() or DEFAULT_CLIPROXY_MODEL,
            **self._collect_style_dial(),
            whisper_model=self.whisper_model.get(),
            do_subtitles=self.do_subtitles.get(),
            do_dubbing=self.do_dubbing.get(),
            do_watermark_text=self.do_watermark_text.get(),
            watermark_text=self.watermark_text.get(),
            watermark_text_style=self.watermark_text_style.get(),
            do_watermark_logo=self.do_watermark_logo.get(),
            watermark_logo_path=self.watermark_logo_path or None,
            watermark_position=self.watermark_position.get(),
            watermark_x_frac=self.watermark_x_frac.get() if self.watermark_position.get() == "custom" else None,
            watermark_y_frac=self.watermark_y_frac.get() if self.watermark_position.get() == "custom" else None,
            watermark_text_opacity=self.watermark_text_opacity.get(),
            watermark_logo_opacity=self.watermark_logo_opacity.get(),
            watermark_scale_frac=self.watermark_scale_frac.get(),
            watermark_speed=self.watermark_speed.get(),
            watermark_pattern=self.watermark_pattern.get(),
            watermark_font_size=self.watermark_font_size.get(),
            trim_start_sec=self._safe_float(self.trim_start_sec.get(), 0.0),
            trim_end_sec=self._safe_float(self.trim_end_sec.get(), 0.0),
            subtitle_preset=self.preset.get(),
            font_size=int(self.font_size.get()),
            subtitle_display_mode=self.subtitle_display_mode.get(),
            subtitle_font=self.subtitle_font.get(),
            subtitle_position="custom",
            subtitle_pos_x_frac=sub_x_frac,
            subtitle_pos_y_frac=sub_y_frac,
            subtitle_box_enabled=self.subtitle_box_enabled.get(),
            subtitle_box_color=self.subtitle_box_color.get(),
            subtitle_box_opacity=self.subtitle_box_opacity.get(),
            subtitle_effect=self.subtitle_effect.get(),
            split_long_subtitles=self.split_long_subtitles.get(),
            max_subtitle_chars=int(self.max_subtitle_chars.get()),
            speech_rate=f"{self.speech_rate_pct.get():+d}%",
            voice_pitch_semitones=self.voice_pitch_semitones.get(),
            voice_speed=self.voice_speed.get(),
            fit_text_to_timing=self.fit_text_to_timing.get(),
            fit_text_tolerance=self.fit_text_tolerance.get(),
            rewrite_after_translate=self.rewrite_after_translate.get(),
            rewrite_keep_ratio=self.rewrite_keep_ratio.get(),
            calibrate_speech_rate_cps=self.calibrate_speech_rate_cps.get(),
            dub_max_speedup=self.dub_max_speedup.get(),
            dub_emergency_max_speedup=(
                self.dub_max_speedup.get() if self.never_exceed_max_speedup.get() else 1.6
            ),
            pre_slowdown_speed=(self.pre_slowdown_speed.get() if self.enable_speed_trick.get() else None),
            post_speedup_speed=(self.post_speedup_speed.get() if self.enable_speed_trick.get() else None),
            keep_original_audio_in_dub=self.keep_original_audio.get(),
            tts_engine=self.tts_engine.get(),
            voice_name=self.voice_name.get() or None,
            voice_profiles_dir=self.voice_profiles_dir,
            voice_gender="male" if self.voice_gender.get() == "Nam" else "female",
            detect_speaker_gender=self.detect_speaker_gender.get(),
            detect_speaker_by_face=self.detect_speaker_by_face.get(),
            edge_voice_male=(self.edge_voice_male.get().split(" — ")[0].strip() or None),
            edge_voice_female=(self.edge_voice_female.get().split(" — ")[0].strip() or None),
            vieneu_voice_male=self.vieneu_voice_male.get() or None,
            vieneu_voice_female=self.vieneu_voice_female.get() or None,
            omnivoice_instruct=_omni_default_instruct,
            omnivoice_instruct_male=_omni_male_instruct,
            omnivoice_instruct_female=_omni_female_instruct,
            auto_remove_original_logo=self.auto_remove_original_logo.get(),
            auto_remove_original_subtitle=self.auto_remove_original_subtitle.get(),
            watermark_removal_engine=self.watermark_removal_engine.get(),
            blur_original_subtitle=self.blur_original_subtitle.get(),
            blur_regions=self.blur_regions,
            blur_strength=int(self.blur_strength.get()),
            remove_original_audio=self.remove_original_audio.get(),
            background_music_path=self.background_music_path or None,
            bg_music_volume=self.bg_music_volume.get(),
            dub_volume=self.dub_volume.get(),
            flip_horizontal=self.flip_horizontal.get(),
            flip_vertical=self.flip_vertical.get(),
            filter_blur=self.filter_blur.get(),
            filter_sharpen=self.filter_sharpen.get(),
            filter_brightness=self.filter_brightness.get(),
            filter_contrast=self.filter_contrast.get(),
            filter_saturation=self.filter_saturation.get(),
            aspect_ratio=self.aspect_ratio.get() if self.aspect_ratio.get() != "original" else None,
            aspect_mode=self.aspect_mode.get(),
            resolution=self.resolution.get() if self.resolution.get() != "original" else None,
            silent_video_ai_script=self.silent_video_ai_script.get(),
            silent_video_narration_style=self.silent_video_narration_style.get(),
            add_hook_intro=self.add_hook_intro.get(),
        )

    def start_pipeline(self):
        if not getattr(self, "_video_full_path", None):
            self.toast.show("Chưa chọn video - hãy chọn video rồi bấm Bắt đầu lại.", "warn")
            self.choose_video()
            return

        if not self._validate_pipeline_settings():
            return

        self.run_btn.configure(state="disabled", text="Đang xử lý...")
        self.batch_btn.configure(state="disabled")
        self._reset_steps()
        self.progress.set(0)

        omni_instructs = self._build_omnivoice_instructs()

        # Mỗi video chạy trong một thư mục tạm RIÊNG. history.json vẫn nằm ở
        # reup_output gốc để Job Center nhìn thấy toàn bộ lịch sử. Khi thành công,
        # pipeline sẽ chuyển chỉ final_vi.mp4 + translated.srt + NOTE.txt sang
        # folder có tên "Tên gốc => Tiêu đề tiếng Việt" rồi xóa thư mục tạm.
        root_output_dir = os.path.abspath(self.work_dir)
        os.makedirs(root_output_dir, exist_ok=True)
        job_work_dir = os.path.join(
            root_output_dir, f".processing_{uuid.uuid4().hex[:12]}"
        )

        # Tinh lai vi tri phu de NGAY TRUOC KHI submit - dam bao dung dung vung che
        # mo MOI NHAT neu dang o che do "blur_region" (phong khi nguoi dung sua lai
        # vung che mo SAU khi da chon radio nay truoc do).
        sub_x_frac, sub_y_frac = self._resolve_subtitle_position_fracs(silent=True)

        cfg = self._build_pipeline_config(
            video_path=self._video_full_path,
            job_work_dir=job_work_dir,
            root_output_dir=root_output_dir,
            sub_x_frac=sub_x_frac,
            sub_y_frac=sub_y_frac,
            omni_instructs=omni_instructs,
        )

        thread = threading.Thread(target=self._run_pipeline_thread, args=(cfg,), daemon=True)
        thread.start()

    def _pick_batch_folder(self) -> Optional[str]:
        """Mở hộp thoại chọn thư mục cho tính năng render hàng loạt - gợi ý sẵn
        thư mục Downloads của người dùng (đúng như yêu cầu 'video có sẵn trong
        download') nếu tồn tại, để đỡ phải tự dò tìm."""
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        initial_dir = downloads_dir if os.path.isdir(downloads_dir) else os.path.expanduser("~")
        folder = filedialog.askdirectory(
            title="Chọn thư mục chứa các video cần render",
            initialdir=initial_dir,
        )
        return folder or None

    def _scan_videos_in_folder(self, folder: str) -> list:
        """Quét file video (không đệ quy vào thư mục con) theo phần mở rộng thường
        gặp, sắp xếp theo tên cho kết quả ổn định giữa các lần chạy."""
        try:
            names = os.listdir(folder)
        except OSError as e:
            messagebox.showerror("Lỗi đọc thư mục", str(e))
            return []
        videos = [
            os.path.join(folder, name)
            for name in names
            if os.path.splitext(name)[1].lower() in BATCH_VIDEO_EXTENSIONS
            and os.path.isfile(os.path.join(folder, name))
        ]
        videos.sort(key=lambda p: os.path.basename(p).lower())
        return videos

    def start_batch_pipeline(self):
        """Bấm 1 nút -> chọn 1 thư mục -> render LẦN LƯỢT tất cả video có trong đó,
        dùng đúng cấu hình đang thiết lập trên giao diện cho từng video."""
        if self._batch_running:
            messagebox.showinfo("Đang chạy", "Đang render hàng loạt, vui lòng đợi xong lượt hiện tại.")
            return

        if not self._validate_pipeline_settings():
            return

        folder = self._pick_batch_folder()
        if not folder:
            return

        videos = self._scan_videos_in_folder(folder)
        if not videos:
            messagebox.showwarning(
                "Không tìm thấy video",
                f"Không có video nào (mp4/mov/mkv/avi/webm/...) trong:\n{folder}",
            )
            return

        if not messagebox.askyesno(
            "Xác nhận render hàng loạt",
            f"Tìm thấy {len(videos)} video trong:\n{folder}\n\n"
            "Sẽ render LẦN LƯỢT từng video theo đúng cấu hình đang thiết lập trên "
            "giao diện hiện tại.\n\n"
            "Lưu ý: tuỳ chọn 'Dùng file .srt có sẵn' (nếu đang bật) sẽ bị BỎ QUA ở chế "
            "độ này vì mỗi video cần được tách thoại + dịch phụ đề riêng.\n\n"
            "Tiếp tục?",
        ):
            return

        self._batch_running = True
        self._batch_videos = videos
        self._batch_total = len(videos)
        self._batch_results = []  # list[(video_path, ok, err_or_none)]
        self._batch_resume_event.set()  # đảm bảo không kẹt ở trạng thái tạm dừng cũ

        self.run_btn.configure(state="disabled")
        self.batch_btn.configure(state="disabled", text=f"⏳ Đang render 0/{self._batch_total}")
        self.batch_pause_btn.configure(text="⏸ Tạm dừng", state="normal")
        self.batch_pause_btn.pack(side="right", padx=6, before=self.batch_btn)
        self._reset_steps()
        self.progress.set(0)
        self.log(f"\n📁 Bắt đầu render hàng loạt {self._batch_total} video trong: {folder}")

        thread = threading.Thread(target=self._run_batch_thread, daemon=True)
        thread.start()

    def _toggle_batch_pause(self):
        """Tạm dừng hàng loạt SAU KHI video hiện tại render xong (không ngắt giữa
        chừng 1 video vì dễ hỏng file output) - cho phép người dùng chỉnh lại các
        tuỳ chọn trên giao diện (giọng đọc, watermark, phụ đề...) rồi bấm 'Tiếp tục'
        để áp dụng cấu hình MỚI cho các video còn lại trong hàng đợi."""
        if not self._batch_running:
            return
        if self._batch_resume_event.is_set():
            self._batch_resume_event.clear()
            self.batch_pause_btn.configure(text="▶ Tiếp tục")
            self.log(
                "\n⏸ Đã yêu cầu tạm dừng - sẽ dừng lại NGAY SAU KHI video hiện tại render "
                "xong. Bạn có thể chỉnh lại cấu hình trong lúc chờ, rồi bấm 'Tiếp tục' để "
                "áp dụng cho các video còn lại."
            )
        else:
            self._batch_resume_event.set()
            self.batch_pause_btn.configure(text="⏸ Tạm dừng")
            self.log("▶ Tiếp tục render hàng loạt với cấu hình hiện tại.")

    def _run_batch_thread(self):
        root_output_dir = os.path.abspath(self.work_dir)
        os.makedirs(root_output_dir, exist_ok=True)

        for i, video_path in enumerate(self._batch_videos, start=1):
            # Nếu người dùng vừa bấm "Tạm dừng", video TRƯỚC đó đã render xong -
            # block ở đây cho tới khi bấm "Tiếp tục". Trong lúc chờ, người dùng có
            # thể chỉnh lại bất kỳ tuỳ chọn nào trên giao diện.
            if not self._batch_resume_event.is_set():
                self.after(0, self._on_batch_paused_ui, i)
                self._batch_resume_event.wait()
                self.after(0, self._on_batch_resumed_ui, i)

            # Đọc lại toàn bộ cấu hình (kể cả omnivoice instruct) NGAY TRƯỚC KHI
            # render video này - để nếu vừa tạm dừng và chỉnh sửa gì đó, video này
            # (và các video sau) sẽ dùng cấu hình MỚI NHẤT chứ không phải cấu hình
            # lúc bấm "Render cả thư mục".
            omni_instructs = self._build_omnivoice_instructs()

            self.after(0, self._on_batch_video_start, i, video_path)

            job_work_dir = os.path.join(root_output_dir, f".processing_{uuid.uuid4().hex[:12]}")
            sub_x_frac, sub_y_frac = self._resolve_subtitle_position_fracs(silent=True)
            cfg = self._build_pipeline_config(
                video_path=video_path,
                job_work_dir=job_work_dir,
                root_output_dir=root_output_dir,
                sub_x_frac=sub_x_frac,
                sub_y_frac=sub_y_frac,
                omni_instructs=omni_instructs,
                use_input_srt_override=False,
            )

            def on_progress(step, pct, msg, _i=i):
                self.after(0, self._on_batch_progress_ui, _i, step, pct, msg)

            pipeline = Pipeline(cfg, on_progress=on_progress)
            try:
                pipeline.run()
                self._maybe_generate_variants(pipeline.result_video)
                self._finalize_single_output(pipeline.result_video, pipeline.srt_path)
                self._batch_results.append((video_path, True, None))
                self.after(0, self._on_batch_video_done, i, pipeline)
            except Exception as e:
                self._batch_results.append((video_path, False, str(e)))
                self.after(0, self._on_batch_video_error, i, video_path, str(e))

        self.after(0, self._on_batch_all_done)

    def _on_batch_paused_ui(self, next_idx: int):
        self.status_label.configure(
            text=f"⏸ Đã tạm dừng - video {next_idx}/{self._batch_total} sẽ chờ. Chỉnh cấu hình rồi bấm 'Tiếp tục'."
        )
        self.log(f"⏸ Tạm dừng - đang chờ trước video {next_idx}/{self._batch_total}.")

    def _on_batch_resumed_ui(self, next_idx: int):
        self.log(f"▶ Tiếp tục - render video {next_idx}/{self._batch_total} với cấu hình mới nhất.")

    def _on_batch_video_start(self, idx: int, video_path: str):
        self._reset_steps()
        self.progress.set(0)
        name = os.path.basename(video_path)
        self.batch_btn.configure(text=f"⏳ Đang render {idx}/{self._batch_total}")
        self.status_label.configure(text=f"[{idx}/{self._batch_total}] {name}")
        self.log(f"\n▶ [{idx}/{self._batch_total}] Bắt đầu: {name}")

    def _on_batch_progress_ui(self, idx: int, step, pct, msg):
        if step == "Error":
            self.log(f"[LỖI] {msg}")
            return
        self.steps_panel.set_state(step, "active" if pct < 1.0 else "done")
        sidx = STEPS.index(step) if step in STEPS else -1
        for i, s in enumerate(STEPS):
            if i < sidx:
                self.steps_panel.set_state(s, "done")
        overall = (sidx + pct) / len(STEPS) if sidx >= 0 else 0
        self.progress.set(min(1.0, max(0.0, overall)))
        self.status_label.configure(text=f"[{idx}/{self._batch_total}] [{step}] {msg}")
        self.log(f"[{idx}/{self._batch_total}][{step}] {int(pct*100)}% - {msg}")

    def _on_batch_video_done(self, idx: int, pipeline: Pipeline):
        for s in STEPS:
            self.steps_panel.set_state(s, "done")
        self.log(f"✅ [{idx}/{self._batch_total}] Xong: {pipeline.result_video}")

    def _on_batch_video_error(self, idx: int, video_path: str, err: str):
        self.log(f"❌ [{idx}/{self._batch_total}] Lỗi ở {os.path.basename(video_path)}: {err}")

    def _on_batch_all_done(self):
        self._batch_running = False
        self._batch_resume_event.set()  # tránh kẹt pause cho lần chạy sau
        self.run_btn.configure(state="normal", text="▶ Bắt đầu dịch")
        self.batch_btn.configure(state="normal", text="📁 Render cả thư mục")
        self.batch_pause_btn.pack_forget()
        self.progress.set(1.0)

        total = len(self._batch_results)
        ok_count = sum(1 for _, ok, _ in self._batch_results if ok)
        fail_count = total - ok_count
        self.status_label.configure(text=f"Hoàn tất render hàng loạt: {ok_count}/{total} thành công")
        self.log(f"\n🏁 Hoàn tất render hàng loạt: {ok_count}/{total} thành công, {fail_count} lỗi.")

        lines = [f"Đã render {total} video: {ok_count} thành công, {fail_count} lỗi."]
        if fail_count:
            lines.append("\nCác video bị lỗi:")
            for path, ok, err in self._batch_results:
                if not ok:
                    lines.append(f"- {os.path.basename(path)}: {err}")
        messagebox.showinfo("Hoàn tất render hàng loạt", "\n".join(lines))

    def _finalize_single_output(self, source_video: Optional[str], srt_path: Optional[str] = None):
        """Chuẩn hoá folder kết quả thành đúng 3 file người dùng cần:
        1 video MP4 + NOTE.txt + translated.srt.

        Mọi thư mục con, video phụ, audio tạm, thumbnail, log/txt phụ... trong
        folder kết quả đều bị xoá. history.json vẫn nằm ở work_dir gốc và không
        bị đụng tới.
        """
        if not source_video or not os.path.isfile(source_video):
            return

        import shutil

        output_dir = os.path.dirname(os.path.abspath(source_video))
        keep_video = os.path.abspath(source_video)

        # Chuẩn hoá SRT về đúng tên translated.srt.
        srt_candidate = srt_path if srt_path and os.path.isfile(srt_path) else None
        if srt_candidate:
            target_srt = os.path.join(output_dir, "translated.srt")
            if os.path.abspath(srt_candidate) != os.path.abspath(target_srt):
                try:
                    if os.path.exists(target_srt):
                        os.remove(target_srt)
                    shutil.move(srt_candidate, target_srt)
                except Exception as e:
                    self.after(0, self.log, f"⚠ Không chuẩn hoá được tên SRT: {e}")

        # Giữ NOTE.txt; nếu pipeline tạo tên khác chỉ đổi tên file ghi chú đó.
        note_path = os.path.join(output_dir, "NOTE.txt")
        if not os.path.isfile(note_path):
            for name in os.listdir(output_dir):
                full = os.path.join(output_dir, name)
                if (
                    os.path.isfile(full)
                    and name.lower() in {"note.txt", "note.md", "note"}
                ):
                    try:
                        if os.path.abspath(full) != os.path.abspath(note_path):
                            if os.path.exists(note_path):
                                os.remove(note_path)
                            shutil.move(full, note_path)
                    except Exception as e:
                        self.after(0, self.log, f"⚠ Không chuẩn hoá được NOTE.txt: {e}")
                    break

        # Xoá toàn bộ thứ không thuộc 3 file cuối cùng. Đặc biệt xoá bien_the/.
        keep_names = {
            os.path.basename(keep_video).lower(),
            "translated.srt",
            "note.txt",
        }
        for name in list(os.listdir(output_dir)):
            full = os.path.join(output_dir, name)
            if name.lower() in keep_names:
                continue
            try:
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                else:
                    os.remove(full)
            except Exception as e:
                self.after(0, self.log, f"⚠ Không xoá được file tạm '{name}': {e}")

        self.after(0, self.log, "🧹 Đã dọn output: chỉ giữ 1 video + NOTE.txt + translated.srt.")

    def _maybe_generate_variants(self, source_video: Optional[str], force: bool = False):
        """Nếu bật 'Chỉnh sửa nhẹ video cuối cùng', chỉ tạo 1 bản tạm rồi
        thay thế chính video đầu ra. Tuyệt đối không tạo output/bien_the riêng.

        Nếu checkbox tắt thì bỏ qua chỉnh sửa, nhưng vẫn luôn chuẩn hoá output
        để kết quả cuối cùng chỉ còn 1 video + NOTE.txt + translated.srt.
        """
        if not source_video or not os.path.isfile(source_video):
            self.after(0, self.log, "⚠ Không tìm thấy video đầu ra để hoàn tất output.")
            return

        import shutil

        if (force or self.variant_enabled.get()) and VARIANT_RENDER_AVAILABLE:
            output_dir = os.path.dirname(os.path.abspath(source_video))
            temp_dir = os.path.join(output_dir, f".variant_tmp_{uuid.uuid4().hex[:10]}")
            os.makedirs(temp_dir, exist_ok=True)

            # BUG ĐÃ SỬA: trước đây mode bị HARD-CODE "long" (1920x1080 ngang) ở đây,
            # bất kể cfg.aspect_ratio ở bước Export đã xuất ra 9:16 dọc hay chưa.
            # build_video_filter() trong core/render_variant.py thấy target là ngang
            # (target_w >= target_h) mà nguồn lại đang DỌC (height > width) thì tự
            # động "transpose=2" XOAY video về ngang - đây chính là lý do render 9:16
            # nhưng output ra 16:9. Giờ tự dò đúng kích thước THẬT của chính video
            # cuối cùng rồi truyền thẳng target_size = kích thước đó (không đoán qua
            # cfg, không ép về khung chuẩn 1920x1080/1080x1920 của RENDER_TARGETS) -
            # bước "chỉnh sửa nhẹ" giờ CHỈ áp màu/zoom/grain, không bao giờ tự ý
            # xoay/đổi kích thước khung hình gốc nữa. crop_short=False để đảm bảo
            # không bị cắt ngẫu nhiên còn 120s dù video là dọc và dài hơn 120s (giữ
            # đúng 1:1 với phụ đề, đúng như log cũ yêu cầu).
            mode = "long"
            target_size = None
            if _variant_get_video_info is not None:
                try:
                    _src_info = _variant_get_video_info(source_video)
                    target_size = (_src_info["width"], _src_info["height"])
                    if _src_info["height"] > _src_info["width"]:
                        mode = "short"
                except Exception as e:
                    self.after(0, self.log, f"⚠ Không đọc được kích thước video gốc ({e}), dùng mode mặc định 'long'.")

            account = {"output": temp_dir, "style": {}}
            try:
                self.after(0, self.log, f"🎲 Chỉnh sửa nhẹ 1 lần ({mode}) cho video cuối cùng...")
                out_path = variant_render_video(
                    source_video, account, index=1, mode=mode,
                    target_size=target_size, crop_short=False,
                    log_cb=lambda m: self.after(0, self.log, f"[Chỉnh sửa] {m}"),
                )
                if not out_path or not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
                    raise RuntimeError("Render chỉnh sửa không tạo được video hợp lệ")

                backup = source_video + ".before_variant.tmp"
                if os.path.exists(backup):
                    os.remove(backup)
                os.replace(source_video, backup)
                try:
                    shutil.move(out_path, source_video)
                    if os.path.exists(backup):
                        os.remove(backup)
                    self.after(0, self.log, "✅ Đã thay thế video bằng đúng 1 bản chỉnh sửa.")
                except Exception:
                    if os.path.exists(backup) and not os.path.exists(source_video):
                        os.replace(backup, source_video)
                    raise
            except Exception as e:
                self.after(0, self.log, f"⚠ Không áp dụng được chỉnh sửa biến thể: {e}. Giữ video gốc.")
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        elif (force or self.variant_enabled.get()) and not VARIANT_RENDER_AVAILABLE:
            self.after(0, self.log, "⚠ Module chỉnh sửa biến thể không sẵn sàng - giữ video gốc.")

    def _run_pipeline_thread(self, cfg: PipelineConfig):
        def on_progress(step, pct, msg):
            self.after(0, self._on_progress_ui, step, pct, msg)

        pipeline = Pipeline(cfg, on_progress=on_progress)
        try:
            pipeline.run()
            self._maybe_generate_variants(pipeline.result_video)
            self._finalize_single_output(pipeline.result_video, pipeline.srt_path)
            self.after(0, self._on_done, pipeline)
        except Exception as e:
            self.after(0, self._on_error, str(e))

    def _on_progress_ui(self, step, pct, msg):
        if step == "Error":
            self.log(f"[LỖI] {msg}")
            return
        self.steps_panel.set_state(step, "active" if pct < 1.0 else "done")
        # đánh dấu các bước trước là done
        idx = STEPS.index(step) if step in STEPS else -1
        for i, s in enumerate(STEPS):
            if i < idx:
                self.steps_panel.set_state(s, "done")

        overall = (idx + pct) / len(STEPS) if idx >= 0 else 0
        self.progress.set(min(1.0, max(0.0, overall)))
        self.status_label.configure(text=f"[{step}] {msg}")
        self.log(f"[{step}] {int(pct*100)}% - {msg}")

    def _on_done(self, pipeline: Pipeline):
        self._reset_steps()
        for s in STEPS:
            self.steps_panel.set_state(s, "done")
        self.progress.set(1.0)
        self.run_btn.configure(state="normal", text="▶ Bắt đầu dịch")
        self.batch_btn.configure(state="normal")
        self.log(f"✅ Hoàn tất! Video: {pipeline.result_video}")
        self.log(f"✅ Phụ đề: {pipeline.srt_path}")
        if messagebox.askyesno(
            "Hoàn tất",
            f"Video đã xuất tại:\n{pipeline.result_video}\n\nMở trong Editor để chỉnh sửa tiếp?",
        ):
            # Nếu pipeline đã đốt cứng phụ đề vào hình thì KHÔNG nạp thêm .srt (tránh chữ chồng đôi).
            burned = bool(getattr(pipeline.cfg, "do_subtitles", False))
            self.open_in_editor(pipeline.result_video, None if burned else pipeline.srt_path)

    def _on_error(self, err: str):
        self.run_btn.configure(state="normal", text="▶ Bắt đầu dịch")
        self.batch_btn.configure(state="normal")
        self.log(f"❌ LỖI: {err}")
        messagebox.showerror("Lỗi", err)


def main():
    _apply_auto_screen_scaling()
    app = ReupStudioApp()
    app.mainloop()


if __name__ == "__main__":
    main()