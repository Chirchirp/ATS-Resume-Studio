"""
Provider-neutral AI gateway with bounded in-memory caching and usage metadata.

Supported providers:
- Groq (native SDK)
- OpenRouter (OpenAI-compatible REST API)
- Google Gemini (native REST API)
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import requests
from groq import Groq


CACHE_LIMIT = 64
_CACHE: OrderedDict[str, "AIResult"] = OrderedDict()
_CACHE_LOCK = threading.Lock()


class AIClientError(RuntimeError):
    """A typed, user-safe provider failure."""

    def __init__(self, message: str, *, retryable: bool = False, provider: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.provider = provider


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class AIResult:
    text: str
    provider: str
    model: str
    usage: AIUsage
    cache_hit: bool = False
    fallback_used: bool = False


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _cache_key(
    cache_scope: str,
    provider: str,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    reasoning_effort: str,
) -> str:
    raw = json.dumps(
        {
            "v": 3,
            "scope": cache_scope,
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "system": system_prompt,
            "max_tokens": max_tokens,
            "temperature": round(temperature, 3),
            "reasoning_effort": reasoning_effort,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_cached(key: str) -> AIResult | None:
    with _CACHE_LOCK:
        value = _CACHE.get(key)
        if value:
            _CACHE.move_to_end(key)
            return AIResult(
                text=value.text,
                provider=value.provider,
                model=value.model,
                usage=AIUsage(cached_tokens=value.usage.total_tokens),
                cache_hit=True,
                fallback_used=value.fallback_used,
            )
    return None


def _put_cached(key: str, result: AIResult):
    with _CACHE_LOCK:
        _CACHE[key] = result
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_LIMIT:
            _CACHE.popitem(last=False)


def clear_response_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def _safe_error(exc: Exception, provider: str) -> AIClientError:
    message = str(exc).lower()
    if "401" in message or "invalid_api_key" in message or "unauthenticated" in message:
        return AIClientError(
            f"Invalid API key or authentication failure for {provider}.",
            provider=provider,
        )
    if "403" in message or "permission" in message:
        return AIClientError(
            f"{provider} denied access to this model or project.",
            provider=provider,
        )
    if "429" in message or "rate limit" in message or "resource_exhausted" in message:
        return AIClientError(
            f"{provider} rate limit reached.",
            retryable=True,
            provider=provider,
        )
    if any(term in message for term in ("timeout", "timed out", "502", "503", "504")):
        return AIClientError(
            f"{provider} is temporarily unavailable.",
            retryable=True,
            provider=provider,
        )
    return AIClientError(
        f"{provider} could not complete this request.",
        provider=provider,
    )


def _groq_result(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    reasoning_effort: str = "",
) -> AIResult:
    client = Groq(api_key=api_key, timeout=45.0, max_retries=2)
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt})
    request: dict[str, Any] = {
        "messages": messages,
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if reasoning_effort:
        request["reasoning_effort"] = reasoning_effort
        request["reasoning_format"] = "hidden"
    completion = client.chat.completions.create(
        **request
    )
    text = completion.choices[0].message.content or ""
    if not text.strip():
        raise AIClientError(
            "The selected Groq model used its completion budget without returning final text. "
            "Use a non-reasoning model for short tasks or increase the task output limit.",
            provider="groq",
        )
    raw_usage = getattr(completion, "usage", None)
    prompt_tokens = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(raw_usage, "completion_tokens", 0) or 0)
    details = getattr(raw_usage, "prompt_tokens_details", None)
    cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
    return AIResult(
        text=text,
        provider="groq",
        model=model,
        usage=AIUsage(
            input_tokens=prompt_tokens or _estimate_tokens(system_prompt + prompt),
            output_tokens=completion_tokens or _estimate_tokens(text),
            cached_tokens=cached_tokens,
        ),
    )


def _openrouter_result(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
) -> AIResult:
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt})
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/ats-resume-studio",
            "X-Title": "ATS Resume Studio",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"].get("content", "") or ""
    usage = data.get("usage") or {}
    return AIResult(
        text=text,
        provider="openrouter",
        model=data.get("model") or model,
        usage=AIUsage(
            input_tokens=int(usage.get("prompt_tokens") or _estimate_tokens(system_prompt + prompt)),
            output_tokens=int(usage.get("completion_tokens") or _estimate_tokens(text)),
            cached_tokens=int(usage.get("cached_tokens") or 0),
        ),
    )


def _gemini_result(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
) -> AIResult:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_prompt.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise AIClientError(
            "Gemini returned no candidate output, possibly because of a safety filter.",
            provider="gemini",
        )
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts)
    usage = data.get("usageMetadata") or {}
    return AIResult(
        text=text,
        provider="gemini",
        model=model,
        usage=AIUsage(
            input_tokens=int(usage.get("promptTokenCount") or _estimate_tokens(system_prompt + prompt)),
            output_tokens=int(usage.get("candidatesTokenCount") or _estimate_tokens(text)),
            cached_tokens=int(usage.get("cachedContentTokenCount") or 0),
        ),
    )


def get_ai_result(
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int = 2048,
    *,
    provider: str = "groq",
    system_prompt: str = "",
    temperature: float = 0.2,
    reasoning_effort: str = "",
    use_cache: bool = True,
    cache_scope: str = "",
) -> AIResult:
    """Generate through one provider and return text plus usage metadata."""
    if not api_key:
        raise AIClientError(
            f"No {provider} API key is configured.",
            provider=provider,
        )
    if provider not in {"groq", "openrouter", "gemini"}:
        raise AIClientError(f"Unsupported AI provider: {provider}")

    temperature = max(0.0, min(1.0, temperature))
    max_tokens = max(32, min(8192, int(max_tokens)))
    key = _cache_key(
        cache_scope,
        provider,
        model,
        prompt,
        system_prompt,
        max_tokens,
        temperature,
        reasoning_effort,
    )
    if use_cache:
        cached = _get_cached(key)
        if cached:
            return cached

    try:
        if provider == "groq":
            result = _groq_result(
                api_key,
                model,
                prompt,
                system_prompt,
                max_tokens,
                temperature,
                reasoning_effort,
            )
        elif provider == "openrouter":
            result = _openrouter_result(
                api_key, model, prompt, system_prompt, max_tokens, temperature
            )
        else:
            result = _gemini_result(
                api_key, model, prompt, system_prompt, max_tokens, temperature
            )
    except AIClientError:
        raise
    except Exception as exc:
        raise _safe_error(exc, provider) from exc

    if use_cache and result.text:
        _put_cached(key, result)
    return result


def get_ai_result_with_fallback(
    *,
    api_key: str,
    provider: str,
    model: str,
    prompt: str,
    max_tokens: int = 2048,
    system_prompt: str = "",
    temperature: float = 0.2,
    reasoning_effort: str = "",
    fallback_api_key: str = "",
    fallback_provider: str = "",
    fallback_model: str = "",
    fallback_reasoning_effort: str = "",
    use_cache: bool = True,
    cache_scope: str = "",
) -> AIResult:
    """Use a fallback only for rate limits or transient provider failures."""
    try:
        return get_ai_result(
            api_key,
            model,
            prompt,
            max_tokens,
            provider=provider,
            system_prompt=system_prompt,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            use_cache=use_cache,
            cache_scope=cache_scope,
        )
    except AIClientError as exc:
        if not (
            exc.retryable
            and fallback_provider
            and fallback_api_key
            and fallback_model
            and fallback_provider != provider
        ):
            raise
        fallback_result = get_ai_result(
            fallback_api_key,
            fallback_model,
            prompt,
            max_tokens,
            provider=fallback_provider,
            system_prompt=system_prompt,
            temperature=temperature,
            reasoning_effort=fallback_reasoning_effort,
            use_cache=use_cache,
            cache_scope=cache_scope,
        )
        return AIResult(
            text=fallback_result.text,
            provider=fallback_result.provider,
            model=fallback_result.model,
            usage=fallback_result.usage,
            cache_hit=fallback_result.cache_hit,
            fallback_used=True,
        )


def get_ai_response(
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int = 2048,
    *,
    provider: str = "groq",
    system_prompt: str = "",
    temperature: float = 0.2,
    reasoning_effort: str = "",
) -> str:
    """Backward-compatible text-only wrapper."""
    return get_ai_result(
        api_key,
        model,
        prompt,
        max_tokens,
        provider=provider,
        system_prompt=system_prompt,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    ).text


def list_provider_models(provider: str, api_key: str) -> list[str]:
    """Discover active model IDs from the selected provider."""
    if not api_key:
        raise AIClientError(f"No {provider} API key is configured.", provider=provider)
    try:
        if provider == "groq":
            data = Groq(api_key=api_key, timeout=30.0, max_retries=1).models.list()
            return sorted(model.id for model in data.data)
        if provider == "openrouter":
            response = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            response.raise_for_status()
            return sorted(item["id"] for item in response.json().get("data", []))
        if provider == "gemini":
            response = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key, "pageSize": 1000},
                timeout=30,
            )
            response.raise_for_status()
            return sorted(
                item["name"].removeprefix("models/")
                for item in response.json().get("models", [])
                if "generateContent" in item.get("supportedGenerationMethods", [])
            )
        raise AIClientError(f"Unsupported AI provider: {provider}")
    except AIClientError:
        raise
    except Exception as exc:
        raise _safe_error(exc, provider) from exc
