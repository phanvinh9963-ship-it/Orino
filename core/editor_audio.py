"""
core/editor_audio.py
Phát âm thanh xem trước cho Editor, có CHUỖI DỰ PHÒNG + công cụ chẩn đoán.

Thứ tự thử trên Windows (cái nào chạy được thì dùng):
  1. sounddevice - lần lượt các lớp âm thanh WASAPI -> DirectSound -> MME -> mặc định
     (WASAPI là lớp trình duyệt/YouTube đang dùng nên ít dính lỗi "thiết bị bị chiếm").
  2. MCI (winmm)          - đọc thẳng từ file, nhảy vị trí tức thì.
  3. ffplay               - nếu có (cùng thư mục ffmpeg hoặc trong PATH); dùng SDL nên không đi qua MME.
  4. winsound             - cuối cùng, chỉ nghe tối đa 2 phút (có thể im lặng không báo lỗi với file lớn).
Hệ khác: sounddevice -> ffplay.

Phát được -> trả True; `backend` cho biết đang dùng đường nào. Không phát được ->
`hint` là hướng dẫn cụ thể và `last_error` là chi tiết kỹ thuật (cho hộp thoại 🔊).

Thiết bị người dùng đã chọn (nếu có) lưu ở ~/.reup_studio_audio.json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from typing import List, Optional, Tuple

_PREF_FILE = os.path.join(os.path.expanduser("~"), ".reup_studio_audio.json")
FALLBACK_SECONDS = 120.0
FFPLAY_STARTUP = 0.45          # ffplay mất ~0.4s mới ra tiếng - bù bằng cách bắt đầu sớm hơn chừng đó


# ----------------------------------------------------------------------------
# tiện ích chung
# ----------------------------------------------------------------------------
def sd_modules():
    """(sounddevice, numpy) hoặc None nếu chưa cài / lỗi nạp."""
    try:
        import numpy as np
        import sounddevice as sd
        return sd, np
    except Exception:
        return None


def sd_import_error() -> str:
    try:
        import sounddevice  # noqa: F401
        import numpy  # noqa: F401
        return ""
    except Exception as e:
        return f"{e.__class__.__name__}: {e}"


def find_ffplay() -> Optional[str]:
    p = shutil.which("ffplay")
    if p:
        return p
    try:
        from core import editor_media as M
        d = os.path.dirname(M.ffmpeg_exe())
        for name in ("ffplay.exe", "ffplay"):
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return cand
    except Exception:
        pass
    return None


def load_pref() -> Optional[str]:
    try:
        with open(_PREF_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("device") or None
    except Exception:
        return None


def save_pref(key: Optional[str]):
    try:
        with open(_PREF_FILE, "w", encoding="utf-8") as f:
            json.dump({"device": key}, f, ensure_ascii=False)
    except Exception:
        pass


def _hostapi_name(sd, dev: int) -> str:
    try:
        return sd.query_hostapis(sd.query_devices(dev)["hostapi"])["name"]
    except Exception:
        return "?"


def device_key(sd, dev: int) -> str:
    return f"{_hostapi_name(sd, dev)}|{sd.query_devices(dev)['name']}"


def list_output_devices() -> List[Tuple[int, str]]:
    """[(chỉ số thiết bị, nhãn hiển thị)] của mọi thiết bị phát âm thanh."""
    mods = sd_modules()
    if mods is None:
        return []
    sd, _ = mods
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_output_channels", 0) > 0:
                out.append((i, f"[{_hostapi_name(sd, i)}] {d['name']}"))
    except Exception:
        pass
    return out


def _resolve_pref(sd) -> Optional[int]:
    key = load_pref()
    if not key:
        return None
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_output_channels", 0) > 0 and device_key(sd, i) == key:
                return i
    except Exception:
        pass
    return None


def _extra_for(sd, dev: int):
    if "WASAPI" in _hostapi_name(sd, dev):
        try:
            return sd.WasapiSettings(auto_convert=True)      # cho WASAPI tự đổi sample rate/kênh
        except Exception:
            return None
    return None


def _device_attempts(sd, prefer: Optional[int]):
    attempts, seen = [], set()

    def add(dev):
        if dev is None or dev < 0 or dev in seen:
            return
        seen.add(dev)
        attempts.append((dev, _extra_for(sd, dev)))

    if prefer is not None:
        add(prefer)
    if sys.platform == "win32":
        try:
            apis = sd.query_hostapis()
            for want in ("WASAPI", "DirectSound", "MME"):
                for h in apis:
                    if want in h.get("name", ""):
                        add(h.get("default_output_device", -1))
        except Exception:
            pass
    attempts.append((None, None))                            # mặc định của PortAudio
    return attempts


def open_stream(sd, sr: int, ch: int, cb, prefer: Optional[int] = None, finished=None):
    """Mở luồng phát trên thiết bị đầu tiên chạy được. Trả (stream, nhãn). Lỗi -> RuntimeError(chi tiết)."""
    errs = []
    for dev, extra in _device_attempts(sd, prefer):
        label = "mặc định" if dev is None else f"{_hostapi_name(sd, dev)}: {sd.query_devices(dev)['name']}"
        try:
            kw = dict(samplerate=sr, channels=ch, dtype="int16", callback=cb, device=dev)
            if extra is not None:
                kw["extra_settings"] = extra
            if finished is not None:
                kw["finished_callback"] = finished
            s = sd.OutputStream(**kw)
            s.start()
            return s, label
        except Exception as e:
            first = (str(e).strip().splitlines() or [e.__class__.__name__])[0]
            errs.append(f"{label} → {first}")
    raise RuntimeError(" | ".join(errs)[:400])


# ----------------------------------------------------------------------------
# Trình phát
# ----------------------------------------------------------------------------
class AudioPlayer:
    ALIAS = "rpplay"

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._tmp: Optional[str] = None
        self._copy: Optional[str] = None
        self._copy_sig = None
        self._mci_open = False
        self._n = 0
        self._stream = None
        self._pcm = None
        self._pcm_sig = None
        self._pcm_lock = threading.Lock()
        self.backend = ""          # đường phát đang dùng, vd "sounddevice · WASAPI: Speakers"
        self.degraded = False      # True = đang ở chế độ cuối (winsound, chỉ nghe được 2 phút)
        self.hint = ""             # hướng dẫn khi phát lỗi / chế độ dự phòng
        self.last_error = ""       # chi tiết kỹ thuật

    # ---- sounddevice
    def _load_pcm(self, np, wav: str):
        with self._pcm_lock:
            sig = (wav, os.path.getmtime(wav), os.path.getsize(wav))
            if self._pcm is None or self._pcm_sig != sig:
                with wave.open(wav) as w:
                    if w.getsampwidth() != 2:
                        raise RuntimeError("file preview không phải PCM 16-bit")
                    ch, sr = w.getnchannels(), w.getframerate()
                    raw = w.readframes(w.getnframes())
                self._pcm = (np.frombuffer(raw, dtype=np.int16).reshape(-1, ch), sr)
                self._pcm_sig = sig
            return self._pcm

    def preload(self, wav: str):
        """Nạp sẵn file preview vào RAM (gọi từ luồng nền) để bấm Play không bị khựng."""
        mods = sd_modules()
        if mods is not None and os.path.isfile(wav):
            try:
                self._load_pcm(mods[1], wav)
            except Exception:
                pass

    def _play_sd(self, mods, wav: str, start: float):
        sd, np = mods
        data, sr = self._load_pcm(np, wav)
        pos = int(max(0.0, start) * sr)
        if pos >= len(data) - 1:
            raise EOFError("vị trí phát nằm ở cuối âm thanh")
        st = {"pos": pos}

        def cb(outdata, frames, time_info, status):
            p = st["pos"]
            chunk = data[p:p + frames]
            n = len(chunk)
            outdata[:n] = chunk
            if n < frames:
                outdata[n:] = 0
                st["pos"] = len(data)
                raise sd.CallbackStop
            st["pos"] = p + frames

        self._stream, label = open_stream(sd, sr, data.shape[1], cb, prefer=_resolve_pref(sd))
        self.backend = f"sounddevice · {label}"

    # ---- MCI (Windows)
    @staticmethod
    def _mci(cmd: str):
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        err = ctypes.windll.winmm.mciSendStringW(cmd, buf, 255, 0)
        if err:
            eb = ctypes.create_unicode_buffer(256)
            ctypes.windll.winmm.mciGetErrorStringW(err, eb, 255)
            return err, eb.value or f"mã lỗi {err}"
        return 0, buf.value

    def _mci_close(self):
        if self._mci_open:
            try:
                self._mci(f"stop {self.ALIAS}")
                self._mci(f"close {self.ALIAS}")
            except Exception:
                pass
            self._mci_open = False

    def _drop_copy(self):
        self._mci_close()
        if self._copy:
            try:
                os.remove(self._copy)
            except OSError:
                pass
        self._copy, self._copy_sig = None, None

    def _play_mci(self, wav: str, start: float):
        sig = (wav, os.path.getmtime(wav), os.path.getsize(wav))
        if self._copy is None or self._copy_sig != sig or not os.path.isfile(self._copy):
            self._drop_copy()
            self._n += 1
            dst = os.path.join(tempfile.gettempdir(), f"rp_play_{os.getpid()}_{self._n}.wav")
            shutil.copyfile(wav, dst)
            self._copy, self._copy_sig = dst, sig
        if not self._mci_open:
            err, msg = self._mci(f'open "{self._copy}" type waveaudio alias {self.ALIAS}')
            if err:
                self._drop_copy()                     # đừng để sót bản sao hàng chục MB trong thư mục tạm
                raise RuntimeError(msg)
            self._mci_open = True
            self._mci(f"set {self.ALIAS} time format milliseconds")
        err, msg = self._mci(f"play {self.ALIAS} from {int(max(0.0, start) * 1000)}")
        if err:
            self._mci_close()
            raise RuntimeError(msg)
        self.backend = "MCI (winmm)"

    # ---- ffplay
    def _play_ffplay(self, wav: str, start: float):
        ff = find_ffplay()
        if not ff:
            raise RuntimeError("không tìm thấy ffplay")
        cmd = [ff, "-nodisp", "-autoexit", "-loglevel", "error", "-ss", f"{max(0.0, start + FFPLAY_STARTUP):.3f}", wav]
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000                   # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, **kw)
        time.sleep(0.25)                                       # chết ngay -> báo lỗi thật thay vì im lặng
        rc = self._proc.poll()
        if rc not in (None, 0):
            msg = ""
            try:
                msg = (self._proc.stderr.read(400) or b"").decode("utf-8", "replace").strip()
            except Exception:
                pass
            self._proc = None
            raise RuntimeError(msg or f"ffplay thoát mã {rc}")
        self.backend = "ffplay"

    # ---- winsound: dự phòng cuối
    @staticmethod
    def _slice(path: str, start: float, max_sec: Optional[float] = None) -> Optional[str]:
        with wave.open(path) as w:
            sr, n = w.getframerate(), w.getnframes()
            pos = int(start * sr)
            if pos >= n - 1:
                return None
            w.setpos(pos)
            count = n - pos if not max_sec else min(n - pos, int(max_sec * sr))
            data = w.readframes(count)
            out = os.path.join(tempfile.gettempdir(), f"rp_slice_{os.getpid()}_{int(time.time() * 1000)}.wav")
            with wave.open(out, "wb") as o:
                o.setnchannels(w.getnchannels())
                o.setsampwidth(w.getsampwidth())
                o.setframerate(sr)
                o.writeframes(data)
        return out

    def _play_winsound(self, wav: str, start: float):
        import winsound
        path = self._slice(wav, max(0.0, start), FALLBACK_SECONDS)
        if not path:
            raise EOFError("vị trí phát nằm ở cuối âm thanh")
        self._tmp = path
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        self.backend = "winsound (chỉ nghe tối đa 2 phút)"
        self.degraded = True

    # ---- điều khiển
    def play(self, wav: str, start: float) -> bool:
        self.stop()
        self.last_error, self.hint, self.backend, self.degraded = "", "", "", False
        if not os.path.isfile(wav):
            self.last_error = "chưa có file âm thanh xem trước"
            return False
        errs: List[str] = []
        at_end = False

        def attempt(name, fn) -> bool:
            nonlocal at_end
            try:
                fn()
                return True
            except EOFError:
                at_end = True
                return False
            except Exception as e:
                errs.append(f"{name}: {e}")
                self.stop()
                return False

        mods = sd_modules()
        steps = []
        if mods is not None:
            steps.append(("sounddevice", lambda: self._play_sd(mods, wav, start)))
        if sys.platform == "win32":
            steps.append(("MCI", lambda: self._play_mci(wav, start)))
        steps.append(("ffplay", lambda: self._play_ffplay(wav, start)))
        if sys.platform == "win32":
            steps.append(("winsound", lambda: self._play_winsound(wav, start)))

        ok = False
        for name, fn in steps:
            if attempt(name, fn):
                ok = True
                break
            if at_end:
                self.last_error = "vị trí phát nằm ở cuối âm thanh"
                return False
        self.last_error = " | ".join(errs)
        if not ok or self.degraded:
            if mods is None:
                self.hint = ("Chưa cài thư viện sounddevice nên chỉ còn các đường phát cũ (hay bị lỗi 'thiết bị đang bận'). "
                             "Bấm 🔊 → “Cài sounddevice”.")
            else:
                self.hint = ("Thiết bị phát âm thanh của Windows đang bị chiếm hoặc không hỗ trợ. "
                             "Bấm 🔊 để chọn thiết bị khác và phát âm thử.")
        return ok

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if sys.platform == "win32":
            try:
                if self._mci_open:
                    self._mci(f"stop {self.ALIAS}")
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
        if self._tmp:
            try:
                os.remove(self._tmp)
            except OSError:
                pass
            self._tmp = None

    def release(self):
        """Dừng hẳn, đóng thiết bị, xoá file tạm (gọi khi đóng Editor)."""
        self.stop()
        self._drop_copy()
        self._pcm, self._pcm_sig = None, None


# ----------------------------------------------------------------------------
# Chẩn đoán / thử âm / cài đặt
# ----------------------------------------------------------------------------
def diagnose() -> str:
    lines = [f"Python: {sys.executable}  ({sys.version.split()[0]})", f"Hệ điều hành: {sys.platform}"]
    mods = sd_modules()
    if mods is None:
        lines.append(f"sounddevice: CHƯA CÀI hoặc lỗi nạp ({sd_import_error()})")
        lines.append("  → bấm “Cài sounddevice” bên dưới (hoặc: pip install sounddevice numpy)")
    else:
        sd, _ = mods
        lines.append(f"sounddevice: {getattr(sd, '__version__', '?')}")
        try:
            apis = sd.query_hostapis()
            devs = sd.query_devices()
            for hi, h in enumerate(apis):
                dd = h.get("default_output_device", -1)
                lines.append(f"• {h['name']}  (mặc định phát: "
                             f"{devs[dd]['name'] if dd is not None and dd >= 0 else 'không có'})")
                for i, d in enumerate(devs):
                    if d["hostapi"] == hi and d.get("max_output_channels", 0) > 0:
                        lines.append(f"     #{i} {d['name']}  ({int(d['default_samplerate'])} Hz, {d['max_output_channels']} kênh)")
        except Exception as e:
            lines.append(f"  không liệt kê được thiết bị: {e}")
    ff = find_ffplay()
    lines.append(f"ffplay: {ff or 'không có'}")
    pref = load_pref()
    lines.append(f"Thiết bị đã chọn: {pref or 'tự động'}")
    return "\n".join(lines)


def test_tone(device: Optional[int] = None, seconds: float = 1.2) -> Tuple[bool, str]:
    """Phát tiếng bíp ~1 giây qua thiết bị chỉ định (hoặc tự động). Trả (mở được luồng?, nhãn/lỗi).
    Chỉ người nghe mới biết có ra tiếng thật - hàm này xác nhận Windows MỞ ĐƯỢC thiết bị."""
    mods = sd_modules()
    if mods is None:
        return False, "sounddevice chưa cài"
    sd, np = mods
    sr, n = 44100, int(44100 * seconds)
    t = np.arange(n) / sr
    env = np.minimum(1.0, np.minimum(t, seconds - t) * 20)             # vào/ra êm, không bị 'tách'
    tone = (0.3 * np.sin(2 * np.pi * 660 * t) * env * 32767).astype(np.int16).reshape(-1, 1)
    st, done = {"pos": 0}, threading.Event()

    def cb(outdata, frames, ti, status):
        p = st["pos"]
        chunk = tone[p:p + frames]
        outdata[:len(chunk)] = chunk
        if len(chunk) < frames:
            outdata[len(chunk):] = 0
            raise sd.CallbackStop
        st["pos"] = p + frames

    try:
        stream, label = open_stream(sd, sr, 1, cb, prefer=device, finished=done.set)
    except Exception as e:
        return False, str(e)
    done.wait(seconds + 2.0)
    try:
        stream.close()
    except Exception:
        pass
    return True, label


def install_sounddevice(log=lambda s: None) -> Tuple[bool, str]:
    """pip install sounddevice numpy bằng ĐÚNG Python đang chạy app. Chạy trong luồng nền."""
    if getattr(sys, "frozen", False):
        return False, "App đang chạy dạng .exe đóng gói - không cài thêm thư viện được. Hãy đóng gói lại có sounddevice."
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "sounddevice", "numpy"]
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace", **kw)
    except Exception as e:
        return False, f"Không chạy được pip: {e}"
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-4:]
    log("\n".join(tail))
    if r.returncode != 0:
        return False, "pip báo lỗi:\n" + "\n".join(tail)
    import importlib
    importlib.invalidate_caches()
    for m in [k for k in sys.modules if k == "sounddevice" or k.startswith("sounddevice.")]:
        sys.modules.pop(m, None)
    if sd_modules() is None:
        return True, "Đã cài xong. Hãy MỞ LẠI app để nạp thư viện mới."
    return True, "Đã cài xong và sẵn sàng dùng."
