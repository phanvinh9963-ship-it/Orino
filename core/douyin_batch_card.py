"""
core/douyin_batch_card.py
Khối giao diện "Tải hàng loạt từ Douyin" đặt trong tab Download của Reup Studio.

Tính năng:
  - Dán nhiều link Douyin (mỗi dòng 1 link): video lẻ hoặc link trang cá nhân.
  - Chọn thư mục lưu video (mặc định là thư mục "Video" của người dùng),
    lựa chọn được ghi nhớ cho lần sau.
  - Nút "Bắt đầu tải" / nút "Dừng" - việc tải chạy ở luồng nền nên giao diện
    không bị đơ.
  - Thanh tiến trình + bảng trạng thái từng video (đang tải / xong / lỗi)
    + đếm tổng số video đã tải.
  - Cookie Douyin được đọc tự động từ tệp cố định
    <thư mục app>\\cookies\\douyin_cookies.txt (người dùng không phải chọn).

Toàn bộ logic tải nằm ở mô-đun `douyin_batch` (được lấy từ bộ tải Douyin
chính thức), giao diện này chỉ lo phần hiển thị và điều khiển.
"""
from __future__ import annotations

import os
import queue
import threading
from tkinter import filedialog, messagebox
from typing import Callable, List, Optional

import customtkinter as ctk

_DEFAULT_THEME = dict(
    PANEL="#15161c", PANEL2="#1b1c24", ACCENT="#6c5ce7", ACCENT_HOVER="#5a4bd6",
    TEXT_MUTED="#8b8d98", BORDER="#26272f", BORDER_SOFT="#2f3038",
    GREEN="#2ecc71", RED="#e74c3c", AMBER="#e0a030",
    RADIUS_PANEL=16, RADIUS_CARD=14, RADIUS_ROW=10,
)

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm")


def default_video_dir() -> str:
    """Thư mục lưu video mặc định: thư mục "Video" của người dùng (Windows).

    Nếu không có thư mục Video thì dùng thư mục Tải xuống, cuối cùng là thư mục
    gốc của người dùng.
    """
    home = os.path.expanduser("~")
    for name in ("Videos", "Video", "Downloads", "Downloads"):
        candidate = os.path.join(home, name)
        if os.path.isdir(candidate):
            return candidate
    return home


def find_douyin_cookie_file() -> str:
    """Đường dẫn cố định của tệp cookie Douyin.

    Ưu tiên thư mục "cookies" cạnh app; nếu thư mục cài đặt không ghi được
    thì dùng thư mục dữ liệu người dùng.
    """
    app_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(__import__("sys"), "frozen", False):
        app_base = os.path.dirname(__import__("sys").executable)
    app_cookie = os.path.join(app_base, "cookies", "douyin_cookies.txt")
    if os.path.isdir(os.path.dirname(app_cookie)):
        return app_cookie
    return app_cookie


class DouyinBatchCard(ctk.CTkFrame):
    """Khối tải hàng loạt Douyin."""

    def __init__(
        self,
        parent,
        theme: Optional[dict] = None,
        font: str = "Segoe UI",
        out_dir_var=None,
        cookie_path: str = "",
        log: Callable[[str], None] = lambda s: None,
        open_folder: Optional[Callable[[str], None]] = None,
        on_use: Optional[Callable[[str], None]] = None,
    ):
        self.T = {**_DEFAULT_THEME, **(theme or {})}
        super().__init__(parent, fg_color=self.T["PANEL"], corner_radius=self.T["RADIUS_PANEL"])
        self.F = font
        self._log = log
        self._open_folder = open_folder
        self._on_use = on_use
        self._cookie_path = cookie_path or find_douyin_cookie_file()
        self._q: "queue.Queue" = queue.Queue()
        self._service = None
        self._busy = False
        self._downloaded_count = 0

        # Biến lưu thư mục đích - được lưu cùng cấu hình chung của app nên
        # lần sau mở app vẫn nhớ đúng thư mục người dùng đã chọn.
        if out_dir_var is None:
            import tkinter as tk
            out_dir_var = tk.StringVar(value=default_video_dir())
        self.out_dir_var = out_dir_var
        if not (self.out_dir_var.get() or "").strip():
            self.out_dir_var.set(default_video_dir())

        self._build()

    # ------------------------------------------------------------------ giao diện
    def _build(self) -> None:
        T, F = self.T, self.F
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(inner, text="⏬ Tải hàng loạt từ Douyin", font=(F, 14, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            inner,
            text="Dán link trang cá nhân Douyin (tải được cả trang) hoặc link video lẻ - "
                 "mỗi dòng một link. Video sẽ được tải về thư mục bạn chọn, "
                 "sau đó dùng nút “▶ Dùng video này” để đưa sang tab Dịch.",
            font=(F, 11), text_color=T["TEXT_MUTED"], justify="left", wraplength=900,
        ).pack(anchor="w", pady=(2, 8))

        # ---- Ô nhập link ----
        self.box = ctk.CTkTextbox(inner, height=76, fg_color=T["PANEL2"])
        self.box.pack(fill="x", pady=(0, 8))
        self.box.bind("<KeyRelease>", lambda _e: self._detect())
        self.box.bind("<Control-Return>", lambda _e: (self.start(), "break")[1])

        self.detect_lbl = ctk.CTkLabel(inner, text="", font=(F, 11), text_color=T["TEXT_MUTED"], anchor="w")
        self.detect_lbl.pack(fill="x", pady=(0, 6))

        # ---- Thư mục lưu video ----
        folder_box = ctk.CTkFrame(inner, fg_color="transparent")
        folder_box.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(folder_box, text="Thư mục lưu video", font=(F, 11), text_color=T["TEXT_MUTED"]).pack(side="left")
        ctk.CTkEntry(
            folder_box, textvariable=self.out_dir_var, fg_color=T["PANEL2"], border_color=T["BORDER"],
        ).pack(side="left", fill="x", expand=True, padx=(12, 8))
        ctk.CTkButton(
            folder_box, text="📁 Chọn thư mục", width=130, fg_color=T["PANEL2"], hover_color=T["BORDER"],
            border_width=1, border_color=T["BORDER_SOFT"], command=self.pick_folder,
        ).pack(side="left")
        ctk.CTkButton(
            folder_box, text="📂 Mở", width=70, fg_color="transparent", hover_color=T["PANEL2"],
            text_color=T["TEXT_MUTED"], command=self.open_output_folder,
        ).pack(side="left", padx=(6, 0))

        # ---- Cookie ----
        self.cookie_lbl = ctk.CTkLabel(inner, text="", font=(F, 11), text_color=T["TEXT_MUTED"], anchor="w")
        self.cookie_lbl.pack(fill="x", pady=(2, 8))
        self._refresh_cookie_status()

        # ---- Nút bấm ----
        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(fill="x")
        self.go_btn = ctk.CTkButton(
            btns, text="▶ Bắt đầu tải", fg_color=T["ACCENT"], hover_color=T["ACCENT_HOVER"],
            command=self.start,
        )
        self.go_btn.pack(side="left")
        self.stop_btn = ctk.CTkButton(
            btns, text="⏹ Dừng", width=90, fg_color=T["PANEL2"], hover_color=T["BORDER"],
            border_width=1, border_color=T["BORDER_SOFT"], command=self.stop, state="disabled",
        )
        self.stop_btn.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            btns, text="📋 Dán", width=80, fg_color=T["PANEL2"], hover_color=T["BORDER"],
            border_width=1, border_color=T["BORDER_SOFT"], command=self.paste,
        ).pack(side="left", padx=(8, 0))
        self.counter_lbl = ctk.CTkLabel(btns, text="Tổng số video đã tải: 0", font=(F, 12), text_color=T["TEXT_MUTED"])
        self.counter_lbl.pack(side="right")

        # ---- Tiến trình + trạng thái ----
        self.bar = ctk.CTkProgressBar(inner, fg_color=T["BORDER"], progress_color=T["ACCENT"])
        self.bar.set(0)
        self.bar.pack(fill="x", pady=(12, 4))
        self.status = ctk.CTkLabel(
            inner, text="Sẵn sàng", font=(F, 11), text_color=T["TEXT_MUTED"],
            justify="left", anchor="w", wraplength=900,
        )
        self.status.pack(fill="x")

        # ---- Bảng trạng thái từng video ----
        ctk.CTkLabel(inner, text="Danh sách video", font=(F, 12, "bold")).pack(anchor="w", pady=(10, 4))
        self.table = ctk.CTkScrollableFrame(inner, fg_color=T["PANEL2"], corner_radius=T["RADIUS_CARD"], height=150)
        self.table.pack(fill="x")
        self._table_rows: List[ctk.CTkFrame] = []
        self._empty_row = ctk.CTkLabel(self.table, text="Chưa có video nào trong phiên này.", text_color=T["TEXT_MUTED"])
        self._empty_row.pack(anchor="w", padx=12, pady=10)

    # ------------------------------------------------------------------ tiện ích
    def _say(self, text: str, color: Optional[str] = None) -> None:
        self.status.configure(text=text, text_color=color or self.T["TEXT_MUTED"])

    def _links(self) -> List[str]:
        raw = self.box.get("1.0", "end")
        links = []
        seen = set()
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Tách những link nằm chung một dòng (dán từ trình duyệt)
            for part in line.replace(",", " ").replace("，", " ").split():
                if part.startswith("http") and part not in seen:
                    seen.add(part)
                    links.append(part)
        return links

    def _detect(self) -> None:
        links = self._links()
        if not links:
            self.detect_lbl.configure(text="")
            return
        profiles = sum(1 for u in links if "/user/" in u)
        videos = len(links) - profiles
        bits = []
        if profiles:
            bits.append(f"{profiles} link trang cá nhân")
        if videos:
            bits.append(f"{videos} link video")
        self.detect_lbl.configure(
            text="Đã nhận " + ", ".join(bits) + " - sẵn sàng tải." if bits else "")

    def paste(self) -> None:
        try:
            txt = self.clipboard_get()
        except Exception:
            self._say("Bộ nhớ tạm đang trống - hãy copy link trước đã.")
            return
        self.box.delete("1.0", "end")
        self.box.insert("1.0", txt.strip())
        self._detect()

    def pick_folder(self) -> None:
        current = (self.out_dir_var.get() or "").strip() or default_video_dir()
        path = filedialog.askdirectory(title="Chọn thư mục lưu video", initialdir=current)
        if path:
            self.out_dir_var.set(path)
            self._say(f"Đã chọn thư mục lưu: {path}")

    def open_output_folder(self) -> None:
        path = (self.out_dir_var.get() or "").strip()
        if not path:
            messagebox.showwarning("Chưa chọn thư mục", "Hãy chọn thư mục lưu video trước.")
            return
        if self._open_folder:
            self._open_folder(path)
        else:
            try:
                os.startfile(path)
            except Exception as exc:
                messagebox.showerror("Lỗi", f"Không mở được thư mục: {exc}")

    def _refresh_cookie_status(self) -> None:
        """Hiển thị trạng thái tệp cookie Douyin cố định."""
        path = self._cookie_path
        if not path or not os.path.isfile(path):
            self.cookie_lbl.configure(
                text="🍪 Chưa có file cookie Douyin. Video công khai vẫn tải được; "
                     "muốn tải trang cá nhân thì hãy đặt file "
                     "cookies\\douyin_cookies.txt cạnh app (xem file MẪU trong thư mục cookies).",
                text_color=self.T["AMBER"],
            )
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size <= 0:
            self.cookie_lbl.configure(
                text="🍪 File cookie Douyin đang trống - hãy dán cookie của bạn vào "
                     "để tải được trang cá nhân.",
                text_color=self.T["AMBER"],
            )
        else:
            self.cookie_lbl.configure(
                text=f"🍪 Đã dùng file cookie Douyin: {os.path.basename(path)} ({size:,} byte).",
                text_color=self.T["GREEN"],
            )

    # ------------------------------------------------------------------ tải
    def start(self) -> None:
        if self._busy:
            return
        links = self._links()
        if not links:
            messagebox.showwarning(
                "Thiếu link",
                "Hãy dán ít nhất 1 link trang cá nhân hoặc link video Douyin vào ô trên.",
            )
            return

        out_dir = (self.out_dir_var.get() or "").strip()
        if not out_dir:
            out_dir = default_video_dir()
            self.out_dir_var.set(out_dir)

        # Kiểm tra thư mục lưu có ghi được không - báo lỗi tiếng Việt ngay.
        try:
            os.makedirs(out_dir, exist_ok=True)
            probe = os.path.join(out_dir, ".reup_write_test")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
        except Exception as exc:
            messagebox.showerror(
                "Không ghi được thư mục",
                f"Không thể lưu video vào thư mục này:\n{out_dir}\n\n"
                f"Lý do: {exc}\n\nHãy chọn một thư mục khác (ví dụ thư mục Video trong ổ D:).",
            )
            return

        try:
            from douyin_batch.service import DouyinBatchService, load_cookies_from_file
        except Exception as exc:
            messagebox.showerror(
                "Thiếu thành phần tải Douyin",
                f"Không nạp được mô-đun tải Douyin:\n{exc}\n\n"
                "Hãy thử cài lại bản Reup Studio.",
            )
            return

        cookies = load_cookies_from_file(self._cookie_path)
        service = DouyinBatchService(out_dir=out_dir, cookies=cookies)
        self._service = service

        self._busy = True
        self.go_btn.configure(state="disabled", text="⏳ Đang tải...")
        self.stop_btn.configure(state="normal")
        self.bar.set(0.01)
        self._clear_table()
        self._say(f"Đang chuẩn bị tải {len(links)} link vào: {out_dir}")
        self._log(f"[Douyin hàng loạt] Bắt đầu tải {len(links)} link -> {out_dir}")

        def work():
            try:
                result = service.run(
                    links,
                    progress_cb=lambda p, m: self._q.put(("p", p, m)),
                    item_cb=lambda st, lb: self._q.put(("i", st, lb)),
                )
                self._q.put(("done", result))
            except Exception as exc:  # noqa: BLE001 - không để nút bị treo
                self._q.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._pump)

    def stop(self) -> None:
        if self._service is not None:
            self._service.stop()
            self._say("Đang dừng, vui lòng chờ...")
            self._log("[Douyin hàng loạt] Người dùng bấm Dừng.")

    # ------------------------------------------------------------------ cập nhật giao diện
    def _pump(self) -> None:
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]
                if kind == "p":
                    self.bar.set(min(1.0, max(0.0, item[1])))
                    self._say(item[2])
                elif kind == "i":
                    self._add_table_row(item[1], item[2])
                elif kind == "done":
                    self._finish(item[1])
                    return
                elif kind == "error":
                    self._reset_buttons()
                    self._say(f"✕ Lỗi: {item[1]}", self.T["RED"])
                    self._log(f"[Douyin hàng loạt] ✕ Lỗi: {item[1]}")
                    return
        except queue.Empty:
            pass
        if self._busy:
            self.after(100, self._pump)

    def _reset_buttons(self) -> None:
        self._busy = False
        self.go_btn.configure(state="normal", text="▶ Bắt đầu tải")
        self.stop_btn.configure(state="disabled")

    def _finish(self, result) -> None:
        self._reset_buttons()
        lines = []
        if result.videos:
            self._downloaded_count += len(result.videos)
            self.counter_lbl.configure(text=f"Tổng số video đã tải: {self._downloaded_count}")
            lines.append(f"✓ Đã tải xong {len(result.videos)} video.")
        for err in result.errors[:4]:
            lines.append(f"✕ {err}")
        if len(result.errors) > 4:
            lines.append(f"… và {len(result.errors) - 4} lỗi khác (xem log bên dưới).")
        if not lines:
            lines.append("Không có video nào được tải.")
        color = self.T["GREEN"] if result.videos and not result.errors else (
            self.T["AMBER"] if result.videos else self.T["RED"])
        self._say("\n".join(lines), color)
        self._log(f"[Douyin hàng loạt] {result.summary()}")
        for err in result.errors:
            self._log(f"[Douyin hàng loạt] ✕ {err}")

    # ------------------------------------------------------------------ bảng trạng thái
    def _clear_table(self) -> None:
        for row in self._table_rows:
            row.destroy()
        self._table_rows.clear()
        self._empty_row = ctk.CTkLabel(
            self.table, text="Đang tải...", text_color=self.T["TEXT_MUTED"])
        self._empty_row.pack(anchor="w", padx=12, pady=10)

    def _add_table_row(self, status: str, label: str) -> None:
        T, F = self.T, self.F
        if self._empty_row is not None:
            try:
                self._empty_row.destroy()
            except Exception:
                pass
            self._empty_row = None

        color = {
            "xong": T["GREEN"],
            "lỗi": T["RED"],
            "đang tải": T["ACCENT"],
            "bỏ qua": T["AMBER"],
        }.get(status, T["TEXT_MUTED"])
        icon = {
            "xong": "✓",
            "lỗi": "✕",
            "đang tải": "⏳",
            "bỏ qua": "→",
        }.get(status, "•")

        row = ctk.CTkFrame(self.table, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row, text=icon, font=(F, 12), text_color=color, width=18).pack(side="left")
        name = label or "(không rõ tên)"
        if len(name) > 70:
            name = name[:35] + "…" + name[-32:]
        ctk.CTkLabel(row, text=name, font=(F, 11), anchor="w", text_color=T["TEXT_MUTED"]).pack(
            side="left", fill="x", expand=True)
        ctk.CTkLabel(row, text=status, font=(F, 11), text_color=color, width=90, anchor="e").pack(side="right")
        self._table_rows.append(row)
