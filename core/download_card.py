"""
core/download_card.py
Khối giao diện "⬇ Tải video từ link bất kỳ" cho tab Download: dán link -> bấm Tải xuống.
Logic tải nằm ở core/video_download.py (yt-dlp). File này chỉ lo giao diện + chạy nền.

Gắn vào trang (xem main.py):
    card = DownloadAnyCard(page, theme=dict(PANEL=..., ...), font=FONT_FAMILY,
                           out_dir=lambda: os.path.join(self.work_dir, "downloads"),
                           log=self.log, on_done=self._refresh_douyin_downloads,
                           on_use=self._use_downloaded_video)
    card.pack(fill="x", pady=(0, 14))
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from tkinter import filedialog, messagebox
from typing import Callable, List, Optional

import customtkinter as ctk

from core import video_download as V

_DEFAULT_THEME = dict(
    PANEL="#16161d", PANEL2="#1c1c26", ACCENT="#6c5ce7", ACCENT_HOVER="#7d6ff0", TEXT_MUTED="#8a8aa0",
    BORDER="#2a2a3a", BORDER_SOFT="#25253a", GREEN="#2ecc71", RED="#e74c3c", AMBER="#e2b93b",
    RADIUS_PANEL=14, RADIUS_CARD=10,
)
COOKIE_NONE = "(không dùng)"
COOKIE_CHOICES = [COOKIE_NONE, "chrome", "edge", "firefox", "brave", "opera"]
AUDIO_EXTS = (".mp3", ".m4a", ".opus", ".ogg", ".wav", ".aac")


def find_ffmpeg() -> Optional[str]:
    """Đường dẫn ffmpeg THẬT (vendor\bin / REUP_FFMPEG / PATH / imageio-ffmpeg)."""
    try:
        from core.external_tools import find_ffmpeg as _find
        path = _find()
        if path and (os.path.isfile(path) or shutil.which(path)):
            return path
    except Exception:
        pass
    return shutil.which("ffmpeg")


class DownloadAnyCard(ctk.CTkFrame):
    def __init__(self, parent, theme: Optional[dict] = None, font: str = "Segoe UI",
                 out_dir: Callable[[], str] = lambda: os.path.join(os.getcwd(), "downloads"),
                 log: Callable[[str], None] = lambda s: None,
                 on_done: Optional[Callable[[], None]] = None,
                 on_use: Optional[Callable[[str], None]] = None,
                 open_folder: Optional[Callable[[str], None]] = None):
        self.T = {**_DEFAULT_THEME, **(theme or {})}
        super().__init__(parent, fg_color=self.T["PANEL"], corner_radius=self.T["RADIUS_PANEL"])
        self.F = font
        self._out_dir, self._log, self._on_done, self._on_use, self._open_folder = out_dir, log, on_done, on_use, open_folder
        self._q: "queue.Queue" = queue.Queue()
        self._cancel: Optional[threading.Event] = None
        self._busy = False
        self._last_video: Optional[str] = None
        self._build()

    # ------------------------------------------------------------------ giao diện
    def _build(self):
        T, F = self.T, self.F
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(inner, text="⬇ Tải video từ link bất kỳ", font=(F, 14, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            inner, justify="left", font=(F, 11), text_color=T["TEXT_MUTED"], wraplength=900,
            text="Dán link YouTube, TikTok, X/Twitter, Instagram, Facebook, Threads, Vimeo, Reddit, Twitch... "
                 "(hơn 1.800 trang) - mỗi dòng 1 link, rồi bấm Tải xuống. Video lưu cùng chỗ với video Douyin ở bên dưới.",
        ).pack(anchor="w", pady=(2, 8))

        self.box = ctk.CTkTextbox(inner, height=62, fg_color=T["PANEL2"])
        self.box.pack(fill="x", pady=(0, 6))
        self.box.bind("<KeyRelease>", lambda e: self._detect())
        self.box.bind("<Control-Return>", lambda e: (self.start(), "break")[1])

        self.detect_lbl = ctk.CTkLabel(inner, text="", font=(F, 11), text_color=T["TEXT_MUTED"], anchor="w")
        self.detect_lbl.pack(fill="x", pady=(0, 6))

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        q = ctk.CTkFrame(row, fg_color="transparent")
        q.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(q, text="Chất lượng", font=(F, 11), text_color=T["TEXT_MUTED"]).pack(anchor="w")
        self.quality = ctk.CTkComboBox(q, values=list(V.QUALITIES), width=190, fg_color=T["PANEL2"],
                                       border_color=T["BORDER"], state="readonly")
        self.quality.set(V.DEFAULT_QUALITY)
        self.quality.pack(anchor="w", pady=(4, 0))
        c = ctk.CTkFrame(row, fg_color="transparent")
        c.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(c, text="Cookie trình duyệt (khi trang đòi đăng nhập)", font=(F, 11),
                     text_color=T["TEXT_MUTED"]).pack(anchor="w")
        self.cookie = ctk.CTkComboBox(c, values=COOKIE_CHOICES, width=190, fg_color=T["PANEL2"],
                                      border_color=T["BORDER"], state="readonly")
        self.cookie.set(COOKIE_NONE)
        self.cookie.pack(anchor="w", pady=(4, 0))
        f = ctk.CTkFrame(row, fg_color="transparent")
        f.pack(side="left")
        ctk.CTkLabel(f, text="...hoặc file cookies.txt (ổn định hơn)", font=(F, 11),
                     text_color=T["TEXT_MUTED"]).pack(anchor="w")
        frow = ctk.CTkFrame(f, fg_color="transparent")
        frow.pack(anchor="w", pady=(4, 0))
        self.cookie_file: Optional[str] = None
        self.cookie_file_lbl = ctk.CTkLabel(frow, text="Chưa chọn", font=(F, 11), text_color=T["TEXT_MUTED"])
        self.cookie_file_lbl.pack(side="left", padx=(0, 8))
        ctk.CTkButton(frow, text="Chọn", width=60, fg_color=T["PANEL2"], hover_color=T["BORDER"],
                      border_width=1, border_color=T["BORDER_SOFT"], command=self.pick_cookie_file).pack(side="left")
        ctk.CTkButton(frow, text="✕", width=28, fg_color="transparent", hover_color=T["PANEL2"],
                      text_color=T["TEXT_MUTED"], command=lambda: self._set_cookie_file(None)).pack(side="left", padx=(4, 0))

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(fill="x", pady=(10, 0))
        self.go_btn = ctk.CTkButton(btns, text="⬇ Tải xuống", fg_color=T["ACCENT"], hover_color=T["ACCENT_HOVER"],
                                    command=self.start)
        self.go_btn.pack(side="left")
        self.stop_btn = ctk.CTkButton(btns, text="■ Dừng", width=80, fg_color=T["PANEL2"], hover_color=T["BORDER"],
                                      border_width=1, border_color=T["BORDER_SOFT"], command=self.stop)
        ctk.CTkButton(btns, text="📋 Dán", width=80, fg_color=T["PANEL2"], hover_color=T["BORDER"],
                      border_width=1, border_color=T["BORDER_SOFT"], command=self.paste).pack(side="left", padx=(8, 0))
        ctk.CTkButton(btns, text="⟳ Cập nhật yt-dlp", width=140, fg_color="transparent", hover_color=T["PANEL2"],
                      text_color=T["TEXT_MUTED"], command=self.update_ytdlp).pack(side="right")

        self.bar = ctk.CTkProgressBar(inner, fg_color=T["BORDER"], progress_color=T["ACCENT"])
        self.bar.set(0)
        self.bar.pack(fill="x", pady=(12, 4))
        self.status = ctk.CTkLabel(inner, text="Sẵn sàng", font=(F, 11), text_color=T["TEXT_MUTED"],
                                   justify="left", anchor="w", wraplength=900)
        self.status.pack(fill="x")
        self.result_row = ctk.CTkFrame(inner, fg_color="transparent")     # hiện sau khi tải xong

    # ------------------------------------------------------------------ tiện ích
    def _say(self, text: str, color: Optional[str] = None):
        self.status.configure(text=text, text_color=color or self.T["TEXT_MUTED"])

    def _urls(self) -> List[str]:
        return V.extract_urls(self.box.get("1.0", "end"))

    def _detect(self):
        urls = self._urls()
        if not urls:
            self.detect_lbl.configure(text="")
            return
        counts: dict = {}
        for u in urls:
            name = "Douyin/Xiaohongshu (dùng khối phía trên)" if V.is_own_block_site(u) else V.detect_platform(u)
            counts[name] = counts.get(name, 0) + 1
        self.detect_lbl.configure(
            text="Phát hiện: " + ", ".join(f"{k} ×{n}" if n > 1 else k for k, n in counts.items()))

    def pick_cookie_file(self):
        p = filedialog.askopenfilename(title="Chọn file cookies.txt (định dạng Netscape)",
                                       filetypes=[("Cookie/Text files", "*.txt"), ("All files", "*.*")])
        if p:
            self._set_cookie_file(p)

    def _set_cookie_file(self, path: Optional[str]):
        self.cookie_file = path
        self.cookie_file_lbl.configure(text=os.path.basename(path) if path else "Chưa chọn",
                                       text_color="white" if path else self.T["TEXT_MUTED"])

    def paste(self):
        try:
            txt = self.clipboard_get()
        except Exception:
            self._say("Clipboard đang trống - hãy copy link trước.")
            return
        self.box.delete("1.0", "end")
        self.box.insert("1.0", txt.strip())
        self._detect()

    # ------------------------------------------------------------------ tải
    def start(self):
        if self._busy:
            return
        urls = self._urls()
        if not urls:
            messagebox.showwarning("Thiếu link", "Dán ít nhất 1 link video vào ô trên rồi bấm Tải xuống.")
            return
        own = [u for u in urls if V.is_own_block_site(u)]
        urls = [u for u in urls if not V.is_own_block_site(u)]
        if not urls:
            messagebox.showinfo("Dùng khối Douyin", "Link Douyin / Xiaohongshu hãy dán vào khối “Tải video từ Douyin” "
                                                    "ở phía trên (có hỗ trợ cookie riêng và tải cả trang cá nhân).")
            return
        cookie = self.cookie.get()
        cookie = None if cookie in ("", COOKIE_NONE) else cookie
        cookie_file = self.cookie_file if (self.cookie_file and os.path.isfile(self.cookie_file)) else None
        quality, out_dir, ffmpeg = self.quality.get(), self._out_dir(), find_ffmpeg()
        self._busy = True
        self._last_video = None
        self._cancel = threading.Event()
        self.result_row.pack_forget()
        for w in self.result_row.winfo_children():
            w.destroy()
        self.go_btn.configure(state="disabled", text="Đang tải...")
        self.stop_btn.pack(side="left", padx=(8, 0), after=self.go_btn)
        self.bar.set(0.01)
        skipped = f" (bỏ qua {len(own)} link Douyin/Xiaohongshu)" if own else ""
        self._say(f"Đang chuẩn bị tải {len(urls)} link{skipped}...")
        self._log(f"[Download] Tải {len(urls)} link ({quality}) -> {out_dir}" + (f" · cookie {cookie}" if cookie else ""))
        cancel = self._cancel

        def work():
            try:
                res = V.download_urls(urls, out_dir, quality, ffmpeg, cookie, cookie_file,
                                      progress_cb=lambda p, m: self._q.put(("p", p, m)), cancel=cancel)
                self._q.put(("done", res))
            except Exception as e:                       # lỗi không lường trước - đừng để nút bị treo
                self._q.put(("error", str(e)))
        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._pump)

    def stop(self):
        if self._cancel is not None:
            self._cancel.set()
            self._say("Đang dừng...")

    def _pump(self):
        try:
            while True:
                item = self._q.get_nowait()
                if item[0] == "p":
                    self.bar.set(min(1.0, max(0.0, item[1])))
                    self._say(item[2])
                elif item[0] == "done":
                    self._finish(item[1])
                    return
                elif item[0] == "error":
                    self._reset_buttons()
                    self._say(f"✕ Lỗi: {item[1]}", self.T["RED"])
                    self._log(f"[Download] ✕ Lỗi: {item[1]}")
                    return
        except queue.Empty:
            pass
        if self._busy:                                   # chỉ hỏi hàng đợi khi đang tải
            self.after(100, self._pump)

    def _reset_buttons(self):
        self._busy = False
        self.go_btn.configure(state="normal", text="⬇ Tải xuống")
        self.stop_btn.pack_forget()

    def _finish(self, res: "V.DownloadResult"):
        self._reset_buttons()
        for note in res.notes:
            self._log(f"[Download] ℹ {note}")
        if res.cancelled and not res.videos:
            self.bar.set(0)
            self._say("Đã dừng.")
            return
        ok, bad = len(res.videos), len(res.failed)
        self.bar.set(1.0 if ok else 0)
        lines = []
        if ok:
            lines.append(f"✓ Đã tải xong {ok} video" + (f" ({bad} link lỗi)" if bad else "") + " - xem ở “Video đã tải” bên dưới.")
        for url, reason in res.failed[:4]:
            lines.append(f"✕ {url}\n   {reason}")
        if len(res.failed) > 4:
            lines.append(f"… và {len(res.failed) - 4} link lỗi khác (xem log).")
        lines += [f"ℹ {n}" for n in res.notes]
        color = self.T["GREEN"] if ok and not bad else (self.T["AMBER"] if ok else self.T["RED"])
        self._say("\n".join(lines), color)
        for url, reason in res.failed:
            self._log(f"[Download] ✕ {url} -> {reason}")
        for p in res.videos:
            self._log(f"[Download] ✓ {p}")
        if ok:
            self._last_video = res.videos[-1]
            self._show_result_row(res.videos[-1])
            if self._on_done:
                try:
                    self._on_done()
                except Exception:
                    pass

    def _show_result_row(self, path: str):
        T, F = self.T, self.F
        self.result_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(self.result_row, text=os.path.basename(path), font=(F, 11), anchor="w",
                     text_color=T["TEXT_MUTED"]).pack(side="left", fill="x", expand=True, padx=(0, 10))
        if self._open_folder:
            ctk.CTkButton(self.result_row, text="Mở thư mục", width=100, fg_color=T["PANEL2"], hover_color=T["BORDER"],
                          border_width=1, border_color=T["BORDER_SOFT"],
                          command=lambda: self._open_folder(os.path.dirname(path))).pack(side="right")
        if self._on_use and not path.lower().endswith(AUDIO_EXTS):          # file âm thanh thì không dịch được
            ctk.CTkButton(self.result_row, text="▶ Dùng video này", width=140, fg_color=T["ACCENT"],
                          hover_color=T["ACCENT_HOVER"], command=lambda: self._on_use(path)).pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------------ cập nhật yt-dlp
    def update_ytdlp(self):
        if self._busy:
            return
        if getattr(sys, "frozen", False):
            messagebox.showinfo("Cập nhật yt-dlp", "App đang chạy dạng .exe đóng gói - hãy đóng gói lại với yt-dlp mới nhất.")
            return
        self._busy = True
        self.go_btn.configure(state="disabled")
        self.bar.set(0.2)
        self._say("Đang cập nhật yt-dlp (pip install -U yt-dlp)… vài chục giây.")

        def work():
            kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
            try:
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "--disable-pip-version-check", "yt-dlp[default]"],
                                   capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace", **kw)
                tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-2:]
                if r.returncode == 0:
                    msg, col = "✓ Đã cập nhật yt-dlp. Hãy MỞ LẠI app để dùng bản mới.", self.T["GREEN"]
                else:
                    msg, col = "✕ Cập nhật lỗi: " + " ".join(tail), self.T["RED"]
            except Exception as e:
                msg, col = f"✕ Không chạy được pip: {e}", self.T["RED"]
            self._q.put(("msg", msg, col))
        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._pump_update)

    def _pump_update(self):
        try:
            item = self._q.get_nowait()
        except queue.Empty:
            self.after(100, self._pump_update)
            return
        self._reset_buttons()
        self.bar.set(1.0 if item[2] == self.T["GREEN"] else 0)
        self._say(item[1], item[2])
        self._log(f"[Download] {item[1]}")
