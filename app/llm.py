import base64
import logging
from typing import Any

import requests

from . import config

log = logging.getLogger(__name__)


class LlmError(Exception):
    pass


def chat(system: str, user_parts: list[dict[str, Any]]) -> str:
    """Single-turn chat call.

    `user_parts` is a list of normalized parts:
      {"type": "text", "text": "..."}
      {"type": "image", "data": bytes, "media_type": "image/jpeg"}
    """
    provider = config.LLM_PROVIDER
    if provider == "lmstudio":
        return _call_lmstudio(system, user_parts)
    if provider == "anthropic":
        return _call_anthropic(system, user_parts)
    raise LlmError(f"Unknown LLM_PROVIDER: {provider!r}")


def _call_lmstudio(system: str, user_parts: list[dict[str, Any]]) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [_lmstudio_part(p) for p in user_parts]},
    ]
    body = {
        "model": config.LM_STUDIO_MODEL,
        "messages": messages,
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
    }
    data = _post(config.LM_STUDIO_URL, {"Content-Type": "application/json"}, body)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LlmError(f"Unexpected LM Studio response shape: {e}: {data}")


def _lmstudio_part(part: dict[str, Any]) -> dict[str, Any]:
    if part["type"] == "text":
        return {"type": "text", "text": part["text"]}
    if part["type"] == "image":
        b64 = base64.b64encode(part["data"]).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{part['media_type']};base64,{b64}"},
        }
    raise LlmError(f"Unknown part type: {part['type']!r}")


def _call_anthropic(system: str, user_parts: list[dict[str, Any]]) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise LlmError("ANTHROPIC_API_KEY not set")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": config.ANTHROPIC_API_VERSION,
    }
    body = {
        "model": config.ANTHROPIC_MODEL,
        "system": system,
        "messages": [{"role": "user", "content": [_anthropic_part(p) for p in user_parts]}],
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
    }
    data = _post(config.ANTHROPIC_URL, headers, body)
    try:
        return data["content"][0]["text"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LlmError(f"Unexpected Anthropic response shape: {e}: {data}")


def _anthropic_part(part: dict[str, Any]) -> dict[str, Any]:
    if part["type"] == "text":
        return {"type": "text", "text": part["text"]}
    if part["type"] == "image":
        b64 = base64.b64encode(part["data"]).decode("ascii")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": part["media_type"],
                "data": b64,
            },
        }
    raise LlmError(f"Unknown part type: {part['type']!r}")


def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    log.info("LLM POST %s", url)
    try:
        resp = requests.post(
            url, headers=headers, json=body, timeout=(10, config.LLM_READ_TIMEOUT)
        )
    except requests.RequestException as e:
        raise LlmError(f"LLM HTTP error calling {url}: {e}")
    if resp.status_code >= 300:
        raise LlmError(f"LLM endpoint {url} returned {resp.status_code}: {resp.text}")
    return resp.json()
