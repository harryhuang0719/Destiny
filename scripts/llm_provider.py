"""Explicit, auditable adapters for Destiny's optional external LLM providers."""

from __future__ import annotations

import math
import os
from typing import Any
from urllib.parse import urlparse

try:
    import httpx

    HAS_HTTPX = True
except ImportError:  # pragma: no cover - covered in clean-room doctor checks
    httpx = None
    HAS_HTTPX = False


ALLOWED_ENV_KEYS = {
    "MINIMAX_API_KEY",
    "MINIMAX_API_URL",
    "MINIMAX_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_URL",
    "DEEPSEEK_MODEL",
    "CUSTOM_API_KEY",
    "CUSTOM_API_BASE",
    "CUSTOM_MODEL",
    "DESTINY_LLM_TIMEOUT",
}


def _extract_minimax(data: dict[str, Any]) -> str:
    return "\n".join(
        block.get("text", "").strip()
        for block in data.get("content", [])
        if block.get("type") == "text" and block.get("text")
    ).strip()


def _extract_openai_compatible(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    # Do not expose a provider's hidden reasoning when final content is empty.
    return (message.get("content") or "").strip()


def _validated_https_url(url: str, provider: str, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{provider} endpoint 必须是无内嵌凭据的 HTTPS URL")
    if allowed_hosts is not None and parsed.hostname.lower() not in allowed_hosts:
        raise ValueError(f"{provider} endpoint host 不受信任: {parsed.hostname}")
    return url


def _provider_configs(system_prompt: str, user_message: str) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {}

    minimax_key = os.getenv("MINIMAX_API_KEY")
    if minimax_key:
        model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
        url = _validated_https_url(
            os.getenv("MINIMAX_API_URL", "https://api.minimax.io/anthropic/v1/messages"),
            "minimax",
            {"api.minimax.io"},
        )
        configs["minimax"] = {
            "url": url,
            "headers": {
                "x-api-key": minimax_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            "payload": {
                "model": model,
                "max_tokens": 4000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
                "temperature": 1.0,
            },
            "extract": _extract_minimax,
            "model": model,
        }

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
        url = _validated_https_url(
            os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"),
            "deepseek",
            {"api.deepseek.com"},
        )
        configs["deepseek"] = {
            "url": url,
            "headers": {
                "authorization": f"Bearer {deepseek_key}",
                "content-type": "application/json",
            },
            "payload": {
                "model": model,
                "max_tokens": 4000,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.7,
            },
            "extract": _extract_openai_compatible,
            "model": model,
        }

    custom_key = os.getenv("CUSTOM_API_KEY")
    custom_base = os.getenv("CUSTOM_API_BASE")
    if custom_key and custom_base:
        model = os.getenv("CUSTOM_MODEL")
        if not model:
            raise ValueError("custom provider 必须显式设置 CUSTOM_MODEL")
        base = _validated_https_url(custom_base.rstrip("/"), "custom")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        configs["custom"] = {
            "url": url,
            "headers": {
                "authorization": f"Bearer {custom_key}",
                "content-type": "application/json",
            },
            "payload": {
                "model": model,
                "max_tokens": 4000,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.7,
            },
            "extract": _extract_openai_compatible,
            "model": model,
        }
    return configs


async def call_llm(
    system_prompt: str,
    user_message: str,
    *,
    provider: str | None = None,
    allow_fallback: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Call one selected provider and return auditable, key-free metadata."""
    try:
        request_timeout = float(
            timeout if timeout is not None else os.getenv("DESTINY_LLM_TIMEOUT", "120")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("LLM timeout 必须是 1-600 秒的有限数值") from exc
    if not math.isfinite(request_timeout) or not 1 <= request_timeout <= 600:
        raise ValueError("LLM timeout 必须是 1-600 秒的有限数值")
    if not HAS_HTTPX:
        return {
            "status": "error",
            "provider": provider,
            "model": None,
            "text": "[LLM不可用] 未安装 httpx；请重新运行 bootstrap。",
        }

    configs = _provider_configs(system_prompt, user_message)
    requested = provider or os.getenv("DESTINY_LLM_PROVIDER")
    if not requested:
        return {
            "status": "error",
            "provider": None,
            "model": None,
            "text": "[LLM未启用] 请同时使用 --llm --provider minimax|deepseek|custom。",
        }
    if requested not in ("minimax", "deepseek", "custom"):
        return {
            "status": "error",
            "provider": requested,
            "model": None,
            "text": f"[LLM配置错误] 未知 provider: {requested}",
        }
    if requested not in configs and not allow_fallback:
        return {
            "status": "error",
            "provider": requested,
            "model": None,
            "text": f"[LLM配置错误] {requested} 缺少 API key 或 endpoint。",
        }

    order = [requested]
    if allow_fallback:
        order.extend(name for name in ("minimax", "deepseek", "custom") if name != requested)
    order = [name for name in order if name in configs]
    if not order:
        return {
            "status": "error",
            "provider": requested,
            "model": None,
            "text": "[LLM配置错误] 没有任何已配置 provider。",
        }

    errors: list[str] = []
    async with httpx.AsyncClient(timeout=request_timeout, trust_env=False) as client:
        for name in order:
            cfg = configs[name]
            try:
                response = await client.post(
                    cfg["url"], headers=cfg["headers"], json=cfg["payload"]
                )
                response.raise_for_status()
                text = cfg["extract"](response.json())
                if not text:
                    raise ValueError("empty text response")
                return {
                    "status": "ok",
                    "provider": name,
                    "model": cfg["model"],
                    "text": text,
                }
            except Exception as exc:  # never include response bodies or headers
                if HAS_HTTPX and isinstance(exc, httpx.HTTPStatusError):
                    detail = f"HTTP {exc.response.status_code}"
                else:
                    detail = f"{type(exc).__name__}: {exc}"
                errors.append(f"{name}: {detail}")

    return {
        "status": "error",
        "provider": order[-1],
        "model": configs[order[-1]]["model"],
        "text": f"[LLM解读失败] {'; '.join(errors)}",
    }
