"""
core/rewrite_srt.py
Công cụ ĐỨNG ĐỘC LẬP (không cần video, không qua Transcript/Translate/Voice):

    SRT gốc -> phân tích độ dài câu -> viết lại (BIẾN TẤU, CÙNG NGÔN NGỮ, không
    dịch) -> tính lại thời lượng đọc theo văn bản mới -> cân chỉnh timestamp ->
    loại bỏ khoảng lặng thừa giữa các câu -> xuất SRT mới.

Mục đích: tạo 1 bản phụ đề "không giống y hệt bản gốc" (né trùng lặp nội dung)
trong khi vẫn giữ nguyên toàn bộ SỰ KIỆN/SỐ LIỆU/TÊN RIÊNG - và một file SRT có
timing gọn gàng, khớp với tốc độ đọc thật của văn bản mới thay vì giữ nguyên
timing (thường bị lệch) của bản gốc.

Dùng lại hạ tầng gọi Gemini Web2API đã có ở core/gemini_fastapi_server.py (health
check) và bảng tốc độ đọc CHARS_PER_SEC đã hiệu chỉnh sẵn ở core/text_fit.py -
KHÔNG phụ thuộc core/translate.py (module dịch NGÔN NGỮ KHÁC, có hệ thống Content
Rewriter/persona/hook riêng phục vụ mục đích khác - ở đây chỉ cần viết lại CÙNG
ngôn ngữ với tỉ lệ biến tấu do người dùng chỉnh, nên tách riêng cho gọn và dễ
chỉnh độc lập).
"""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Callable, List, Optional

from core.transcribe import SubtitleSegment, parse_srt, save_srt
from core.text_fit import CHARS_PER_SEC, DEFAULT_CPS, estimate_duration_sec

GEMINI_FASTAPI_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_GEMINI_FASTAPI_MODEL = "gemini-3.6-flash"

SEP = "\n<<<SEG>>>\n"


def _openai_compatible_error_detail(resp) -> str:
    """Đọc thông báo lỗi thật từ response JSON kiểu FastAPI/OpenAI, thay vì chỉ
    có mã lỗi HTTP chung chung."""
    try:
        payload = resp.json()
    except Exception:
        return (getattr(resp, "text", "") or "").strip()[:600]
    if not isinstance(payload, dict):
        return str(payload)[:600]
    if payload.get("detail"):
        return str(payload["detail"])[:600]
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:600]
    if error:
        return str(error)[:600]
    return str(payload)[:600]


# --------------------------------------------------------------------------
# BƯỚC 1: phân tích độ dài câu (chỉ để đưa thông tin tham khảo vào prompt -
# giúp model tự biết câu nào đang dài để ưu tiên viết gọn lại hơn, câu nào
# đang ngắn thì không cần cắt).
# --------------------------------------------------------------------------

def analyze_segment_lengths(segments: List[SubtitleSegment], language: str) -> List[dict]:
    """Trả về danh sách dict {index, n_chars, cue_duration, est_read_sec, ratio}
    - ratio > 1.0 nghĩa là văn bản gốc đọc LÂU HƠN khung giờ cue gốc (đã bị dồn
    chữ/đọc nhanh trong bản gốc); ratio < 1.0 nghĩa là cue gốc còn dư giờ."""
    out = []
    for seg in segments:
        cue_dur = max(0.01, seg.end - seg.start)
        est = estimate_duration_sec(seg.text, language)
        out.append({
            "index": seg.index,
            "n_chars": len(seg.text.strip()),
            "cue_duration": cue_dur,
            "est_read_sec": est,
            "ratio": est / cue_dur,
        })
    return out


# --------------------------------------------------------------------------
# BƯỚC 2: viết lại CÙNG NGÔN NGỮ theo tỉ lệ biến tấu chỉnh được (mặc định giữ
# ~40% ý/cách diễn đạt gốc, biến tấu ~60% còn lại).
# --------------------------------------------------------------------------

def rewrite_segments_gemini_fastapi(
    segments: List[SubtitleSegment],
    language: str,
    base_url: str = GEMINI_FASTAPI_DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    model: str = DEFAULT_GEMINI_FASTAPI_MODEL,
    keep_ratio: float = 0.4,
    batch_size: int = 20,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    max_retries: int = 4,
    retry_delay: float = 2.0,
    timeout: float = 120.0,
    extra_style_notes: Optional[str] = None,
    char_budgets: Optional[List[int]] = None,  # MỚI: 1 số nguyên/câu (cùng thứ tự `segments`) - số ký
    # tự TỐI ĐA khuyên dùng để câu đọc VỪA ĐÚNG khung giờ gốc của nó (tính sẵn từ tốc độ đọc THẬT ×
    # thời lượng cue - xem core/pipeline.py). Khi truyền tham số này, mục đích của hàm đổi hẳn từ
    # "biến tấu tránh trùng lặp" sang "VIẾT NGẮN GỌN, TỰ NHIÊN, KHỚP NHỊP ĐỌC" - AI được cho biết
    # ngân sách ký tự cụ thể cho TỪNG câu ngay khi viết, thay vì viết tự do rồi phải cắt/nén sau -
    # nhờ vậy nhịp đọc ra tự nhiên, không nhanh không chậm, mà không mất chữ/mất nghĩa.
) -> List[SubtitleSegment]:
    """
    Viết lại từng câu CÙNG NGÔN NGỮ `language` (KHÔNG dịch) qua Gemini Web2API.

    keep_ratio (0.0 - 1.0): tỉ lệ GIỮ nguyên ý/cách diễn đạt gốc mong muốn - vd
    0.4 = giữ khoảng 40% (từ ngữ/cấu trúc gần bản gốc ở mức vừa phải), biến tấu
    khoảng 60% còn lại (đổi cấu trúc câu, từ đồng nghĩa, cách mở đầu/kết câu).
    keep_ratio thấp hơn -> biến tấu MẠNH hơn (câu chữ khác xa bản gốc hơn);
    keep_ratio cao hơn -> biến tấu NHẸ hơn (gần sát bản gốc hơn). Trong mọi
    trường hợp, SỰ KIỆN/SỐ LIỆU/TÊN RIÊNG luôn được giữ nguyên 100%.

    Nếu server Gemini Web2API không kết nối được, hàm RAISE lỗi ngay thay vì
    treo âm thầm (giống các hàm *_gemini_fastapi trong core/translate.py).
    """
    import requests

    if not segments:
        return []
    if not (0.0 <= keep_ratio <= 1.0):
        raise ValueError("keep_ratio phải nằm trong khoảng 0.0 - 1.0")

    base_url = (base_url or GEMINI_FASTAPI_DEFAULT_BASE_URL).strip()
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    try:
        from core.gemini_fastapi_server import check_server_health
        ok, health_msg = check_server_health(base_url, timeout=5.0)
        if progress_cb:
            progress_cb(0.0, f"Kiểm tra Gemini Web2API: {health_msg}")
        if not ok and "CHƯA CHẠY" in health_msg:
            raise RuntimeError(
                f"Gemini Web2API CHƯA CHẠY tại {base_url}. Hãy khởi động server "
                "(hoặc bật 'Tự khởi động Gemini Web2API cùng app') rồi thử lại."
            )
    except ImportError:
        pass

    variation_pct = int(round((1.0 - keep_ratio) * 100))
    keep_pct = 100 - variation_pct

    if char_budgets is not None:
        if len(char_budgets) != len(segments):
            raise ValueError("char_budgets phải có đúng số phần tử bằng số segments")
        system_prompt = (
            "You are a professional narration script editor. Your job is to rewrite each "
            "line to be CONCISE and NATURAL when spoken aloud, fitting a specific character "
            "budget per line, WITHOUT losing any meaning, facts, numbers, or names - a good "
            "editor removes filler and redundancy, never truncates a sentence mid-thought."
        )
    else:
        system_prompt = (
            "You are a professional script editor rewriting narration lines for "
            "content-uniqueness purposes (avoiding duplicate-content detection), "
            "while preserving 100% of the factual content."
        )

    def _call(prompt: str) -> str:
        resp = requests.post(
            url, headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=timeout,
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Gemini Web2API từ chối request (HTTP {resp.status_code}) - kiểm tra API Key."
            )
        if resp.status_code == 404:
            raise RuntimeError(f"HTTP 404 tại {url} - kiểm tra Base URL hoặc model '{model}'.")
        if not resp.ok:
            detail = _openai_compatible_error_detail(resp)
            raise RuntimeError(
                f"HTTP {resp.status_code} {resp.reason} tại {url}"
                + (f" - chi tiết từ server: {detail}" if detail else "")
            )
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""

    def _rewrite_batch(texts: List[str], budgets: Optional[List[int]] = None, depth: int = 0) -> List[str]:
        if not texts:
            return []
        if budgets is not None:
            numbered = SEP.join(
                f"[{i + 1}] (tối đa {b} ký tự) {t}" for i, (t, b) in enumerate(zip(texts, budgets))
            )
        else:
            numbered = SEP.join(f"[{i + 1}] {t}" for i, t in enumerate(texts))
        style_extra = ""
        if extra_style_notes and extra_style_notes.strip():
            style_extra = f"\nYêu cầu thêm (bắt buộc tuân theo):\n{extra_style_notes.strip()}\n"

        if budgets is not None:
            task_block = f"""
        Viết lại {len(texts)} câu phụ đề dưới đây, CÙNG NGÔN NGỮ ({language}),
        KHÔNG dịch sang ngôn ngữ khác.

        Mỗi câu đã kèm sẵn ngân sách ký tự tối đa (vd "(tối đa 45 ký tự)") - đây
        là số ký tự để câu đọc thành tiếng VỪA KHỚP khung giờ hình ảnh gốc của nó,
        KHÔNG nhanh KHÔNG chậm. Hãy VIẾT NGẮN GỌN, LOẠI BỎ từ đệm/thừa, GIỮ NGUYÊN
        toàn bộ ý nghĩa - đây là biên tập câu chữ cho súc tích, KHÔNG PHẢI cắt bớt
        cụt câu. Nếu 1 câu thực sự không thể ngắn hơn mà vẫn giữ trọn ý, được phép
        vượt ngân sách một chút (ưu tiên giữ NGHĨA hơn đúng tuyệt đối số ký tự)."""
        else:
            task_block = f"""
        Viết lại {len(texts)} câu phụ đề dưới đây, CÙNG NGÔN NGỮ ({language}),
        KHÔNG dịch sang ngôn ngữ khác.

        Mức độ biến tấu: giữ khoảng {keep_pct}% cách diễn đạt/từ ngữ gần bản gốc,
        thay đổi khoảng {variation_pct}% còn lại (đổi cấu trúc câu, dùng từ đồng
        nghĩa, đổi cách mở đầu/kết câu, đổi thứ tự mệnh đề trong câu) - miễn là
        câu văn vẫn tự nhiên, mượt mà khi đọc thành tiếng."""

        prompt = f"""
        ========================================================
        NHIỆM VỤ
        ========================================================
        {task_block}

        ========================================================
        PHẢI GIỮ NGUYÊN (không được vi phạm)
        ========================================================
        Giữ nguyên 100% sự kiện, số liệu, tên riêng, mốc thời gian, quan hệ
        nhân-quả như bản gốc. Không thêm, không bớt, không suy diễn thông tin
        mới. Không đổi thứ tự các câu (câu [1] vẫn là câu [1] sau khi viết lại).
        {style_extra}
        ========================================================
        ĐỊNH DẠNG TRẢ VỀ (BẮT BUỘC)
        ========================================================
        Trả về ĐÚNG {len(texts)} câu đã viết lại, phân cách bằng dòng riêng
        chứa đúng chuỗi: <<<SEG>>>
        KHÔNG đánh số thứ tự, KHÔNG ghi lại phần "(tối đa N ký tự)", KHÔNG thêm
        giải thích, KHÔNG thêm markdown.

        ========================================================
        CÁC CÂU CẦN VIẾT LẠI
        ========================================================
        {numbered}
        """

        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                raw = _call(prompt)
                parts = [p.strip() for p in raw.split("<<<SEG>>>")]
                parts = [p for p in parts if p.strip()]
                # Model đôi khi vẫn lỡ đánh số "[1] ..." dù đã dặn không làm - dọn sạch.
                import re as _re
                parts = [_re.sub(r"^\[\d+\]\s*", "", p).strip() for p in parts]
                if len(parts) == len(texts):
                    return parts
                last_err = ValueError(
                    f"Model trả về {len(parts)} câu, cần đúng {len(texts)} câu - thử lại."
                )
            except Exception as e:
                last_err = e
            if progress_cb:
                progress_cb(0.0, f"⚠ Lỗi viết lại lô (lần {attempt + 1}/{max_retries}): {last_err} - đang thử lại...")
            time.sleep(retry_delay * (attempt + 1))

        # Hết lượt thử mà vẫn lỗi/lệch số dòng - nếu lô chỉ có 1 câu thì không
        # còn cách chia nhỏ hơn, đành GIỮ NGUYÊN bản gốc cho câu đó (an toàn hơn
        # là làm hỏng thứ tự cả video). Nếu lô > 1 câu, chia đôi và thử lại từng
        # nửa (tương tự cơ chế fallback trong core/translate.py).
        if len(texts) == 1:
            if progress_cb:
                progress_cb(0.0, f"⚠ Bỏ qua 1 câu (giữ nguyên bản gốc) - lỗi cuối: {last_err}")
            return texts
        mid = len(texts) // 2
        if depth > 6:
            return texts
        b1 = budgets[:mid] if budgets is not None else None
        b2 = budgets[mid:] if budgets is not None else None
        return _rewrite_batch(texts[:mid], b1, depth + 1) + _rewrite_batch(texts[mid:], b2, depth + 1)

    out: List[SubtitleSegment] = []
    total = len(segments)
    total_batches = (total + batch_size - 1) // batch_size
    for b in range(total_batches):
        chunk = segments[b * batch_size: (b + 1) * batch_size]
        texts = [s.text.strip() for s in chunk]
        chunk_budgets = char_budgets[b * batch_size: (b + 1) * batch_size] if char_budgets is not None else None
        rewritten = _rewrite_batch(texts, chunk_budgets)
        for seg, new_text in zip(chunk, rewritten):
            out.append(replace(seg, text=new_text or seg.text))
        if progress_cb:
            progress_cb((b + 1) / total_batches, f"Đang viết lại lô {b + 1}/{total_batches}")
        if b < total_batches - 1:
            time.sleep(1.0)

    return out


def rewrite_segments_gemini_api(
    segments: List[SubtitleSegment],
    language: str,
    api_keys,
    model: str = DEFAULT_GEMINI_FASTAPI_MODEL,
    keep_ratio: float = 0.4,
    batch_size: int = 20,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    max_retries: int = 4,
    retry_delay: float = 2.0,
    extra_style_notes: Optional[str] = None,
    char_budgets: Optional[List[int]] = None,  # xem ghi chú ở rewrite_segments_gemini_fastapi phía trên -
    # cùng cơ chế: khi có, đổi mục đích prompt sang "viết ngắn gọn khớp nhịp đọc" thay vì "biến tấu".
) -> List[SubtitleSegment]:
    """
    Bản DÙNG THẲNG GEMINI API CHÍNH THỨC (Google, https://aistudio.google.com/apikey,
    package google-genai) của rewrite_segments_gemini_fastapi ở trên - CÙNG hành vi/
    prompt/format, chỉ khác cách gọi model: không cần chạy Gemini Web2API (server
    local wrap cookie web) nữa, gọi thẳng API bằng API key.

    HỖ TRỢ NHIỀU API KEY - truyền `api_keys` là 1 chuỗi (1 key) hoặc list nhiều key:
    XOAY VÒNG (round-robin) giữa các lô, tự động chuyển key kế tiếp nếu key đang
    dùng bị rate-limit (429/quota) hoặc bị từ chối (401/403) - giống hệt cơ chế
    trong core/translate.py:translate_segments_gemini.

    Cài đặt: pip install google-genai
    """
    try:
        from google import genai
    except ImportError as e:
        raise ImportError(
            "Cần cài đặt: pip install google-genai để viết lại bằng Gemini API."
        ) from e

    if not segments:
        return []
    if not (0.0 <= keep_ratio <= 1.0):
        raise ValueError("keep_ratio phải nằm trong khoảng 0.0 - 1.0")

    if isinstance(api_keys, str):
        api_keys = [api_keys]
    keys = [k.strip() for k in (api_keys or []) if k and k.strip()]
    if not keys:
        raise ValueError(
            "rewrite_segments_gemini_api cần ít nhất 1 Gemini API key (xem https://aistudio.google.com/apikey)"
        )

    _clients = {}

    def _client_for(key: str):
        if key not in _clients:
            _clients[key] = genai.Client(api_key=key)
        return _clients[key]

    variation_pct = int(round((1.0 - keep_ratio) * 100))
    keep_pct = 100 - variation_pct

    if char_budgets is not None:
        if len(char_budgets) != len(segments):
            raise ValueError("char_budgets phải có đúng số phần tử bằng số segments")
        system_prompt = (
            "You are a professional narration script editor. Your job is to rewrite each "
            "line to be CONCISE and NATURAL when spoken aloud, fitting a specific character "
            "budget per line, WITHOUT losing any meaning, facts, numbers, or names - a good "
            "editor removes filler and redundancy, never truncates a sentence mid-thought."
        )
    else:
        system_prompt = (
            "You are a professional script editor rewriting narration lines for "
            "content-uniqueness purposes (avoiding duplicate-content detection), "
            "while preserving 100% of the factual content."
        )

    _rr_state = {"idx": 0}

    def _call(prompt: str) -> str:
        """Gọi 1 lần tới Gemini, tự xoay vòng qua các key nếu key hiện tại lỗi/hết quota."""
        start = _rr_state["idx"]
        _rr_state["idx"] = (start + 1) % len(keys)
        last_err: Optional[Exception] = None
        full_prompt = f"{system_prompt}\n\n{prompt}"

        for offset in range(len(keys)):
            key_idx = (start + offset) % len(keys)
            key = keys[key_idx]
            try:
                resp = _client_for(key).models.generate_content(model=model, contents=full_prompt)
                return resp.text or ""
            except Exception as e:
                text = str(e).lower()
                is_quota = "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text
                is_auth = "401" in text or "403" in text or "permission" in text or "api key not valid" in text
                if is_quota or is_auth:
                    last_err = e
                    if progress_cb:
                        reason = "hết quota (429)" if is_quota else "bị từ chối (401/403 - sai key hoặc hết quyền)"
                        progress_cb(0.0, f"⚠ Gemini key #{key_idx + 1} {reason} - chuyển key kế tiếp...")
                    continue
                last_err = e
                continue

        raise RuntimeError(f"Cả {len(keys)} Gemini API key đều lỗi/hết quota. Lỗi cuối: {last_err}")

    def _rewrite_batch(texts: List[str], budgets: Optional[List[int]] = None, depth: int = 0) -> List[str]:
        if not texts:
            return []
        if budgets is not None:
            numbered = SEP.join(
                f"[{i + 1}] (tối đa {b} ký tự) {t}" for i, (t, b) in enumerate(zip(texts, budgets))
            )
        else:
            numbered = SEP.join(f"[{i + 1}] {t}" for i, t in enumerate(texts))
        style_extra = ""
        if extra_style_notes and extra_style_notes.strip():
            style_extra = f"\nYêu cầu thêm (bắt buộc tuân theo):\n{extra_style_notes.strip()}\n"

        if budgets is not None:
            task_block = f"""
        Viết lại {len(texts)} câu phụ đề dưới đây, CÙNG NGÔN NGỮ ({language}),
        KHÔNG dịch sang ngôn ngữ khác.

        Mỗi câu đã kèm sẵn ngân sách ký tự tối đa (vd "(tối đa 45 ký tự)") - đây
        là số ký tự để câu đọc thành tiếng VỪA KHỚP khung giờ hình ảnh gốc của nó,
        KHÔNG nhanh KHÔNG chậm. Hãy VIẾT NGẮN GỌN, LOẠI BỎ từ đệm/thừa, GIỮ NGUYÊN
        toàn bộ ý nghĩa - đây là biên tập câu chữ cho súc tích, KHÔNG PHẢI cắt bớt
        cụt câu. Nếu 1 câu thực sự không thể ngắn hơn mà vẫn giữ trọn ý, được phép
        vượt ngân sách một chút (ưu tiên giữ NGHĨA hơn đúng tuyệt đối số ký tự)."""
        else:
            task_block = f"""
        Viết lại {len(texts)} câu phụ đề dưới đây, CÙNG NGÔN NGỮ ({language}),
        KHÔNG dịch sang ngôn ngữ khác.

        Mức độ biến tấu: giữ khoảng {keep_pct}% cách diễn đạt/từ ngữ gần bản gốc,
        thay đổi khoảng {variation_pct}% còn lại (đổi cấu trúc câu, dùng từ đồng
        nghĩa, đổi cách mở đầu/kết câu, đổi thứ tự mệnh đề trong câu) - miễn là
        câu văn vẫn tự nhiên, mượt mà khi đọc thành tiếng."""

        prompt = f"""
        ========================================================
        NHIỆM VỤ
        ========================================================
        {task_block}

        ========================================================
        PHẢI GIỮ NGUYÊN (không được vi phạm)
        ========================================================
        Giữ nguyên 100% sự kiện, số liệu, tên riêng, mốc thời gian, quan hệ
        nhân-quả như bản gốc. Không thêm, không bớt, không suy diễn thông tin
        mới. Không đổi thứ tự các câu (câu [1] vẫn là câu [1] sau khi viết lại).
        {style_extra}
        ========================================================
        ĐỊNH DẠNG TRẢ VỀ (BẮT BUỘC)
        ========================================================
        Trả về ĐÚNG {len(texts)} câu đã viết lại, phân cách bằng dòng riêng
        chứa đúng chuỗi: <<<SEG>>>
        KHÔNG đánh số thứ tự, KHÔNG ghi lại phần "(tối đa N ký tự)", KHÔNG thêm
        giải thích, KHÔNG thêm markdown.

        ========================================================
        CÁC CÂU CẦN VIẾT LẠI
        ========================================================
        {numbered}
        """

        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                raw = _call(prompt)
                parts = [p.strip() for p in raw.split("<<<SEG>>>")]
                parts = [p for p in parts if p.strip()]
                import re as _re
                parts = [_re.sub(r"^\[\d+\]\s*", "", p).strip() for p in parts]
                if len(parts) == len(texts):
                    return parts
                last_err = ValueError(
                    f"Model trả về {len(parts)} câu, cần đúng {len(texts)} câu - thử lại."
                )
            except Exception as e:
                last_err = e
            if progress_cb:
                progress_cb(0.0, f"⚠ Lỗi viết lại lô (lần {attempt + 1}/{max_retries}): {last_err} - đang thử lại...")
            time.sleep(retry_delay * (attempt + 1))

        if len(texts) == 1:
            if progress_cb:
                progress_cb(0.0, f"⚠ Bỏ qua 1 câu (giữ nguyên bản gốc) - lỗi cuối: {last_err}")
            return texts
        mid = len(texts) // 2
        if depth > 6:
            return texts
        b1 = budgets[:mid] if budgets is not None else None
        b2 = budgets[mid:] if budgets is not None else None
        return _rewrite_batch(texts[:mid], b1, depth + 1) + _rewrite_batch(texts[mid:], b2, depth + 1)

    out: List[SubtitleSegment] = []
    total = len(segments)
    total_batches = (total + batch_size - 1) // batch_size
    for b in range(total_batches):
        chunk = segments[b * batch_size: (b + 1) * batch_size]
        texts = [s.text.strip() for s in chunk]
        chunk_budgets = char_budgets[b * batch_size: (b + 1) * batch_size] if char_budgets is not None else None
        rewritten = _rewrite_batch(texts, chunk_budgets)
        for seg, new_text in zip(chunk, rewritten):
            out.append(replace(seg, text=new_text or seg.text))
        if progress_cb:
            progress_cb((b + 1) / total_batches, f"Đang viết lại lô {b + 1}/{total_batches}")
        if b < total_batches - 1:
            time.sleep(1.0)

    return out


# --------------------------------------------------------------------------
# BƯỚC 3+4: tính lại thời lượng đọc theo văn bản MỚI, cân chỉnh timestamp, và
# nén bớt khoảng lặng quá dài giữa các câu (không đụng audio/video - chỉ SRT).
# --------------------------------------------------------------------------

def retime_segments(
    segments: List[SubtitleSegment],
    language: str,
    speech_rate: str = "+0%",
    cps_override: Optional[float] = None,
    min_gap_sec: float = 0.12,
    max_gap_sec: float = 1.2,
    keep_original_start: bool = True,
    total_duration_sec: Optional[float] = None,  # MỚI: trần cứng - tổng thời lượng video/audio gốc
    # (giây). Nếu đặt, hàm đảm bảo TOÀN BỘ timeline mới (kể cả câu cuối cùng) KHÔNG BAO GIỜ vượt
    # quá mốc này. Không có tham số này (giá trị mặc định None, hành vi CŨ, dùng cho CLI đứng độc
    # lập không có video), hàm chỉ nối tuần tự KHÔNG kiểm tra trần - với văn bản viết lại (đặc biệt
    # keep_ratio thấp, biến tấu mạnh -> câu thường DÀI hơn câu gốc), độ lệch nhỏ ở mỗi câu CỘNG DỒN
    # qua hàng chục câu, khiến các câu VỀ CUỐI bị đẩy vượt xa khung giờ video thật - lúc đó bước
    # fit_segments_to_timing/TTS phía sau (bị ràng buộc bởi video CÓ THẬT, độ dài cố định) mới phát
    # hiện ra và phải dồn ép/cắt gấp gáp CHỈ ở các câu cuối - nghe "đầu chậm rãi, cuối dồn dập/cụt
    # chữ" rất khó chịu. Có total_duration_sec, hàm tự NÉN ĐỀU cho MỌI câu ngay từ bước này, theo
    # đúng 2 mức ưu tiên: (1) nén khoảng nghỉ trước (không đụng tốc độ đọc), (2) chỉ khi nén hết
    # khoảng nghỉ vẫn không đủ mới nén ĐỀU tốc độ đọc của TẤT CẢ câu theo CÙNG 1 hệ số - để nhịp đọc
    # đều xuyên suốt cả video, không có đoạn nào bị xử ép riêng.
) -> List[SubtitleSegment]:
    """
    Đi tuần tự qua từng câu, đặt lại (start, end) theo THỜI LƯỢNG ĐỌC THẬT của
    văn bản MỚI (ước lượng bằng core/text_fit.py:estimate_duration_sec), đồng
    thời NÉN các khoảng lặng giữa 2 câu về tối đa `max_gap_sec` (nếu khoảng
    lặng gốc dài hơn - "khoảng lặng thừa") và đảm bảo tối thiểu `min_gap_sec`
    (tránh 2 câu dính sát/đè lên nhau khi câu trước bị kéo dài).

    keep_original_start=True: câu ĐẦU TIÊN giữ nguyên timestamp start gốc (hữu
    ích nếu SRT này vẫn cần khớp với video gốc từ giây 0); =False thì câu đầu
    bắt đầu từ 0s (dùng khi SRT không đi kèm video nào, chỉ cần timing NỘI BỘ
    hợp lý giữa các câu với nhau).
    """
    if not segments:
        return []

    n = len(segments)
    start0 = segments[0].start if keep_original_start else 0.0

    # Khoảng nghỉ "mong muốn" cho từng cặp câu liên tiếp (dựa theo khoảng lặng THẬT giữa
    # các cue gốc, cùng công thức như bản gốc - min/max_gap_sec).
    wanted_gaps = []
    for i in range(1, n):
        original_gap = segments[i].start - segments[i - 1].end
        capped = min(max(original_gap, 0.0), max_gap_sec) if original_gap > 0 else 0.0
        wanted_gaps.append(max(capped, min_gap_sec))

    natural_durs = [
        max(estimate_duration_sec(seg.text, language, speech_rate=speech_rate, cps_override=cps_override), 0.5)
        for seg in segments
    ]

    gaps = wanted_gaps
    durs = natural_durs

    if total_duration_sec is not None:
        budget = max(0.0, total_duration_sec - start0)
        total_gap_wanted = sum(wanted_gaps)
        total_dur_natural = sum(natural_durs)

        if total_dur_natural + total_gap_wanted > budget:
            # BƯỚC 1 - nén khoảng nghỉ trước (không đụng tốc độ đọc/chữ nghĩa gì cả).
            min_gap_total = min_gap_sec * (n - 1) if n > 1 else 0.0
            if total_dur_natural + min_gap_total <= budget:
                # Đủ chỗ nếu nén hết khoảng nghỉ về min_gap_sec -> rải đều phần dư (nếu có)
                # cho các khoảng nghỉ, KHÔNG cần đụng tới tốc độ đọc của bất kỳ câu nào.
                extra = budget - total_dur_natural - min_gap_total
                extra_each = extra / (n - 1) if n > 1 else 0.0
                gaps = [min_gap_sec + extra_each for _ in wanted_gaps]
                durs = natural_durs
            else:
                # BƯỚC 2 - nén hết khoảng nghỉ (về đúng min_gap_sec) VẪN không đủ chỗ -> nén
                # ĐỀU tốc độ đọc của TẤT CẢ các câu theo CÙNG 1 hệ số (không riêng câu nào bị
                # xử ép nặng hơn câu khác - nhịp đọc đều xuyên suốt, dù nhanh hơn bình thường).
                gaps = [min_gap_sec for _ in wanted_gaps]
                budget_for_durs = max(0.0, budget - min_gap_total)
                scale = (budget_for_durs / total_dur_natural) if total_dur_natural > 0 else 1.0
                durs = [max(0.3, d * scale) for d in natural_durs]

    out: List[SubtitleSegment] = []
    cursor = start0
    for i, seg in enumerate(segments):
        new_start = cursor if i == 0 else cursor + gaps[i - 1]
        new_end = new_start + durs[i]
        out.append(replace(seg, start=new_start, end=new_end))
        cursor = new_end

    return out


# --------------------------------------------------------------------------
# HÀM TỔNG: chạy trọn pipeline SRT gốc -> SRT mới.
# --------------------------------------------------------------------------

def rewrite_srt_file(
    srt_path: str,
    out_path: str,
    language: str,
    base_url: str = GEMINI_FASTAPI_DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    model: str = DEFAULT_GEMINI_FASTAPI_MODEL,
    keep_ratio: float = 0.4,
    speech_rate: str = "+0%",
    cps_override: Optional[float] = None,
    min_gap_sec: float = 0.12,
    max_gap_sec: float = 1.2,
    keep_original_start: bool = True,
    total_duration_sec: Optional[float] = None,  # MỚI - xem ghi chú ở retime_segments() bên trên
    extra_style_notes: Optional[str] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> str:
    """Chạy trọn: đọc `srt_path` -> phân tích -> viết lại (biến tấu, cùng ngôn
    ngữ) -> cân chỉnh timestamp + nén khoảng lặng thừa -> lưu ra `out_path`.
    Trả về `out_path`."""

    def _cb(pct: float, msg: str):
        if progress_cb:
            progress_cb(pct, msg)

    _cb(0.0, f"Đang đọc {srt_path}...")
    segments = parse_srt(srt_path)

    _cb(0.02, f"Đã đọc {len(segments)} câu - đang phân tích độ dài...")
    analyze_segment_lengths(segments, language)  # chỉ để log/debug nếu cần, không bắt buộc dùng kết quả

    def _rewrite_progress(pct: float, msg: str):
        _cb(0.05 + pct * 0.80, msg)

    rewritten = rewrite_segments_gemini_fastapi(
        segments, language, base_url=base_url, api_key=api_key, model=model,
        keep_ratio=keep_ratio, progress_cb=_rewrite_progress, extra_style_notes=extra_style_notes,
    )

    _cb(0.90, "Đang cân chỉnh timestamp + nén khoảng lặng thừa...")
    retimed = retime_segments(
        rewritten, language, speech_rate=speech_rate, cps_override=cps_override,
        min_gap_sec=min_gap_sec, max_gap_sec=max_gap_sec, keep_original_start=keep_original_start,
        total_duration_sec=total_duration_sec,
    )

    # Đánh lại index tuần tự 1..N cho SRT hợp lệ (viết lại có thể đã fallback
    # giữ nguyên vài câu lỗi, index gốc không còn ý nghĩa thứ tự liên tục).
    retimed = [replace(seg, index=i + 1) for i, seg in enumerate(retimed)]

    _cb(0.95, f"Đang lưu {out_path}...")
    save_srt(retimed, out_path)
    _cb(1.0, f"Hoàn tất - đã xuất {out_path}")
    return out_path
