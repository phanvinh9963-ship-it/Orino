"""
core/llm_shorten.py
Rút gọn (viết lại NGẮN HƠN, có nghĩa) 1 câu phụ đề/lời dẫn bằng LLM - dùng khi
core/text_fit.py:fit_segments_to_timing ước lượng giọng đọc TTS sẽ đọc lâu hơn
khoảng trống thời gian gốc của câu đó.

Khác với core/text_fit.py:shorten_text_rule_based (cắt cơ học theo ký tự, dễ cắt
cụt ý giữa chừng), hàm ở đây gọi LLM để VIẾT LẠI câu ngắn hơn nhưng vẫn giữ đúng
thông tin/ý nghĩa - nghe tự nhiên hơn nhiều khi lồng tiếng.

Dùng Gemini Web2API (server local, wrap Gemini qua cookie web, endpoint
OpenAI-compatible '/v1/chat/completions') - CÙNG server/base_url/model mà
core/translate.py:translate_segments_gemini_fastapi đang dùng cho bước dịch,
không cần thêm API key trả phí riêng.
"""
from __future__ import annotations
from typing import Callable, Optional


def make_gemini_fastapi_shorten_fn(
    base_url: str,
    api_key: Optional[str] = None,
    model: str = "gemini-3.6-flash",
    timeout: float = 30.0,
    max_retries: int = 2,
) -> Callable[[str, str, int], str]:
    """
    Trả về 1 hàm (text, lang, target_chars) -> str để truyền vào
    core/text_fit.py:fit_segments_to_timing(llm_shorten_fn=...).

    QUAN TRỌNG VỀ LỖI: hàm trả về được (closure) KHÔNG BAO GIỜ raise ra ngoài -
    bất kỳ lỗi nào (server Gemini Web2API chưa chạy, mất mạng, model từ chối,
    response rỗng...) đều được nuốt và trả lại CHÍNH văn bản gốc chưa rút gọn.
    core/text_fit.py khi thấy hàm trả về vẫn dài hơn target_chars sẽ tự động rơi
    xuống shorten_text_rule_based cho đúng câu đó - một câu lỗi không làm hỏng
    hay làm chậm cả video.
    """
    if not base_url or not base_url.strip():
        raise ValueError("make_gemini_fastapi_shorten_fn cần base_url (vd http://127.0.0.1:8000)")

    base_url = base_url.strip()
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    def _shorten(text: str, lang: str, target_chars: int) -> str:
        import requests

        text = (text or "").strip()
        if not text or target_chars <= 0 or len(text) <= target_chars:
            return text

        prompt = (
            f"Viết lại câu thoại sau bằng ngôn ngữ {lang}, NGẮN HƠN, tối đa khoảng "
            f"{target_chars} ký tự (tính cả dấu câu/khoảng trắng). Bắt buộc:\n"
            f"- Giữ nguyên toàn bộ thông tin/ý nghĩa/số liệu/tên riêng quan trọng, "
            f"không bịa thêm, không bỏ sót ý chính.\n"
            f"- Đọc lên vẫn phải là 1 câu trọn vẹn, tự nhiên như người bản xứ nói "
            f"(paraphrase thật sự, không phải văn dịch máy, không cắt cụt giữa chừng).\n"
            f"- CHỈ trả về đúng câu đã viết lại. Không giải thích, không đóng ngoặc "
            f"kép, không markdown, không thêm ghi chú/tiêu đề gì khác.\n\n"
            f"Câu gốc: {text}"
        )

        last_err: Optional[Exception] = None
        for _attempt in range(max_retries):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Bạn là biên tập viên viết lại lời thoại video ngắn gọn, tự nhiên, giữ nguyên ý nghĩa gốc.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                    },
                    timeout=timeout,
                )
                resp.raise_for_status()
                out = (resp.json()["choices"][0]["message"]["content"] or "").strip()
                # Gemini đôi khi bọc câu trả lời trong dấu ngoặc kép hoặc markdown ```..```
                out = out.strip("`").strip()
                if out.startswith('"') and out.endswith('"') and len(out) >= 2:
                    out = out[1:-1].strip()
                if out:
                    return out
                last_err = ValueError("Gemini Web2API trả về nội dung rỗng")
            except Exception as e:
                last_err = e

        # Hết số lần thử - trả lại nguyên văn gốc, để text_fit tự rơi xuống rule-based.
        return text

    return _shorten


def make_gemini_webapi_shorten_fn(
    secure_1psid: str,
    secure_1psidts: Optional[str] = None,
    proxy: Optional[str] = None,
    model: str = "gemini-3-flash",
    timeout: float = 60.0,
    max_retries: int = 2,
) -> Callable[[str, str, int], str]:
    """
    Bản "Gemini API master" (gemini_webapi, đăng nhập bằng cookie - xem
    core/gemini_webapi_client.py) của make_gemini_fastapi_shorten_fn ở trên: trả về
    1 hàm (text, lang, target_chars) -> str để truyền vào
    core/text_fit.py:fit_segments_to_timing(llm_shorten_fn=...).

    Dùng khi translation_method="gemini_webapi" - tái sử dụng ĐÚNG cookie/model đã
    cấu hình cho bước dịch, không cần thêm cấu hình riêng.

    QUAN TRỌNG VỀ LỖI: hàm trả về được (closure) KHÔNG BAO GIỜ raise ra ngoài - mọi
    lỗi (cookie hết hạn, mất mạng, model từ chối, response rỗng...) đều được nuốt và
    trả lại CHÍNH văn bản gốc chưa rút gọn, để text_fit tự rơi xuống rule-based cho
    đúng câu đó.
    """
    if not secure_1psid or not secure_1psid.strip():
        raise ValueError("make_gemini_webapi_shorten_fn cần secure_1psid (cookie __Secure-1PSID)")

    secure_1psid = secure_1psid.strip()

    def _shorten(text: str, lang: str, target_chars: int) -> str:
        from core.gemini_webapi_client import generate_text

        text = (text or "").strip()
        if not text or target_chars <= 0 or len(text) <= target_chars:
            return text

        prompt = (
            f"Viết lại câu thoại sau bằng ngôn ngữ {lang}, NGẮN HƠN, tối đa khoảng "
            f"{target_chars} ký tự (tính cả dấu câu/khoảng trắng). Bắt buộc:\n"
            f"- Giữ nguyên toàn bộ thông tin/ý nghĩa/số liệu/tên riêng quan trọng, "
            f"không bịa thêm, không bỏ sót ý chính.\n"
            f"- Đọc lên vẫn phải là 1 câu trọn vẹn, tự nhiên như người bản xứ nói "
            f"(paraphrase thật sự, không phải văn dịch máy, không cắt cụt giữa chừng).\n"
            f"- CHỈ trả về đúng câu đã viết lại. Không giải thích, không đóng ngoặc "
            f"kép, không markdown, không thêm ghi chú/tiêu đề gì khác.\n\n"
            f"Câu gốc: {text}"
        )

        try:
            out = generate_text(
                prompt,
                secure_1psid=secure_1psid, secure_1psidts=secure_1psidts, proxy=proxy,
                model=model,
                system_prompt="Bạn là biên tập viên viết lại lời thoại video ngắn gọn, tự nhiên, giữ nguyên ý nghĩa gốc.",
                timeout=timeout, max_retries=max_retries,
            )
            out = (out or "").strip().strip("`").strip()
            if out.startswith('"') and out.endswith('"') and len(out) >= 2:
                out = out[1:-1].strip()
            if out:
                return out
        except Exception:
            pass

        return text

    return _shorten
