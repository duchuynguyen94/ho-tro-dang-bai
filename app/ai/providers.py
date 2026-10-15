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
# OpenAI-compatible (Groq, OpenRouter, OpenAI, Ollama)
# --------------------------------------------------------------------------- #
def _openai_compatible(base_url: str, model: str, prompt: str, api_key: str) -> str:
    headers = {"Content-Type": "application/json", **UA}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://localhost"
        headers["X-Title"] = "Ho Tro Dang Bai"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý viết nội dung tiếng Việt, trả về JSON hợp lệ."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
    }
    r = httpx.post(base_url, json=body, headers=headers, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise AIError(f"{base_url} trả về {r.status_code}: {r.text[:200]}")
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
    r = _gemini_call(model, prompt, api_key)

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
            f"Vào Cấu hình → AI nội dung để đổi model.{hint}"
        )

    if r.status_code >= 400:
        raise AIError(f"Gemini trả về {r.status_code}: {r.text[:200]}")
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
    if provider == "openrouter":
        return _openai_compatible(
            "https://openrouter.ai/api/v1/chat/completions",
            model or "meta-llama/llama-3.3-70b-instruct:free", prompt, api_key,
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
