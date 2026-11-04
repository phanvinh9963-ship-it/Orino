"""
core/editor_ui.py
Trang "Editor" (dựng video kiểu CapCut) cho Reup Studio.

    from core.editor_ui import EditorPage
    page = EditorPage(parent, app=self, theme={...}, font="Segoe UI")

Phím tắt: Space phát/dừng · S tách · Delete xóa · Ctrl+Z / Ctrl+Y hoàn tác/làm lại ·
          ←/→ lùi/tiến 1 khung (Shift = 1 giây) · Home/End · Ctrl+S lưu dự án ·
          Ctrl+lăn chuột = zoom timeline, lăn chuột = cuộn ngang.
"""
from __future__ import annotations

import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import wave
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox
from typing import Dict, List, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from core import editor_ai as AI
from core import editor_audio as AU
from core.editor_audio import AudioPlayer
from core import editor_media as M
from dataclasses import asdict

from core.editor_model import (LANES, LANE_LABEL, MIN_DUR, Clip, Project, _clip_from_dict, format_srt,
                                parse_srt)

DEFAULT_THEME = dict(BG="#0e0f13", PANEL="#15161c", PANEL2="#1b1c24", ACCENT="#6c5ce7",
                     ACCENT_HOVER="#5a4bd6", TEXT_MUTED="#8b8d98", BORDER="#26272f", GREEN="#2ecc71")

LABEL_W, RULER_H, LANE_GAP = 78, 26, 4
LANE_H = {"sub": 30, "text": 26, "voice": 40, "music": 40, "video": 60}
LANE_COL = {   # fill, edge, chữ/sóng
    "sub":   ("#3b3320", "#d9a93b", "#f3dfae"),
    "text":  ("#1f3b3a", "#3fb8af", "#b9f1ec"),
    "voice": ("#15382a", "#2ecc71", "#5fe39b"),
    "music": ("#16294a", "#4aa3ff", "#7fbfff"),
    "video": ("#2a2552", "#6c5ce7", "#a79dff"),
}
NICE_STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600]
SNAP_PX = 8
EDGE_PX = 6
AUDIO_LATENCY = 0.05           # bù độ trễ khởi động âm thanh (giây)
FIT_MODES = {"Nền mờ (khuyên dùng)": "blur", "Viền đen": "fit", "Lấp đầy (cắt mép)": "fill"}
RES_MODES = {"Giữ nguyên": None, "720p": 720, "1080p": 1080, "1440p": 1440}
FONTS = ["Arial", "Segoe UI", "Tahoma", "Verdana", "Calibri", "Times New Roman", "Impact", "Arial Black"]
PPS_MIN, PPS_MAX = 0.3, 400.0
THUMB_H = 52
_TEXT_CLASSES = ("Entry", "Text", "TEntry", "TCombobox", "Spinbox", "TSpinbox")
VIDEO_TYPES = [("Video / Ảnh", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.flv *.wmv *.ts *.png *.jpg *.jpeg *.webp *.bmp"),
               ("Tất cả", "*.*")]
AUDIO_TYPES = [("Âm thanh / Video", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mov *.mkv"),
               ("Tất cả", "*.*")]


def fmt_time(t: float, tenth: bool = True) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    body = f"{int(m):02d}:{s:04.1f}" if tenth else f"{int(m):02d}:{int(s):02d}"
    return f"{int(h)}:{body}" if h >= 1 else body


def parse_secs(text: str) -> float:
    """"12.5", "1:05.2", "1:02:03" (có thể dùng dấu phẩy thập phân) -> giây."""
    parts = text.strip().replace(",", ".").split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(text)
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def copy_project(p: Project) -> Project:
    q = Project()
    q._restore(p._state())
    return q


def pack_rows(clips: List[Clip], max_rows: int = 3) -> Dict[str, tuple]:
    """Xếp các clip gối nhau trong cùng lane thành nhiều hàng mỏng để nhìn được hết."""
    ends: List[float] = []
    rows: Dict[str, int] = {}
    for c in clips:
        for i, e in enumerate(ends):
            if c.start >= e - 1e-6:
                ends[i], rows[c.id] = c.end, i
                break
        else:
            ends.append(c.end)
            rows[c.id] = len(ends) - 1
    n = min(len(ends), max_rows)
    return {k: (min(v, n - 1), n) for k, v in rows.items()}


class EditorPage(ctk.CTkFrame):
    def __init__(self, parent, app=None, theme: Optional[dict] = None, font: str = "Segoe UI"):
        self.T = {**DEFAULT_THEME, **(theme or {})}
        super().__init__(parent, fg_color=self.T["BG"])
        self.app, self.F = app, font
        self.proj = Project()
        self.sel: Optional[str] = None
        self.playhead = 0.0
        self.playing = False
        self.pps = 60.0            # pixel / giây
        self.scroll = 0.0          # px cuộn ngang
        self._hit: List[tuple] = []
        self._drag: Optional[dict] = None
        self._tl_pending = self._pv_pending = False
        self._list_ids: List[str] = []
        self._pv_img = None
        # media cache
        self.readers: Dict[str, M.FrameReader] = {}
        self.proxies: Dict[str, str] = {}
        self.thumbs: Dict[str, tuple] = {}
        self.waves: Dict[str, object] = {}
        self._stills: Dict[str, Image.Image] = {}
        self._loading: set = set()
        # phát
        self.audio = AudioPlayer()
        self._audio_wav = os.path.join(M.cache_dir(), f"preview_{os.getpid()}.wav")
        self._audio_rev = -1
        self._audio_busy = False
        self._audio_timer = None
        self._play_job = None
        self._p0 = self._t0 = 0.0
        # xuất
        self._exp_cancel: Optional[threading.Event] = None
        # cấu hình
        self.snap = tk.BooleanVar(value=True)
        self.ripple = tk.BooleanVar(value=True)
        self.keep_assets = tk.BooleanVar(value=True)   # main.py đọc: giữ tài nguyên khi dịch xong
        self._q: "queue.Queue" = queue.Queue()         # luồng nền -> UI (an toàn với Tk)
        self._closed = False
        self._cur_sub: Optional[str] = None
        self._thumb_tk: Dict[tuple, ImageTk.PhotoImage] = {}
        self._bad: set = set()
        self._done_assets: set = set()
        self._audio_started = False
        self._audio_dirty = False
        self._pv_geom = (0, 0, 1, 1)
        self._pv_drag: Optional[dict] = None
        self._cursor = "arrow"
        self._cap_shown = False

        lanes_y, y = {}, RULER_H + 4
        for ln in LANES:
            lanes_y[ln] = (y, y + LANE_H[ln])
            y += LANE_H[ln] + LANE_GAP
        self.lane_y, self.tl_h = lanes_y, y + 4

        # AI gợi ý cắt (tab ✨ AI)
        self._ai_items: List[dict] = []
        self._ai_marks: List[tuple] = []
        self._ai_cancel: Optional[threading.Event] = None
        self._ai_busy = False
        self._ai_rev = -1

        self._build()
        # CTkFrame.bind gắn vào canvas bên trong -> dùng tk.Frame.bind để nhận sự kiện của CHÍNH khung này
        tk.Frame.bind(self, "<Unmap>", lambda e: self.pause() if e.widget is self else None, add="+")
        self.winfo_toplevel().bind("<KeyPress>", self._on_key, add="+")
        tk.Frame.bind(self, "<Destroy>", lambda e: self.shutdown() if e.widget is self else None, add="+")
        self.after(60, self._pump)
        self.after(100, self._refresh_all)

    # ------------------------------------------------------------------ giao diện
    def _btn(self, parent, text, cmd, width=None, primary=False, **kw):
        T = self.T
        return ctk.CTkButton(
            parent, text=text, command=cmd, height=32, width=width or 0, corner_radius=8,
            font=(self.F, 12, "bold" if primary else "normal"),
            fg_color=T["ACCENT"] if primary else T["PANEL2"],
            hover_color=T["ACCENT_HOVER"] if primary else T["BORDER"], **kw)

    def _build(self):
        T, F = self.T, self.F
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---- thanh công cụ
        bar = ctk.CTkFrame(self, fg_color=T["PANEL"], corner_radius=12)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=8, pady=6)

        self.file_btn = self._btn(inner, "📁 Tệp ▾", self._popup_file_menu, 84)
        self.file_btn.pack(side="left", padx=(0, 6))
        for text, cmd in (("＋ Video/Ảnh", self.add_video_dialog), ("Aa Chữ", self.op_add_text),
                          ("♪ Nhạc", lambda: self.add_audio_dialog("music")),
                          ("🎙 Giọng", lambda: self.add_audio_dialog("voice"))):
            self._btn(inner, text, cmd).pack(side="left", padx=3)
        ctk.CTkFrame(inner, width=1, height=22, fg_color=T["BORDER"]).pack(side="left", padx=8)
        self.undo_btn = self._btn(inner, "↶", self.op_undo, 36)
        self.undo_btn.pack(side="left", padx=2)
        self.redo_btn = self._btn(inner, "↷", self.op_redo, 36)
        self.redo_btn.pack(side="left", padx=2)
        ctk.CTkFrame(inner, width=1, height=22, fg_color=T["BORDER"]).pack(side="left", padx=8)
        self._btn(inner, "✂ Tách", self.op_split).pack(side="left", padx=3)
        self._btn(inner, "🗑 Xóa", self.op_delete).pack(side="left", padx=3)
        self.title_lbl = ctk.CTkLabel(inner, text="", font=(F, 11), text_color=T["TEXT_MUTED"])
        self.title_lbl.pack(side="left", padx=14)
        self._btn(inner, "⬆ Xuất video", lambda: (self.tabs.set("Xuất"), self.export_dialog()),
                  primary=True).pack(side="right")

        # ---- giữa: xem trước | tab bên phải
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.grid(row=1, column=0, sticky="nsew")
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(mid, fg_color=T["PANEL"], corner_radius=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.pv = tk.Canvas(left, bg="#000000", highlightthickness=0, height=220)
        self.pv.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.pv.bind("<Configure>", lambda e: self._schedule_preview())
        self.pv.bind("<Button-1>", self._on_pv_press)
        self.pv.bind("<B1-Motion>", self._on_pv_motion)
        self.pv.bind("<ButtonRelease-1>", self._on_pv_release)
        tr = ctk.CTkFrame(left, fg_color="transparent")
        tr.pack(fill="x", padx=10, pady=(0, 10))
        self._btn(tr, "⏮", lambda: self.seek(0), 38).pack(side="left")
        self.play_btn = self._btn(tr, "▶", self.toggle_play, 46, primary=True)
        self.play_btn.pack(side="left", padx=6)
        self._btn(tr, "⏭", lambda: self.seek(self.proj.duration), 38).pack(side="left")
        self.time_lbl = ctk.CTkLabel(tr, text="00:00.0 / 00:00.0", font=("Consolas", 13, "bold"))
        self.time_lbl.pack(side="left", padx=12)
        self._btn(tr, "🔊", self.audio_dialog, 36).pack(side="right")          # kiểm tra / chọn thiết bị âm thanh
        self.status_lbl = ctk.CTkLabel(tr, text="", font=(F, 11), text_color=T["TEXT_MUTED"], anchor="e")
        self.status_lbl.pack(side="right", fill="x", expand=True, padx=(0, 6))

        right = ctk.CTkFrame(mid, fg_color=T["PANEL"], corner_radius=14, width=372)
        right.grid(row=0, column=1, sticky="nsew")
        right.pack_propagate(False)
        self.tabs = ctk.CTkTabview(right, fg_color=T["PANEL2"], corner_radius=10,
                                   segmented_button_selected_color=T["ACCENT"],
                                   segmented_button_selected_hover_color=T["ACCENT_HOVER"],
                                   segmented_button_unselected_color=T["PANEL"])
        self.cap_box = ctk.CTkFrame(right, fg_color=T["PANEL2"], corner_radius=10)   # nhập nội dung chữ
        self.cap_box.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        for name in ("Phụ đề", "Thuộc tính", "✨ AI", "Xuất"):
            self.tabs.add(name)
        self._build_sub_tab(self.tabs.tab("Phụ đề"))
        self._build_props_tab(self.tabs.tab("Thuộc tính"))
        self._build_ai_tab(self.tabs.tab("✨ AI"))
        self._build_export_tab(self.tabs.tab("Xuất"))
        self._build_caption_box()

        # ---- timeline
        tlw = ctk.CTkFrame(self, fg_color=T["PANEL"], corner_radius=14)
        tlw.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        head = ctk.CTkFrame(tlw, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(head, text="Timeline", font=(F, 12, "bold")).pack(side="left")
        ctk.CTkCheckBox(head, text="Dính mép", variable=self.snap, width=20, checkbox_width=16,
                        checkbox_height=16, font=(F, 11), fg_color=T["ACCENT"],
                        hover_color=T["ACCENT_HOVER"]).pack(side="left", padx=(16, 4))
        ctk.CTkCheckBox(head, text="Xóa video thì dồn cả phụ đề/giọng", variable=self.ripple, width=20,
                        checkbox_width=16, checkbox_height=16, font=(F, 11), fg_color=T["ACCENT"],
                        hover_color=T["ACCENT_HOVER"]).pack(side="left", padx=8)
        self._btn(head, "Vừa khung", self.zoom_fit, 84).configure(height=24)
        self.zoom_sl = ctk.CTkSlider(head, from_=0, to=1, width=150, height=14, command=self._on_zoom_slider,
                                     button_color=T["ACCENT"], button_hover_color=T["ACCENT_HOVER"],
                                     progress_color=T["ACCENT"])
        self.zoom_sl.pack(side="right")
        ctk.CTkLabel(head, text="🔍", font=(F, 12)).pack(side="right", padx=4)
        # nút "Vừa khung" đặt bên phải nhóm zoom
        for w in head.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.pack(side="right", padx=(0, 10))

        self.tl = tk.Canvas(tlw, height=self.tl_h, bg=T["PANEL"], highlightthickness=0)
        self.tl.pack(fill="x", padx=10, pady=(6, 0))
        self.hs = ctk.CTkScrollbar(tlw, orientation="horizontal", command=self._on_hscroll, height=12)
        self.hs.pack(fill="x", padx=10, pady=(2, 8))
        self.tl.bind("<Configure>", lambda e: self._schedule_timeline())
        self.tl.bind("<Button-1>", self._on_press)
        self.tl.bind("<B1-Motion>", self._on_motion)
        self.tl.bind("<ButtonRelease-1>", self._on_release)
        self.tl.bind("<Motion>", self._on_hover)
        self.tl.bind("<Double-Button-1>", self._on_double)
        self.tl.bind("<Button-3>", self._on_right_click)
        self.tl.bind("<MouseWheel>", self._on_wheel)
        self.tl.bind("<Button-4>", lambda e: self._on_wheel(e, 120))
        self.tl.bind("<Button-5>", lambda e: self._on_wheel(e, -120))

    # ---- tab Phụ đề
    def _build_sub_tab(self, tab):
        T, F = self.T, self.F
        self.q = tk.StringVar()
        ctk.CTkEntry(tab, textvariable=self.q, placeholder_text="Tìm trong phụ đề…", height=30,
                     font=(F, 12)).pack(fill="x", pady=(4, 6))
        self.q.trace_add("write", lambda *a: self._fill_list())
        box = ctk.CTkFrame(tab, fg_color="transparent")
        box.pack(fill="both", expand=True)
        sb = ctk.CTkScrollbar(box, command=lambda *a: self.lb.yview(*a))
        sb.pack(side="right", fill="y")
        self.lb = tk.Listbox(box, bg=T["PANEL"], fg="#dcdde4", selectbackground=T["ACCENT"],
                             selectforeground="white", highlightthickness=0, borderwidth=0,
                             activestyle="none", font=(F, 10), exportselection=False,
                             yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        self.lb.bind("<<ListboxSelect>>", self._on_list_select)
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        self.sub_count = ctk.CTkLabel(row, text="0 dòng", font=(F, 11), text_color=T["TEXT_MUTED"])
        self.sub_count.pack(side="left")
        self._btn(row, "＋ Dòng mới", self.op_add_sub).configure(height=26)
        for w in row.winfo_children():
            if isinstance(w, ctk.CTkButton):
                w.pack(side="right")
        self._btn(row, "📝 Nhập SRT", self.import_srt_dialog).configure(height=26)
        for w in row.winfo_children():
            if isinstance(w, ctk.CTkButton) and w.cget("text") == "📝 Nhập SRT":
                w.pack(side="right", padx=6)

    # ---- tab ✨ AI: gợi ý đoạn thừa để cắt rút gọn
    def _build_ai_tab(self, tab):
        T, F = self.T, self.F
        ctk.CTkLabel(tab, text="AI xem lời thoại + khung hình, gợi ý đoạn thừa để video gọn, giữ chân người xem.",
                     font=(F, 11), text_color=T["TEXT_MUTED"], wraplength=320, justify="left", anchor="w"
                     ).pack(fill="x", pady=(2, 6))
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="Mức rút gọn", font=(F, 11), text_color=T["TEXT_MUTED"]).pack(side="left")
        self.ai_level = ctk.CTkComboBox(row, values=list(AI.LEVELS), height=28, font=(F, 11), state="readonly", width=170)
        self.ai_level.set("Vừa (~10-20%)")
        self.ai_level.pack(side="right")
        self.ai_frames = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(tab, text="Gửi kèm khung hình (chính xác hơn, chậm hơn)", variable=self.ai_frames,
                        width=20, checkbox_width=16, checkbox_height=16, font=(F, 11), fg_color=T["ACCENT"],
                        hover_color=T["ACCENT_HOVER"]).pack(anchor="w", pady=(8, 6))
        brow = ctk.CTkFrame(tab, fg_color="transparent")
        brow.pack(fill="x")
        self.ai_btn = self._btn(brow, "🤖 AI phân tích video", self.ai_start, primary=True)
        self.ai_btn.pack(side="left", fill="x", expand=True)
        self.ai_stop_btn = self._btn(brow, "Dừng", self.ai_stop, 60)
        self.ai_bar = ctk.CTkProgressBar(tab, height=6, progress_color=T["ACCENT"])
        self.ai_bar.set(0)
        self.ai_bar.pack(fill="x", pady=(8, 2))
        self.ai_lbl = ctk.CTkLabel(tab, text="", font=(F, 11), text_color=T["TEXT_MUTED"], wraplength=330,
                                   justify="left", anchor="w")
        self.ai_lbl.pack(fill="x")
        # cụm nút dưới cùng ghim ở ĐÁY trước, để danh sách đề xuất co giãn trong phần còn lại
        foot = ctk.CTkFrame(tab, fg_color="transparent")
        foot.pack(side="bottom", fill="x")
        self.ai_list = ctk.CTkScrollableFrame(tab, fg_color=T["PANEL"], corner_radius=8, height=40)
        self.ai_list.pack(fill="both", expand=True, pady=(6, 6))
        self.ai_sum = ctk.CTkLabel(foot, text="", font=(F, 11, "bold"), anchor="w")
        self.ai_sum.pack(side="top", fill="x", pady=(0, 4))
        self._btn(foot, "Chọn hết", lambda: self._ai_set_all(True), 80).pack(side="left")
        self._btn(foot, "Bỏ chọn", lambda: self._ai_set_all(False), 80).pack(side="left", padx=6)
        self.ai_cut_btn = self._btn(foot, "✂ Cắt đoạn đã chọn", self.ai_apply, primary=True)
        self.ai_cut_btn.pack(side="right")

    def _ai_settings(self):
        """Lấy cấu hình Gemini Web2API từ app chính (cùng cổng/khoá/model với tab Translate)."""
        def val(name, default):
            try:
                v = getattr(self.app, name).get().strip()
                return v or default
            except Exception:
                return default
        return (val("gemini_fastapi_base_url", AI.DEFAULT_BASE_URL),
                val("gemini_fastapi_api_key", "") or None,
                val("gemini_fastapi_model", AI.DEFAULT_MODEL))

    def _ai_clear(self):
        self._ai_items = []
        self._ai_marks = []
        try:
            for w in self.ai_list.winfo_children():
                w.destroy()
            self.ai_sum.configure(text="")
            self._schedule_timeline()
        except Exception:
            pass

    def ai_start(self):
        if self._ai_busy:
            return
        if self.proj.duration <= 0:
            self._say("Chưa có video để AI phân tích")
            return
        if self.playing:
            self.pause()
        self._ai_clear()
        base, key, model = self._ai_settings()
        level, frames = self.ai_level.get(), self.ai_frames.get()
        self._ai_busy = True
        self._ai_cancel = threading.Event()
        self._ai_rev = self.proj.rev
        self.ai_btn.configure(state="disabled", text="⏳ AI đang phân tích...")
        self.ai_stop_btn.pack(side="left", padx=(6, 0))
        self.ai_bar.set(0.02)
        self.ai_lbl.configure(text=f"Kết nối {base} ...", text_color=self.T["TEXT_MUTED"])
        proj, cancel = self.proj, self._ai_cancel

        def work():
            try:
                res = AI.analyze(proj, base, key, model, level, frames,
                                 progress=lambda f, m: self._post(self._ai_progress, f, m), cancel=cancel)
                self._post(self._ai_done, res, None)
            except AI.AICancelled:
                self._post(self._ai_done, None, "cancel")
            except Exception as e:
                self._post(self._ai_done, None, str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()

    def ai_stop(self):
        if self._ai_cancel:
            self._ai_cancel.set()
            self.ai_lbl.configure(text="Đang dừng...")

    def _ai_progress(self, f: float, msg: str):
        if self._closed:
            return
        self.ai_bar.set(max(0.02, min(1.0, f)))
        self.ai_lbl.configure(text=msg, text_color=self.T["TEXT_MUTED"])

    def _ai_done(self, res, err):
        if self._closed:
            return
        self._ai_busy = False
        self.ai_btn.configure(state="normal", text="🤖 AI phân tích video")
        self.ai_stop_btn.pack_forget()
        if err:
            self.ai_bar.set(0)
            self.ai_lbl.configure(text="Đã dừng." if err == "cancel" else f"⚠ {err}",
                                  text_color=self.T["TEXT_MUTED"] if err == "cancel" else "#ff8a8a")
            return
        self.ai_bar.set(1.0)
        sug = res.suggestions
        if not sug:
            self.ai_lbl.configure(text="AI thấy video đã gọn - không có đoạn nào đáng cắt. 👍",
                                  text_color=self.T["GREEN"])
            return
        notes = [res.summary, res.note, "" if res.used_frames else "(chỉ dựa vào lời thoại)"]
        self.ai_lbl.configure(text=" ".join(n for n in notes if n), text_color=self.T["TEXT_MUTED"])
        self._ai_fill(sug)

    def _ai_fill(self, sug):
        T, F = self.T, self.F
        for w in self.ai_list.winfo_children():
            w.destroy()
        self._ai_items = []
        for s in sug:
            var = tk.BooleanVar(value=s.priority <= 2)
            card = ctk.CTkFrame(self.ai_list, fg_color=T["PANEL2"], corner_radius=8)
            card.pack(fill="x", padx=4, pady=3)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=8, pady=(6, 0))
            ctk.CTkCheckBox(top, text="", variable=var, width=22, checkbox_width=16, checkbox_height=16,
                            fg_color=T["ACCENT"], hover_color=T["ACCENT_HOVER"],
                            command=self._ai_refresh_marks).pack(side="left")
            ctk.CTkLabel(top, text=f"{fmt_time(s.start)} → {fmt_time(s.end)}", font=("Consolas", 11, "bold")
                         ).pack(side="left", padx=(2, 8))
            ctk.CTkLabel(top, text=f"−{s.dur:.1f}s", font=(F, 11, "bold"), text_color="#ff8a8a").pack(side="left")
            self._btn(top, "▶", lambda a=s.start: self.ai_preview(a), 30).configure(height=24)
            top.winfo_children()[-1].pack(side="right")
            ctk.CTkLabel(card, text=f"{AI.KIND_LABEL.get(s.kind, s.kind)} · {s.reason}", font=(F, 11),
                         text_color=T["TEXT_MUTED"], wraplength=290, justify="left", anchor="w"
                         ).pack(fill="x", padx=10, pady=(2, 7))
            self._ai_items.append(dict(s=s, var=var))
        self._ai_refresh_marks()
        if self._ai_items:
            self.seek(max(0.0, self._ai_items[0]["s"].start - 1.0))
            self._ensure_visible(self.playhead, force=True)

    def _ai_selected(self):
        return [it["s"] for it in self._ai_items if it["var"].get()]

    def _ai_refresh_marks(self):
        self._ai_marks = [(it["s"].start, it["s"].end, bool(it["var"].get())) for it in self._ai_items]
        sel = self._ai_selected()
        cut = sum(s.dur for s in sel)
        d = self.proj.duration
        self.ai_sum.configure(
            text=f"Đã chọn {len(sel)}/{len(self._ai_items)} đoạn · cắt {cut:.1f}s  ({fmt_time(d, False)} → {fmt_time(max(0.0, d - cut), False)})"
            if self._ai_items else "")
        self._schedule_timeline()

    def _ai_set_all(self, on: bool):
        for it in self._ai_items:
            it["var"].set(on)
        self._ai_refresh_marks()

    def ai_preview(self, start: float):
        """Nhảy tới trước đoạn gợi ý 1.5s và phát để nghe/xem thử trước khi quyết định cắt."""
        self.seek(max(0.0, start - 1.5))
        self._ensure_visible(self.playhead, force=True)
        if not self.playing:
            self.toggle_play()

    def ai_apply(self):
        sel = self._ai_selected()
        if not sel:
            self._say("Chưa chọn đoạn nào để cắt")
            return
        if self.proj.rev != self._ai_rev:
            messagebox.showwarning("Dự án đã thay đổi",
                                   "Bạn đã chỉnh sửa dự án sau khi AI phân tích nên mốc thời gian có thể lệch.\n"
                                   "Hãy bấm “AI phân tích video” lại.")
            return
        total = sum(s.dur for s in sel)
        if not messagebox.askyesno("Cắt đoạn thừa",
                                   f"Cắt {len(sel)} đoạn, tổng {total:.1f}s?\n"
                                   "(Phụ đề/giọng đọc dồn theo. Có thể hoàn tác bằng Ctrl+Z.)"):
            return
        if self.playing:
            self.pause()

        def do():
            done = 0.0
            for s in sorted(sel, key=lambda x: x.start, reverse=True):   # cắt từ cuối về đầu
                done += self.proj.cut_range(s.start, s.end)
            return done
        done = self._edit(do)
        self._ai_clear()
        self.ai_lbl.configure(text=f"✓ Đã cắt {done:.1f}s. Nhấn ↶ (Ctrl+Z) nếu muốn hoàn tác.",
                              text_color=self.T["GREEN"])
        self.seek(min(self.playhead, self.proj.duration))
        self._schedule_audio(100)        # dựng lại âm thanh xem trước ngay để nghe kiểm tra sớm

    # ---- tab Thuộc tính
    def _build_props_tab(self, tab):
        T, F = self.T, self.F
        tab.grid_columnconfigure(0, weight=1)
        self.p_title = ctk.CTkLabel(tab, text="Chưa chọn clip", font=(F, 12, "bold"), anchor="w")
        self.p_title.grid(row=0, column=0, sticky="ew", pady=(4, 6))

        def field(parent, label, r, width=80):
            ctk.CTkLabel(parent, text=label, font=(F, 11), text_color=T["TEXT_MUTED"], anchor="w"
                         ).grid(row=r, column=0, sticky="w", pady=3)
            e = ctk.CTkEntry(parent, width=width, height=26, font=(F, 11))
            e.grid(row=r, column=1, sticky="e", pady=3)
            e.bind("<Return>", lambda ev: self._apply_time_fields())
            e.bind("<FocusOut>", lambda ev: self._apply_time_fields())
            return e

        def slider(parent, label, r, lo, hi, cmd):
            ctk.CTkLabel(parent, text=label, font=(F, 11), text_color=T["TEXT_MUTED"], anchor="w"
                         ).grid(row=r, column=0, sticky="w", pady=3)
            s = ctk.CTkSlider(parent, from_=lo, to=hi, height=14, command=cmd, button_color=T["ACCENT"],
                              button_hover_color=T["ACCENT_HOVER"], progress_color=T["ACCENT"])
            s.grid(row=r, column=1, sticky="ew", padx=(10, 0), pady=3)
            s.bind("<ButtonRelease-1>", lambda ev: self._commit_live())
            return s

        self.g_time = ctk.CTkFrame(tab, fg_color="transparent")
        self.g_time.grid(row=1, column=0, sticky="ew")
        self.g_time.grid_columnconfigure(1, weight=1)
        self.e_start = field(self.g_time, "Bắt đầu (giây)", 0)
        self.e_dur = field(self.g_time, "Thời lượng (giây)", 1)

        self.g_media = ctk.CTkFrame(tab, fg_color="transparent")
        self.g_media.grid(row=2, column=0, sticky="ew")
        self.g_media.grid_columnconfigure(1, weight=1)
        self.s_vol = slider(self.g_media, "Âm lượng", 0, 0, 2, self._live_vol)
        self.vol_lbl = ctk.CTkLabel(self.g_media, text="100%", font=(F, 11), width=44)
        self.vol_lbl.grid(row=0, column=2)
        self.e_speed = field(self.g_media, "Tốc độ (x)", 1)

        self.g_cap = ctk.CTkFrame(tab, fg_color="transparent")
        self.g_cap.grid(row=3, column=0, sticky="ew")
        self.g_cap.grid_columnconfigure(1, weight=1)
        self.s_size = slider(self.g_cap, "Cỡ chữ", 0, 16, 200, lambda v: self._live_style("size", int(v)))
        self.s_x = slider(self.g_cap, "Vị trí ngang", 1, 0.05, 0.95, lambda v: self._live_style("x", float(v)))
        self.s_y = slider(self.g_cap, "Vị trí dọc", 2, 0.05, 0.95, lambda v: self._live_style("y", float(v)))
        cr = ctk.CTkFrame(self.g_cap, fg_color="transparent")
        cr.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        self.b_color = self._btn(cr, "Màu chữ", lambda: self._pick_color("color"))
        self.b_color.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.b_outline = self._btn(cr, "Màu viền", lambda: self._pick_color("outline"))
        self.b_outline.pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.box_var = tk.BooleanVar()
        ctk.CTkCheckBox(self.g_cap, text="Nền hộp mờ phía sau chữ", variable=self.box_var, font=(F, 11),
                        command=self._toggle_box, fg_color=T["ACCENT"], hover_color=T["ACCENT_HOVER"]
                        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=4)
        self._btn(self.g_cap, "Áp dụng kiểu này cho TẤT CẢ phụ đề", self.op_style_all
                  ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        self.g_proj = ctk.CTkFrame(tab, fg_color="transparent")
        self.g_proj.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        self.g_proj.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.g_proj, text="Cả dự án", font=(F, 11, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        self.duck_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.g_proj, text="Tự hạ tiếng gốc khi có giọng đọc", variable=self.duck_var,
                        font=(F, 11), command=self._toggle_duck, fg_color=T["ACCENT"],
                        hover_color=T["ACCENT_HOVER"]).grid(row=1, column=0, sticky="w", pady=4)
        fr = ctk.CTkFrame(self.g_proj, fg_color="transparent")
        fr.grid(row=2, column=0, sticky="ew")
        ctk.CTkLabel(fr, text="Font chữ", font=(F, 11), text_color=T["TEXT_MUTED"]).pack(side="left")
        self.font_cb = ctk.CTkComboBox(fr, values=FONTS, width=170, height=26, font=(F, 11),
                                       command=self._set_font)
        self.font_cb.pack(side="right")
        self.font_cb.set("Arial")

    # ---- hộp nhập nội dung chữ
    def _build_caption_box(self):
        T, F = self.T, self.F
        ctk.CTkLabel(self.cap_box, text="Nội dung chữ đang chọn", font=(F, 11, "bold"), anchor="w"
                     ).pack(fill="x", padx=10, pady=(8, 2))
        self.txt = ctk.CTkTextbox(self.cap_box, height=76, font=(F, 12), fg_color=T["PANEL"], wrap="word")
        self.txt.pack(fill="x", padx=10, pady=(0, 10))
        self.txt.bind("<FocusIn>", lambda e: self.proj.begin())
        self.txt.bind("<KeyRelease>", self._on_text_key)
        self.txt.bind("<FocusOut>", lambda e: self._commit_live())
        self.cap_box.pack_forget()

    # ---- tab Xuất
    def _build_export_tab(self, tab):
        T, F = self.T, self.F
        tab.grid_columnconfigure(1, weight=1)

        def combo(label, r, values, default):
            ctk.CTkLabel(tab, text=label, font=(F, 11), text_color=T["TEXT_MUTED"], anchor="w"
                         ).grid(row=r, column=0, sticky="w", pady=5)
            cb = ctk.CTkComboBox(tab, values=list(values), height=28, font=(F, 11), state="readonly")
            cb.grid(row=r, column=1, sticky="ew", padx=(10, 0), pady=5)
            cb.set(default)
            return cb

        self.x_aspect = combo("Tỉ lệ khung", 0, M.ASPECTS, "Gốc")
        self.x_res = combo("Độ phân giải", 1, RES_MODES, "Giữ nguyên")
        self.x_fit = combo("Khi lệch tỉ lệ", 2, FIT_MODES, "Nền mờ (khuyên dùng)")
        self.x_q = combo("Chất lượng", 3, M.QUALITY, "Chuẩn (CRF 21)")
        self._btn(tab, "⬆ Xuất video…", self.export_dialog, primary=True).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(14, 6))
        self.exp_bar = ctk.CTkProgressBar(tab, height=8, progress_color=T["ACCENT"])
        self.exp_bar.set(0)
        self.exp_bar.grid(row=5, column=0, columnspan=2, sticky="ew", pady=4)
        self.exp_lbl = ctk.CTkLabel(tab, text="", font=(F, 11), text_color=T["TEXT_MUTED"], wraplength=300,
                                    justify="left", anchor="w")
        self.exp_lbl.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.exp_cancel_btn = self._btn(tab, "Hủy xuất", self._cancel_export)
        self._btn(tab, "📝 Xuất phụ đề (.srt)…", self.export_srt_dialog).grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(14, 0))

    # ================================================================== nền tảng
    def _post(self, fn, *a):
        """Luồng nền gọi hàm này để chạy `fn(*a)` trên luồng UI (Tk không an toàn đa luồng)."""
        self._q.put((fn, a))

    def _pump(self):
        if self._closed:
            return
        try:
            while True:
                fn, a = self._q.get_nowait()
                try:
                    fn(*a)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        try:
            self.after(50, self._pump)
        except Exception:
            pass

    def shutdown(self):
        """Dừng phát, đóng file đang mở, xoá file tạm. An toàn khi gọi nhiều lần."""
        if self._closed:
            return
        self._closed = True
        try:
            self.pause()
        except Exception:
            pass
        for r in list(self.readers.values()):
            r.close()
        self.readers.clear()
        try:
            self.audio.release()
        except Exception:
            pass
        for f in (self._audio_wav, self._audio_wav + ".tmp.wav"):
            try:
                os.remove(f)
            except OSError:
                pass

    def _say(self, msg: str):
        try:
            self.status_lbl.configure(text=msg)
        except Exception:
            pass

    # ---- toạ độ timeline
    def _px(self, t: float) -> float:
        return LABEL_W + t * self.pps - self.scroll

    def _tx(self, x: float) -> float:
        return (x - LABEL_W + self.scroll) / self.pps

    def _view_w(self) -> float:
        return max(50.0, self.tl.winfo_width() - LABEL_W)

    def _total_px(self) -> float:
        return max(self.proj.duration + 4.0, 10.0) * self.pps + self._view_w() * 0.25

    def _clamp_scroll(self):
        self.scroll = max(0.0, min(self.scroll, max(0.0, self._total_px() - self._view_w())))

    def _schedule_timeline(self):
        if not self._tl_pending:
            self._tl_pending = True
            self.after_idle(self._draw_timeline)

    def _schedule_preview(self):
        if not self._pv_pending:
            self._pv_pending = True
            self.after_idle(self._draw_preview)

    def _pkey(self):
        return (id(self.proj), self.proj.rev)

    # ================================================================== làm mới giao diện
    def _on_changed(self):
        """Gọi sau mỗi thay đổi nội dung dự án (đã commit)."""
        if self.playing:
            self.pause()
        self._refresh_all()

    def _refresh_all(self):
        if self._closed:
            return
        p = self.proj
        if self.sel and not p.get(self.sel):
            self.sel = None
        self.playhead = max(0.0, min(self.playhead, p.duration))
        name = os.path.basename(p.path) if p.path else "Dự án chưa lưu"
        info = f"   ·   {p.w}×{p.h} @ {p.fps:g}fps" if p.lane("video") else ""
        self.title_lbl.configure(text=f"{name}{'  •' if p.dirty else ''}{info}")
        self.undo_btn.configure(state="normal" if p.can_undo else "disabled")
        self.redo_btn.configure(state="normal" if p.can_redo else "disabled")
        self.duck_var.set(p.duck)
        self.font_cb.set(p.font)
        self._fill_list()
        self._sync_selection()
        self._ensure_assets()
        self._update_zoom_slider()
        self._update_time_label()
        self._schedule_timeline()
        self._schedule_preview()
        self._schedule_audio()
        miss = p.missing_media()
        if miss:
            self._say(f"⚠ Thiếu {len(miss)} file: {os.path.basename(miss[0])}" + ("…" if len(miss) > 1 else ""))

    def _update_time_label(self):
        self.time_lbl.configure(text=f"{fmt_time(self.playhead)} / {fmt_time(self.proj.duration)}")

    def _fill_list(self):
        q = self.q.get().strip().lower()
        subs = self.proj.lane("sub")
        self.lb.delete(0, "end")
        self._list_ids = []
        for i, c in enumerate(subs, 1):
            if q and q not in c.text.lower():
                continue
            self.lb.insert("end", f"{i:>3}   {fmt_time(c.start)}   {c.text.replace(chr(10), ' ')}")
            self._list_ids.append(c.id)
        n = len(subs)
        shown = len(self._list_ids)
        self.sub_count.configure(text=f"{n} dòng" if shown == n else f"{shown}/{n} dòng")
        if self.sel in self._list_ids:
            i = self._list_ids.index(self.sel)
            self.lb.selection_set(i)
            self.lb.see(i)
        self._cur_sub = None

    def _on_list_select(self, _e=None):
        sel = self.lb.curselection()
        if not sel or sel[0] >= len(self._list_ids):
            return
        c = self.proj.get(self._list_ids[sel[0]])
        if not c:
            return
        self.sel = c.id
        self._sync_selection()
        self.seek(c.start + 0.01)
        self._ensure_visible(c.start, force=True)
        self._schedule_timeline()

    def _sync_selection(self):
        """Đồng bộ tab Thuộc tính + hộp nhập chữ với clip đang chọn."""
        c = self.proj.get(self.sel)
        for g in (self.g_time, self.g_media, self.g_cap):
            g.grid_remove()
        if not c:
            self.p_title.configure(text="Chưa chọn clip - nhấn vào một clip trên timeline")
            self._show_cap_box(False)
            return
        label = c.name or c.text.replace("\n", " ")[:28] or "(trống)"
        self.p_title.configure(text=f"{LANE_LABEL[c.lane]}  ·  {label}")
        self.g_time.grid()
        self._set_entry(self.e_start, f"{c.start:.2f}", disabled=(c.lane == "video"))
        self._set_entry(self.e_dur, f"{c.dur:.2f}")
        if c.is_media:
            self.g_media.grid()
            self.s_vol.set(min(2.0, c.vol))
            self.vol_lbl.configure(text=f"{int(round(c.vol * 100))}%")
            self._set_entry(self.e_speed, f"{c.speed:g}", disabled=c.still)
        if c.is_caption:
            self.g_cap.grid()
            self.s_size.set(c.size)
            self.s_x.set(c.x)
            self.s_y.set(c.y)
            self.box_var.set(c.box)
            for btn, col in ((self.b_color, c.color), (self.b_outline, c.outline)):
                lum = sum(int(col.lstrip("#")[i:i + 2] or "0", 16) * w for i, w in ((0, .3), (2, .59), (4, .11)))
                btn.configure(fg_color=col, hover_color=col, text_color="#000000" if lum > 140 else "#ffffff")
            self._show_cap_box(True)
            focused = False
            try:
                focused = self.focus_get() is self.txt._textbox
            except Exception:
                pass
            if not focused and self.txt.get("1.0", "end-1c") != c.text:
                self.txt.delete("1.0", "end")
                self.txt.insert("1.0", c.text)
        else:
            self._show_cap_box(False)

    @staticmethod
    def _set_entry(entry, text: str, disabled: bool = False):
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, text)
        if disabled:
            entry.configure(state="disabled")

    def _show_cap_box(self, show: bool):
        if show and not self._cap_shown:
            self.cap_box.pack(side="bottom", fill="x", padx=10, pady=(0, 10), before=self.tabs)
            self._cap_shown = True
        elif not show and self._cap_shown:
            self.cap_box.pack_forget()
            self._cap_shown = False

    # ================================================================== chỉnh sửa
    def _edit(self, fn, *a):
        rev0 = self.proj.rev
        with self.proj.edit():
            r = fn(*a)
        if self.proj.rev != rev0:
            self._on_changed()
        return r

    def op_undo(self):
        if self.proj.undo():
            self._on_changed()

    def op_redo(self):
        if self.proj.redo():
            self._on_changed()

    def op_split(self):
        p = self.proj
        target = self.sel
        c = p.get(target) if target else None
        if not c or not (c.start < self.playhead < c.end):
            vc, _ = p.video_at(self.playhead)          # không chọn gì / đầu phát ngoài clip -> tách clip hình tại đầu phát
            c = vc
        if not c:
            self._say("Đặt đầu phát lên clip cần tách.")
            return
        res = self._edit(p.split, c.id, self.playhead)
        if res is None:
            self._say("Không tách được ở vị trí này (quá sát mép clip).")
        else:
            self.sel = res.id
            self._sync_selection()

    def op_delete(self):
        c = self.proj.get(self.sel)
        if not c:
            self._say("Chưa chọn clip để xóa.")
            return
        self.sel = None
        self._edit(self.proj.delete, c.id, self.ripple.get())

    def op_duplicate(self):
        c = self.proj.get(self.sel)
        if not c or c.lane == "video":
            return
        def do():
            n = _clip_from_dict(asdict(c))
            n.id = uuid.uuid4().hex[:8]
            n.start = c.end
            self.proj.clips.append(n)
            return n
        n = self._edit(do)
        if n:
            self.sel = n.id
            self._sync_selection()

    def _toggle_mute(self):
        c = self.proj.get(self.sel)
        if c and c.is_media:
            def do():
                c.vol = 0.0 if c.vol > 0 else 1.0
            self._edit(do)

    def op_add_text(self, at: Optional[float] = None):
        c = self._edit(self.proj.add_text, self.playhead if at is None else at, "Chữ mới", 3.0, "text")
        if c:
            self.sel = c.id
            self._sync_selection()
            self.tabs.set("Thuộc tính")
            self.txt.focus_set()
            self.txt.tag_add("sel", "1.0", "end-1c")

    def op_add_sub(self):
        c = self._edit(self.proj.add_text, self.playhead, "Phụ đề mới", 2.5, "sub")
        if c:
            self.sel = c.id
            self._sync_selection()
            self.txt.focus_set()
            self.txt.tag_add("sel", "1.0", "end-1c")

    def op_style_all(self):
        c = self.proj.get(self.sel)
        if c and c.is_caption:
            self._edit(self.proj.apply_style_to_all, c.id, c.lane)
            self._say(f"Đã áp dụng kiểu chữ cho tất cả '{LANE_LABEL[c.lane]}'.")

    # ---- sửa trực tiếp (kéo thanh trượt / gõ chữ): begin() khi bắt đầu, commit khi thả
    def _commit_live(self):
        if self.proj.commit():
            self._on_changed()

    def _live_vol(self, v):
        c = self.proj.get(self.sel)
        if c and c.is_media:
            self.proj.begin()
            c.vol = round(float(v), 2)
            self.vol_lbl.configure(text=f"{int(round(c.vol * 100))}%")

    def _live_style(self, key, v):
        c = self.proj.get(self.sel)
        if c and c.is_caption:
            self.proj.begin()
            setattr(c, key, v)
            self._schedule_preview()

    def _on_text_key(self, _e=None):
        c = self.proj.get(self.sel)
        if not c or not c.is_caption:
            return
        txt = self.txt.get("1.0", "end-1c")
        if txt != c.text:
            self.proj.begin()
            c.text = txt
            self._schedule_preview()
            self._schedule_timeline()

    def _toggle_box(self):
        c = self.proj.get(self.sel)
        if c and c.is_caption:
            def do():
                c.box = bool(self.box_var.get())
            self._edit(do)

    def _pick_color(self, key: str):
        c = self.proj.get(self.sel)
        if not c or not c.is_caption:
            return
        _, hexv = colorchooser.askcolor(color=getattr(c, key), parent=self.winfo_toplevel(),
                                        title="Chọn màu chữ" if key == "color" else "Chọn màu viền")
        if hexv:
            def do():
                setattr(c, key, hexv.upper())
            self._edit(do)

    def _toggle_duck(self):
        def do():
            self.proj.duck = bool(self.duck_var.get())
        self._edit(do)

    def _set_font(self, v):
        def do():
            self.proj.font = v
        self._edit(do)

    def _apply_time_fields(self):
        c = self.proj.get(self.sel)
        if not c:
            return
        try:
            ns = c.start if c.lane == "video" else max(0.0, parse_secs(self.e_start.get()))
            nd = max(MIN_DUR, parse_secs(self.e_dur.get()))
            sp = c.speed
            if c.is_media and not c.still:
                sp = min(8.0, max(0.25, float(self.e_speed.get().replace(",", "."))))
        except ValueError:
            self._sync_selection()
            return
        if abs(ns - c.start) < 5e-3 and abs(nd - c.dur) < 5e-3 and abs(sp - c.speed) < 1e-6:
            return

        def do():
            dur = nd
            if abs(sp - c.speed) > 1e-6:                 # đổi tốc độ: giữ nguyên đoạn nguồn, độ dài co giãn theo
                used = c.dur * c.speed
                c.speed = sp
                if abs(nd - c.dur) < 5e-3:
                    dur = used / sp
            c.start, c.dur = ns, dur
            c.dur = max(MIN_DUR, min(c.dur, c.max_dur()))
            if c.lane == "video":
                self.proj.relayout_video()
        self._edit(do)

    # ================================================================== dự án / tệp
    def _confirm_discard(self) -> bool:
        if self.proj.dirty and self.proj.clips:
            return messagebox.askyesno("Dự án chưa lưu", "Dự án hiện tại có thay đổi chưa lưu.\nBỏ các thay đổi này?",
                                       parent=self.winfo_toplevel())
        return True

    def _set_project(self, p: Project):
        self._ai_clear()
        self.pause()
        self.proj = p
        self.sel = None
        self.playhead = 0.0
        self.scroll = 0.0
        for r in self.readers.values():
            r.close()
        self.readers.clear()
        self._audio_rev = -1
        self._refresh_all()
        self.after(50, self.zoom_fit)

    def project_new(self):
        if self._confirm_discard():
            self._set_project(Project())

    def project_open(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(title="Mở dự án", filetypes=[("Dự án RP Editor", "*.rpedit"), ("Tất cả", "*.*")])
        if not path:
            return
        try:
            p = Project.load(path)
        except Exception as e:
            messagebox.showerror("Không mở được dự án", str(e))
            return
        self._set_project(p)
        miss = p.missing_media()
        if miss:
            messagebox.showwarning("Thiếu file gốc", "Không tìm thấy:\n" + "\n".join(miss[:8]))

    def project_save(self, save_as: bool = False):
        path = self.proj.path
        if save_as or not path:
            path = filedialog.asksaveasfilename(title="Lưu dự án", defaultextension=".rpedit",
                                                filetypes=[("Dự án RP Editor", "*.rpedit")])
        if not path:
            return
        try:
            self.proj.save(path)
        except Exception as e:
            messagebox.showerror("Không lưu được", str(e))
            return
        self._refresh_all()
        self._say(f"Đã lưu: {path}")

    def _popup_file_menu(self):
        T = self.T
        m = tk.Menu(self, tearoff=0, bg=T["PANEL2"], fg="#e6e6ee", activebackground=T["ACCENT"],
                    activeforeground="white", bd=0, font=(self.F, 10))
        for it in (("Dự án mới", self.project_new), ("Mở dự án…", self.project_open),
                   ("Lưu dự án      Ctrl+S", self.project_save),
                   ("Lưu dự án thành…", lambda: self.project_save(True)), None,
                   ("Mở video khác (dự án mới)…", self.open_video_dialog),
                   ("Nhập phụ đề (.srt)…", self.import_srt_dialog),
                   ("Xuất phụ đề (.srt)…", self.export_srt_dialog), None,
                   ("Xuất video…", lambda: (self.tabs.set("Xuất"), self.export_dialog()))):
            if it is None:
                m.add_separator()
            else:
                m.add_command(label=it[0], command=it[1])
        b = self.file_btn
        try:
            m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            m.grab_release()

    def _probe_or_warn(self, path: str) -> Optional[dict]:
        try:
            return M.probe(path)
        except Exception as e:
            messagebox.showerror("Không đọc được file", f"{os.path.basename(path)}\n\n{e}", parent=self.winfo_toplevel())
            return None

    @staticmethod
    def _read_srt(path: str):
        raw = open(path, "rb").read()
        text = None
        for enc in ("utf-8-sig", "utf-16", "cp1258", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return parse_srt(text or raw.decode("utf-8", "replace"))

    def open_media(self, video_path: str, srt_path: Optional[str] = None) -> bool:
        """API cho main.py: mở 1 video (+ tuỳ chọn file .srt làm phụ đề) thành dự án mới."""
        if not self._confirm_discard():
            return False
        info = self._probe_or_warn(video_path)
        if not info:
            return False
        if not info.get("has_video"):
            messagebox.showerror("Không phải video/ảnh", os.path.basename(video_path))
            return False
        p = Project()
        p.add_video(video_path, info)
        if srt_path and os.path.isfile(srt_path):
            try:
                p.set_subs(self._read_srt(srt_path))
            except Exception as e:
                self._say(f"⚠ Không đọc được SRT: {e}")
        self._set_project(p)
        return True

    def open_video_dialog(self):
        path = filedialog.askopenfilename(title="Chọn video / ảnh", filetypes=VIDEO_TYPES)
        if path:
            self.open_media(path)

    def add_video_dialog(self):
        paths = filedialog.askopenfilenames(title="Thêm video / ảnh vào cuối track Hình", filetypes=VIDEO_TYPES)
        if not paths:
            return
        infos = []
        for path in paths:
            info = self._probe_or_warn(path)
            if info and info.get("has_video"):
                infos.append((path, info))
        if not infos:
            return
        first = not self.proj.lane("video")

        def do():
            c = None
            for path, info in infos:
                c = self.proj.add_video(path, info)
            return c
        c = self._edit(do)
        if c:
            self.sel = c.id
            self._sync_selection()
            if first:
                self.after(50, self.zoom_fit)

    def add_audio_dialog(self, lane: str):
        if not self.proj.lane("video"):
            messagebox.showinfo("Chưa có video", "Hãy thêm video trước rồi mới thêm âm thanh.", parent=self.winfo_toplevel())
            return
        paths = filedialog.askopenfilenames(title="Chọn giọng đọc" if lane == "voice" else "Chọn nhạc / âm thanh",
                                            filetypes=AUDIO_TYPES)
        if not paths:
            return
        infos = []
        for path in paths:
            info = self._probe_or_warn(path)
            if info and info.get("has_audio"):
                infos.append((path, info))
            elif info:
                messagebox.showwarning("Không có âm thanh", os.path.basename(path))
        if not infos:
            return
        start_at = self.playhead

        def do():
            c, at = None, start_at
            for path, info in infos:
                c = self.proj.add_audio(lane, path, info, at=at)
                at += c.dur
            return c
        c = self._edit(do)
        if c:
            self.sel = c.id
            self._sync_selection()

    def import_srt_dialog(self):
        path = filedialog.askopenfilename(title="Chọn file phụ đề", filetypes=[("Phụ đề SRT", "*.srt"), ("Tất cả", "*.*")])
        if not path:
            return
        try:
            items = self._read_srt(path)
        except Exception as e:
            messagebox.showerror("Không đọc được SRT", str(e))
            return
        if not items:
            messagebox.showwarning("File rỗng", "Không tìm thấy dòng phụ đề hợp lệ trong file này.")
            return
        if self.proj.lane("sub") and not messagebox.askyesno(
                "Thay phụ đề", f"Thay {len(self.proj.lane('sub'))} dòng phụ đề hiện có bằng {len(items)} dòng từ file?"):
            return
        self._edit(self.proj.set_subs, items)
        self._say(f"Đã nhập {len(items)} dòng phụ đề.")

    def export_srt_dialog(self):
        if not self.proj.lane("sub"):
            messagebox.showinfo("Chưa có phụ đề", "Track Phụ đề đang trống.")
            return
        path = filedialog.asksaveasfilename(title="Xuất phụ đề", defaultextension=".srt", filetypes=[("Phụ đề SRT", "*.srt")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.proj.captions_as_srt("sub"))
        self._say(f"Đã xuất phụ đề: {path}")

    # ================================================================== zoom / cuộn
    def _update_zoom_slider(self):
        v = math.log(self.pps / PPS_MIN) / math.log(PPS_MAX / PPS_MIN)
        self.zoom_sl.set(max(0.0, min(1.0, v)))

    def _set_zoom(self, pps: float, anchor_x: Optional[float] = None):
        pps = max(PPS_MIN, min(PPS_MAX, pps))
        ax = LABEL_W + self._view_w() / 2 if anchor_x is None else anchor_x
        ta = self._tx(ax)
        self.pps = pps
        self.scroll = ta * pps - (ax - LABEL_W)
        self._clamp_scroll()
        self._update_zoom_slider()
        self._schedule_timeline()

    def _on_zoom_slider(self, v):
        pps = PPS_MIN * (PPS_MAX / PPS_MIN) ** float(v)
        x = self._px(self.playhead)
        self._set_zoom(pps, x if LABEL_W <= x <= self.tl.winfo_width() else None)

    def zoom_fit(self):
        if self.tl.winfo_width() < 120:
            self.after(80, self.zoom_fit)
            return
        dur = max(1.0, self.proj.duration)
        self.pps = max(PPS_MIN, min(PPS_MAX, (self._view_w() - 24) / dur))
        self.scroll = 0.0
        self._update_zoom_slider()
        self._schedule_timeline()

    def _on_hscroll(self, *args):
        tot, vw = self._total_px(), self._view_w()
        if args and args[0] == "moveto":
            self.scroll = float(args[1]) * tot
        elif args and args[0] == "scroll":
            n = int(args[1])
            self.scroll += n * (vw * 0.1 if args[2] == "units" else vw * 0.9)
        self._clamp_scroll()
        self._schedule_timeline()

    def _update_hscroll(self):
        tot, vw = self._total_px(), self._view_w()
        self.hs.set(self.scroll / tot, min(1.0, (self.scroll + vw) / tot))

    def _on_wheel(self, e, delta: Optional[int] = None):
        d = delta if delta is not None else e.delta
        if not d:
            return "break"
        if e.state & 0x4:                                   # Ctrl + lăn = zoom quanh con trỏ
            self._set_zoom(self.pps * (1.18 if d > 0 else 1 / 1.18), e.x)
        else:                                               # lăn = cuộn ngang
            self.scroll -= (d / 120.0) * self._view_w() * 0.12
            self._clamp_scroll()
            self._schedule_timeline()
        return "break"

    def _ensure_visible(self, t: float, force: bool = False):
        x = self._px(t)
        W = self.tl.winfo_width()
        if force:
            if x < LABEL_W + 10 or x > W - 30:
                self.scroll = max(0.0, t * self.pps - self._view_w() * 0.3)
                self._clamp_scroll()
                self._schedule_timeline()
        elif x > W - 20 or x < LABEL_W:
            self.scroll = max(0.0, t * self.pps - self._view_w() * 0.12)
            self._clamp_scroll()
            self._schedule_timeline()

    # ================================================================== vẽ timeline
    def _draw_timeline(self):
        self._tl_pending = False
        if self._closed:
            return
        T, F, c = self.T, self.F, self.tl
        W = c.winfo_width()
        if W < 60:
            return
        c.delete("all")
        self._hit = []
        self._clamp_scroll()
        vw = W - LABEL_W
        t0, t1 = self.scroll / self.pps, (self.scroll + vw) / self.pps

        for ln in LANES:
            y0, y1 = self.lane_y[ln]
            c.create_rectangle(LABEL_W, y0, W, y1, fill="#12131a", outline="")
        self._draw_ruler(c, W, t0, t1)
        for ln in LANES:
            self._draw_lane(c, ln, W, t0, t1)
        if not self.proj.clips:
            y0, y1 = self.lane_y["video"]
            c.create_text(LABEL_W + 20, (y0 + y1) / 2, anchor="w", fill=T["TEXT_MUTED"], font=(F, 10),
                          text="Chưa có gì - nhấn “＋ Video/Ảnh” để bắt đầu dựng")

        for s, e, on in self._ai_marks:                     # đoạn AI gợi ý cắt (đỏ)
            xa, xb = max(LABEL_W, self._px(s)), min(W, self._px(e))
            if xb > xa:
                c.create_rectangle(xa, RULER_H, xb, self.tl_h - 4, fill="#ff4d6d", outline="",
                                   stipple="gray25" if on else "gray12")
                c.create_rectangle(xa, RULER_H - 4, xb, RULER_H, fill="#ff4d6d" if on else "#7a3a48", outline="")
        c.create_rectangle(0, 0, LABEL_W, self.tl_h, fill=T["PANEL"], outline="")      # cột nhãn (che phần tràn)
        for ln in LANES:
            y0, y1 = self.lane_y[ln]
            c.create_text(10, (y0 + y1) / 2, text=LANE_LABEL[ln], anchor="w", fill=T["TEXT_MUTED"], font=(F, 9))
        c.create_line(LABEL_W, 0, LABEL_W, self.tl_h, fill=T["BORDER"])
        self._draw_playhead()
        self._update_hscroll()

    def _draw_ruler(self, c, W, t0, t1):
        T = self.T
        c.create_rectangle(LABEL_W, 0, W, RULER_H, fill="#101116", outline="")
        step = next((s for s in NICE_STEPS if s * self.pps >= 80), NICE_STEPS[-1])
        i = int(t0 // step)
        while True:
            t = i * step
            if t > t1 + step:
                break
            x = self._px(t)
            if x >= LABEL_W - 1:
                c.create_line(x, RULER_H - 10, x, RULER_H, fill="#5a5c69")
                c.create_text(x + 4, 9, text=fmt_time(t, step < 1), anchor="w", fill=T["TEXT_MUTED"], font=("Consolas", 8))
            xm = self._px(t + step / 2)
            if xm >= LABEL_W:
                c.create_line(xm, RULER_H - 5, xm, RULER_H, fill="#3a3b46")
            i += 1
        c.create_line(LABEL_W, RULER_H, W, RULER_H, fill=T["BORDER"])

    def _draw_lane(self, c, ln, W, t0, t1):
        clips = self.proj.lane(ln)
        if not clips:
            return
        y0, y1 = self.lane_y[ln]
        fill, edge, ink = LANE_COL[ln]
        rows = pack_rows(clips, 1 if ln == "video" else 2)
        for cl in clips:
            if cl.end < t0 - 0.5 or cl.start > t1 + 0.5:
                continue
            row, n = rows[cl.id]
            rh = (y1 - y0) / n
            ya, yb = y0 + row * rh + 1, y0 + (row + 1) * rh - 1
            xa, xb = self._px(cl.start), self._px(cl.end)
            sel = cl.id == self.sel
            c.create_rectangle(xa, ya, xb, yb, fill=fill, outline="#ffffff" if sel else edge, width=2 if sel else 1)
            self._hit.append((xa, ya, xb, yb, cl.id))
            w = xb - xa
            if ln == "video":
                self._draw_video_clip(c, cl, xa, ya, xb, yb, W, t0, t1)
            elif ln in ("voice", "music"):
                self._draw_wave(c, cl, ya, yb, ink, t0, t1, amp=(yb - ya) * 0.42)
                if w > 70 and n == 1:
                    c.create_text(xa + 4, ya + 8, text=cl.name, anchor="w", fill=ink, font=(self.F, 8))
            else:
                maxc = int((w - 8) / 5.4)
                if maxc >= 2:
                    txt = cl.text.replace("\n", " ")
                    txt = txt if len(txt) <= maxc else txt[:maxc - 1] + "…"
                    c.create_text(xa + 4, (ya + yb) / 2, text=txt, anchor="w", fill=ink, font=(self.F, 8 if n > 1 else 9))
            if sel and w > 14:                                            # tay nắm kéo mép
                for hx in (xa + 2, xb - 4):
                    c.create_rectangle(hx, ya + 4, hx + 2, yb - 4, fill="#ffffff", outline="")

    def _thumb_photo(self, src: str, idx: int, w: int):
        key = (src, idx, w)
        ph = self._thumb_tk.get(key)
        if ph is None:
            _, imgs = self.thumbs[src]
            im = imgs[idx]
            if w < im.width:
                im = im.crop((0, 0, max(1, w), im.height))
            if len(self._thumb_tk) > 700:
                self._thumb_tk.clear()
            ph = self._thumb_tk[key] = ImageTk.PhotoImage(im)
        return ph

    def _draw_video_clip(self, c, cl, xa, ya, xb, yb, W, t0, t1):
        th = self.thumbs.get(cl.src)
        if th and th[1]:
            step, imgs = th
            tw = imgs[0].width
            vis0, vis1 = max(xa, LABEL_W - tw), min(xb, W)
            i0 = max(0, int((vis0 - xa) // tw))
            i1 = int(math.ceil((vis1 - xa) / tw))
            for i in range(i0, i1):
                x = xa + i * tw
                mid_t = (x + tw / 2 - xa) / self.pps
                st = cl.src_in + mid_t * cl.speed
                idx = 0 if cl.still else max(0, min(len(imgs) - 1, int(st / step + 0.5)))
                wpx = int(min(tw, xb - x))
                if wpx < 2:
                    continue
                c.create_image(x, ya + (yb - ya - imgs[0].height) / 2, image=self._thumb_photo(cl.src, idx, wpx), anchor="nw")
        else:
            c.create_text(xa + 8, (ya + yb) / 2, text="đang tải hình…", anchor="w", fill="#a79dff", font=(self.F, 8))
        if xb - xa > 40:                                       # tên + thanh sóng âm mỏng ở đáy
            c.create_rectangle(xa + 1, ya + 1, min(xb - 1, xa + 10 + 5.6 * len(cl.name)), ya + 14, fill="#15161c",
                               outline="")
            c.create_text(xa + 5, ya + 8, text=cl.name, anchor="w", fill="#ffffff", font=(self.F, 8))
        if cl.has_audio and not cl.still and cl.src in self.waves:
            c.create_rectangle(xa + 1, yb - 16, xb - 1, yb - 1, fill="#15161c", outline="")
            self._draw_wave(c, cl, yb - 16, yb - 1, "#e6d27a", t0, t1, amp=6.5)

    def _draw_wave(self, c, cl, ya, yb, ink, t0, t1, amp):
        w = self.waves.get(cl.src)
        if w is None or len(w) < 2:
            return
        import numpy as np
        a, b = max(cl.start, t0), min(cl.end, t1)
        if b <= a:
            return
        xa, xb = self._px(a), self._px(b)
        n = max(2, int((xb - xa) // 2))
        xs = np.linspace(xa, xb, n)
        ts = cl.src_in + (a - cl.start + (xs - xa) / self.pps) * cl.speed
        idx = np.clip((ts * M.WAVE_PER_SEC).astype(int), 0, len(w) - 1)
        k = int(M.WAVE_PER_SEC * cl.speed * 2 / self.pps)          # zoom xa: lấy đỉnh trong cửa sổ 2px, đỡ nhấp nháy
        amps = np.array([w[i:i + k].max() for i in idx]) if k > 1 else w[idx]
        yc = (ya + yb) / 2
        h = np.maximum(0.6, amps * amp)
        pts = np.concatenate([np.column_stack((xs, yc - h)), np.column_stack((xs[::-1], (yc + h)[::-1]))]).ravel()
        c.create_polygon(pts.tolist(), fill=ink, outline="")

    def _draw_playhead(self):
        c = self.tl
        c.delete("ph")
        x = self._px(self.playhead)
        if x < LABEL_W - 1 or x > c.winfo_width():
            return
        c.create_line(x, 0, x, self.tl_h, fill="#ff4d5e", width=2, tags="ph")
        c.create_polygon(x - 6, 0, x + 6, 0, x, 10, fill="#ff4d5e", outline="", tags="ph")

    # ================================================================== chuột trên timeline
    def _clip_at(self, x, y):
        if x < LABEL_W:
            return None, 0, 0
        for xa, ya, xb, yb, cid in reversed(self._hit):
            if xa <= x <= xb and ya <= y <= yb:
                return cid, xa, xb
        return None, 0, 0

    @staticmethod
    def _edge_zone(xa, xb) -> float:
        return EDGE_PX if (xb - xa) > 3 * EDGE_PX else max(2.0, (xb - xa) / 4)

    def _on_press(self, e):
        self.tl.focus_set()                                  # chốt mọi ô nhập đang sửa dở (FocusOut) TRƯỚC khi đổi clip
        self._drag = None
        if e.x < LABEL_W:
            return
        if e.y < RULER_H:
            self.pause()
            self._drag = {"mode": "scrub"}
            self.seek(self._tx(e.x))
            return
        cid, xa, xb = self._clip_at(e.x, e.y)
        if not cid:
            self.pause()
            self.sel = None
            self._sync_selection()
            self._schedule_timeline()
            self._drag = {"mode": "scrub"}
            self.seek(self._tx(e.x))
            return
        c = self.proj.get(cid)
        self.sel = cid
        z = self._edge_zone(xa, xb)
        mode = "l" if e.x - xa <= z else "r" if xb - e.x <= z else "move"
        self.proj.begin()
        self._drag = dict(mode=mode, cid=cid, x0=e.x, start0=c.start, dur0=c.dur, in0=c.src_in, moved=False)
        self._sync_selection()
        self._schedule_timeline()

    def _snap(self, t: float, pts) -> float:
        if not self.snap.get():
            return t
        thr = SNAP_PX / self.pps
        best = min(pts, key=lambda q: abs(q - t))
        return best if abs(best - t) <= thr else t

    def _snap_pts(self, exclude: str):
        pts = [0.0, self.playhead]
        for o in self.proj.clips:
            if o.id != exclude:
                pts += (o.start, o.end)
        return pts

    def _on_motion(self, e):
        d = self._drag
        if not d:
            return
        if d["mode"] == "scrub":
            x = max(e.x, LABEL_W)
            W = self.tl.winfo_width()
            if x > W - 24:                                   # kéo sát mép -> tự cuộn theo
                self.scroll += 24
            elif x < LABEL_W + 24 and self.scroll > 0:
                self.scroll -= 24
            self._clamp_scroll()
            self.seek(self._tx(x))
            self._schedule_timeline()
            return
        c = self.proj.get(d["cid"])
        if not c or (not d["moved"] and abs(e.x - d["x0"]) < 3):
            return
        d["moved"] = True
        dt = (e.x - d["x0"]) / self.pps
        s0, dur0, in0 = d["start0"], d["dur0"], d["in0"]
        video = c.lane == "video"
        pts = None if video else self._snap_pts(c.id)
        mode = d["mode"]

        if mode == "move":
            s = max(0.0, s0 + dt)
            if video:
                c.start = s
                self.proj.relayout_video(c.id)
            else:
                da, db = self._snap(s, pts) - s, self._snap(s + c.dur, pts) - (s + c.dur)
                best = min((x for x in (da, db) if x), key=abs, default=0.0)
                c.start = max(0.0, s + best)
        elif mode == "l":
            end0 = s0 + dur0
            lo = -1e9 if video else 0.0
            if c.is_media and not c.still:
                lo = max(lo, s0 - in0 / max(c.speed, 0.01))
            ns = max(lo, min(s0 + dt, end0 - MIN_DUR))
            if not video:
                ns = max(lo, min(self._snap(ns, pts), end0 - MIN_DUR))
            c.start, c.dur = ns, end0 - ns
            if c.is_media and not c.still:
                c.src_in = in0 + (ns - s0) * c.speed
            if video:
                self.proj.relayout_video()
        else:                                                # "r"
            ne = max(c.start + MIN_DUR, s0 + dur0 + dt)
            if not video:
                ne = max(c.start + MIN_DUR, self._snap(ne, pts))
            c.dur = max(MIN_DUR, min(ne - c.start, c.max_dur()))
            if video:
                self.proj.relayout_video()
        self._schedule_timeline()
        self._schedule_preview()

    def _on_release(self, _e=None):
        d, self._drag = self._drag, None
        if not d or d["mode"] == "scrub":
            return
        if self.proj.commit():
            self._on_changed()
        else:
            self._sync_selection()
            self._schedule_timeline()

    def _on_hover(self, e):
        cur = "arrow"
        if e.x >= LABEL_W and e.y >= RULER_H:
            cid, xa, xb = self._clip_at(e.x, e.y)
            if cid:
                z = self._edge_zone(xa, xb)
                cur = "sb_h_double_arrow" if (e.x - xa <= z or xb - e.x <= z) else "hand2"
        if cur != self._cursor:
            self._cursor = cur
            self.tl.configure(cursor=cur)

    def _on_double(self, e):
        cid, _, _ = self._clip_at(e.x, e.y)
        c = self.proj.get(cid) if cid else None
        if c and c.is_caption:
            self.sel = cid
            self._sync_selection()
            self.txt.focus_set()
            self.txt.tag_add("sel", "1.0", "end-1c")

    def _on_right_click(self, e):
        T = self.T
        cid, _, _ = self._clip_at(e.x, e.y)
        m = tk.Menu(self, tearoff=0, bg=T["PANEL2"], fg="#e6e6ee", activebackground=T["ACCENT"],
                    activeforeground="white", bd=0, font=(self.F, 10))
        if cid:
            self.sel = cid
            self._sync_selection()
            self._schedule_timeline()
            c = self.proj.get(cid)
            m.add_command(label="✂   Tách tại đầu phát   (S)", command=self.op_split)
            m.add_command(label="🗑   Xóa   (Delete)", command=self.op_delete)
            if c.lane != "video":
                m.add_command(label="⧉   Nhân đôi", command=self.op_duplicate)
            if c.is_media:
                m.add_command(label="🔇   Tắt / bật tiếng clip này", command=self._toggle_mute)
            if c.is_caption:
                m.add_command(label="🎨   Áp dụng kiểu này cho tất cả", command=self.op_style_all)
        else:
            t = max(0.0, self._tx(e.x)) if e.x >= LABEL_W else self.playhead
            m.add_command(label="Aa   Thêm chữ tại đây", command=lambda: self.op_add_text(t))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ================================================================== phím tắt
    def _on_key(self, e):
        if self._closed or not self.winfo_ismapped():
            return
        ctrl, shift = bool(e.state & 0x4), bool(e.state & 0x1)
        ks = e.keysym
        if ctrl and ks.lower() == "s":
            self.project_save()
            return "break"
        try:
            cls = self.focus_get().winfo_class()
        except Exception:
            cls = ""
        if cls in _TEXT_CLASSES:
            return
        if ctrl:
            if ks.lower() == "z":
                (self.op_redo if shift else self.op_undo)()
                return "break"
            if ks.lower() == "y":
                self.op_redo()
                return "break"
            return
        if ks == "space":
            self.toggle_play()
        elif ks.lower() == "s":
            self.op_split()
        elif ks in ("Delete", "BackSpace"):
            self.op_delete()
        elif ks in ("Left", "Right"):
            step = 1.0 if shift else 1.0 / max(self.proj.fps, 1.0)
            self.seek(self.playhead + (step if ks == "Right" else -step))
            self._ensure_visible(self.playhead)
        elif ks == "Home":
            self.seek(0)
            self._ensure_visible(0, force=True)
        elif ks == "End":
            self.seek(self.proj.duration)
            self._ensure_visible(self.proj.duration, force=True)
        else:
            return
        return "break"

    # ================================================================== xem trước
    def _reader(self, path: str):
        r = self.readers.get(path)
        if r is not None:
            return r
        if path in self._bad:
            return None
        if len(self.readers) >= 4:
            for k in list(self.readers):
                self.readers.pop(k).close()
        try:
            r = M.FrameReader(path)
        except Exception:
            self._bad.add(path)
            return None
        self.readers[path] = r
        return r

    def _preview_frame(self, rw: int, rh: int):
        clip, st = self.proj.video_at(self.playhead)
        if not clip or not os.path.isfile(clip.src):
            return None
        if clip.still:
            im = self._stills.get(clip.src)
            if im is None:
                return None
            k = min(rw / im.width, rh / im.height)
            return im.resize((max(2, int(im.width * k)), max(2, int(im.height * k))), Image.BILINEAR)
        rd = self._reader(self.proxies.get(clip.src) or clip.src)
        if rd is None:
            return None
        try:
            return rd.frame_at(max(0.0, st), box=(rw, rh))
        except Exception:
            self.readers.pop(self.proxies.get(clip.src) or clip.src, None)
            rd.close()
            return None

    def _draw_preview(self):
        self._pv_pending = False
        if self._closed:
            return
        c, T, p = self.pv, self.T, self.proj
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw < 30 or ch < 30:
            return
        c.delete("all")
        if not p.lane("video"):
            c.create_text(cw / 2, ch / 2, fill=T["TEXT_MUTED"], font=(self.F, 13), justify="center",
                          text="＋\n\nNhấn vào đây để mở video\nhoặc dùng nút “＋ Video/Ảnh” phía trên")
            return
        k = min((cw - 16) / p.w, (ch - 16) / p.h)
        rw, rh = max(2, int(p.w * k)), max(2, int(p.h * k))
        rx, ry = (cw - rw) // 2, (ch - rh) // 2
        c.create_rectangle(rx, ry, rx + rw, ry + rh, fill="#000000", outline=T["BORDER"])
        img = self._preview_frame(rw, rh)
        if img is not None:
            self._pv_img = ImageTk.PhotoImage(img)
            c.create_image(rx + rw // 2, ry + rh // 2, image=self._pv_img)
        else:
            clip, _ = p.video_at(self.playhead)
            msg = "Không tìm thấy file nguồn" if clip and not os.path.isfile(clip.src) else "Đang tải khung hình…"
            c.create_text(rx + rw / 2, ry + rh / 2, text=msg, fill=T["TEXT_MUTED"], font=(self.F, 11))
        self._pv_geom = (rx, ry, rw, rh)
        for cap in p.captions_at(self.playhead):
            self._draw_caption(cap, rx, ry, rw, rh)

    def _draw_caption(self, cap: Clip, rx, ry, rw, rh):
        if not cap.text.strip():
            return
        c = self.pv
        px = max(8, int(cap.size * rh / 1080))
        font = (self.proj.font, -px, "bold")
        x, y = rx + cap.x * rw, ry + cap.y * rh
        kw = dict(text=cap.text, font=font, width=int(rw * 0.9), justify="center", anchor="center")
        if cap.box:
            t = c.create_text(x, y, fill=cap.color, **kw)
            bb = c.bbox(t)
            if bb:
                pad = max(3, px // 4)
                r = c.create_rectangle(bb[0] - pad, bb[1] - pad // 2, bb[2] + pad, bb[3] + pad // 2,
                                       fill="#000000", stipple="gray50", outline="")
                c.tag_lower(r, t)
        else:
            o = max(1, px // 14)
            for dx, dy in ((-o, -o), (o, -o), (-o, o), (o, o), (0, -o), (0, o), (-o, 0), (o, 0)):
                c.create_text(x + dx, y + dy, fill=cap.outline, **kw)
            c.create_text(x, y, fill=cap.color, **kw)
        if cap.id == self.sel:
            bb = c.bbox(c.create_text(x, y, fill="", **kw))
            if bb:
                c.create_rectangle(bb[0] - 4, bb[1] - 2, bb[2] + 4, bb[3] + 2, outline="#6c5ce7", dash=(4, 3))

    # ---- kéo chữ trực tiếp trên khung xem trước
    def _on_pv_press(self, e):
        if not self.proj.lane("video"):
            self.open_video_dialog()
            return
        self.tl.focus_set()
        rx, ry, rw, rh = self._pv_geom
        hit = None
        for cap in reversed(self.proj.captions_at(self.playhead)):
            px = max(8, int(cap.size * rh / 1080))
            cx, cy = rx + cap.x * rw, ry + cap.y * rh
            half_w = min(rw * 0.45, max(px * 0.6 * len(max(cap.text.split("\n"), key=len)) / 2, 30))
            lines = cap.text.count("\n") + 1
            if abs(e.x - cx) <= half_w + 8 and abs(e.y - cy) <= px * lines * 0.7 + 8:
                hit = cap
                break
        if hit:
            self.sel = hit.id
            self.proj.begin()
            self._pv_drag = dict(cid=hit.id, dx=hit.x - (e.x - rx) / rw, dy=hit.y - (e.y - ry) / rh)
            self._sync_selection()
            self._schedule_timeline()
            self._schedule_preview()

    def _on_pv_motion(self, e):
        d = self._pv_drag
        c = self.proj.get(d["cid"]) if d else None
        if not c:
            return
        rx, ry, rw, rh = self._pv_geom
        c.x = min(0.98, max(0.02, (e.x - rx) / rw + d["dx"]))
        c.y = min(0.98, max(0.02, (e.y - ry) / rh + d["dy"]))
        self._schedule_preview()

    def _on_pv_release(self, _e=None):
        if self._pv_drag:
            self._pv_drag = None
            if self.proj.commit():
                self._on_changed()

    # ================================================================== phát / tua
    def seek(self, t: float):
        t = max(0.0, min(float(t), self.proj.duration))
        self.playhead = t
        if self.playing:
            self._p0, self._t0 = t, time.perf_counter()
            self.audio.stop()
            self._audio_started = False
            if self._audio_rev == self._pkey():
                self._start_audio()
        self._after_seek_ui()

    def _after_seek_ui(self, playing: bool = False):
        self._update_time_label()
        self._draw_playhead()
        self._ensure_visible(self.playhead)
        self._follow_sub()
        if playing:
            self._draw_preview()               # vẽ ngay để bám nhịp phát
        else:
            self._schedule_preview()

    def _follow_sub(self):
        cur = next((c.id for c in self.proj.captions_at(self.playhead) if c.lane == "sub"), None)
        if cur == self._cur_sub:
            return
        self._cur_sub = cur
        if cur in self._list_ids:
            i = self._list_ids.index(cur)
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(i)
            self.lb.see(i)

    def toggle_play(self):
        if self.playing:
            self.pause()
            return
        if self.proj.duration <= 0:
            return
        if self.playhead >= self.proj.duration - 0.05:
            self.playhead = 0.0
        self.playing = True
        self.play_btn.configure(text="⏸")
        self._p0, self._t0 = self.playhead, time.perf_counter()
        self._audio_started = False
        if self._audio_rev == self._pkey():
            self._start_audio()
        else:
            self._build_audio()                 # âm thanh chưa kịp dựng: phát hình trước, có tiếng ngay khi xong
        self._tick()

    def pause(self):
        was = self.playing
        self.playing = False
        if self._play_job is not None:
            try:
                self.after_cancel(self._play_job)
            except Exception:
                pass
            self._play_job = None
        self.audio.stop()
        self._audio_started = False
        if was:
            try:
                self.play_btn.configure(text="▶")
            except Exception:
                pass

    def _tick(self):
        if not self.playing or self._closed:
            return
        t_start = time.perf_counter()
        t = self._p0 + (t_start - self._t0)
        dur = self.proj.duration
        if t >= dur:
            self.playhead = dur
            self.pause()
            self._after_seek_ui()
            return
        self.playhead = t
        self._after_seek_ui(playing=True)
        spent = (time.perf_counter() - t_start) * 1000
        self._play_job = self.after(max(1, int(1000 / 30 - spent)), self._tick)

    # ================================================================== âm thanh xem trước
    def _schedule_audio(self, delay: int = 1200):
        if self._audio_timer is not None:
            try:
                self.after_cancel(self._audio_timer)
            except Exception:
                pass
        self._audio_timer = self.after(delay, self._build_audio)

    def _build_audio(self):
        self._audio_timer = None
        if self._closed or self.proj.duration <= 0 or self._audio_rev == self._pkey():
            return
        if self._audio_busy:
            self._audio_dirty = True
            return
        self._audio_busy, self._audio_dirty = True, False
        key, snap = self._pkey(), copy_project(self.proj)
        out, tmp = self._audio_wav, self._audio_wav + ".tmp.wav"
        self._say("Đang chuẩn bị âm thanh xem trước…")

        def work():
            ok = False
            try:
                ok = M.render_audio_preview(snap, tmp)
                if ok and self._closed:
                    return                          # Editor đã đóng giữa chừng: bỏ kết quả, khỏi báo lỗi lặt vặt
                if ok:
                    os.replace(tmp, out)
                    self.audio.preload(out)
            except Exception:
                traceback.print_exc()
                ok = False
            self._post(self._audio_done, key, ok)
        threading.Thread(target=work, daemon=True).start()

    def _audio_done(self, key, ok: bool):
        self._audio_busy = False
        if ok:
            self._audio_rev = key
            self._say("")
        else:
            self._say("⚠ Không dựng được âm thanh xem trước (vẫn xuất video được bình thường).")
        if self._audio_dirty or (ok and key != self._pkey()):
            self._schedule_audio(200)              # dự án vừa đổi tiếp -> dựng lại bản mới (nếu cần)
        # BẮT ĐẦU PHÁT độc lập với việc dựng lại: nếu bản vừa dựng vẫn khớp dự án hiện tại và đang
        # phát hình mà chưa có tiếng (người dùng bấm Play lúc âm thanh còn đang dựng) thì vào tiếng ngay.
        if ok and key == self._pkey() and self.playing and not self._audio_started:
            self._start_audio()

    def _start_audio(self):
        if not os.path.isfile(self._audio_wav):
            return
        ok = self.audio.play(self._audio_wav, self.playhead + AUDIO_LATENCY)
        if ok:
            self._audio_started = True
            self._p0, self._t0 = self.playhead, time.perf_counter()
            if self.audio.degraded:
                self._say("⚠ Chỉ nghe được 2 phút đầu (chế độ dự phòng) - bấm 🔊 để sửa")
                self._maybe_open_audio_dialog()
        else:
            if self.audio.hint:                          # lỗi thật (khác với 'đã ở cuối âm thanh')
                self._say("⚠ Không phát được tiếng - bấm 🔊 để kiểm tra thiết bị âm thanh")
                self._maybe_open_audio_dialog()

    def _maybe_open_audio_dialog(self):
        """Tự mở hộp thoại chẩn đoán 1 lần mỗi phiên khi âm thanh hỏng, để người dùng khỏi phải đoán."""
        if self.audio.hint and not getattr(self, "_aud_auto", False):
            self._aud_auto = True
            self.after(150, self.audio_dialog)

    # ---- hộp thoại 🔊 Kiểm tra âm thanh
    def audio_dialog(self):
        old = getattr(self, "_aud_dlg", None)
        try:
            if old is not None and old.winfo_exists():
                old.lift()
                old.focus_force()
                return
        except Exception:
            pass
        T, F = self.T, self.F
        dlg = ctk.CTkToplevel(self)
        dlg.title("Kiểm tra âm thanh")
        dlg.geometry("680x560")
        dlg.configure(fg_color=T["BG"])
        try:
            dlg.transient(self.winfo_toplevel())
        except Exception:
            pass
        self._aud_dlg = dlg
        ctk.CTkLabel(dlg, text="Chẩn đoán âm thanh xem trước", font=(F, 15, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        if self.audio.hint:
            ctk.CTkLabel(dlg, text=self.audio.hint, font=(F, 11), text_color="#ffb86b", wraplength=640, justify="left",
                         anchor="w").pack(fill="x", padx=16, pady=(0, 6))
        box = ctk.CTkTextbox(dlg, height=250, font=("Consolas", 11), fg_color=T["PANEL"], wrap="none")
        box.pack(fill="both", expand=True, padx=16, pady=(4, 8))
        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(fill="x", padx=16)
        ctk.CTkLabel(row, text="Thiết bị phát", font=(F, 12)).pack(side="left")
        auto_lbl = "Tự động (khuyên dùng)"
        combo = ctk.CTkComboBox(row, values=[auto_lbl], width=420, height=30, font=(F, 11), state="readonly")
        combo.pack(side="left", padx=10)
        msg = ctk.CTkLabel(dlg, text="", font=(F, 12), wraplength=640, justify="left", anchor="w")
        msg.pack(fill="x", padx=16, pady=(8, 4))
        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))
        devmap: Dict[str, Optional[int]] = {auto_lbl: None}

        def say(text, color=None):
            msg.configure(text=text, text_color=color or T["TEXT_MUTED"])

        def refresh():
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", AU.diagnose())
            box.configure(state="disabled")
            devs = AU.list_output_devices()
            devmap.clear()
            devmap[auto_lbl] = None
            for idx, label in devs:
                devmap[label] = idx
            combo.configure(values=list(devmap))
            combo.set(auto_lbl)
            mods = AU.sd_modules()
            if mods is not None:
                pref = AU.load_pref()
                for label, idx in devmap.items():
                    if idx is not None and pref and AU.device_key(mods[0], idx) == pref:
                        combo.set(label)
            if AU.sd_modules() is None:
                install_btn.pack(side="left", padx=(0, 8), before=test_btn)      # hành động quan trọng nhất -> đứng đầu
            else:
                install_btn.pack_forget()

        def do_test():
            idx = devmap.get(combo.get())
            say("Đang phát tiếng bíp ~1 giây… hãy lắng nghe.")
            test_btn.configure(state="disabled")

            def work():
                ok, info = AU.test_tone(idx)
                self._post(done_test, ok, info, idx)
            threading.Thread(target=work, daemon=True).start()

        def done_test(ok, info, idx):
            try:
                test_btn.configure(state="normal")
            except Exception:
                return
            if ok:
                mods = AU.sd_modules()
                AU.save_pref(AU.device_key(mods[0], idx) if (mods and idx is not None) else None)
                say(f"✅ Đã mở được thiết bị: {info}. Bạn có nghe tiếng bíp không? Nếu KHÔNG, chọn thiết bị khác "
                    f"trong danh sách rồi bấm Phát âm thử lại. Thiết bị này đã được lưu để dùng cho Editor.", T["GREEN"])
            else:
                say(f"❌ Không mở được thiết bị: {info}", "#ff8a8a")

        def do_install():
            install_btn.configure(state="disabled", text="Đang cài…")
            say("Đang chạy pip install sounddevice… (vài chục giây)")

            def work():
                ok, info = AU.install_sounddevice()
                self._post(done_install, ok, info)
            threading.Thread(target=work, daemon=True).start()

        def done_install(ok, info):
            try:
                install_btn.configure(state="normal", text="Cài sounddevice")
            except Exception:
                return
            refresh()
            say(("✅ " if ok else "❌ ") + info, T["GREEN"] if ok else "#ff8a8a")

        def do_copy():
            try:
                self.clipboard_clear()
                self.clipboard_append(box.get("1.0", "end"))
                say("Đã sao chép chẩn đoán vào clipboard.")
            except Exception:
                pass

        test_btn = self._btn(btns, "🔔 Phát âm thử", do_test, primary=True)
        test_btn.pack(side="left", padx=(0, 8))
        install_btn = self._btn(btns, "Cài sounddevice", do_install, 150, primary=True)
        self._btn(btns, "Làm mới", refresh, 80).pack(side="left", padx=(0, 8))
        self._btn(btns, "Sao chép", do_copy, 90).pack(side="left")
        refresh()

    # ================================================================== nạp tài nguyên nền
    def _ensure_assets(self):
        for c in self.proj.clips:
            if not c.is_media or not c.src or not os.path.isfile(c.src):
                continue
            kind = "v" if c.lane == "video" else "a"
            key = (c.src, kind)
            if key in self._loading or key in self._done_assets:
                continue
            self._loading.add(key)
            args = (c.src, c.still, c.has_audio, c.src_len or c.dur)
            threading.Thread(target=self._video_worker if kind == "v" else self._audio_worker,
                             args=args, daemon=True).start()

    def _video_worker(self, src, still, has_audio, dur):
        try:
            if still:
                im = Image.open(src).convert("RGB")
                im.thumbnail((1600, 1600))
                self._post(self._got_still, src, im)
                return
            self._post(self._got_thumbs, src, M.make_thumbs(src, dur, THUMB_H, 300 if dur <= 90 else 40))
            if has_audio:
                self._post(self._got_wave, src, M.waveform(src))
            proxy = M.make_proxy(src)
            self._post(self._got_proxy, src, proxy)
            if proxy and dur > 90:
                self._post(self._got_thumbs, src, M.make_thumbs(proxy, dur, THUMB_H, 300))
        except Exception:
            traceback.print_exc()
        finally:
            self._post(self._asset_finished, (src, "v"))

    def _audio_worker(self, src, still, has_audio, dur):
        try:
            self._post(self._got_wave, src, M.waveform(src))
        except Exception:
            traceback.print_exc()
        finally:
            self._post(self._asset_finished, (src, "a"))

    def _asset_finished(self, key):
        self._loading.discard(key)
        self._done_assets.add(key)

    def _got_still(self, src, im):
        self._stills[src] = im
        th = im.copy()
        th.thumbnail((THUMB_H * 4, THUMB_H))
        self.thumbs[src] = (1.0, [th])
        self._schedule_timeline()
        self._schedule_preview()

    def _got_thumbs(self, src, th):
        if not th:
            return
        step = (th[1][0] - th[0][0]) if len(th) > 1 else 1.0
        self.thumbs[src] = (max(step, 0.01), [im for _, im in th])
        for k in [k for k in self._thumb_tk if k[0] == src]:
            del self._thumb_tk[k]
        self._schedule_timeline()

    def _got_wave(self, src, arr):
        self.waves[src] = arr
        self._schedule_timeline()

    def _got_proxy(self, src, proxy):
        if not proxy:
            return
        self.proxies[src] = proxy
        r = self.readers.pop(src, None)          # chuyển sang bản proxy nhẹ để tua mượt
        if r:
            r.close()
        self._schedule_preview()

    # ================================================================== xuất video
    def export_dialog(self):
        p = self.proj
        if p.duration <= 0:
            messagebox.showinfo("Chưa có video", "Hãy thêm video vào dự án trước khi xuất.", parent=self.winfo_toplevel())
            return
        if self._exp_cancel is not None:
            messagebox.showinfo("Đang xuất", "Đang có một lượt xuất video chạy rồi.", parent=self.winfo_toplevel())
            return
        miss = p.missing_media()
        if miss:
            messagebox.showerror("Thiếu file gốc", "Không xuất được vì không tìm thấy:\n" + "\n".join(miss[:8]),
                                 parent=self.winfo_toplevel())
            return
        base = os.path.splitext(os.path.basename(p.path or (p.lane("video")[0].src)))[0]
        init_dir = os.path.dirname(p.lane("video")[0].src)
        out = filedialog.asksaveasfilename(title="Xuất video", defaultextension=".mp4", initialdir=init_dir,
                                           initialfile=f"{base}_edit.mp4", filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        size = M.output_size(p, M.ASPECTS[self.x_aspect.get()], RES_MODES[self.x_res.get()])
        fit, crf = FIT_MODES[self.x_fit.get()], M.QUALITY[self.x_q.get()]
        snap, cancel = copy_project(p), threading.Event()
        self._exp_cancel = cancel
        self.pause()
        self.exp_bar.set(0)
        self.exp_lbl.configure(text=f"Đang xuất {size[0]}×{size[1]}…", text_color=self.T["TEXT_MUTED"])
        self.exp_cancel_btn.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        def work():
            try:
                ok, msg = M.export_video(snap, out, size, fit, crf,
                                         progress=lambda f: self._post(self._export_progress, f), cancel=cancel)
            except Exception as e:
                ok, msg = False, str(e)
            self._post(self._export_done, ok, msg, out, cancel.is_set())
        threading.Thread(target=work, daemon=True).start()

    def _export_progress(self, f: float):
        self.exp_bar.set(f)
        self.exp_lbl.configure(text=f"Đang xuất… {int(f * 100)}%")

    def _cancel_export(self):
        if self._exp_cancel is not None:
            self._exp_cancel.set()
            self.exp_lbl.configure(text="Đang hủy…")

    def _export_done(self, ok: bool, msg: str, out: str, cancelled: bool):
        self._exp_cancel = None
        self.exp_cancel_btn.grid_remove()
        if ok:
            self.exp_bar.set(1)
            self.exp_lbl.configure(text=f"✅ Đã xuất: {out}", text_color=self.T["GREEN"])
            if messagebox.askyesno("Xuất xong", f"Đã lưu video:\n{out}\n\nMở thư mục chứa file?", parent=self.winfo_toplevel()):
                self._reveal(out)
        else:
            try:
                os.remove(out)
            except OSError:
                pass
            self.exp_bar.set(0)
            if cancelled:
                self.exp_lbl.configure(text="Đã hủy xuất.", text_color=self.T["TEXT_MUTED"])
            else:
                self.exp_lbl.configure(text="❌ Xuất thất bại.", text_color="#e74c3c")
                messagebox.showerror("Xuất thất bại", (msg or "ffmpeg báo lỗi")[-900:], parent=self.winfo_toplevel())

    @staticmethod
    def _reveal(path: str):
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception:
            pass
