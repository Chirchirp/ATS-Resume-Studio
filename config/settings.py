"""
Provider, model, and secure API-key configuration.

Keys are resolved in this order:
1. Streamlit session state (entered in the sidebar)
2. Streamlit secrets
3. Environment variables

No key is written to disk by application code.
"""

from __future__ import annotations

import os

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


def get_api_key(provider: str | None = None) -> str:
    """Resolve the selected provider's key without persisting it."""
    provider_id = provider or get_provider()
    secret_name = str(PROVIDERS[provider_id]["secret"])
    session_keys = st.session_state.get("provider_api_keys", {})
    session_value = session_keys.get(provider_id, "") if isinstance(session_keys, dict) else ""
    legacy_value = st.session_state.get("groq_api_key", "") if provider_id == "groq" else ""
    return (
        str(session_value).strip()
        or str(legacy_value).strip()
        or _secret_value(secret_name)
        or os.environ.get(secret_name, "").strip()
    )


def set_api_key(key: str, provider: str | None = None):
    """Keep a provider API key in server-side Streamlit session state."""
    provider_id = provider or get_provider()
    keys = dict(st.session_state.get("provider_api_keys", {}))
    keys[provider_id] = key.strip()
    st.session_state["provider_api_keys"] = keys
    if provider_id == "groq":
        st.session_state["groq_api_key"] = key.strip()


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
