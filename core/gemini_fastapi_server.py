"""
Compatibility bridge for Reup Studio.

Reup Studio vẫn import:
    core.gemini_fastapi_server

và dùng để:
    - kiểm tra server Gemini-FastAPI đang chạy ở http://127.0.0.1:8000
    - TỰ KHỞI ĐỘNG server Gemini-FastAPI đi kèm app nếu máy chưa có server nào
      chạy sẵn (bản đóng gói công khai phải chạy được ngay sau khi cài).

Server đi kèm nằm ở thư mục "gemini_fastapi_server" cạnh app, được chạy như một
tiến trình Python riêng với:
    - thư mục làm việc: <thư mục dữ liệu người dùng>\\gemini_fastapi
    - biến môi trường CONFIG_PATH trỏ tới file cấu hình trong thư mục đó

Nhờ vậy cấu hình và dữ liệu của server KHÔNG nằm trong thư mục cài đặt, nên
người dùng khác cài app vẫn có cấu hình sạch (không dính cookie của người khác).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_MODEL = "gemini-flash"

LogCallback = Optional[Callable[[str], None]]


def _log(cb: LogCallback, message: str) -> None:
    if cb:
        try:
            cb(message)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Vị trí thư mục
# --------------------------------------------------------------------------
def _app_base_dir() -> str:
    """Thư mục gốc của app (nơi đặt main.py / ReupStudio.exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_data_dir() -> str:
    """Thư mục dữ liệu người dùng (%APPDATA%\\ReupStudio)."""
    override = os.environ.get("REUP_STUDIO_DATA_DIR", "").strip()
    if override:
        base = override
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "ReupStudio")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = os.path.join(os.path.expanduser("~"), ".reup_studio")
        os.makedirs(path, exist_ok=True)
    return path


def _bundled_server_dir() -> Optional[str]:
    """Thư mục chứa server Gemini FastAPI đi kèm app (nếu có)."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "gemini_fastapi_server"))
    candidates.append(os.path.join(_app_base_dir(), "gemini_fastapi_server"))
    for path in candidates:
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "run.py")):
            return path
    return None


def _prepare_server_workspace(server_dir: str) -> str:
    """Chuẩn bị thư mục làm việc cho server (cấu hình + dữ liệu nằm ở thư mục
    dữ liệu người dùng, KHÔNG nằm trong thư mục cài đặt).

    Trả về đường dẫn thư mục làm việc.
    """
    work_dir = os.path.join(_user_data_dir(), "gemini_fastapi")
    config_dir = os.path.join(work_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    os.makedirs(os.path.join(work_dir, "data"), exist_ok=True)

    config_path = os.path.join(config_dir, "config.yaml")
    if not os.path.isfile(config_path):
        # Ưu tiên bản cấu hình có sẵn trong thư mục app (nếu người dùng đã
        # tự cấu hình), nếu không thì tạo từ mẫu đi kèm.
        source = os.path.join(server_dir, "config", "config.yaml")
        if os.path.isfile(source):
            try:
                shutil.copy2(source, config_path)
            except Exception:
                pass
        if not os.path.isfile(config_path):
            _write_default_config(config_path)
    return work_dir


def _write_default_config(config_path: str) -> None:
    """Tạo file cấu hình mặc định (chưa có tài khoản Gemini) kèm hướng dẫn."""
    content = """# ============================================================
#  CẤU HÌNH GEMINI FASTAPI SERVER - Reup Studio
#
#  Muốn dùng Gemini (không cần API key trả phí), hãy điền thông tin
#  đăng nhập Google của bạn vào mục "gemini.clients" bên dưới:
#
#    secure_1psid    : cookie __Secure-1PSID trên gemini.google.com
#    secure_1psidts : cookie __Secure-1PSIDTS trên gemini.google.com
#
#  Cách lấy: mở https://gemini.google.com bằng trình duyệt, đăng nhập,
#  mở DevTools (F12) -> Application -> Cookies -> https://gemini.google.com
#  -> copy giá trị của __Secure-1PSID và __Secure-1PSIDTS.
#
#  Để trống thì server vẫn chạy được nhưng sẽ báo "chưa có tài khoản".
# ============================================================

gemini:
  clients:
    - id: "account-1"
      secure_1psid: ""
      secure_1psidts: ""
      proxy: null

  timeout: 600
  watchdog_timeout: 300
  auto_refresh: true
  refresh_interval: 600
  verbose: false
  max_chars_per_request: 1000000
  oversized_context_strategy: "compaction"
  chat_mode: "normal"
  model_strategy: "append"
  models: []
"""
    try:
        with open(config_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    except Exception:
        pass


def _server_python() -> list:
    """Lệnh dùng để chạy server: ưu tiên python của chính app (kể cả khi đóng gói)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable]


def _server_launch_command(server_dir: str) -> Optional[list]:
    """Lệnh khởi chạy server Gemini FastAPI.

    - Bản đóng gói: dùng file GeminiFastAPI_Server.exe đi kèm app.
    - Chạy từ mã nguồn: dùng python của máy với <server_dir>\\run.py.
    """
    exe_path = os.path.join(_app_base_dir(), "GeminiFastAPI_Server", "GeminiFastAPI_Server.exe")
    if os.path.isfile(exe_path):
        return [exe_path]
    run_py = os.path.join(server_dir, "run.py")
    if os.path.isfile(run_py):
        return [sys.executable, run_py]
    return None


def _normalise_base_url(base_url: str) -> str:
    value = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")

    if value.endswith("/v1"):
        value = value[:-3]

    return value.rstrip("/")


def _port_from_base_url(base_url: str) -> int:
    parsed = urlparse(_normalise_base_url(base_url))

    if parsed.hostname not in (
        None,
        "127.0.0.1",
        "localhost",
        "0.0.0.0",
    ):
        raise ValueError(
            "Chỉ hỗ trợ Base URL local "
            "(127.0.0.1/localhost/0.0.0.0)."
        )

    if parsed.port:
        return parsed.port

    return 443 if parsed.scheme == "https" else 80


def _extract_server_error(response) -> str:
    try:
        payload = response.json()
    except Exception:
        return (getattr(response, "text", "") or "").strip()[:1000]

    if not isinstance(payload, dict):
        return str(payload)[:1000]

    detail = payload.get("detail")

    if detail:
        return str(detail)[:1000]

    error = payload.get("error")

    if isinstance(error, dict):
        return str(error.get("message") or error)[:1000]

    if error:
        return str(error)[:1000]

    return str(payload)[:1000]


def check_server_health(
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """
    Kiểm tra Gemini-FastAPI đang chạy.

    Không yêu cầu schema Web2API cũ.
    Chỉ cần endpoint /health trả về ok=True.
    """

    root = _normalise_base_url(base_url)

    try:
        response = requests.get(
            root + "/health",
            timeout=timeout,
        )

        if not response.ok:
            detail = _extract_server_error(response)

            return (
                False,
                f"Gemini-FastAPI trả về HTTP "
                f"{response.status_code}: {detail or response.reason}",
            )

        try:
            data = response.json()
        except Exception:
            data = {}

        if not isinstance(data, dict):
            return (
                False,
                f"Server {root} phản hồi nhưng không trả JSON hợp lệ.",
            )

        # Gemini-FastAPI hiện tại trả:
        #
        # {
        #     "ok": true,
        #     "storage": {...},
        #     "clients": {...}
        # }
        #
        if data.get("ok") is True:
            clients = data.get("clients")

            if isinstance(clients, dict):
                active_clients = [
                    str(k)
                    for k, v in clients.items()
                    if v
                ]

                if active_clients:
                    return (
                        True,
                        "✓ Gemini-FastAPI đang chạy tại "
                        f"{root} | clients: "
                        f"{', '.join(active_clients)}",
                    )

            return (
                True,
                f"✓ Gemini-FastAPI đang chạy tại {root}.",
            )

        # Một số phiên bản có thể dùng status=ok
        if str(data.get("status", "")).lower() == "ok":
            return (
                True,
                f"✓ Gemini-FastAPI đang chạy tại {root}.",
            )

        return (
            False,
            f"Cổng {root} đang phản hồi nhưng "
            "không xác nhận Gemini-FastAPI.",
        )

    except requests.Timeout:
        return (
            False,
            f"Gemini-FastAPI timeout tại {root}.",
        )

    except requests.ConnectionError:
        return (
            False,
            f"Gemini-FastAPI CHƯA CHẠY tại {root}.",
        )

    except Exception as exc:
        return (
            False,
            f"Không kiểm tra được Gemini-FastAPI tại "
            f"{root}: {exc}",
        )


def get_models(
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 10.0,
) -> Tuple[bool, list, str]:
    """
    Lấy danh sách model từ /v1/models.
    """

    root = _normalise_base_url(base_url)

    try:
        response = requests.get(
            root + "/v1/models",
            timeout=timeout,
        )

        if not response.ok:
            return (
                False,
                [],
                _extract_server_error(response),
            )

        data = response.json()

        models = data.get("data", [])

        if not isinstance(models, list):
            return (
                False,
                [],
                "Response /v1/models không có data dạng list.",
            )

        names = []

        for item in models:
            if isinstance(item, dict) and item.get("id"):
                names.append(str(item["id"]))

        return True, names, ""

    except Exception as exc:
        return False, [], str(exc)


def test_chat_completion(
    base_url: str = DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    timeout: float = 90.0,
) -> Tuple[bool, str]:
    """
    Gửi một request thật tới Gemini-FastAPI.
    """

    root = _normalise_base_url(base_url)

    headers = {
        "Content-Type": "application/json",
    }

    if api_key and api_key.strip():
        headers["Authorization"] = (
            f"Bearer {api_key.strip()}"
        )

    selected_model = model or DEFAULT_MODEL

    try:
        response = requests.post(
            root + "/v1/chat/completions",
            headers=headers,
            json={
                "model": selected_model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly: OK",
                    }
                ],
                "stream": False,
            },
            timeout=timeout,
        )

        if not response.ok:
            detail = _extract_server_error(response)

            return (
                False,
                f"✗ Gọi Gemini thất bại "
                f"(HTTP {response.status_code}): "
                f"{detail or response.reason}",
            )

        try:
            data = response.json()
        except Exception as exc:
            return (
                False,
                f"✗ Gemini trả response không phải JSON: {exc}",
            )

        choices = data.get("choices") or []

        if not choices:
            return (
                False,
                "✗ Gemini-FastAPI kết nối được "
                "nhưng không trả về choices.",
            )

        first = choices[0]

        if not isinstance(first, dict):
            return (
                False,
                "✗ Response choices không hợp lệ.",
            )

        message = first.get("message") or {}

        if not isinstance(message, dict):
            message = {}

        content = message.get("content") or ""

        if isinstance(content, list):
            content = str(content)

        content = str(content).strip()

        if not content:
            return (
                False,
                "✗ Gemini-FastAPI kết nối được "
                "nhưng trả về nội dung rỗng.",
            )

        return (
            True,
            f"✓ Gọi Gemini thành công bằng model "
            f"{selected_model}: {content[:200]}",
        )

    except requests.Timeout:
        return (
            False,
            "✗ Request thử Gemini bị timeout.",
        )

    except requests.ConnectionError:
        return (
            False,
            f"✗ Không kết nối được Gemini-FastAPI "
            f"tại {root}.",
        )

    except Exception as exc:
        return (
            False,
            f"✗ Không gọi thử được Gemini: {exc}",
        )


class GeminiFastAPIProcess:
    """
    Compatibility class.

    Tên class được giữ nguyên để không làm hỏng Reup Studio.

    Khác với bản cũ:
        - KHÔNG import gemini_web2api
        - KHÔNG tạo ThreadedServer
        - KHÔNG mở port mới
        - KHÔNG quản lý cookie Gemini
        - KHÔNG tạo server thứ hai

    Nó chỉ quản lý kết nối tới Gemini-FastAPI
    đang chạy bên ngoài tại 127.0.0.1:8000.
    """

    def __init__(self) -> None:
        self._base_url = DEFAULT_BASE_URL
        self._last_start_kwargs: Dict[str, object] = {}
        self._process: Optional[subprocess.Popen] = None
        self._started_by_us = False

    @property
    def is_alive(self) -> bool:
        """
        Kiểm tra server Gemini-FastAPI bên ngoài.
        """

        ok, _ = check_server_health(
            self._base_url,
            timeout=2.0,
        )

        return ok

    @staticmethod
    def _detect_cookie_file(
        requested: Optional[str],
        server_dir=None,
    ) -> Optional[str]:
        """
        Giữ method để tương thích code cũ.

        Cookie hiện được quản lý bởi Gemini-FastAPI,
        nên Reup Studio không cần đọc cookie.
        """

        if requested:
            return requested

        return None

    def start(
        self,
        api_key: Optional[str] = None,
        cookie_file: Optional[str] = None,
        proxy: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        auth_user: Optional[str] = None,
        xsrf_token: Optional[str] = None,
        log_cb: LogCallback = None,
    ) -> bool:

        del cookie_file
        del proxy
        del auth_user
        del xsrf_token

        try:
            self._base_url = _normalise_base_url(base_url)

            _port_from_base_url(self._base_url)

        except Exception as exc:
            _log(
                log_cb,
                f"Base URL Gemini không hợp lệ: {exc}",
            )
            return False

        self._last_start_kwargs = {
            "api_key": api_key,
            "base_url": self._base_url,
        }

        _log(
            log_cb,
            "Đang kiểm tra Gemini-FastAPI dùng chung "
            f"tại {self._base_url}...",
        )

        ok, message = check_server_health(
            self._base_url,
            timeout=5.0,
        )

        _log(log_cb, message)

        if ok:
            _log(
                log_cb,
                "✓ Reup Studio sẽ dùng Gemini-FastAPI hiện tại "
                f"tại {self._base_url}.",
            )
            return True

        # Chưa có server nào chạy -> tự khởi động server đi kèm app.
        if self._start_bundled_server(log_cb):
            if self.wait_until_ready(
                base_url=self._base_url, timeout=40.0, log_cb=log_cb
            ):
                return True

        _log(
            log_cb,
            "Gemini-FastAPI chưa sẵn sàng. "
            "Hãy khởi động server tại "
            f"{self._base_url}.",
        )
        return False

    def _start_bundled_server(self, log_cb: LogCallback = None) -> bool:
        """Khởi động server Gemini FastAPI đi kèm app (nếu có trong bản cài)."""
        server_dir = _bundled_server_dir()
        exe_path = os.path.join(_app_base_dir(), "GeminiFastAPI_Server", "GeminiFastAPI_Server.exe")
        if not server_dir and not os.path.isfile(exe_path):
            _log(
                log_cb,
                "Không tìm thấy thư mục server Gemini FastAPI đi kèm app.",
            )
            return False
        if self._process is not None and self._process.poll() is None:
            return True

        try:
            work_dir = _prepare_server_workspace(server_dir)
        except Exception as exc:
            _log(log_cb, f"Không chuẩn bị được thư mục cho server Gemini: {exc}")
            return False

        env = dict(os.environ)
        env["CONFIG_PATH"] = os.path.join(work_dir, "config", "config.yaml")
        if server_dir:
            existing_path = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = server_dir + (os.pathsep + existing_path if existing_path else "")
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("PYTHONUTF8", "1")

        cmd = _server_launch_command(server_dir)
        if not cmd:
            _log(log_cb, "Không tìm thấy cách chạy Gemini FastAPI server.")
            return False

        _log(log_cb, f"Đang khởi động Gemini FastAPI server: {' '.join(cmd)}")
        try:
            creationflags = 0x08000000 if sys.platform == "win32" else 0
            self._process = subprocess.Popen(
                cmd,
                cwd=work_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            self._started_by_us = True
        except Exception as exc:
            _log(log_cb, f"Không khởi động được Gemini FastAPI server: {exc}")
            self._process = None
            self._started_by_us = False
            return False
        return True

    def wait_until_ready(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 25.0,
        poll_interval: float = 0.5,
        log_cb: LogCallback = None,
    ) -> bool:

        self._base_url = _normalise_base_url(base_url)

        deadline = time.time() + timeout
        last_message = ""

        while time.time() < deadline:

            ok, message = check_server_health(
                self._base_url,
                timeout=min(3.0, poll_interval + 1.0),
            )

            last_message = message

            if ok:
                _log(log_cb, message)
                return True

            time.sleep(poll_interval)

        _log(
            log_cb,
            "Hết thời gian chờ Gemini-FastAPI "
            f"sẵn sàng: {last_message}",
        )

        return False

    def stop(self, timeout: float = 8.0) -> None:
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

    def restart(
        self,
        log_cb: LogCallback = None,
        **overrides,
    ) -> bool:
        """
        Không restart server chung.

        Chỉ kiểm tra lại kết nối.
        """

        params = dict(self._last_start_kwargs)
        params.update(
            {
                key: value
                for key, value in overrides.items()
                if value is not None
            }
        )

        return self.start(
            log_cb=log_cb,
            **params,
        )


def get_bundled_server_dir() -> Optional[str]:
    """
    Thư mục chứa server Gemini FastAPI đi kèm app (nếu bản cài có).

    Trả về None khi bản cài không kèm server - khi đó người dùng phải tự
    chạy server riêng ở http://127.0.0.1:8000.
    """
    return _bundled_server_dir()