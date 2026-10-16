"""Các nhà cung cấp AI viết nội dung."""
from __future__ import annotations

import json
from typing import Any

import httpx

UA = {"User-Agent": "Mozilla/5.0 (WP Multi Poster)"}
TIMEOUT = 90


class AIError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Dịch lỗi HTTP của nhà cung cấp sang tiếng Việt cho người dùng hiểu
# --------------------------------------------------------------------------- #
STATUS_VI = {
    400: "Yêu cầu gửi lên không hợp lệ",
    401: "API key không hợp lệ",
    403: "Không có quyền truy cập (kiểm tra API key / khu vực)",
    404: "Không tìm thấy model này",
    408: "Máy chủ AI phản hồi quá chậm",
    413: "Nội dung gửi lên quá lớn",
    422: "Dữ liệu gửi lên không đúng định dạng",
    429: "Đã hết hạn mức / gửi quá nhiều yêu cầu",
    500: "Máy chủ AI bị lỗi nội bộ",
    502: "Kết nối tới máy chủ AI bị lỗi",
    503: "Máy chủ AI đang QUÁ TẢI",
    504: "Máy chủ AI phản hồi quá lâu",
}

STATUS_HINT = {
    429: "Chờ hạn mức làm mới (hoặc đổi model/provider khác) rồi thử lại.",
    500: "Lỗi tạm thời phía nhà cung cấp — thử lại sau ít phút.",
    502: "Lỗi tạm thời — thử lại sau ít phút.",
    503: "Thường chỉ tạm thời — thử lại sau ít phút.",
    504: "Thử lại sau ít phút.",
    401: "Vào Cài đặt → AI nội dung để kiểm tra lại API key.",
    403: "Vào Cài đặt → AI nội dung để kiểm tra lại API key.",
}


def _extract_provider_message(body: str) -> str:
    """Lấy câu mô tả gốc của nhà cung cấp (nếu có) để hiện kèm."""
    if not body:
        return ""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"]).strip()
        for key in ("message", "detail", "error"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key].strip()
    return ""


def http_error_vi(status: int, body: str = "", who: str = "") -> str:
    """Câu báo lỗi tiếng Việt cho mã HTTP của nhà cung cấp AI."""
    base = STATUS_VI.get(status) or f"Máy chủ AI trả về mã lỗi {status}"
    head = f"{who}: " if who else ""
    text = f"{head}{base} (mã {status})."
    hint = STATUS_HINT.get(status)
    if hint:
        text += f" {hint}"
    # chỉ kèm mô tả gốc khi lỗi liên quan tới DỮ LIỆU gửi lên (các mã khác đã đủ rõ bằng tiếng Việt)
    if status not in STATUS_VI or status in (400, 404, 422):
        detail = _extract_provider_message(body)
        if detail and detail.lower() not in text.lower():
            text += f"\nChi tiết từ nhà cung cấp: {detail[:300]}"
    return text


def network_error_vi(exc: Exception, who: str = "") -> str:
    head = f"{who}: " if who else ""
    name = type(exc).__name__
    if "Timeout" in name:
        return (f"{head}Không kết nối được tới máy chủ AI (quá thời gian chờ). "
                "Kiểm tra mạng rồi thử lại.")
    return (f"{head}Không kết nối được tới máy chủ AI ({name}). Kiểm tra mạng rồi thử lại.")


# --------------------------------------------------------------------------- #
# OpenAI-compatible (Groq, OpenRouter, OpenAI, Ollama)
# --------------------------------------------------------------------------- #
def _openai_compatible(base_url: str, model: str, prompt: str, api_key: str) -> str:
    headers = {"Content-Type": "application/json", **UA}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý viết nội dung tiếng Việt, trả về JSON hợp lệ."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
    }
    try:
        r = httpx.post(base_url, json=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise AIError(network_error_vi(exc, "AI")) from exc
    if r.status_code >= 400:
        raise AIError(http_error_vi(r.status_code, r.text, "AI"))
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover
        raise AIError(f"Phản hồi không hợp lệ: {str(data)[:200]}") from exc


def _gemini_models(api_key: str) -> list[str]:
    """Danh sách model Gemini khả dụng cho key này."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    r = httpx.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    out: list[str] = []
    for m in r.json().get("models", []):
        name = str(m.get("name", "")).replace("models/", "")
        methods = m.get("supportedGenerationMethods") or []
        if "generateContent" in methods and "embedding" not in name and "aqa" not in name:
            out.append(name)
    return out


def _gemini_call(model: str, prompt: str, api_key: str):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"},
    }
    return httpx.post(url, json=body, headers={"Content-Type": "application/json", **UA}, timeout=TIMEOUT)


def _gemini_text(resp) -> str:
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"] or ""
    except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover
        raise AIError(f"Phản hồi không hợp lệ: {str(data)[:200]}") from exc


def _gemini(model: str, prompt: str, api_key: str) -> str:
    if not api_key:
        raise AIError("Chưa có API key cho Gemini.")
    model = model or "gemini-3.8-flash"
    try:
        r = _gemini_call(model, prompt, api_key)
    except httpx.HTTPError as exc:
        raise AIError(network_error_vi(exc, "Gemini")) from exc

    # Model không còn khả dụng -> tự dò model khác đang hoạt động
    if r.status_code == 404:
        tried: list[str] = []
        try:
            for cand in _gemini_models(api_key):
                low = cand.lower()
                if "flash" not in low or "image" in low or "embedding" in low or "tts" in low:
                    continue
                tried.append(cand)
                r2 = _gemini_call(cand, prompt, api_key)
                if r2.status_code < 400:
                    return _gemini_text(r2)
        except Exception:
            pass
        hint = f" Model đang hoạt động: {', '.join(tried[:5])}." if tried else ""
        raise AIError(
            f"Model “{model}” không còn khả dụng (404). "
            f"Vào Cài đặt → AI nội dung để đổi model.{hint}"
        )

    if r.status_code >= 400:
        raise AIError(http_error_vi(r.status_code, r.text, "Gemini"))
    return _gemini_text(r)


# --------------------------------------------------------------------------- #
# Điều phối
# --------------------------------------------------------------------------- #
def generate_text(provider: str, cfg: dict[str, Any], prompt: str, api_key: str = "") -> str:
    provider = (provider or "").lower()
    model = cfg.get("model", "")

    if provider == "gemini":
        return _gemini(model or "gemini-2.5-flash", prompt, api_key)
    if provider == "groq":
        return _openai_compatible(
            "https://api.groq.com/openai/v1/chat/completions",
            model or "llama-3.3-70b-versatile", prompt, api_key,
        )
    if provider == "openai":
        return _openai_compatible(
            "https://api.openai.com/v1/chat/completions",
            model or "gpt-4o-mini", prompt, api_key,
        )
    if provider == "deepseek":
        return _openai_compatible(
            "https://api.deepseek.com/chat/completions",
            model or "deepseek-chat", prompt, api_key,
        )
    if provider == "ollama":
        base = (cfg.get("base_url") or "http://localhost:11434").rstrip("/")
        return _openai_compatible(
            f"{base}/v1/chat/completions", model or "qwen2.5:7b", prompt, api_key=""
        )
    if provider == "chatgpt":
        raise AIError("Provider ChatGPT (qua trình duyệt) chưa được bật trong bản này.")
    raise AIError(f"Provider không hỗ trợ: {provider}")


def parse_json_response(text: str) -> dict:
    """Trích JSON từ phản hồi AI (chấp nhận bọc trong ```json ... ```)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)
