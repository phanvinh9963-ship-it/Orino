"""
core/gemini_webapi_client.py
Tích hợp "Gemini API master" (gemini_webapi, https://github.com/HanaokaYuzu/Gemini-API) -
thư viện Python BẤT ĐỒNG BỘ (async) gọi THẲNG gemini.google.com bằng cookie trình
duyệt (__Secure-1PSID / __Secure-1PSIDTS), KHÔNG cần chạy thêm 1 server phụ như
Gemini-FastAPI (core/gemini_fastapi_server.py) - đổi lại CẦN cookie đăng nhập Google
còn hiệu lực (dễ hết hạn hơn, xem hướng dẫn lấy cookie trong README của
Gemini-API-master).

Thư mục source "Gemini-API-master" (giải nén từ Gemini-API-master.zip) được đặt
CẠNH main.py, dạng:
    <project_root>/Gemini-API-master/src/gemini_webapi/...
Module này TỰ ĐỘNG thêm thư mục "src" đó vào sys.path nếu gemini_webapi chưa được
cài qua pip - người dùng không cần tự "pip install -e Gemini-API-master".
Yêu cầu cài sẵn 3 gói phụ thuộc của gemini_webapi: curl_cffi, loguru, orjson, pydantic
(pip install curl_cffi loguru orjson pydantic).

Vì gemini_webapi là thư viện asyncio trong khi phần còn lại của app (core/translate.py,
core/llm_shorten.py...) chạy đồng bộ (dùng requests) - module này tự quản lý 1 event
loop asyncio riêng chạy nền trong 1 thread daemon, và chỉ expose các hàm ĐỒNG BỘ
(sync, blocking) để nơi gọi dùng như bình thường, không cần sửa gì thêm.

Phiên đăng nhập (GeminiClient) được CACHE lại theo (secure_1psid, secure_1psidts,
proxy) để không phải bắt tay lại với Gemini web mỗi lần dịch 1 lô câu (tốn vài giây/
lần, và tạo phiên mới liên tục dễ bị Google nghi ngờ là bot).
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import Optional, Tuple

DEFAULT_MODEL = "gemini-3-flash"

# Thư mục project_root/Gemini-API-master (bundle sẵn cùng app, CẠNH main.py, tức
# thư mục cha của core/). Liệt kê thêm vài biến thể tên thường gặp khi giải nén
# (Windows đôi khi tự thêm hậu tố khi giải nén đè lần 2, hoặc người dùng đổi tên
# thư mục theo repo gốc "Gemini-API").
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUNDLED_CANDIDATES = [
    os.path.join(_PROJECT_ROOT, "Gemini-API-master", "src"),
    os.path.join(_PROJECT_ROOT, "Gemini-API-master (1)", "src"),
    os.path.join(_PROJECT_ROOT, "gemini-api-master", "src"),
    os.path.join(_PROJECT_ROOT, "Gemini-API", "src"),
]


def get_bundled_src_dir() -> Optional[str]:
    """Trả về thư mục 'src' của Gemini-API-master đã bundle cạnh main.py, hoặc None
    nếu không tìm thấy (vd người dùng đã pip install package thật thay vì để cạnh app,
    hoặc đặt tên thư mục khác 4 biến thể ở trên - có thể tự thêm vào _BUNDLED_CANDIDATES)."""
    for cand in _BUNDLED_CANDIDATES:
        if os.path.isdir(os.path.join(cand, "gemini_webapi")):
            return cand
    return None


def _ensure_importable() -> None:
    """Đảm bảo `import gemini_webapi` chạy được: thử import thẳng trước (trường hợp đã
    pip install), nếu không được thì tự thêm thư mục bundle vào sys.path rồi thử lại.
    Raise ImportError kèm hướng dẫn rõ ràng nếu cả 2 cách đều thất bại."""
    try:
        import gemini_webapi  # noqa: F401
        return
    except ImportError:
        pass

    src_dir = get_bundled_src_dir()
    if src_dir and src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    try:
        import gemini_webapi  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Không import được 'gemini_webapi'. Hãy đảm bảo thư mục 'Gemini-API-master' "
            "(giải nén từ file zip cùng tên) nằm CẠNH main.py (cùng cấp với thư mục core/), "
            "và đã cài các gói phụ thuộc: pip install curl_cffi loguru orjson pydantic"
        ) from e


# ---------------------------------------------------------------------------
# Event loop nền DÙNG CHUNG cho toàn app, chạy trong 1 thread riêng - vì GeminiClient
# là async và cần giữ session/cookie sống xuyên suốt nhiều lần gọi, không thể tạo
# asyncio.run() mới mỗi lần (sẽ mất session, phải bắt tay/handshake lại từ đầu).
# ---------------------------------------------------------------------------
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        _loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _loop_thread = threading.Thread(target=_run, daemon=True, name="gemini-webapi-loop")
        _loop_thread.start()
        return _loop


def _run_sync(coro, timeout: float):
    """Chạy 1 coroutine trên event loop nền, chờ kết quả ĐỒNG BỘ (blocking) tối đa
    `timeout` giây - để các hàm sync bên dưới gọi được thư viện bất đồng bộ."""
    loop = _get_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


# ---------------------------------------------------------------------------
# Cache client theo (secure_1psid, secure_1psidts, proxy) - tránh khởi tạo lại
# (handshake với Gemini web) mỗi lần gọi.
# ---------------------------------------------------------------------------
_clients: dict = {}
_clients_lock = threading.Lock()


def _client_key(secure_1psid: str, secure_1psidts: Optional[str], proxy: Optional[str]) -> tuple:
    return (secure_1psid.strip(), (secure_1psidts or "").strip(), (proxy or "").strip())


async def _get_or_init_client(secure_1psid: str, secure_1psidts: Optional[str], proxy: Optional[str]):
    _ensure_importable()
    from gemini_webapi import GeminiClient

    key = _client_key(secure_1psid, secure_1psidts, proxy)
    with _clients_lock:
        client = _clients.get(key)
    if client is not None:
        return client

    client = GeminiClient(
        secure_1psid.strip(), (secure_1psidts or "").strip() or None, proxy=(proxy or None),
    )
    await client.init(timeout=180, auto_close=False, auto_refresh=True, verbose=False)
    with _clients_lock:
        _clients[key] = client
    return client


def _invalidate_client(secure_1psid: str, secure_1psidts: Optional[str], proxy: Optional[str]) -> None:
    """Xoá client khỏi cache (khi phiên hỏng/cookie hết hạn) để lần gọi kế tiếp tự
    khởi tạo lại từ đầu, thay vì tiếp tục dùng session đã chết."""
    key = _client_key(secure_1psid, secure_1psidts, proxy)
    with _clients_lock:
        _clients.pop(key, None)


def _friendly_error(e: Exception) -> str:
    """Map exception của gemini_webapi sang thông báo tiếng Việt dễ hiểu. Cố tình GIỮ
    NGUYÊN các cụm "429"/"Too Many Requests" trong chuỗi lỗi khi phù hợp, để logic
    retry/backoff dò chuỗi lỗi ở core/translate.py vẫn nhận diện đúng loại lỗi."""
    try:
        from gemini_webapi.exceptions import (
            AuthError, TemporarilyBlocked, UsageLimitExceeded, ModelInvalid,
            TimeoutError as GWTimeoutError, GeminiError,
        )
    except ImportError:
        return str(e)

    if isinstance(e, AuthError):
        return (
            f"Xác thực thất bại (cookie sai/hết hạn): {e}. Lấy lại cookie "
            f"__Secure-1PSID/__Secure-1PSIDTS mới (đăng nhập gemini.google.com trên "
            f"trình duyệt, mở DevTools > Application/Storage > Cookies) rồi điền lại."
        )
    if isinstance(e, TemporarilyBlocked):
        return f"429 Too Many Requests - Google tạm chặn IP/tài khoản: {e}"
    if isinstance(e, UsageLimitExceeded):
        return f"Đã hết hạn mức sử dụng model cho tài khoản này: {e}"
    if isinstance(e, ModelInvalid):
        return f"Model không hợp lệ: {e}"
    if isinstance(e, GWTimeoutError):
        return f"Gemini web phản hồi quá chậm (timeout): {e}"
    if isinstance(e, GeminiError):
        return f"Lỗi từ Gemini web: {e}"
    return str(e)


def check_credentials(
    secure_1psid: str,
    secure_1psidts: Optional[str] = None,
    proxy: Optional[str] = None,
    timeout: float = 45.0,
) -> Tuple[bool, str]:
    """Thử khởi tạo (hoặc lấy lại từ cache) phiên đăng nhập Gemini web bằng cookie.
    Trả về (ok, message). Bước NHẸ (chỉ handshake, chưa gọi generate_content thật) -
    tương đương check_server_health() của Gemini-FastAPI."""
    secure_1psid = (secure_1psid or "").strip()
    if not secure_1psid:
        return False, "Thiếu cookie __Secure-1PSID."
    try:
        _run_sync(_get_or_init_client(secure_1psid, secure_1psidts, proxy), timeout=timeout)
        return True, "✓ Đăng nhập Gemini web bằng cookie thành công."
    except Exception as e:
        _invalidate_client(secure_1psid, secure_1psidts, proxy)
        return False, _friendly_error(e)


def test_chat_completion(
    secure_1psid: str,
    secure_1psidts: Optional[str] = None,
    proxy: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    timeout: float = 90.0,
) -> Tuple[bool, str]:
    """Gọi thử THẬT 1 lượt generate_content (không streaming) để chắc chắn luồng dịch
    sẽ hoạt động, không chỉ dừng ở bước đăng nhập. Dùng cho nút '🔎 Test Gemini (API
    master)' trên UI."""
    try:
        text = generate_text(
            "Trả lời đúng 1 chữ: OK",
            secure_1psid=secure_1psid, secure_1psidts=secure_1psidts, proxy=proxy,
            model=model, timeout=timeout, max_retries=1,
        )
        return True, f"✓ Gọi Gemini (API master) thành công. Model trả lời: {text!r}"
    except Exception as e:
        return False, str(e)


def generate_text(
    prompt: str,
    secure_1psid: str,
    secure_1psidts: Optional[str] = None,
    proxy: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    system_prompt: Optional[str] = None,
    timeout: float = 120.0,
    max_retries: int = 1,
) -> str:
    """Gửi 1 prompt, trả về text trả lời (ĐỒNG BỘ, blocking tới khi có kết quả hoặc
    hết timeout). Đây là hàm DUY NHẤT core/translate.py và core/llm_shorten.py cần
    gọi tới - retry/backoff THEO LÔ (batch câu phụ đề) vẫn do nơi gọi tự quản lý y hệt
    pattern của Gemini-FastAPI (xem translate_segments_gemini_webapi), hàm này chỉ lo
    đúng 1 lượt gọi (+ max_retries lần thử lại nội bộ nếu > 1).

    system_prompt: gemini_webapi (web UI) không có role "system" tách biệt như API
    chính thức trả phí - được NỐI vào ĐẦU prompt dưới dạng 1 khối hướng dẫn thay thế.

    Raises: Exception với message tiếng Việt dễ hiểu (xem _friendly_error) nếu lỗi.
    """
    secure_1psid = (secure_1psid or "").strip()
    if not secure_1psid:
        raise ValueError("Cần cookie __Secure-1PSID (xem hướng dẫn lấy cookie trong README Gemini-API-master).")

    full_prompt = prompt if not system_prompt else f"{system_prompt.strip()}\n\n{prompt}"

    last_err: Optional[Exception] = None
    for attempt in range(max(1, max_retries)):
        try:
            client = _run_sync(
                _get_or_init_client(secure_1psid, secure_1psidts, proxy), timeout=timeout,
            )

            async def _gen():
                return await client.generate_content(full_prompt, model=model)

            output = _run_sync(_gen(), timeout=timeout)
            text = (output.text or "").strip()
            if text:
                return text
            last_err = RuntimeError("Gemini (API master) trả về nội dung rỗng")
        except Exception as e:
            last_err = e
            err_msg = _friendly_error(e)
            # Lỗi xác thực/session hỏng -> xoá cache để lần thử SAU (nếu còn) tự khởi
            # tạo lại phiên mới, thay vì tiếp tục dùng session đã chết.
            if "Xác thực thất bại" in err_msg or "hết hạn" in err_msg.lower():
                _invalidate_client(secure_1psid, secure_1psidts, proxy)
            if attempt < max_retries - 1:
                continue
            raise RuntimeError(err_msg) from e

    raise RuntimeError(_friendly_error(last_err) if last_err else "Lỗi không xác định khi gọi Gemini (API master)")


def close_all(timeout: float = 10.0) -> None:
    """Đóng toàn bộ client đã cache (gọi khi tắt app) - dọn dẹp session/kết nối HTTP,
    tương tự GeminiFastAPIProcess.stop() cho Gemini-FastAPI."""
    global _clients
    with _clients_lock:
        clients = list(_clients.values())
        _clients = {}
    for client in clients:
        try:
            _run_sync(client.close(), timeout=timeout)
        except Exception:
            pass
