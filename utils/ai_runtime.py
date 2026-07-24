"""Streamlit-aware AI routing, token budgets, fallback, and telemetry."""

from __future__ import annotations

import uuid

import streamlit as st

from config.settings import (
    get_api_key,
    get_fallback_provider,
    get_provider,
    get_reasoning_effort,
    get_task_model,
)
from utils.ai_client import AIClientError, AIResult, get_ai_result_with_fallback


TASK_OUTPUT_LIMITS = {
    "classification": 96,
    "query": 700,
    "rewrite": 900,
    "resume_quality": 1600,
    "cover_letter": 1200,
    "analysis": 2200,
    "recruiter": 2800,
    "resume": 3200,
}


class TokenBudgetError(RuntimeError):
    """Raised before a request that would exceed the configured session budget."""


def run_ai(
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.2,
    task: str = "query",
    max_tokens: int | None = None,
    use_cache: bool = True,
) -> AIResult:
    provider = get_provider()
    model = get_task_model(task, provider)
    fallback_provider = get_fallback_provider()
    fallback_model = (
        get_task_model(task, fallback_provider) if fallback_provider else ""
    )
    if "ai_cache_scope" not in st.session_state:
        st.session_state["ai_cache_scope"] = uuid.uuid4().hex

    session_budget = int(st.session_state.get("session_token_budget", 50_000))
    tokens_used = int(st.session_state.get("ai_input_tokens", 0)) + int(
        st.session_state.get("ai_output_tokens", 0)
    )
    estimated_input = max(1, len(system_prompt + prompt) // 4)
    limit = min(
        max_tokens or TASK_OUTPUT_LIMITS.get(task, 1000),
        TASK_OUTPUT_LIMITS.get(task, max_tokens or 1000),
    )
    if tokens_used + estimated_input + limit > session_budget:
        raise TokenBudgetError(
            "This request could exceed the session token budget. Increase the budget "
            "in the sidebar or start a new session."
        )

    result = get_ai_result_with_fallback(
        api_key=get_api_key(provider),
        provider=provider,
        model=model,
        prompt=prompt,
        max_tokens=limit,
        system_prompt=system_prompt,
        temperature=temperature,
        reasoning_effort=get_reasoning_effort(model, provider),
        fallback_api_key=get_api_key(fallback_provider) if fallback_provider else "",
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
        fallback_reasoning_effort=(
            get_reasoning_effort(fallback_model, fallback_provider)
            if fallback_provider and fallback_model
            else ""
        ),
        use_cache=use_cache,
        cache_scope=st.session_state["ai_cache_scope"],
    )

    st.session_state["ai_input_tokens"] = int(
        st.session_state.get("ai_input_tokens", 0)
    ) + result.usage.input_tokens
    st.session_state["ai_output_tokens"] = int(
        st.session_state.get("ai_output_tokens", 0)
    ) + result.usage.output_tokens
    st.session_state["ai_cached_tokens"] = int(
        st.session_state.get("ai_cached_tokens", 0)
    ) + result.usage.cached_tokens
    st.session_state["last_ai_call"] = {
        "provider": result.provider,
        "model": result.model,
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "cache_hit": result.cache_hit,
        "fallback_used": result.fallback_used,
    }
    return result


def user_safe_ai_error(exc: Exception) -> str:
    if isinstance(exc, (AIClientError, TokenBudgetError)):
        return str(exc)
    return "The AI request could not be completed."
