"""
Provider, model, and secure API-key configuration.

Keys are resolved in this order:
1. Streamlit session state (entered in the sidebar)
2. Streamlit secrets
3. Environment variables

No key is written to disk by application code.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata

import streamlit as st


PROVIDERS = {
    "groq": {
        "label": "Groq",
        "secret": "GROQ_API_KEY",
        "placeholder": "gsk_...",
        "signup_url": "https://console.groq.com/keys",
        "models": [
            "openai/gpt-oss-120b",
            "qwen/qwen3.6-27b",
            "openai/gpt-oss-20b",
        ],
        "default_model": "openai/gpt-oss-120b",
    },
    "gemini": {
        "label": "Google Gemini",
        "secret": "GEMINI_API_KEY",
        "placeholder": "AIza...",
        "signup_url": "https://aistudio.google.com/app/apikey",
        "models": [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ],
        "default_model": "gemini-2.5-flash",
    },
    "openrouter": {
        "label": "OpenRouter",
        "secret": "OPENROUTER_API_KEY",
        "placeholder": "sk-or-v1-...",
        "signup_url": "https://openrouter.ai/settings/keys",
        "models": [
            "openrouter/free",
        ],
        "default_model": "openrouter/free",
    },
}

DEFAULT_PROVIDER = "groq"
GROQ_MODEL_DEFAULT = PROVIDERS["groq"]["default_model"]
AVAILABLE_MODELS = PROVIDERS["groq"]["models"]

MODEL_LABELS = {
    "openai/gpt-oss-120b": "GPT OSS 120B · recommended quality",
    "qwen/qwen3.6-27b": "Qwen 3.6 27B · preview reasoning",
    "openai/gpt-oss-20b": "GPT OSS 20B · fast & economical",
}

API_KEY_VALIDATION_STATE = "provider_key_validation"


def get_provider() -> str:
    provider = st.session_state.get("ai_provider", DEFAULT_PROVIDER)
    return provider if provider in PROVIDERS else DEFAULT_PROVIDER


def get_provider_label(provider: str | None = None) -> str:
    return PROVIDERS[provider or get_provider()]["label"]


def get_available_models(provider: str | None = None) -> list[str]:
    return list(PROVIDERS[provider or get_provider()]["models"])


def get_default_model(provider: str | None = None) -> str:
    return str(PROVIDERS[provider or get_provider()]["default_model"])


def get_model_label(model: str) -> str:
    """Return a readable label while preserving the exact provider model ID."""
    return MODEL_LABELS.get(model, model)


def get_reasoning_options(model: str, provider: str | None = None) -> tuple[list[str], str]:
    """Return only reasoning-effort values supported by the selected model."""
    provider_id = provider or get_provider()
    if provider_id != "groq":
        return [], ""
    if model in {"openai/gpt-oss-120b", "openai/gpt-oss-20b"}:
        return ["low", "medium", "high"], "medium"
    if model == "qwen/qwen3.6-27b":
        return ["none", "default"], "none"
    return [], ""


def get_reasoning_effort(model: str, provider: str | None = None) -> str:
    """Resolve a safe, model-compatible reasoning setting from session state."""
    provider_id = provider or get_provider()
    options, default = get_reasoning_options(model, provider_id)
    if not options:
        return ""
    value = str(
        st.session_state.get(f"reasoning_effort_{provider_id}", default)
    )
    return value if value in options else default


def _secret_value(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
    except (FileNotFoundError, KeyError):
        value = ""
    return str(value).strip() if value else ""


def normalize_api_key(value: object) -> str:
    """Normalize common copy/paste artifacts without logging the credential."""
    key = str(value or "").strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in {'"', "'"}:
        key = key[1:-1].strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return "".join(
        character
        for character in key
        if not character.isspace() and unicodedata.category(character) != "Cf"
    )


def _key_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] if value else ""


def get_api_key_source(provider: str | None = None) -> str:
    """Return the active credential source without exposing its value."""
    provider_id = provider or get_provider()
    secret_name = str(PROVIDERS[provider_id]["secret"])
    session_keys = st.session_state.get("provider_api_keys", {})
    session_value = (
        session_keys.get(provider_id, "") if isinstance(session_keys, dict) else ""
    )
    legacy_value = (
        st.session_state.get("groq_api_key", "") if provider_id == "groq" else ""
    )
    if normalize_api_key(session_value) or normalize_api_key(legacy_value):
        return "session override"
    if normalize_api_key(_secret_value(secret_name)):
        return "Streamlit secret"
    if normalize_api_key(os.environ.get(secret_name, "")):
        return "environment variable"
    return ""


def get_api_key(provider: str | None = None) -> str:
    """Resolve the selected provider's key without persisting it."""
    provider_id = provider or get_provider()
    secret_name = str(PROVIDERS[provider_id]["secret"])
    session_keys = st.session_state.get("provider_api_keys", {})
    session_value = session_keys.get(provider_id, "") if isinstance(session_keys, dict) else ""
    legacy_value = st.session_state.get("groq_api_key", "") if provider_id == "groq" else ""
    return normalize_api_key(
        session_value
        or legacy_value
        or _secret_value(secret_name)
        or os.environ.get(secret_name, "")
    )


def set_api_key(key: str, provider: str | None = None):
    """Keep a provider API key in server-side Streamlit session state."""
    provider_id = provider or get_provider()
    normalized = normalize_api_key(key)
    previous = get_api_key(provider_id)
    keys = dict(st.session_state.get("provider_api_keys", {}))
    keys[provider_id] = normalized
    st.session_state["provider_api_keys"] = keys
    if provider_id == "groq":
        st.session_state["groq_api_key"] = normalized
    if normalized != previous:
        validations = dict(st.session_state.get(API_KEY_VALIDATION_STATE, {}))
        validations.pop(provider_id, None)
        st.session_state[API_KEY_VALIDATION_STATE] = validations


def clear_session_api_key(
    provider: str | None = None,
    widget_key: str = "",
) -> None:
    """Remove a session override so deployed secrets can take effect again."""
    provider_id = provider or get_provider()
    keys = dict(st.session_state.get("provider_api_keys", {}))
    keys.pop(provider_id, None)
    st.session_state["provider_api_keys"] = keys
    if provider_id == "groq":
        st.session_state["groq_api_key"] = ""
    validations = dict(st.session_state.get(API_KEY_VALIDATION_STATE, {}))
    validations.pop(provider_id, None)
    st.session_state[API_KEY_VALIDATION_STATE] = validations
    if widget_key:
        st.session_state[widget_key] = ""


def set_api_key_validation(provider: str, status: str) -> None:
    """Record verification only for the exact active credential."""
    if status not in {"verified", "rejected"}:
        raise ValueError("API key validation status must be verified or rejected.")
    key = get_api_key(provider)
    validations = dict(st.session_state.get(API_KEY_VALIDATION_STATE, {}))
    if key:
        validations[provider] = {
            "fingerprint": _key_fingerprint(key),
            "status": status,
        }
    else:
        validations.pop(provider, None)
    st.session_state[API_KEY_VALIDATION_STATE] = validations


def get_api_key_validation(provider: str | None = None) -> str:
    """Return verified/rejected only when it matches the active credential."""
    provider_id = provider or get_provider()
    key = get_api_key(provider_id)
    validations = st.session_state.get(API_KEY_VALIDATION_STATE, {})
    record = validations.get(provider_id, {}) if isinstance(validations, dict) else {}
    if not key or not isinstance(record, dict):
        return "unverified"
    if record.get("fingerprint") != _key_fingerprint(key):
        return "unverified"
    status = str(record.get("status", ""))
    return status if status in {"verified", "rejected"} else "unverified"


def is_api_key_set(provider: str | None = None) -> bool:
    key = get_api_key(provider)
    return bool(key and len(key) >= 16)


def get_model(provider: str | None = None) -> str:
    provider_id = provider or get_provider()
    custom = st.session_state.get(f"custom_model_{provider_id}", "").strip()
    if custom:
        return custom
    return st.session_state.get(
        f"model_{provider_id}",
        get_default_model(provider_id),
    )


def get_task_model(task: str, provider: str | None = None) -> str:
    """Route cheap tasks and document tasks independently when configured."""
    provider_id = provider or get_provider()
    if st.session_state.get(f"enable_task_routing_{provider_id}", False):
        route = (
            "fast"
            if task in {"classification", "query"}
            else "quality"
        )
        routed = st.session_state.get(f"{route}_model_{provider_id}", "")
        if routed:
            return str(routed)
    return get_model(provider_id)


def get_fallback_provider() -> str:
    provider = st.session_state.get("fallback_provider", "")
    if provider in PROVIDERS and provider != get_provider() and is_api_key_set(provider):
        return provider
    return ""
