# -*- coding: utf-8 -*-
"""
Tiện ích giao diện cho Reup Studio (customtkinter). Tách riêng khỏi main.py để dễ test/bảo trì:
  - Toast: thông báo nổi, KHÔNG chặn thao tác (thay cho messagebox "Đã lưu...")
  - build_section_nav: hàng nút "nhảy nhanh" tới từng mục trong panel cấu hình dài
  - bind_shortcuts: phím tắt toàn app
  - parse_dropped_files: đọc danh sách file từ sự kiện kéo-thả (tkinterdnd2, tuỳ chọn)
"""
from __future__ import annotations

import os
import re
from typing import Callable, Dict, List, Optional, Sequence

import customtkinter as ctk

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mpg", ".mpeg"}


# --------------------------------------------------------------------------- Toast
class Toast:
    """Thông báo nhỏ nổi ở góc dưới-phải cửa sổ, tự tắt sau vài giây."""

    def __init__(self, root, theme: Dict[str, str], font: str):
        self.root, self.theme, self.font = root, theme, font
        self._label: Optional[ctk.CTkLabel] = None
        self._after_id = None

    def _colors(self, kind: str):
        t = self.theme
        return {
            "ok": ("#1f6f43", "white"),
            "warn": ("#8a6d1a", "white"),
            "error": ("#a53030", "white"),
        }.get(kind, (t.get("PANEL2", "#2a2a3a"), "white"))

    def show(self, msg: str, kind: str = "info", ms: int = 2800):
        try:
            self.hide()
            bg, fg = self._colors(kind)
            self._label = ctk.CTkLabel(
                self.root, text=msg, fg_color=bg, text_color=fg, corner_radius=10,
                font=(self.font, 12), padx=16, pady=10, wraplength=420, justify="left",
            )
            self._label.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
            self._label.lift()
            self._after_id = self.root.after(ms, self.hide)
        except Exception:
            pass

    def hide(self):
        try:
            if self._after_id is not None:
                self.root.after_cancel(self._after_id)
        except Exception:
            pass
        self._after_id = None
        if self._label is not None:
            try:
                self._label.destroy()
            except Exception:
                pass
            self._label = None


# --------------------------------------------------------------------------- Section nav
def _is_section_header(w) -> bool:
    """Nhãn tiêu đề mục: CTkLabel chữ IN HOA, ngắn, font 11 đậm (đúng kiểu 'TRANSLATION CONFIG', 'ÂM THANH'...)."""
    if not isinstance(w, ctk.CTkLabel):
        return False
    try:
        text = str(w.cget("text")).strip()
    except Exception:
        return False
    if not text or len(text) > 28 or text.upper() != text or not any(c.isalpha() for c in text):
        return False
    try:
        f = w.cget("font")
        if isinstance(f, (tuple, list)):
            size = int(f[1]) if len(f) > 1 else 0
            bold = any(str(x).lower() == "bold" for x in f[2:])
        else:
            size, bold = int(f.cget("size")), f.cget("weight") == "bold"
    except Exception:
        return False
    return size == 11 and bold


def _find_headers(widget, out: List[ctk.CTkLabel]):
    for ch in widget.winfo_children():
        if _is_section_header(ch):
            out.append(ch)
        _find_headers(ch, out)


def scroll_to_widget(scroll: ctk.CTkScrollableFrame, target, pad: int = 6):
    """Cuộn CTkScrollableFrame tới widget bất kỳ nằm bên trong (kể cả lồng nhiều tầng)."""
    scroll.update_idletasks()
    canvas = scroll._parent_canvas
    bbox = canvas.bbox("all")
    total = (bbox[3] - bbox[1]) if bbox else 0
    if total <= 0:
        return
    y = target.winfo_rooty() - scroll.winfo_rooty() - pad
    canvas.yview_moveto(max(0.0, min(1.0, y / total)))


def build_section_nav(parent, scroll: ctk.CTkScrollableFrame, theme: Dict[str, str], font: str):
    """Tạo hàng chip trong `parent`, mỗi chip nhảy tới 1 mục của `scroll`. Gọi SAU khi panel đã dựng xong."""
    headers: List[ctk.CTkLabel] = []
    _find_headers(scroll, headers)
    row = ctk.CTkFrame(parent, fg_color="transparent")
    if not headers:
        return row
    ctk.CTkLabel(row, text="Đi tới:", font=(font, 11), text_color=theme.get("TEXT_MUTED", "gray")).pack(side="left", padx=(2, 8))
    seen = set()
    for h in headers:
        title = str(h.cget("text")).strip()
        if title in seen:
            continue
        seen.add(title)
        ctk.CTkButton(
            row, text=title.title() if len(title) > 3 else title, height=26, width=10, font=(font, 11),
            fg_color=theme.get("PANEL2", "#2a2a3a"), hover_color=theme.get("ACCENT", "#6c5ce7"),
            corner_radius=13, border_width=1, border_color=theme.get("BORDER", "#333"),
            command=lambda w=h: scroll_to_widget(scroll, w),
        ).pack(side="left", padx=3)
    ctk.CTkButton(
        row, text="⬆ Đầu trang", height=26, width=10, font=(font, 11), fg_color="transparent",
        hover_color=theme.get("PANEL2", "#2a2a3a"), text_color=theme.get("TEXT_MUTED", "gray"),
        command=lambda: scroll._parent_canvas.yview_moveto(0.0),
    ).pack(side="right", padx=3)
    return row


# --------------------------------------------------------------------------- Shortcuts
def bind_shortcuts(root, page_order: Sequence[str], show_page: Callable[[str], None],
                   open_video: Callable[[], None], start: Callable[[], None], save: Callable[[], None]):
    """Ctrl+1..N: chuyển trang theo thứ tự sidebar · Ctrl+O: chọn video · Ctrl+Enter: bắt đầu · Ctrl+S: lưu cấu hình."""
    def wrap(fn):
        def _h(_e=None):
            try:
                fn()
            except Exception:
                pass
            return "break"
        return _h

    for i, name in enumerate(page_order[:9], start=1):
        root.bind_all(f"<Control-Key-{i}>", wrap(lambda n=name: show_page(n)))
    root.bind_all("<Control-o>", wrap(open_video))
    root.bind_all("<Control-Return>", wrap(start))
    root.bind_all("<Control-s>", wrap(save))


# --------------------------------------------------------------------------- Drag & drop
def parse_dropped_files(tk_root, data: str) -> List[str]:
    """tkinterdnd2 trả chuỗi kiểu '{C:/a b/x.mp4} C:/y.mp4' -> danh sách đường dẫn."""
    try:
        items = list(tk_root.tk.splitlist(data))
    except Exception:
        items = re.findall(r"\{[^}]*\}|\S+", data or "")
        items = [s.strip("{}") for s in items]
    return [p for p in items if p]


def pick_videos(paths: Sequence[str]) -> List[str]:
    """Lọc video từ danh sách file/thư mục được thả (thư mục: lấy video bên trong, không đệ quy)."""
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            try:
                for fn in sorted(os.listdir(p)):
                    fp = os.path.join(p, fn)
                    if os.path.isfile(fp) and os.path.splitext(fn)[1].lower() in VIDEO_EXTS:
                        out.append(fp)
            except OSError:
                pass
        elif os.path.isfile(p) and os.path.splitext(p)[1].lower() in VIDEO_EXTS:
            out.append(p)
    return out
