"""Provider configuration, preferences, token controls, and session telemetry."""

import streamlit as st

from config.settings import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    get_api_key,
    get_available_models,
    get_default_model,
    get_model,
    get_model_label,
    get_provider,
    get_reasoning_options,
    is_api_key_set,
    set_api_key,
)
from utils.ai_client import AIClientError, list_provider_models
from utils.auth import DEFAULT_LOGIN_USERNAME, logout


def _provider_key_input(provider: str, prefix: str = ""):
    spec = PROVIDERS[provider]
    existing = get_api_key(provider)
    entered = st.text_input(
        f"{spec['label']} API key",
        type="password",
        value=st.session_state.get("provider_api_keys", {}).get(provider, ""),
        placeholder=str(spec["placeholder"]),
        help=(
            "Held in server-side session state. You may alternatively use "
            f"Streamlit secret or environment variable {spec['secret']}."
        ),
        key=f"{prefix}api_key_input_{provider}",
    )
    if entered:
        set_api_key(entered, provider)
    if existing or entered:
        st.success(f"{spec['label']} key available")
    else:
        st.caption(f"[Create a key]({spec['signup_url']})")


def render_sidebar() -> dict:
    with st.sidebar:
        st.markdown(
            """
            <div style="text-align:center; padding: 12px 0 8px 0;">
                <span style="font-size:28px;">📄</span>
                <h2 style="margin:4px 0 2px 0; color:#1a1a2e; font-size:20px; font-weight:700;">
                    ATS Resume Studio
                </h2>
                <p style="margin:0; font-size:12px; color:#666;">Evidence-grounded · Multi-provider</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(f"Signed in as {DEFAULT_LOGIN_USERNAME}")
        if st.button("↪ Sign out", width="stretch", key="auth_sign_out"):
            logout()
            st.rerun()
        st.divider()

        st.markdown("#### 🤖 AI Provider")
        provider_ids = list(PROVIDERS)
        selected_provider = st.selectbox(
            "Primary provider",
            provider_ids,
            index=provider_ids.index(
                st.session_state.get("ai_provider", DEFAULT_PROVIDER)
                if st.session_state.get("ai_provider", DEFAULT_PROVIDER) in provider_ids
                else DEFAULT_PROVIDER
            ),
            format_func=lambda value: str(PROVIDERS[value]["label"]),
            key="ai_provider",
        )
        _provider_key_input(selected_provider)

        available = get_available_models(selected_provider)
        discovered = st.session_state.get(f"discovered_models_{selected_provider}", [])
        model_options = list(dict.fromkeys(available + list(discovered)))
        default_model = get_default_model(selected_provider)
        if st.button("↻ Discover active models", width="stretch"):
            if not is_api_key_set(selected_provider):
                st.error("Configure this provider's key first.")
            else:
                try:
                    discovered = list_provider_models(
                        selected_provider, get_api_key(selected_provider)
                    )
                    st.session_state[f"discovered_models_{selected_provider}"] = discovered
                    st.success(f"Found {len(discovered)} active models.")
                    st.rerun()
                except AIClientError as exc:
                    st.error(str(exc))

        model_key = f"model_{selected_provider}"
        if st.session_state.get(model_key) not in model_options:
            st.session_state[model_key] = default_model
        selected_model = st.selectbox(
            "Model",
            model_options,
            index=model_options.index(default_model) if default_model in model_options else 0,
            format_func=get_model_label,
            key=model_key,
        )
        if selected_provider == "groq":
            st.caption(
                f"Model ID: `{selected_model}` · Llama 3.3/3.1 migration is complete."
            )
        use_custom = st.checkbox(
            "Use custom model ID",
            value=bool(st.session_state.get(f"custom_model_{selected_provider}", "")),
            key=f"use_custom_model_{selected_provider}",
        )
        if use_custom:
            custom_model = st.text_input(
                "Custom model ID",
                key=f"custom_model_{selected_provider}",
                placeholder="Provider model identifier",
            )
        else:
            st.session_state[f"custom_model_{selected_provider}"] = ""
            custom_model = ""

        with st.expander("Model parameters", expanded=selected_provider == "groq"):
            parameter_model = (
                custom_model.strip()
                if use_custom and custom_model.strip()
                else selected_model
            )
            reasoning_options, reasoning_default = get_reasoning_options(
                parameter_model, selected_provider
            )
            if reasoning_options:
                reasoning_key = f"reasoning_effort_{selected_provider}"
                if st.session_state.get(reasoning_key) not in reasoning_options:
                    st.session_state[reasoning_key] = reasoning_default
                reasoning_effort = st.selectbox(
                    "Reasoning effort",
                    reasoning_options,
                    index=reasoning_options.index(reasoning_default),
                    key=reasoning_key,
                    help=(
                        "GPT OSS supports low, medium, and high. Qwen 3.6 supports "
                        "none for efficient responses or default for thinking mode."
                    ),
                )
                if parameter_model == "qwen/qwen3.6-27b":
                    st.caption(
                        "Use `none` for efficient resume editing; use `default` for "
                        "complex analysis. Reasoning is hidden from document output."
                    )
                else:
                    st.caption(
                        f"Current reasoning level: **{reasoning_effort}**. "
                        "Reasoning is hidden from document output."
                    )
            else:
                st.caption(
                    "The selected model has no compatible reasoning-effort control."
                )

        with st.expander("Task-based model routing", expanded=False):
            route_tasks = st.checkbox(
                "Use separate fast and quality models",
                value=False,
                key=f"enable_task_routing_{selected_provider}",
                help="Classification and short queries use the fast model; document work uses the quality model.",
            )
            if route_tasks:
                fast_defaults = {
                    "groq": "openai/gpt-oss-20b",
                    "gemini": "gemini-2.5-flash-lite",
                    "openrouter": "openrouter/free",
                }
                quality_defaults = {
                    "groq": "openai/gpt-oss-120b",
                    "gemini": "gemini-2.5-flash",
                    "openrouter": "openrouter/free",
                }
                fast_default = fast_defaults.get(selected_provider, selected_model)
                quality_default = quality_defaults.get(selected_provider, selected_model)
                st.selectbox(
                    "Fast model",
                    model_options,
                    index=(
                        model_options.index(fast_default)
                        if fast_default in model_options
                        else model_options.index(selected_model)
                    ),
                    format_func=get_model_label,
                    key=f"fast_model_{selected_provider}",
                )
                st.selectbox(
                    "Quality model",
                    model_options,
                    index=(
                        model_options.index(quality_default)
                        if quality_default in model_options
                        else model_options.index(selected_model)
                    ),
                    format_func=get_model_label,
                    key=f"quality_model_{selected_provider}",
                )

        with st.expander("Fallback provider", expanded=False):
            enable_fallback = st.checkbox(
                "Enable fallback for rate limits/timeouts",
                value=False,
                key="enable_fallback",
            )
            alternatives = [value for value in provider_ids if value != selected_provider]
            if enable_fallback and alternatives:
                fallback_provider = st.selectbox(
                    "Fallback",
                    alternatives,
                    format_func=lambda value: str(PROVIDERS[value]["label"]),
                    key="fallback_provider",
                )
                _provider_key_input(fallback_provider, prefix="fallback_")
                fallback_models = get_available_models(fallback_provider)
                st.selectbox(
                    "Fallback model",
                    fallback_models,
                    format_func=get_model_label,
                    key=f"model_{fallback_provider}",
                )
            else:
                st.session_state["fallback_provider"] = ""

        st.divider()
        st.markdown("#### ⚙️ Preferences")
        target_field = st.text_input(
            "Target field / industry",
            placeholder="e.g. Marketing, Healthcare, DevOps",
            help="Leave blank to auto-infer from the Job Description.",
            key="target_field_input",
        )
        auto_infer = st.checkbox(
            "Auto-infer field from JD",
            value=True,
            key="auto_infer_field",
        )
        tone = st.selectbox(
            "Cover letter tone",
            ["Confident & Direct", "Warm & Collaborative", "Humble & Impact-Focused"],
            key="tone_choice",
        )
        achievements_count = st.slider(
            "Achievements per role",
            min_value=3,
            max_value=7,
            value=4,
            key="achievements_count",
        )
        token_budget = st.select_slider(
            "Session token budget",
            options=[10_000, 25_000, 50_000, 100_000, 250_000],
            value=50_000,
            format_func=lambda value: f"{value:,}",
            key="session_token_budget",
            help="AI calls stop when recorded uncached tokens reach this session budget.",
        )

        st.divider()
        st.markdown("#### 📊 Session Usage")
        input_tokens = int(st.session_state.get("ai_input_tokens", 0))
        output_tokens = int(st.session_state.get("ai_output_tokens", 0))
        cached_tokens = int(st.session_state.get("ai_cached_tokens", 0))
        total = input_tokens + output_tokens
        st.metric("Uncached tokens", f"{total:,}")
        st.progress(min(1.0, total / max(token_budget, 1)))
        st.caption(
            f"Input {input_tokens:,} · Output {output_tokens:,} · "
            f"Cache savings {cached_tokens:,}"
        )
        st.caption(
            f"Primary: {PROVIDERS[selected_provider]['label']} / {get_model(selected_provider)}"
        )

        if st.button("🔄 Reset everything", width="stretch"):
            for key in list(st.session_state.keys()):
                st.session_state.pop(key, None)
            st.rerun()

    return {
        "target_field": target_field,
        "auto_infer_field": auto_infer,
        "tone_choice": tone,
        "achievements_count": achievements_count,
        "api_ready": is_api_key_set(selected_provider),
        "provider": get_provider(),
        "model": get_model(selected_provider) or selected_model,
        "token_budget": token_budget,
    }
