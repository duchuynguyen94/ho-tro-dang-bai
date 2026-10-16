"""Chỉnh sửa ảnh bằng AI (Gemini Image / OpenAI Images / fal.ai)."""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import httpx

from ..config import output_dir
from ..ai.providers import http_error_vi
from ..storage import crypto
from ..storage.models import new_id


class AIEditError(RuntimeError):
    pass


def _read_b64(path: str) -> tuple[str, str]:
    p = Path(path)
    data = p.read_bytes()
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return base64.b64encode(data).decode("ascii"), mime


def _save_bytes(data: bytes, suffix: str = ".png") -> str:
    out = output_dir() / f"ai_{new_id()}{suffix}"
    out.write_bytes(data)
    return str(out)


# --------------------------------------------------------------------------- #
# Gemini Image (nano banana)
# --------------------------------------------------------------------------- #
def _gemini_models(api_key: str) -> list[str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    r = httpx.get(url, timeout=30)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        name = str(m.get("name", "")).replace("models/", "")
        if "image" in name.lower() and "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append(name)
    return out


def _gemini_edit_once(image_path: str, prompt: str, api_key: str, model: str) -> bytes | None:
    b64, mime = _read_b64(image_path)
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]
            }
        ]
    }
    r = httpx.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=180)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise AIEditError(http_error_vi(r.status_code, r.text, "Gemini Image"))
    data = r.json()
    for cand in data.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            inline = part.get("inline_data") or part.get("inlineData") or {}
            if inline.get("data"):
                return base64.b64decode(inline["data"])
    raise AIEditError("Gemini không trả về ảnh.")


def _gemini_edit(image_path: str, prompt: str, api_key: str, model: str) -> str:
    if not api_key:
        raise AIEditError("Chưa có API key cho Gemini.")
    model = model or "gemini-3.8-flash-image"
    out = _gemini_edit_once(image_path, prompt, api_key, model)
    if out is None:
        for cand in _gemini_models(api_key):
            out = _gemini_edit_once(image_path, prompt, api_key, cand)
            if out:
                break
    if not out:
        raise AIEditError(
            f"Model “{model}” không còn khả dụng. Vào Cấu hình → AI ảnh để đổi model."
        )
    return _save_bytes(out, ".png")


# --------------------------------------------------------------------------- #
# OpenAI Images
# --------------------------------------------------------------------------- #
def _openai_edit(image_path: str, prompt: str, api_key: str, model: str) -> str:
    if not api_key:
        raise AIEditError("Chưa có API key cho OpenAI.")
    with open(image_path, "rb") as fh:
        files = {"image": (Path(image_path).name, fh, "image/png")}
        data = {"model": model or "gpt-image-1", "prompt": prompt, "size": "1024x1024"}
        r = httpx.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files=files,
            timeout=240,
        )
    if r.status_code >= 400:
        raise AIEditError(http_error_vi(r.status_code, r.text, "OpenAI Images"))
    item = (r.json().get("data") or [{}])[0]
    if item.get("b64_json"):
        return _save_bytes(base64.b64decode(item["b64_json"]), ".png")
    if item.get("url"):
        img = httpx.get(item["url"], timeout=120)
        img.raise_for_status()
        return _save_bytes(img.content, ".png")
    raise AIEditError("OpenAI không trả về ảnh.")


# --------------------------------------------------------------------------- #
# fal.ai (Flux Kontext)
# --------------------------------------------------------------------------- #
def _fal_edit(image_path: str, prompt: str, api_key: str, model: str) -> str:
    if not api_key:
        raise AIEditError("Chưa có API key cho fal.ai.")
    b64, mime = _read_b64(image_path)
    r = httpx.post(
        f"https://fal.run/{model or 'fal-ai/flux-kontext/dev'}",
        headers={"Authorization": f"Key {api_key}", "Content-Type": "application/json"},
        json={"prompt": prompt, "image_url": f"data:{mime};base64,{b64}"},
        timeout=240,
    )
    if r.status_code >= 400:
        raise AIEditError(http_error_vi(r.status_code, r.text, "fal.ai"))
    images = r.json().get("images") or []
    if images and images[0].get("url"):
        img = httpx.get(images[0]["url"], timeout=120)
        img.raise_for_status()
        return _save_bytes(img.content, ".png")
    raise AIEditError("fal.ai không trả về ảnh.")


# --------------------------------------------------------------------------- #
def edit_image(store, image_path: str, prompt: str, log=None) -> str:
    cfg = store.ai_image
    active = cfg.get("active", "gemini")
    pcfg = (cfg.get("providers") or {}).get(active, {})
    api_key = crypto.decrypt(pcfg.get("api_key_enc", ""))
    model = pcfg.get("model", "")

    if active == "off":
        raise AIEditError("AI chỉnh ảnh đang tắt (Cấu hình → AI ảnh).")
    if log:
        log(f"Đang gọi {active} để sửa ảnh…")

    if active == "gemini":
        path = _gemini_edit(image_path, prompt, api_key, model)
    elif active == "openai":
        path = _openai_edit(image_path, prompt, api_key, model)
    elif active == "fal":
        path = _fal_edit(image_path, prompt, api_key, model)
    else:
        raise AIEditError(f"Provider ảnh không hỗ trợ: {active}")

    if log:
        log("Đã sửa ảnh xong.")
    return path
